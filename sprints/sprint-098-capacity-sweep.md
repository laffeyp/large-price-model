# Sprint 098 -- capacity sweep + CAPACITY_SWEEP_COMPLETED (roadmap 077)

---

```yaml
---
id: 098
status: closed
phase: F
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Sweep `position_size_usd` across a log-spaced grid; run `run_simulation_with_trades` at each size; report the largest size where Sharpe stayed positive as `capacity_usd`. Roadmap 077. Sprint 099 = kappa sensitivity plot (final Phase F sprint).

## deliverables

- `src/price_space_llm/simulation/capacity.py` — new:
  - `CapacityPoint` dataclass carrying `size_usd`, `sharpe`, `sharpe_se`.
  - `CapacitySweepResult` dataclass carrying `points: tuple[CapacityPoint, ...]`, `capacity_usd: float`, `sharpe_at_capacity: float`.
  - `run_capacity_sweep(artifact, model, bucket_stats, policy_template, sizes_usd, *, target_symbol, emitter, run_id, checkpoint_run_id, cost_calibration_run_id, split, date_range_start, date_range_end) -> CapacitySweepResult`:
    - For each `size in sizes_usd`: build a `PolicyConfig` from `policy_template` with `position_size_usd=size`; call `run_simulation_with_trades` (per-size sim fires its own `SIM_RUN_STARTED` + `SIM_RUN_COMPLETED` with a size-tagged sub-run_id `{run_id}-cap-{size_usd:012d}`); extract `metrics.sharpe_point` and `metrics.sharpe_se`.
    - `capacity_usd = max(size for point in points if point.sharpe > 0)`; if none positive → 0.0.
    - `sharpe_at_capacity` = the Sharpe at that size, or 0.0.
    - Emit `CAPACITY_SWEEP_COMPLETED` with the `points` list-of-structs + `capacity_usd` + `sharpe_at_capacity`.
- `simulation/__init__.py` exports.

## tests (+6)

1. `test_capacity_sweep_result_has_one_point_per_size` — synthetic model + 3-size sweep produces 3 CapacityPoint entries.
2. `test_capacity_sweep_capacity_usd_is_largest_positive_sharpe_size` — hand-scripted scenario where sharpe positive at sizes [1, 3] and negative at [10] → capacity_usd = 3.
3. `test_capacity_sweep_all_negative_returns_zero_capacity` — every point negative → capacity_usd = 0.0.
4. `test_capacity_sweep_all_positive_returns_max_size` — every point positive → capacity_usd = max(sizes_usd).
5. `test_capacity_sweep_emits_completed_tag` — verify one `CAPACITY_SWEEP_COMPLETED` emit fires per sweep, payload carries the `points` list.
6. `test_capacity_sweep_emits_one_sim_run_pair_per_size` — verify N SIM_RUN_STARTED + N SIM_RUN_COMPLETED for N-size sweep.

## artifact contract

Files created or modified:

- `src/price_space_llm/simulation/capacity.py` — new.
- `src/price_space_llm/simulation/__init__.py` — exports.
- `tests/test_simulation_capacity.py` — new.

Content assertions:

- `grep -q "class CapacitySweepResult" src/price_space_llm/simulation/capacity.py`
- `grep -q "CAPACITY_SWEEP_COMPLETED" src/price_space_llm/simulation/capacity.py`

## signal contract

Emits `CAPACITY_SWEEP_COMPLETED` (v0.7 vocab; category `simulate`, stratum `summary`) with four required payload fields: `run_id`, `points: list<struct<size_usd:float, sharpe:float, sharpe_se:float>>`, `capacity_usd: float`, `sharpe_at_capacity: float`. Per-size `SIM_RUN_STARTED` + `SIM_RUN_COMPLETED` fire from the nested walker calls; the sweep emits the summary tag once at close.

## observation contract

REQUIRED — the sweep tag fires for the first time in live code.

- **Input:** synthetic .pt + `_AlternatingLogitsModel` from Sprint 094/096 fixtures + 3-size sweep `[1M, 3M, 10M]`.
- **Expected trace:** three `SIM_RUN_STARTED` + three `SIM_RUN_COMPLETED` + one `CAPACITY_SWEEP_COMPLETED`.
- **Expected behavior:** `CapacitySweepResult.points` has three entries; `capacity_usd` is the largest positive-Sharpe size or 0.
- **Live smoke on real corpus:** 5-size sweep `[100K, 300K, 1M, 3M, 10M]` on 2000-row slice with xs+10-step checkpoint; report each per-size Sharpe + final `capacity_usd`.

## commands

```
uv run ruff check .
uv run mypy
uv run pytest -q
```

## notes

- 2 code files + 1 test file. Under hard rule 6.
- Log-spaced default sizes matches spec's "$100K through $10M in ~10 steps"; card ships a 5-point default and lets the caller override.
- Sprint 099 (kappa sensitivity plot) uses the same nested-run pattern with a `kappa_scale` sweep parameter instead of `size_usd`.
- Per-size `run_id` embeds size in the payload; the sweep's parent `run_id` is the outer session id. Vocabulary allows multiple SIM_RUN_STARTED/SIM_RUN_COMPLETED emits per session; the pairs are events + summaries, not at-most-once-per-session.
