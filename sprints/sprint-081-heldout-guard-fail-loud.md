# Sprint 081 -- heldout_guard fail-loud on unrecognized artifact shapes

---

```yaml
---
id: 081
status: closed
phase: E
pass_kind: architecture
determinism_budget: bit-deterministic
---
```

## scope

Close 2026-08-16 § 11 drift-watchlist entry (heldout_guard filename brittleness). Pre-Sprint-081 `parquet_range_starts_in_heldout(path)` returned False on any filename that did not match `align-YYYY-MM-` — silently permitting reads on unknown artifact shapes. Sprint 078's new `tokens.<run_id>.pt` shape would have slipped the guard entirely.

## deliverables

- `KNOWN_DATED_PATTERNS` tuple in `src/price_space_llm/heldout_guard.py` listing every current dated-artifact filename convention (aligned/features-aligned parquet; Sprint 078 tokens.<run_id>.pt).
- `UnrecognizedArtifactShape(RuntimeError)`.
- `parquet_range_starts_in_heldout(path, *, allow_unrecognized=False)` iterates the patterns; matches → check year; no match → raises unless `allow_unrecognized=True`.
- `guard_heldout_parquet(path, *, allow_test_look=False, allow_unrecognized=False)` passes the flag through.
- `__all__` exports `UnrecognizedArtifactShape` and `KNOWN_DATED_PATTERNS`.

## tests

- Replaced `test_unrelated_filename_is_not_heldout` (asserted silent False) with `test_unrelated_filename_raises_by_default` (asserts fail-loud) + `test_unrelated_filename_permits_with_allow_unrecognized` (asserts opt-out) + `test_tokens_pt_versioned_filename_detected_as_heldout` (Sprint 078 pattern coverage). Net +2.
