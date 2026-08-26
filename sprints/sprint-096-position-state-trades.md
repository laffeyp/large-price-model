# Sprint 096 -- position state machine + trades (roadmap 075 part 3)

---

```yaml
---
id: 096
status: closed
phase: F
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Add position tracking and trades to the walker. Roadmap 075 part 3. Emits `POSITION_OPENED`, `POSITION_CLOSED`, `TRADE_LEDGERED` per the v0.7 payload schema; computes per-trade `pnl_gross` + `pnl_net` + cost decomposition per tech-arch § 11.4 + § 11.5. Sprint 097 = metrics + block bootstrap on the trade ledger. Sprint 098 = capacity sweep. Sprint 099 = kappa sensitivity plot.

Named approximations documented on the card:

- **Fill price = close at fill bar** (tokenizer carries close-derived log_return, not open). The spec says "entries and exits print at the next bar's open"; the tokenizer only ships close prices via `raw_targets`. The approximation applies to a 15-min bar's close-vs-open gap, which is small relative to the daily microstructure the strategy trades.
- **Single `spread_cost_frac` = round-trip cost fraction.** Per-position cost = `spread_cost_frac × |size|`. Simpler than half-spread on each leg; equivalent under symmetric assumptions.
- **`slippage_frac × |size|` linearizes `kappa × size²`.** Sprint 099's kappa sensitivity plot revisits the quadratic form.

## deliverables

- `src/price_space_llm/simulation/positions.py` — new:
  - `Position` dataclass: `direction`, `size`, `entry_bar_ts_utc: datetime`, `entry_price: float`, `entry_bar_index: int`.
  - `Trade` dataclass: `trade_id: str`, `entry_ts_utc: datetime`, `exit_ts_utc: datetime`, `direction`, `size`, `pnl_gross`, `pnl_net`, `cost_spread`, `cost_slippage`, `hold_duration_bars: int`.
  - `compute_pnl(direction, size, entry_price, exit_price, spread_cost_frac, slippage_frac) -> tuple[float, float, float, float]` returning `(pnl_gross, pnl_net, cost_spread, cost_slippage)`. Return-fraction math: `pnl_gross = size × (exit_price/entry_price − 1)` (signed size handles direction). `cost_spread = spread_cost_frac × |size|`. `cost_slippage = slippage_frac × |size|`. `pnl_net = pnl_gross − cost_spread − cost_slippage`.
  - `derive_prices_from_log_returns(raw_targets: torch.Tensor) -> torch.Tensor` — cumulative anchor at 1.0, `p_t = p_{t-1} × exp(log_return_t)`. NaN log_returns pass through the last valid price.
- Extend `src/price_space_llm/simulation/skeleton.py` with `run_simulation_with_trades(artifact, model, bucket_stats, policy, *, target_symbol, emitter, run_id, checkpoint_run_id, cost_calibration_run_id, split, date_range_start, date_range_end)`:
  - Precompute prices from `artifact.raw_targets`.
  - Per bar `t`: predict (Sprint 093 flow) + decide (Sprint 094 flow) + emit DECISION_MADE/SIGNAL_DROPPED.
  - Position state machine (single-position invariant per spec § 11.4):
    - Direction change (current != decision AND both != flat): close current at fill=t+1's price → emit POSITION_CLOSED + TRADE_LEDGERED with `close_kind="normal"`; open new at fill=t+1's price → emit POSITION_OPENED.
    - flat → non-flat: open at fill=t+1.
    - non-flat → flat: close at fill=t+1.
    - Same direction: no emit (position continues; Sprint 094's `DECISION_MADE.reason="position_held"` already captures this).
  - End-of-range flush: if a position is still open when the walker exits, force-close at the last bar's price with `close_kind="sim_range_end"`.
- `SimResult` extended: `trades: tuple[Trade, ...]` + `n_trades` counted from the ledger + `pnl_total: float`.
- `src/price_space_llm/simulation/__init__.py` exports the new names.

## tests (+7)

1. `test_compute_pnl_long_profit` — size=+1M, entry=100, exit=101 → pnl_gross = +10k; with zero costs, pnl_net = pnl_gross.
2. `test_compute_pnl_short_profit` — size=−1M, entry=100, exit=99 → pnl_gross = +10k (short profits when price falls).
3. `test_compute_pnl_subtracts_costs` — non-zero spread + slippage; pnl_net = pnl_gross − cost_spread − cost_slippage.
4. `test_derive_prices_from_log_returns_anchor_at_one` — first price 1.0; subsequent prices = cumulative exp(log_returns).
5. `test_derive_prices_from_log_returns_nan_holds_last_valid` — NaN in raw_targets does not corrupt subsequent prices.
6. `test_run_simulation_with_trades_scripted_flip_opens_closes_and_ledgers` — `_AlternatingLogitsModel` (Sprint 094 test fixture) forces a flat→long→short pattern; verify POSITION_OPENED + POSITION_CLOSED + TRADE_LEDGERED fire in the correct sequence.
7. `test_run_simulation_with_trades_end_of_range_flush` — model that opens a position that never closes voluntarily → walker emits POSITION_CLOSED with `close_kind="sim_range_end"` on the last valid bar.

## context files

- `src/price_space_llm/simulation/skeleton.py`
- `src/price_space_llm/simulation/policy.py`
- `src/price_space_llm/model/dataset.py` (TokenizedArtifact.raw_targets — Sprint 088)
- `specs/technical-architecture-v4.md` § 11.4 + § 11.5

## signal contract

Emits: `POSITION_OPENED`, `POSITION_CLOSED`, `TRADE_LEDGERED` — all three exist in v0.7 vocabulary. Payload fields listed above. `SIGNAL_DROPPED` gains its second reason `same_direction_position_held` — currently Sprint 094 emits only `hysteresis_below_flip_threshold`; Sprint 096 keeps that path and adds the position-side path.

## observation contract

REQUIRED — three new emit sites fire from live code for the first time.

- **Input:** synthetic .pt with `raw_targets` stamped + Sprint 094's `_AlternatingLogitsModel` scripting position flips.
- **Expected trace:** SIM_RUN_STARTED → per-bar [PREDICTION_EMITTED, BAR_PROCESSED, DECISION_MADE, (POSITION_CLOSED)?, (TRADE_LEDGERED)?, (POSITION_OPENED)?] → SIM_RUN_COMPLETED. Every trade ends with a TRADE_LEDGERED emit paired with a POSITION_CLOSED emit.
- **Expected behavior:** `SimResult.n_trades > 0`; `SimResult.pnl_total` is the sum of `Trade.pnl_net` across the ledger.
- **Live smoke on real corpus:** 10-step xs checkpoint + policy `(threshold=0.01, hysteresis=0.2, lambda_risk=0, spread=0.0005, slippage=0.0002)` on 400-row slice; report `n_trades`, `pnl_total`, and the winners/losers count. All numbers honestly at-chance (Sprint 093's warning applies) but the mechanics must fire the emit surface correctly.

## commands

```
uv run ruff check .
uv run mypy
uv run pytest -q
```

## notes

- 3 code files (`positions.py`, `skeleton.py`, `__init__.py`) + `scripts/simulate.py` + 1 test file. At the hard rule 6 ablation-infrastructure ceiling.
- Sprint 097 opens next: metrics + block bootstrap on the trade ledger.
- Named on card: v0.8 vocab bump candidate carries the two Sprint 097+ deferred fields (`checkpoint_kind` on `CHECKPOINT_WRITTEN` per review § 7.2; `patch_size` + `head_type` + `fusion` on `CONFIG_RESOLVED`); Sprint 096 is not a vocab-bump sprint.
