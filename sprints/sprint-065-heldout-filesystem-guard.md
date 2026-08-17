# Sprint 065 -- filesystem guard on held-out aligned parquet

---

```yaml
---
id: 065
status: closed
phase: 4
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Closes review § 3 aggregate-audit MEDIUM item: filesystem guard on `data/aligned/*.parquet` for held-out reads. Third leg of the test-look defense:

1. Runtime guard on `scripts/evaluate.py --split test` (Sprint 051 wired).
2. Commit-time guard via `check_test_look.sh` (Sprint 064 wired).
3. **Filesystem guard on aligned parquet reads** (Sprint 065, this).

## deliverables

- `src/price_space_llm/heldout_guard.py`:
  - `HeldoutReadRefused` exception.
  - `parquet_range_starts_in_heldout(path)` — True iff filename matches `align-YYYY-MM-...` or `features-align-YYYY-MM-...` with `YYYY >= 2024`.
  - `guard_heldout_parquet(path, *, allow_test_look=False)` — raises `HeldoutReadRefused` unless the caller acknowledges.
- `scripts/features.py` gains `--allow-test-look` flag; guards the aligned parquet read; exits 2 on refusal.
- `scripts/bucketize.py` same treatment for the features parquet read.
- Tests +7: aligned prefix detection; features-align prefix detection; pre-2024 not held-out; unrelated filename not held-out; raises without flag; permits with flag; permits pre-2024 without flag.

## honest audit

- **Filename-based detection.** Parses the aligned parquet naming convention (`align-{YYYY}-{MM}-...`). If a downstream sprint renames the artifact, the guard silently permits everything until updated. Callers that rename should also update `ALIGNED_FILENAME_PATTERN`.
- **The guard does not check `experiments/test_looks.log`.** That is the caller's contract — `allow_test_look=True` is an acknowledgment, not proof the operator registered a look. Sprint 051's `--split test` guard in `evaluate.py` is the authoritative registration point.

Tests +7. Count 408 → 415. Ruff + mypy + pytest green.
