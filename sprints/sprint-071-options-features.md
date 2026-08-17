# Sprint 071 -- options features (20-trading-day rolling z-score)

---

```yaml
---
id: 071
status: closed
phase: 3
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Ships spec § 6 options feature: `z_score_20d` on `options__PCR_SPY` + `options__VOL_SPY`. Staleness pair already lives on the aligned parquet from Sprint 042.

## deliverables

- `OPTIONS_FEATURE_SPECS = ("z_score_20d",)` + `OPTIONS_ROLLING_WINDOW = 20 * BARS_PER_RTH_DAY` (= 520 bars).
- `compute_features` gains `options` branch: `close.rolling_mean(520, min_samples=520)` + `close.rolling_std(520, min_samples=520)`; z-score with the divide-by-zero guard. `min_samples` forces null before the full window fills.
- `_classify_failure` handles `z_score_20d` (insufficient_history through row `OPTIONS_ROLLING_WINDOW - 2`; divide_by_zero when rolling_std=0 on constant runs).
- Per-channel counting in `run_feature_pipeline` gains an `options` branch.

## honest audit

- **Polars rolling window semantics.** Rolling at position `i` covers indices `i-W+1..i` inclusive. Full-window at position `W-1`. Test asserts null through `W-2` and value at `W-1`, matching Polars convention. `min_samples=W` enforces null-until-full rather than min-samples=1 (Polars default).
- **Constant runs → null via divide_by_zero.** Options-VOL_SPY at v1 has real daily variation, but the guard is defensive.

Tests +2. Count 428 → 430. Ruff + mypy + pytest green.
