# Sprint 067 -- regime evaluator switches to real VIX

---

```yaml
---
id: 067
status: closed
phase: 4
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Closes review § 3 aggregate-audit MEDIUM item: *"Regime evaluator ignores real VIX. `evaluation/regimes.py:5-10` + `evaluation/evaluate.py:109` still bucket regimes from `target__{sym}__rolling_std_20`, though Sprint 038 landed VIX in the aligned frame."*

## deliverables

- `_load_features_and_tokens` in `evaluation/evaluate.py` prefers `market_context__VIX__close` when the column is present; falls back to `target__{sym}__rolling_std_20` on features parquets that predate Sprint 038.
- `VIX_LEVEL_COL` constant surfaced so a follow-up sprint can rename the column without touching callers.
- Docstring update in `regimes.py` reflecting the switch.
- Tests +3: prefers-VIX; falls-back-to-rolling-std; raises when neither column present.

## honest audit

- **Back-compat preserved.** Any old features parquet without the VIX column still evaluates via the rolling-std proxy.
- **Doesn't switch tokenizer or trainer.** Only the evaluator's regime partitioning changes. The tokenizer still uses `realized_vol_30` for vol normalization (spec §7.1); that is a distinct concern.

Tests +3. Count 419 → 422. Ruff + mypy + pytest green.
