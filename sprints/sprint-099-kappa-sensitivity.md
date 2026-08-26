# Sprint 099 -- kappa sensitivity plot + SENSITIVITY_PLOT_GENERATED (roadmap 078)

---

```yaml
---
id: 099
status: closed
phase: F
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Sweep a `kappa_multiplier` grid against a baseline `slippage_frac`, run `run_simulation_with_trades` at each, emit `SENSITIVITY_PLOT_GENERATED` with the `(multiplier, sharpe)` list plus the Layer-7 gate flag `sharpe_crosses_zero_in_range`. Roadmap 078. Final Phase F sprint.

Mechanics reuse Sprint 098's nested-run pattern with `slippage_frac` overrides instead of `position_size_usd`. Sprint 096 named the linearization: `slippage_frac × |size|` approximates `kappa × size²`; multiplying `slippage_frac` by `m` scales the linearized kappa cost by the same `m` at fixed size.

## deliverables

- `src/price_space_llm/simulation/sensitivity.py` -- new:
  - `SensitivityPoint` frozen dataclass carrying `kappa_multiplier`, `sharpe`, `sharpe_se`.
  - `SensitivityPlotResult` frozen dataclass carrying `points: tuple[SensitivityPoint, ...]`, `min_sharpe`, `max_sharpe`, `sharpe_crosses_zero_in_range: bool`, `per_multiplier_results: tuple[SimResult, ...]`.
  - `run_kappa_sensitivity(artifact, model, bucket_stats, policy_template, kappa_multipliers, *, target_symbol, emitter, run_id, checkpoint_run_id, cost_calibration_run_id, split, date_range_start, date_range_end) -> SensitivityPlotResult`:
    - For each `m in kappa_multipliers`: `policy = replace(policy_template, slippage_frac=policy_template.slippage_frac * m)`; sub_run_id = `f"{run_id}-kappa-{m:0.4f}"`; call `run_simulation_with_trades`; extract `metrics.sharpe_point` and `metrics.sharpe_se`.
    - `min_sharpe = min(point.sharpe for point in points)`, `max_sharpe = max(point.sharpe for point in points)`.
    - `sharpe_crosses_zero_in_range = (min_sharpe < 0.0) and (max_sharpe > 0.0)`. Both strict; a flat-Sharpe-zero sweep does not "cross."
    - Emit `SENSITIVITY_PLOT_GENERATED` with `run_id`, `kappa_multipliers: list<float>`, `sharpe_by_multiplier: list<float>`, `min_sharpe`, `max_sharpe`, `sharpe_crosses_zero_in_range`.
- `simulation/__init__.py` exports.

## tests (+7)

1. `test_sensitivity_result_has_one_point_per_multiplier` -- 5-multiplier sweep produces 5 points in input order.
2. `test_sensitivity_crosses_zero_true_when_positive_and_negative` -- stubbed sim with sharpe > 0 at some multipliers and sharpe < 0 at others -> flag True.
3. `test_sensitivity_crosses_zero_false_when_all_positive` -- stubbed all-positive -> False.
4. `test_sensitivity_crosses_zero_false_when_all_negative` -- stubbed all-negative -> False.
5. `test_sensitivity_emits_generated_tag_once` -- one `SENSITIVITY_PLOT_GENERATED` per sweep; payload keys and shape match vocab.
6. `test_sensitivity_emits_one_sim_run_pair_per_multiplier` -- N SIM_RUN_STARTED + N SIM_RUN_COMPLETED for N-multiplier sweep.
7. `test_sensitivity_rejects_empty_multipliers` -- `ValueError` with fix-path message.

## artifact contract

Files created or modified:

- `src/price_space_llm/simulation/sensitivity.py` -- new.
- `src/price_space_llm/simulation/__init__.py` -- exports.
- `tests/test_simulation_sensitivity.py` -- new.

Content assertions:

- `grep -q "class SensitivityPlotResult" src/price_space_llm/simulation/sensitivity.py`
- `grep -q "SENSITIVITY_PLOT_GENERATED" src/price_space_llm/simulation/sensitivity.py`

## signal contract

Emits `SENSITIVITY_PLOT_GENERATED` (v0.7 vocab; category `simulate`, stratum `summary`) with six required payload fields per spec: `run_id`, `kappa_multipliers: list<float>`, `sharpe_by_multiplier: list<float>`, `min_sharpe: float`, `max_sharpe: float`, `sharpe_crosses_zero_in_range: bool`. Per-multiplier `SIM_RUN_STARTED` + `SIM_RUN_COMPLETED` fire from the nested walker calls.

## observation contract

REQUIRED -- the sensitivity tag fires for the first time in live code.

- **Input:** synthetic artifact + stubbed sim + 5-multiplier sweep `[0.5, 0.75, 1.0, 1.25, 1.5]`.
- **Expected trace:** five `SIM_RUN_STARTED` + five `SIM_RUN_COMPLETED` + one `SENSITIVITY_PLOT_GENERATED`.
- **Live smoke on real corpus:** 6-multiplier sweep `[0.5, 0.75, 1.0, 1.25, 1.5, 2.0]` on 2000-row slice with xs+8-step checkpoint, baseline `slippage_frac=2e-4`; report each per-multiplier Sharpe + `sharpe_crosses_zero_in_range`.

## commands

```
uv run ruff check .
uv run mypy
uv run pytest -q
```

## notes

- 2 code files + 1 test file. Under hard rule 6.
- Kappa-linearization named in Sprint 096: `slippage_frac × |size|` approximates `kappa × size²`. Scaling `slippage_frac` by `m` scales the linearized cost by `m` at a fixed size.
- Spec § 'Success gates for v1' names `sharpe_crosses_zero_in_range` as the Layer-7 gate; a robust reported number requires this flag be False.
- Closes Phase F. Phase G guards mostly landed; Phase H opens next -- rented-GPU sweeps.
