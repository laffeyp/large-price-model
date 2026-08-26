# Sprint 104 -- Phase-G structure cleanup: extract position helpers + shared axis-sweep helper

---

```yaml
---
id: 104
status: closed
phase: G
pass_kind: architecture
determinism_budget: bit-deterministic
---
```

## scope

Two structural refactors from the Phase F review that reduce line counts and remove duplication without changing behavior.

- §2.69 extract position transition helpers (`_close_position_and_record`, `_emit_position_opened`, `_emit_position_closed`, `_emit_trade_ledgered`) from `skeleton.py` (currently 731 lines) into `positions.py` alongside the `Position` + `Trade` dataclasses. Cluster the position machinery in one module.
- §6.2 factor `capacity.py` and `sensitivity.py` -- both currently iterate a knob via `dataclasses.replace(policy_template, ...)`, call `run_simulation_with_trades` per point, extract `metrics.sharpe_point`+`metrics.sharpe_se`, emit a summary tag. New helper `_run_axis_sweep` in a new `simulation/sweeps.py` module removes the shared shape.

## deliverables

- `src/price_space_llm/simulation/positions.py` -- receive the four helpers verbatim from `skeleton.py`. Their `Trade`/`Position`/`compute_pnl`/`StrictSignalEmitter` imports move with them.
- `src/price_space_llm/simulation/skeleton.py` -- remove the four helpers; import them from `positions.py`; ~130 lines drop.
- `src/price_space_llm/simulation/sweeps.py` -- new module. `_run_axis_sweep(artifact, model, bucket_stats, policy_template, values, *, policy_field, sub_run_id_format, emitter, run_id, checkpoint_step, checkpoint_run_id, cost_calibration_run_id, split, date_range_start, date_range_end, target_symbol) -> tuple[list[SimResult], list[tuple[float, float, float]]]` — for each `v in values`, `policy = replace(policy_template, **{policy_field: v * base_value})`; run walker; return `(per_value_results, [(value, sharpe, sharpe_se), ...])`.
- `src/price_space_llm/simulation/capacity.py` -- delegate to `_run_axis_sweep` with `policy_field="position_size_usd"`, `sub_run_id_format="{run_id}-cap-{int_value:012d}"`. Emit tag composition stays in `capacity.py`.
- `src/price_space_llm/simulation/sensitivity.py` -- symmetric: `policy_field="slippage_frac"`, `sub_run_id_format="{run_id}-kappa-{value:0.4f}"`, `base_value=policy_template.slippage_frac`.

## tests (+2)

1. `test_sweeps_helper_forwards_kwargs_to_walker` -- verify each nested walker call receives the expected kwargs and axis value.
2. `test_run_capacity_sweep_and_run_kappa_sensitivity_produce_identical_output_before_and_after_refactor` -- pin numerical output on the two smoke-test fixtures against the Sprint 102 values.

Every existing test on both sweeps passes unchanged; those are the primary regression fence.

## artifact contract

Files created or modified:

- `src/price_space_llm/simulation/positions.py` -- receives helpers.
- `src/price_space_llm/simulation/skeleton.py` -- shrinks by ~130 lines.
- `src/price_space_llm/simulation/sweeps.py` -- new.
- `src/price_space_llm/simulation/capacity.py` -- delegate.
- `src/price_space_llm/simulation/sensitivity.py` -- delegate.
- `src/price_space_llm/simulation/__init__.py` -- export `sweeps` symbols if any land in the public surface (probably not — `_run_axis_sweep` stays private).
- `tests/test_simulation_sweeps_helper.py` -- new.
- 6 code files + 1 test file. At hard-rule-6 limit.

Content assertions:

- `grep -q "def _close_position_and_record" src/price_space_llm/simulation/positions.py`
- `! grep -q "def _close_position_and_record" src/price_space_llm/simulation/skeleton.py`
- `test -f src/price_space_llm/simulation/sweeps.py`

## signal contract

No new tags. Every payload identical.

## observation contract

Re-run Sprint 100 + Sprint 098 + Sprint 099 smoke; assert every numeric field identical.

## commands

```
uv run ruff check .
uv run mypy
uv run pytest -q
```

## notes

- 6 code files. Hard-rule-6 limit.
- Sprint 105 next: walker → hooks refactor (§2 main). Larger diff, own sprint arc.
