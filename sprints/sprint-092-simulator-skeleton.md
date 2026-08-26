# Sprint 092 -- simulator skeleton (roadmap 074)

---

```yaml
---
id: 092
status: closed
phase: F
pass_kind: architecture
determinism_budget: bit-deterministic
---
```

## scope

Land the simulator's structural surface — package, bar walker, `SimResult` dataclass, three of the roadmap's four skeleton emits (`SIM_RUN_STARTED`, `BAR_PROCESSED`, `SIM_RUN_COMPLETED`). `PREDICTION_EMITTED` needs a model + forward pass and lands in Sprint 093 alongside the decision policy. Roadmap item 074. No cost model consumption yet; no positions; no trades; no metrics. Payload fields the skeleton cannot compute honestly (`checkpoint_step`, `sharpe_point`, `sharpe_se`, `block_bootstrap_positive_fraction`, `max_drawdown`, `time_to_recovery_bars`, `implied_capacity_at_this_size_usd`) land as zeros with a `notes` string in `SimResult` naming the skeleton scope. Sprint 093 replaces the zeros with real numbers.

## deliverables

- `src/price_space_llm/simulation/__init__.py` — new package.
- `src/price_space_llm/simulation/skeleton.py`:
  - `SimResult` dataclass carrying `n_bars_processed: int`, `n_trades: int`, `sharpe_point: float`, `sharpe_se: float`, `block_bootstrap_positive_fraction: float`, `max_drawdown: float`, `time_to_recovery_bars: int`, `implied_capacity_usd: float`, `notes: str`.
  - `run_simulation_skeleton(aligned_parquet_path, *, split, date_range_start, date_range_end, emitter, run_id, checkpoint_run_id="skeleton-no-checkpoint", cost_calibration_run_id="skeleton-no-calibration")`:
    - Emits `SIM_RUN_STARTED` with all required payload fields (checkpoint_step=0, placeholder run_ids per kwargs).
    - Reads the aligned parquet, filters `grid_ts` to `[date_range_start, date_range_end]` inclusive, iterates in order.
    - Emits `BAR_PROCESSED` per bar with the `grid_ts` timestamp.
    - Emits `SIM_RUN_COMPLETED` with n_bars_processed real; every other summary field 0.
    - Returns `SimResult` with `notes="skeleton; Sprint 093 replaces zeros with real numbers"`.
- `scripts/simulate.py` — CLI wrapper. Reads the aligned parquet path + split + date range; opens `script_session(run_kind="simulate", …)`; calls `run_simulation_skeleton`. Uses `heldout_guard.guard_heldout_parquet` when `--split test` (fail-loud on the held-out parquet without `--i-know-this-is-a-test-look`, matching Sprint 065 shape); the skeleton test run against a training-window parquet needs no acknowledgment.
- Tests in `tests/test_simulation_skeleton.py`.

## tests (+5)

1. `test_run_simulation_skeleton_emits_full_tag_sequence` — synthetic 3-row aligned parquet; emit trace shows `[SIM_RUN_STARTED, BAR_PROCESSED, BAR_PROCESSED, BAR_PROCESSED, SIM_RUN_COMPLETED]` in order.
2. `test_run_simulation_skeleton_filters_by_date_range` — aligned parquet with 10 rows across 3 dates; range covering 1 date → 4 bars processed (26 RTH bars/day is our real cadence; synthetic uses 4 rows/day to keep the test tiny).
3. `test_run_simulation_skeleton_returns_sim_result_with_zeroed_metrics` — SimResult.n_trades == 0, sharpe_point == 0.0, etc.; notes string contains "skeleton".
4. `test_simulate_cli_smoke_on_synthetic_parquet` — subprocess `scripts/simulate.py --aligned <synthetic> --split train --date-range-start 2020-01-01 --date-range-end 2020-01-02` exits 0; trace directory carries a `simulate-` run_id prefix; SIM_RUN_STARTED + SIM_RUN_COMPLETED both fire.
5. `test_simulate_cli_refuses_heldout_without_ack` — subprocess `scripts/simulate.py --aligned data/aligned/align-2024-01-2025-06-….parquet --split test` (no `--i-know-this-is-a-test-look`) exits nonzero with `HeldoutReadRefused` in stderr; skips if the heldout parquet isn't on disk.

## context files

- `src/price_space_llm/heldout_guard.py`
- `src/price_space_llm/script_harness.py`
- `src/price_space_llm/signals.py`
- `plans/v1-roadmap.md` § Phase F item 074
- `specs/technical-architecture-v4.md` § 11 (simulator)

## artifact contract

Files created or modified:

- `src/price_space_llm/simulation/__init__.py` — new.
- `src/price_space_llm/simulation/skeleton.py` — new.
- `scripts/simulate.py` — new.
- `tests/test_simulation_skeleton.py` — new.

Content assertions:

- `grep -q "class SimResult" src/price_space_llm/simulation/skeleton.py`
- `grep -q "SIM_RUN_STARTED" src/price_space_llm/simulation/skeleton.py`
- `grep -q "def main" scripts/simulate.py`

## signal contract

Emits: `SIM_RUN_STARTED`, `BAR_PROCESSED`, `SIM_RUN_COMPLETED` — all three exist in v0.7 vocab (added originally in v0.1 and confirmed present through v0.7). `PREDICTION_EMITTED` does not fire in this sprint; Sprint 093 wires it. The `SIM_RUN_COMPLETED` payload requires seven summary fields (`n_trades`, `sharpe_point`, `sharpe_se`, `block_bootstrap_positive_fraction`, `max_drawdown`, `time_to_recovery_bars`, `implied_capacity_at_this_size_usd`); every one lands at 0 or 0.0 with the `notes` in `SimResult` naming the skeleton scope. That is honest — a skeleton run produced zero trades and zero return, so the summary numbers zero out mathematically; not a fabrication.

## observation contract

REQUIRED — new package + new CLI. Live smoke on the real 2015-2022 training-window aligned parquet: skeleton walks 54,262 bars, fires 54,262 BAR_PROCESSED emits + one SIM_RUN_STARTED + one SIM_RUN_COMPLETED, exits 0 in under 10 seconds, produces zeros throughout the summary.

## commands

```
uv run ruff check .
uv run mypy
uv run pytest -q
uv run python scripts/simulate.py --aligned data/aligned/align-2015-01-2022-12-….parquet --split train --date-range-start 2020-01-01 --date-range-end 2020-01-31
```

## notes

- 3 code files + 1 test file. Under hard rule 6 for code files; new-package/new-CLI/new-test triad matches Sprint 087's ablation-infrastructure scope class.
- Sprint 093 next: load a checkpoint, wire `PREDICTION_EMITTED`, add the decision policy + cost model.
- `heldout_guard` reuse: the CLI does not duplicate the heldout-refuse logic; it calls the existing `guard_heldout_parquet` primitive (Sprint 065). Consistent with the Sprint 077 pattern of routing all heldout-facing scripts through one helper.
