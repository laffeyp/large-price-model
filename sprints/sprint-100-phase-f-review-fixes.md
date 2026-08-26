# Sprint 100 -- Phase F review-close fixes: mark-to-market, NaN guards, drawdown fallback

---

```yaml
---
id: 100
status: closed
phase: F.close
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Close six items from `reviews/full-review-phase-f-close.md`:

- §4.1 mark-to-market equity (largest correctness item — the pre-registered Sharpe gates depend on it).
- §4.3 absolute-drawdown fallback when peak is zero.
- §4.5 NaN `raw_target` skip in the walker.
- §6.4 NaN-probs guard on `variance_vn` and `derive_prediction_scalars`.
- §6.5 non-positive `exit_price` guard on `compute_pnl`.

The other Phase-G-shaped items (walker refactor, prices/searchsorted vectorization, checkpoint-kwargs fail-loud, bootstrap vectorization) file to their own sprints. Sprint 101 = required checkpoint kwargs; Sprint 102 = bootstrap vectorization.

## deliverables

- `src/price_space_llm/simulation/positions.py` -- extend:
  - `Trade` dataclass gains `entry_price: float`, `exit_price: float`. Downstream mark-to-market needs both; the walker knows both at construction time.
  - `compute_pnl` gains a symmetric non-positive/non-finite `exit_price` guard mirroring the entry-price guard.
- `src/price_space_llm/simulation/metrics.py` -- extend:
  - `build_equity_curve` gains a keyword-only `prices: np.ndarray | None = None`. When `None`, current closed-trade step-function behavior. When provided (length == `len(bar_timestamps_utc)`), continuous mark-to-market: for each bar `t` in an open interval `[entry_bar_idx, exit_bar_idx)`, `equity[t]` carries `closed_pnl_up_to_t + signed_size * (prices[t] - entry_price) / entry_price`; at `exit_bar_idx` the closed `pnl_net` posts.
  - `max_drawdown_from_equity` returns an absolute-drawdown fraction when `peak_at_trough == 0` — divide the trough loss by the trough's absolute-equity magnitude, or return `(1.0, trough)` when even that would divide by zero. Reported drawdown on an all-loss curve must not read as zero.
  - `compute_sim_metrics` gains a keyword-only `prices: np.ndarray | None = None`; forwards to `build_equity_curve`.
- `src/price_space_llm/simulation/skeleton.py` -- extend:
  - `run_simulation_with_trades` skips bars where `not math.isfinite(fill_price)` alongside the existing `vol <= 0` skip; increments a `n_bars_skipped_nan_price` counter (added to `SimResult`).
  - When constructing each `Trade`, populate `entry_price` and `exit_price` from the walker state.
  - Pass `prices_slice[context_len : n_rows - 1]` (numpy) as the mark-to-market input to `compute_sim_metrics`.
- `src/price_space_llm/simulation/policy.py` -- guard:
  - `variance_vn` raises `ValueError` when `torch.isnan(probs).any()`. Softmax on NaN logits propagates silently; fail-loud instead.
- `src/price_space_llm/simulation/prediction.py` -- guard:
  - `derive_prediction_scalars` raises `ValueError` when `torch.isnan(probs).any()`.

## tests (+10)

1. `test_compute_pnl_raises_on_non_positive_exit_price` -- symmetric with the entry guard.
2. `test_compute_pnl_raises_on_nan_exit_price`.
3. `test_variance_vn_raises_on_nan_probs`.
4. `test_derive_prediction_scalars_raises_on_nan_probs`.
5. `test_max_drawdown_all_loss_curve_reports_non_zero` -- all-negative equity throughout -> non-zero drawdown.
6. `test_build_equity_curve_mark_to_market_step_matches_price_dynamics` -- one long trade, hand-computed prices `[100, 105, 110, 108, 112]`, entry at bar 0, exit at bar 4; `equity[t]` follows price dynamics minus costs.
7. `test_build_equity_curve_no_prices_falls_back_to_step_function` -- backwards-compat check that omitting `prices` yields the Sprint 097 shape.
8. `test_compute_sim_metrics_mark_to_market_produces_meaningful_sharpe` -- 30-bar rising price series, single long hold, produces non-zero Sharpe (vs step-function ~zero).
9. `test_run_simulation_with_trades_skips_nan_raw_target_bar` -- artifact with a NaN at bar `t+1` never opens a trade at that fill; `n_bars_skipped_nan_price` counter increments.
10. `test_trade_carries_entry_and_exit_price_fields` -- integration check that walker-constructed trades populate both fields.

## artifact contract

Files created or modified:

- `src/price_space_llm/simulation/positions.py` -- extend Trade + compute_pnl guard.
- `src/price_space_llm/simulation/metrics.py` -- mark-to-market + drawdown fallback.
- `src/price_space_llm/simulation/skeleton.py` -- NaN-price skip + Trade field wiring + mark-to-market threading.
- `src/price_space_llm/simulation/policy.py` -- NaN-probs guard.
- `src/price_space_llm/simulation/prediction.py` -- NaN-probs guard.
- 5 code files + 1 test file. Under hard rule 6.

Content assertions:

- `grep -q "entry_price: float" src/price_space_llm/simulation/positions.py`
- `grep -q "prices: np.ndarray" src/price_space_llm/simulation/metrics.py`
- `grep -q "n_bars_skipped_nan_price" src/price_space_llm/simulation/skeleton.py`

## signal contract

Zero new tags. `SimResult` gains a field (`n_bars_skipped_nan_price`); `SIM_RUN_COMPLETED` payload unchanged (the new counter reads through the return value, not the emit). Existing `sharpe_point`/`sharpe_se`/`max_drawdown` fields on the emit continue firing; their numeric meaning changes from step-function to mark-to-market (documented on the sprint card + module docstring). This is a metric-semantics change, not a payload-shape change.

## observation contract

REQUIRED -- Sharpe changes semantics from step-function to continuous.

- **Input:** three-trade synthetic ledger with hand-computed prices; expect mark-to-market Sharpe strictly greater than step-function Sharpe on the same trade set.
- **Live smoke on real corpus:** re-run Sprint 097's exact configuration (2000-row slice, xs+8-step, single-trade hold) and report the new Sharpe/max_dd/positive_fraction. The single-trade condition still applies to the untrained checkpoint; the number now reflects the actual price walk through the 334-bar hold rather than a single exit step. Compare against Sprint 097's `sharpe_point=0.0, max_drawdown=0.0` and record both.

## commands

```
uv run ruff check .
uv run mypy
uv run pytest -q
```

## notes

- Mark-to-market changes what the numbers mean. Sprint 097's zeros were correct-for-the-approximation; Sprint 100's numbers will read against the tech-arch §11.5 continuous form. The pre-registered Sprint 088 gates now consume the intended metric.
- The `Trade` dataclass gains two fields. Existing tests that construct `Trade` fixtures need to add `entry_price`/`exit_price`. Grep-and-fix during test authorship.
- `build_equity_curve(prices=None)` preserves backwards compatibility for Sprint 097's tests. Mark-to-market opts in per call.
- Sprint 101 next: strip the placeholder `checkpoint_step=0` defaults from all four walkers and the two sweep drivers (§6.1). Sprint 102: vectorize `block_bootstrap_sharpe` (§3.2).
