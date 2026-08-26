# Sprint 097 -- simulator metrics + block bootstrap (roadmap 076)

---

```yaml
---
id: 097
status: closed
phase: F
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Replace Sprint 096's zeroed summary fields on `SIM_RUN_COMPLETED` with live numbers computed from the trade ledger. Roadmap 076. Every field the vocab declares gets a real value; hit-rate and per-trade P&L land in `SimResult` alongside. Sprint 098 = capacity sweep. Sprint 099 = kappa sensitivity plot.

Metric definitions per tech-arch § 11.5:

- **Sharpe (annualized)** = `sqrt(bars_per_year) × mean(bar_pnl) / std(bar_pnl)`. `bars_per_year = 6552` (252 days × 26 15-min RTH bars). `bar_pnl[t] = equity[t] − equity[t-1]` where `equity[t]` = cumulative `pnl_net` of trades closed on or before bar `t`. Sprint 097 first cut ignores mark-to-market of open positions; named on card.
- **Sharpe SE + block-bootstrap positive fraction.** 18 non-overlapping monthly blocks (546 bars each) × 10,000 resamples with replacement. Per resample: concatenate 18 sampled blocks, compute Sharpe, collect. SE = `std(resample_sharpes)`. `positive_fraction = mean(resample_sharpes > 0)`.
- **Max drawdown** = `max(cummax(equity) − equity) / max(cummax(equity), eps)`. Reported as positive fraction of peak equity. Zero when equity is monotone.
- **Time to recovery bars** = bar count from drawdown trough to first bar where equity re-touches the pre-drawdown peak. If unrecovered by run end: `bars_remaining`.
- **Hit rate** = `mean(1[pnl_net > 0])` across the trade ledger.

## deliverables

- `src/price_space_llm/simulation/metrics.py` — new:
  - `SimMetrics` dataclass carrying `sharpe_point`, `sharpe_se`, `block_bootstrap_positive_fraction`, `max_drawdown`, `time_to_recovery_bars`, `hit_rate`, `n_bars`, `n_trades`.
  - `build_equity_curve(trades, bar_timestamps_utc) -> Tensor[T]` — cumulative `pnl_net` at each bar per bisect on trade exit timestamps.
  - `compute_sharpe(bar_pnl, bars_per_year=6552) -> float` — zero-std guard.
  - `block_bootstrap_sharpe(bar_pnl, *, n_blocks=18, n_resamples=10000, bars_per_block=546, rng=None) -> tuple[float, float]` — returns `(sharpe_se, positive_fraction)`. Uses `numpy.random.Generator` for determinism; caller passes seed; test defaults `n_resamples=200` for speed.
  - `max_drawdown_from_equity(equity) -> tuple[float, int]` — returns `(max_dd_frac, trough_index)`.
  - `time_to_recovery_bars_from_equity(equity, trough_index) -> int`.
  - `compute_sim_metrics(trades, bar_timestamps_utc, *, bars_per_year=6552, n_resamples=10000, rng_seed=42) -> SimMetrics` — orchestrator.
- `src/price_space_llm/simulation/skeleton.py::run_simulation_with_trades` — call `compute_sim_metrics` before emitting `SIM_RUN_COMPLETED`; populate the real fields; `SimResult` gains the `SimMetrics` block.
- `SimResult` gains `metrics: SimMetrics | None` (None on skeleton runs; populated on Sprint 097+ trade runs).
- `src/price_space_llm/simulation/__init__.py` exports the new names.

## tests (+8)

1. `test_build_equity_curve_monotone_from_ledger` — three trades exit at t=10, 20, 30 with pnl_net [+100, -50, +30] → `equity[35] = 80`; `equity[10] = 100`; `equity[9] = 0`.
2. `test_compute_sharpe_zero_std_returns_zero` — constant bar_pnl → 0 without divide-by-zero.
3. `test_compute_sharpe_matches_hand_computed` — 100-bar synthetic bar_pnl with known mean/std → matches formula.
4. `test_max_drawdown_monotone_equity_returns_zero` — strictly increasing → 0 drawdown.
5. `test_max_drawdown_v_shape` — equity `[0, 100, 50, 150]` → dd = 0.5 at index 2.
6. `test_time_to_recovery_from_trough` — same V-shape → recovery at index 3 → 1 bar from trough.
7. `test_time_to_recovery_unrecovered_returns_bars_remaining` — trough at index 2 in `[0, 100, 50, 60]` → recovery bars = 1 (bar remaining).
8. `test_block_bootstrap_sharpe_reproducible_with_seed` — fixed rng_seed → identical `(se, positive_fraction)` across two calls; `positive_fraction ∈ [0, 1]`.

## artifact contract

Files created or modified:

- `src/price_space_llm/simulation/metrics.py` — new.
- `src/price_space_llm/simulation/skeleton.py` — extended: call metrics; populate `SIM_RUN_COMPLETED` real fields; add `metrics` to `SimResult`.
- `src/price_space_llm/simulation/__init__.py` — exports.
- `tests/test_simulation_metrics.py` — new.

Content assertions:

- `grep -q "class SimMetrics" src/price_space_llm/simulation/metrics.py`
- `grep -q "block_bootstrap_sharpe" src/price_space_llm/simulation/metrics.py`
- `grep -q "compute_sim_metrics" src/price_space_llm/simulation/skeleton.py`

## signal contract

Emits: `SIM_RUN_COMPLETED` payload now carries live numbers instead of zeros. Same six required fields per v0.7 schema — populated from `SimMetrics`. `implied_capacity_at_this_size_usd` stays at 0 until Sprint 098's capacity sweep.

## observation contract

REQUIRED — the SIM_RUN_COMPLETED payload's numeric fields go non-zero.

- **Input:** Sprint 096 real-corpus live smoke fixture (400-row slice, xs+10-step checkpoint, `_AlternatingLogitsModel` end-of-range flush) — actually use Sprint 094's real trained model + Sprint 096 policy so at least one trade lands and the metrics compute.
- **Expected:** `sharpe_point` is a finite float; `sharpe_se` ≥ 0; `block_bootstrap_positive_fraction ∈ [0, 1]`; `max_drawdown ∈ [0, 1]`; `time_to_recovery_bars ≥ 0`; `hit_rate ∈ [0, 1]`.
- **Live smoke on real corpus:** report all six with actual numbers.

## commands

```
uv run ruff check .
uv run mypy
uv run pytest -q
```

## notes

- 2 code files + 1 test file. Under hard rule 6.
- Test-side default `n_resamples=200` for speed; production caller uses spec's 10,000.
- Named approximation: `equity[t]` counts trades exited **on or before** bar `t`. Mark-to-market of currently-open positions ignored; Sprint 099+ may refine if the metric drift matters.
- `numpy` already in the project deps (imported in `evaluation/metrics.py`).
