"""Custom Pier agents that add symnav to the sandbox and steer the model to use it.

Referenced from a job config via:
    import_path: symnav_agent:SymnavClaudeCode

They subclass Pier's stock CLI agents and (1) append install steps that clone +
build symnav and put it on PATH, (2) widen the network allowlist so those install
steps can reach GitHub/npm inside the air-gapped sandbox. The "use symnav" firm
directive is passed separately via the agent's `append_system_prompt` kwarg
(natively supported by the claude-code driver).
"""

from pier.agents.installed.claude_code import ClaudeCode
from pier.agents.network import NetworkAllowlist
from pier.models.agent.install import AgentInstallSpec, InstallStep

SYMNAV_REPO = "https://github.com/mohasarc/symnav.git"

# Domains the symnav clone+build needs while the sandbox is air-gapped.
_SYMNAV_INSTALL_DOMAINS = [
    "github.com",
    "codeload.github.com",
    "objects.githubusercontent.com",
    "raw.githubusercontent.com",
    "registry.npmjs.org",
    "nodejs.org",
]

# Root step: make sure git + a node toolchain exist (TS task images usually have
# node already, but be defensive).
_SYMNAV_ROOT_STEP = InstallStep(
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

# Agent step: clone, build, and expose `symnav` on PATH via a wrapper.
_SYMNAV_AGENT_STEP = InstallStep(
    user="agent",
    run=(
        'set -euo pipefail; '
        'export PATH="$HOME/.local/bin:$PATH"; '
        'mkdir -p "$HOME/.local/bin"; '
        'command -v node >/dev/null 2>&1 || { echo "node missing in image" >&2; exit 1; }; '
        f'git clone --depth 1 {SYMNAV_REPO} "$HOME/symnav"; '
        'cd "$HOME/symnav"; '
        'corepack enable >/dev/null 2>&1 || npm install -g corepack >/dev/null 2>&1 || true; '
        'corepack prepare pnpm@latest --activate >/dev/null 2>&1 || npm install -g pnpm >/dev/null 2>&1; '
        'pnpm install --frozen-lockfile; '
        'pnpm build; '
        'printf \'#!/usr/bin/env bash\\nexec node "%s/symnav/apps/cli/dist/cli.js" "$@"\\n\' "$HOME" '
        '  > "$HOME/.local/bin/symnav"; '
        'chmod +x "$HOME/.local/bin/symnav"; '
        'symnav --version'
    ),
)


class SymnavClaudeCode(ClaudeCode):
    """claude-code with symnav installed in the sandbox."""

    def install_spec(self) -> AgentInstallSpec:
        spec = super().install_spec()
        spec.steps = [*spec.steps, _SYMNAV_ROOT_STEP, _SYMNAV_AGENT_STEP]
        return spec

    def network_allowlist(self) -> NetworkAllowlist:
        base = super().network_allowlist()
        return NetworkAllowlist(
            domains=sorted(set(base.domains) | set(_SYMNAV_INSTALL_DOMAINS))
        )
