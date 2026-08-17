# Sprint 069 -- cross-asset features (spec § 6 line 306)

---

```yaml
---
id: 069
status: closed
phase: 3
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Closes the biggest remaining Phase B gap — cross-asset features on the 8 `market_context` symbols per spec § 6 line 306: *"Market-context symbols (QQQ, IWM, VIX, TLT, DXY, GLD, USO) get log_return, realized_vol_30, volume_z_100, bar_shape. VIX additionally emits vix_level and vix_change."*

## deliverables

- `CROSS_ASSET_FEATURE_SPECS = ("realized_vol_30", "volume_z_100", "bar_shape")` — log_return already ships from base pass.
- `VIX_FEATURE_SPECS = ("vix_level", "vix_change")` — VIX-only.
- `compute_features` gains a `market_context` branch: bar_shape + volume_z_100 + realized_vol_30 arithmetic mirrors the target block (minus range_pct / dollar_volume / spread_proxy, which stay target-only). VIX-only nested block adds vix_level (= close) + vix_change (= close - close.shift(1)) per CBOE absolute vol-point convention.
- `_classify_failure` gains `vix_change` insufficient-history branch (row 0 null via shift).
- `run_feature_pipeline` per-channel count logic extended for market_context (+ CROSS_ASSET_FEATURE_SPECS + 2 more for VIX).

## honest audit

- **VIX `volume_z_100` is honest all-null.** VIX INDEX_DATA carries `volume=0` per Sprint 042 note. Rolling std of zeros is zero; the div-by-zero guard flips to null; every row emits `FEATURE_COMPUTATION_FAILED.reason=divide_by_zero`. VXX carries the real VIX-ecosystem volume signal per Sprint 050 substitution.
- **`vix_change` uses absolute delta, not log-change.** VIX is a percentage quantity; CBOE reports absolute vol-point changes. Log-return of a percentage would fold the log through twice.
- **Existing test rename.** `test_non_target_channels_get_no_target_features` renamed to `test_target_only_features_do_not_leak_to_market_context` — the assertion changed (bar_shape now DOES land on market_context; only range_pct / dollar_volume / spread_proxy stay target-only).

Tests +2 (VIX vix_level/vix_change, non-VIX market_context has no VIX features). One existing test updated. Test count 424 → 426. Files touched: 2 (features/compute.py, tests/test_features.py). Ruff + mypy + pytest green.
