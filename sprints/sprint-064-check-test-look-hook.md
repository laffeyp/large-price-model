# Sprint 064 -- check_test_look.sh pre-commit hook

---

```yaml
---
id: 064
status: closed
phase: 4
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Closes review § 3 aggregate-audit MEDIUM item: *"Pre-commit `check_test_look.sh` filesystem-date guard missing. Tech-arch §13 mandates it in addition to the runtime log."* Sprint 051 wired the runtime guard in `scripts/evaluate.py`; Sprint 064 adds the filesystem-date guard at commit time.

## deliverables

- `src/price_space_llm/hooks.py`: pure-Python `check_commit_for_test_look(commit_message, staged_files, config_globs)` returning `(should_block, reason)`. Blocks iff any staged file matches `configs/**/*.json`, `configs/**/*.yaml`, `configs/**/*.yml`, or `data/manifests/**/*.json` AND contains a `YYYY-MM-DD` date with `YYYY >= 2024` AND the commit message lacks `[test-look]`.
- `scripts/check_test_look.sh`: bash wrapper. Install via `ln -sf "$(pwd)/scripts/check_test_look.sh" .git/hooks/commit-msg`. Resolves staged files via `git diff --cached --name-only`, hands the list + commit-message file path to the Python check.
- Regex uses lookahead/lookbehind on digits (not `\b`) so ISO timestamps like `2025-06-30T20:00:00` match — the `T` after `30` is a word character and would otherwise break `\b`-boundary semantics.
- Uses `PurePath.full_match` (Python 3.13+) so `data/manifests/**/*.json` matches a file directly under `data/manifests/`.

Tests +7: no-staged; non-config file; heldout-date without token blocks; heldout-date with token permitted; pre-2024 date does not block; data/manifests path blocks; multiple dates reported.

## honest audit

- **Not installed automatically.** The hook lives in `scripts/check_test_look.sh`. Installation into `.git/hooks/commit-msg` is a one-line symlink documented in the script header. An automatic installer would break `.git/hooks` on machines where the user has their own hooks; the manual step is safer.
- **False-positive risk on YAML/JSON code samples with 2024 dates.** Low at v1; the config paths are narrow.

Tests +7. Count 401 → 408. Ruff + mypy + pytest green.
