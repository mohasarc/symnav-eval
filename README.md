# symnav-eval

Grades the symnav pilot's patches with the [SWE-PolyBench](https://github.com/amazon-science/SWE-PolyBench)
harness on GitHub Actions x86 runners — because the pre-built images are
inaccessible via GHCR and don't build on Apple Silicon under emulation.

## What's here
- `predictions/<arm>-rep<n>.jsonl` — the agent patches (`{instance_id, model_patch}`), 6 groups (symnav vs stock × 3 reps).
- `polybench_subset.csv` — the 25 TypeScript SWE-PolyBench instances (full rows), so the grader only builds the TypeScript base image.
- `.github/workflows/grade.yml` — matrix over the 6 groups, each on a native-x86 `ubuntu-latest` runner.

## Run
Actions → **grade** → Run workflow (blank = all 6 groups; or e.g. `symnav-rep0,stock-rep0`).

Each job: frees runner disk, clones + installs the grader, restores prior results (resume), runs `run_evaluation.py --delete-image --skip-existing`, uploads `*_result.json` as the `results-<group>` artifact. Re-run to resume any group that timed out.

## Collect
Download the artifacts and fold into the pilot's `grades.json`:
```sh
gh run download <run-id> -D artifacts
# then in the symnav repo: map artifacts/results-<group>/*_result.json -> eval/results/eval_logs/<group>/ and run: python eval/grade.py --collect
```
`<id>_result.json` carries `resolved` (bool), `all_f2p_passed`, `passed_tests`, etc.
