# Sprint 068 -- evaluator MarketStateTransformer path

---

```yaml
---
id: 068
status: closed
phase: 4
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Closes the loop between Sprint 053 (MarketStateTransformer + Sprint 052 .pt artifact) and Sprint 088 (first held-out evaluation). Before Sprint 068 the evaluator only knew how to load `PriceSpaceLLM` from bucket-ID checkpoints; a Sprint 053 checkpoint would have failed at load time.

## deliverables

- `_load_market_state_checkpoint(path)` — reconstructs `MarketStateTransformer` from a Sprint 053 `.pt` payload.
- `_checkpoint_is_market_state(path)` — detects the kind by presence of `channel_dims` in the saved config.
- `_deterministic_windows_feats(artifact, context_len, offset, count)` — slices per-channel feature tensors + targets covering `count` valid starts from `offset`.
- `_forward_all_feats_in_batches(model, feats, batch_size)` — runs the market-state forward in batches.
- `run_evaluation_feats(...)` — end-to-end path parallel to `run_evaluation`. Same emit surface: `REGIME_LABELS_FROZEN` + `METRIC_COMPUTED` × 7 × splits × regimes + `BUCKET_FREQUENCY_DRIFT_MEASURED` + `METRIC_SNAPSHOT_WRITTEN`. Metrics JSON carries `checkpoint_kind: "market_state"` so downstream analysis distinguishes the two kinds.
- `scripts/evaluate.py --tokens-pt PATH` mutually exclusive with `--tokens`; dispatches to `run_evaluation_feats`; refuses if the checkpoint isn't a market-state one.
- Tests +2: checkpoint kind detection; end-to-end feats path produces the full emit surface + writes `checkpoint_kind: market_state` in metrics.json.

## honest audit

- **Some duplication with `run_evaluation`.** Regime-scoring + snapshot logic repeats. Extraction into shared helpers deferred to a cleanup sprint after both paths have shipped concrete downstream users.
- **Feats path evaluates the WHOLE artifact (train + val).** Same shape as the bucket-ID path. Sprint 088's held-out flow will pass the test-window .pt as `--tokens-pt` + `--split test` to consume a look via Sprint 051's guard.
- **`run_evaluation_feats` does not yet run through `heldout_guard.guard_heldout_parquet`.** The Sprint 065 guard fires on aligned/features parquets; the .pt artifact isn't guarded yet. Follow-up: extend the guard to `data/tokenized/*.pt` filenames matching the same date-range pattern.

Tests +2. Count 422 → 424. Ruff + mypy + pytest green.
