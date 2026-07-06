"""Custom Pier agents that add symnav to the sandbox and nudge the model to use it.

Referenced from a job config via:
    import_path: symnav_agent:SymnavClaudeCode

Subclasses Pier's stock claude-code agent and:
  1. adds install steps that clone + build symnav and put it on PATH,
  2. writes a one-time "use symnav" PreToolUse hook + a settings file into the
     sandbox, and points Claude Code at it via --settings,
  3. widens the network allowlist so the install can reach GitHub/npm.

Why a hook via --settings instead of --append-system-prompt: Pier builds CLI
flags by bare f-string concatenation with NO shell quoting, so any multi-word or
backtick-containing value (like a directive) corrupts the shell command. A file
path is a single safe token, and the hook's text lives in files (written via
base64), never on a command line.
"""

import base64
import json

from pier.agents.installed.base import CliFlag
from pier.agents.installed.claude_code import ClaudeCode
from pier.agents.network import NetworkAllowlist
from pier.models.agent.install import AgentInstallSpec, InstallStep

SYMNAV_REPO = "https://github.com/mohasarc/symnav.git"
HOOK_DIR = "/tmp/symnav"
SETTINGS_PATH = f"{HOOK_DIR}/settings.json"
NUDGE_PATH = f"{HOOK_DIR}/nudge.js"

_INSTALL_DOMAINS = [
    "github.com", "codeload.github.com", "objects.githubusercontent.com",
    "raw.githubusercontent.com", "registry.npmjs.org", "nodejs.org",
]

# One-time nudge hook (node — guaranteed present in the TS task images). Blocks
# the first search and the first file-read with a hint to use symnav, then allows.
_NUDGE_JS = r"""
const fs = require('fs');
let raw = '';
process.stdin.on('data', d => raw += d);
process.stdin.on('end', () => {
  let tool = '', cmd = '';
  try { const j = JSON.parse(raw); tool = j.tool_name || ''; cmd = (j.tool_input && j.tool_input.command) || ''; }
  catch (e) { process.exit(0); }
  let cat = null;
  if (tool === 'Grep' || tool === 'Glob') cat = 'search';
  else if (tool === 'Read') cat = 'read';
  else if (tool === 'Bash') {
    if (/\bsymnav\b/.test(cmd)) cat = null;
    else if (/\b(grep|egrep|fgrep|rg|ag|ack|find|fd)\b/.test(cmd) || /git\s+grep/.test(cmd)) cat = 'search';
    else if (/\b(cat|head|tail|less|more|bat|nl)\b/.test(cmd) || /sed\s+-n/.test(cmd) || /\bawk\b/.test(cmd)) cat = 'read';
  }
  if (!cat) process.exit(0);
  const flag = '/tmp/symnav/nudged_' + cat;
  if (fs.existsSync(flag)) process.exit(0);
  try { fs.writeFileSync(flag, '1'); } catch (e) {}
  const hints = {
    search: "Prefer symnav to find code (structured, far fewer tokens than grep): `symnav resolve <name>` locates a symbol/file by name; `symnav refs <id>` lists every reference; `symnav overview <file>` shows a file's symbols; `symnav def <id>` where it's defined. One-time reminder — rerun your command if symnav can't answer.",
    read: "Prefer symnav to read code (only what you need, not whole files): `symnav overview <file>` symbol tree; `symnav def <id>` a definition; `symnav context <id>` a symbol's callers/callees/refs; `symnav graph <id>` call paths. One-time reminder — rerun your command if symnav can't answer.",
  };
  process.stderr.write(hints[cat]);
  process.exit(2);
});
"""

_SETTINGS_JSON = json.dumps({
    "hooks": {
        "PreToolUse": [
            {"matcher": "Grep|Glob|Read|Bash",
             "hooks": [{"type": "command", "command": f"node {NUDGE_PATH}"}]}
        ]
    }
})


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


# Root step: ensure git + node toolchain (TS images usually have node; be safe).
_ROOT_STEP = InstallStep(
    user="root",
    env={"DEBIAN_FRONTEND": "noninteractive"},
    run=(
        "if command -v apt-get >/dev/null 2>&1; then "
        "  apt-get update && apt-get install -y git ca-certificates curl; "
        "elif command -v apk >/dev/null 2>&1; then "
        "  apk add --no-cache git nodejs npm bash curl; "
        "fi; true"
    ),
)

# Agent step: clone + build symnav, expose on PATH, and write the hook + settings.
_AGENT_STEP = InstallStep(
    user="agent",
    run=(
        'set -euo pipefail; '
        'export PATH="$HOME/.local/bin:$PATH"; '
        'mkdir -p "$HOME/.local/bin" ' + HOOK_DIR + '; '
        'command -v node >/dev/null 2>&1 || { echo "node missing in image" >&2; exit 1; }; '
        f'git clone --depth 1 {SYMNAV_REPO} "$HOME/symnav"; '
        'cd "$HOME/symnav"; '
        'corepack enable >/dev/null 2>&1 || npm install -g corepack >/dev/null 2>&1 || true; '
        'corepack prepare pnpm@latest --activate >/dev/null 2>&1 || npm install -g pnpm >/dev/null 2>&1; '
        'pnpm install --frozen-lockfile; '
        'pnpm build; '
        'printf \'#!/usr/bin/env bash\\nexec node "%s/symnav/apps/cli/dist/cli.js" "$@"\\n\' "$HOME" > "$HOME/.local/bin/symnav"; '
        'chmod +x "$HOME/.local/bin/symnav"; '
        f'echo {_b64(_NUDGE_JS)} | base64 -d > {NUDGE_PATH}; '
        f'echo {_b64(_SETTINGS_JSON)} | base64 -d > {SETTINGS_PATH}; '
        'symnav --version'
    ),
)


class SymnavClaudeCode(ClaudeCode):
    """claude-code with symnav installed + a one-time use-symnav nudge hook."""

    CLI_FLAGS = ClaudeCode.CLI_FLAGS + [
        CliFlag(kwarg="settings", cli="--settings", type="str", default=SETTINGS_PATH),
    ]

    def install_spec(self) -> AgentInstallSpec:
        spec = super().install_spec()
        spec.steps = [*spec.steps, _ROOT_STEP, _AGENT_STEP]
        return spec

    def network_allowlist(self) -> NetworkAllowlist:
        base = super().network_allowlist()
        return NetworkAllowlist(domains=sorted(set(base.domains) | set(_INSTALL_DOMAINS)))
