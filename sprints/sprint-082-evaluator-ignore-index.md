# Sprint 082 -- evaluator ignore-index filter in _metrics_over_positions

---

```yaml
---
id: 082
status: closed
phase: E
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Real correctness gap in the evaluator on the market-state feats path: `_metrics_over_positions` in `src/price_space_llm/evaluation/evaluate.py` passed last-position targets straight into `compute_metric_set` without stripping the -100 sentinel. `TokenizedArtifact.targets` (Sprint 052) carries -100 for null log-return rows; the sentinels landed in every metric's denominator with a garbage bucket id. `compute_nll` invoked `probs.gather(1, -100)` picking the last row's probability, `top-1` / `top-3` / `dir_acc` compared preds against -100 and always missed (deflating hit rate), `compute_brier` scattered to an invalid row.

## deliverables

- `IGNORE_INDEX = -100` module constant in `evaluation/evaluate.py`.
- `_metrics_over_positions` filters `last_targets != IGNORE_INDEX` before invoking `compute_metric_set`.
- Empty-after-filter path returns a clean zero-metric MetricSet with `n_examples=0`.
- No signal-side change; no vocab bump.

## tests +2

- `test_metrics_over_positions_filters_ignore_index` — synthetic 4-window probs where three targets are valid + one is -100; asserts `n_examples == 3` and `top-1 == 2/3`.
- `test_metrics_over_positions_all_ignore_index_returns_empty` — every last-position target -100 → empty MetricSet, no errors.
