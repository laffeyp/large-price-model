# Sprint 106 -- Phase G audit (roadmap 079-082 spot-check + hook install + hook-wrapper bugfix)

---

```yaml
---
id: 106
status: closed
phase: G
pass_kind: architecture
determinism_budget: bit-deterministic
---
```

## scope

Verify the four Phase G roadmap items (079 logbook writer, 080 pre-commit hook, 081 held-out guard, 082 spec-invariant guard tests) all live in `HEAD` and behave. The errata block in `plans/v1-roadmap.md` claims all four landed bundled into earlier sprints. Spot-check each; install the commit-msg hook (script exists but was never symlinked); fix any drift.

## audit result

Item-by-item:

- **079 `experiments/logbook.csv` + `register_run.py`** -- both exist. `scripts/register_run.py` imports `LogbookEntry` + `append_run` from `price_space_llm.logbook`. `DEFAULT_LOGBOOK_PATH = Path("experiments/logbook.csv")`. `append_run` creates the parent dir on demand (`path.parent.mkdir(parents=True, exist_ok=True)`). Dry-run confirmed: writing one row produces a valid CSV with the 22-column tech-arch §13 header. Directory does not exist idle on disk; that is a design choice, not drift.
- **080 `check_test_look.sh` pre-commit hook** -- script exists at `scripts/check_test_look.sh`. `.git/hooks/commit-msg` symlink absent. **DRIFT.** Fixed: `ln -sf "$(pwd)/scripts/check_test_look.sh" .git/hooks/commit-msg`. Live-verified against a synthesized `configs/audit/heldout_probe.json` carrying `"2024-06-30"`: innocent commit message → hook blocks with a clear `BLOCKING commit. staged config files reference dates >= 2024-01-01 ...` message; `[test-look]` commit message → hook exits 0.
- **080 shell wrapper bugfix** -- while probing the hook, discovered the Sprint 064 shell wrapper had never worked. The line `"$PYTHON" - "$COMMIT_MSG_FILE" <<'PYEOF' <<<"$STAGED_FILES"` uses two competing stdin redirections; bash keeps only the last, so the heredoc Python script never reached the interpreter — Python instead received the staged-files list on stdin, tried to execute it as source, and failed with `NameError: name 'configs' is not defined`. The pure-Python `check_commit_for_test_look` was well-tested; the shell wrapper around it was not. Rewrote the wrapper to pipe staged files on stdin and pass the commit-message path as `argv`. **Named on card:** any commit signed with the broken hook would have exited 1 with a Python traceback, so the hook has provably never been active in this repo -- installing the symlink and running a real commit would have surfaced the bug immediately.
- **081 held-out guard** -- `src/price_space_llm/heldout_guard.py` exists. `scripts/evaluate.py` line 24 imports `register_test_look`; `--split test` requires `--i-know-this-is-a-test-look`. Wiring verified via grep; `tests/test_heldout_guard.py` passes.
- **082 spec-invariant guard tests** -- `tests/test_spec_guards.py` carries three functions: `test_no_hardcoded_target_in_source`, `test_no_hardcoded_target_helper_*` (2), `test_channel_source_of_truth_pt_matches_features_parquet`. Passes. The pre-commit-on-touched-src wiring is not present as a separate hook; the tests run in the normal pytest gate.

## deliverables

- `scripts/check_test_look.sh` -- rewrite. Piped-stdin form. Two paragraphs in the header docstring name the Sprint 064 bug + fix.
- `.git/hooks/commit-msg` -- symlink to `scripts/check_test_look.sh`. Operator-local state; not a repo file. Named in the sprint card so future clones know to run the same `ln -sf` command.
- `tests/test_check_test_look_shell.py` -- new. Four shell-level tests exercise the wrapper end-to-end with a stub `git` on `PATH`: (1) clean tree + clean message → exit 0; (2) clean-of-heldout-dates config + clean message → exit 0; (3) config with 2024-06-30 date + no `[test-look]` → exit 1 + "BLOCKING" in stderr; (4) same config + `[test-look]` in message → exit 0. Tests write a throwaway `configs/_sprint106_probe/heldout_probe.json` and clean it up.

## tests (+4)

Named above. Test count 600 → 604.

## artifact contract

Files modified:

- `scripts/check_test_look.sh` -- rewrite.
- `tests/test_check_test_look_shell.py` -- new.

Content assertions:

- `test -L .git/hooks/commit-msg`  (operator-local state; not in repo)
- `grep -q "git diff --cached --name-only" scripts/check_test_look.sh`
- `! grep -q "PYEOF.*STAGED_FILES" scripts/check_test_look.sh`

## signal contract

Zero. No emit surface touched.

## observation contract

Live-verified above. Innocent commit blocked; `[test-look]` commit passes; hook installed.

## commands

```
uv run ruff check .
uv run mypy
uv run pytest -q
```

## notes

- 1 code file + 1 test file + 1 operator-local symlink. Under hard rule 6.
- The commit-msg hook symlink is repo-local git state and does not travel with clones. Anyone checking out the repo needs to run `ln -sf "$(pwd)/scripts/check_test_look.sh" .git/hooks/commit-msg` once. Named on the sprint card.
- Phase G is now audit-clean. Sprint 107 opens next: pre-provisioning scaffolding for the AWS GPU rental (roadmap 083). AWS account `6488-7982-4221` (awsPro); CLI already authenticated. Hard cost boundaries land before any instance runs.
