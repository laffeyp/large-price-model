# Sprint 049 -- target features (`bar_shape`, `range_pct`, `volume_z_100`, `dollar_volume`, `spread_proxy`, `realized_vol_30`)

---

```yaml
---
id: 049
status: closed
phase: 2
pass_kind: functional
determinism_budget: bit-deterministic
---
```

---

## scope

Ships the six spec §6 target features on the SPY channel. Tech-arch line 302 pins the exact expressions:

- `bar_shape = (close - open) / (high - low + eps)` — dimensionless in [-1, 1]; sign carries close-vs-open direction.
- `range_pct = (high - low) / close_{t-1}` — bar range as fraction of the PRIOR close.
- `volume_z_100 = (volume - roll_mean_100(volume)) / roll_std_100(volume)` — 100-bar backward z-score.
- `dollar_volume = close * volume` — notional traded on the bar.
- `spread_proxy = 2 * |high - low| / (high + low)` — Corwin-Schultz-style half-spread proxy; simulator calibrates it into a real half-spread in §11.
- `realized_vol_30 = std(log_return[t-30:t])` — 30-bar rolling std of log_return; NOT annualized here (annualization lives in the tokenizer's vol normalization per spec §7.1).

Sprint 042 already enriched the aligned parquet with per-channel OHLCV, so the SPY row carries every input this needs. Sprint 049 consumes those columns and emits six new feature columns per grid row on the target channel only. Cross-asset features (spec §6 for QQQ/IWM/VIX/TLT/UUP/GLD/USO) land in Sprint 050.

## halt-and-articulate

None expected. Every input column exists on the aligned parquet after Sprint 048's re-run. The only halt trigger would be `high == low` for `bar_shape` (SPY's smallest 15-min bars still show a nonzero range; `eps=1e-12` per the spec keeps the divisor safe on flat rows without falsifying the value) or `high + low == 0` for `spread_proxy` (SPY prices never touch 0).

## signal contract

### Emits

- `FEATURE_COMPUTED` per (channel, feature_name, timestamp) on non-null values.
- `FEATURE_COMPUTATION_FAILED` per (channel, feature_name, timestamp) on null values, with `reason ∈ {insufficient_history, divide_by_zero, nan_input, downstream_error}`.

Reason table for Sprint 049 features:

| feature | insufficient_history | divide_by_zero | nan_input |
|---|---|---|---|
| `bar_shape` | — | high == low | close or open null |
| `range_pct` | row 0 (no prior close) | prior close == 0 (never SPY) | close null |
| `volume_z_100` | rows 0-99 | roll_std_100 == 0 | volume null |
| `dollar_volume` | — | — | close or volume null |
| `spread_proxy` | — | high + low == 0 (never SPY) | high, low, or close null |
| `realized_vol_30` | rows 0-30 | — | log_return null |

### Invariants

- Every target-feature column keys as `{target_key}__{feature_name}`, matching the base-pass convention (`target__SPY__log_return`).
- Features apply only to channels whose `channel_name == "target"`. Non-target channels (`market_context__*`, `macro__*`, `options__*`, `event__*`) receive no new columns from Sprint 049.
- `bar_shape` divisor uses `+ eps` to survive flat-bar rows without introducing bias (`eps = 1e-12`; on non-flat bars the effect on the ratio is <1e-11).
- `range_pct` reads `close_{t-1}` via `pl.col(close).shift(1)`; row 0 gets null.
- `volume_z_100` uses `rolling_mean(window_size=100)` + `rolling_std(window_size=100)`, backward-only.
- `realized_vol_30` computes on the base-pass `log_return` column, which is already causal.
- Feature computation runs after the base-pass log_return + rolling_mean_20 + rolling_std_20 + rolling_z_score_20 block, so `log_return` exists at that point in the pipeline.

## artifact contract

### Files

- `src/price_space_llm/features/compute.py` — new `TARGET_FEATURE_SPECS` tuple + inline target-feature block inside `compute_features` gated on `channel_name == "target"`. `_classify_failure` gains reason branches for the new features.
- `tests/test_features.py` (or wherever features tests live) — new tests: each of the six features computes the correct value on a synthetic 3-bar target frame; `bar_shape` handles `high == low` without raising; `range_pct` is null on row 0; `volume_z_100` is null through row 99; `realized_vol_30` is null through row 30; `FEATURE_COMPUTATION_FAILED` with correct reason fires on the expected null rows.

### Command exit codes

- `scripts/features.py` on both windows: exit 0.
- ruff, ruff format, mypy, pytest: green.
- Test count 315 → 315+ (new feature tests).

### Live smoke

Re-run features on both windows. Read-back expectations:

- Training window `target__SPY__bar_shape`: distribution in [-1, 1], mean ≈ 0 (roughly balanced up/down closes), std ~0.5.
- Training window `target__SPY__range_pct`: median ~0.001-0.003 (10-30 bps range per 15-min bar), max on stress days ~0.02+.
- Training window `target__SPY__volume_z_100`: after row 100, mean ~0, std ~1 by construction.
- Training window `target__SPY__dollar_volume`: median in $10M-$50M range per 15-min bar; peaks on Fed days / earnings-driven index moves.
- Training window `target__SPY__spread_proxy`: median ~0.001-0.003 (tight); Corwin-Schultz-style so this is a raw feature, not a calibrated spread yet.
- Training window `target__SPY__realized_vol_30`: median ~0.0005-0.002 per 15-min bar log_return std; annualized equivalent ~10-20% vol range for normal regimes.
- Failure counts jump by roughly `100 + 30 + 1 = 131` per-feature nulls on early rows (volume_z_100 through row 99, realized_vol_30 through row 30, range_pct on row 0). Divide-by-zero for `bar_shape` fires only on flat bars.

---

## observation contract

Required (`pass_kind: functional`). Unit tests lock every feature's arithmetic on a hand-checkable 3-bar frame. Live-trace read-back verifies distributions on the training window against economic priors (bar_shape mean ≈ 0, range_pct in tens of bps, volume_z_100 zero-mean unit-variance after the burn-in). Failure-count delta between Sprint 048's baseline and Sprint 049's re-run must equal the sum of expected insufficient-history nulls across the six new features plus any `bar_shape` divide-by-zero incidents.

---

## honest audit

**What lands.** Six spec §6 target features on the SPY channel with real values across both windows. Every feature's arithmetic pinned in a unit test. Failure modes named with typed reasons; no silent nulls.

**What does not land.** Cross-asset features on non-target channels (roadmap Sprint 050). VIX-specific `vix_level` + `vix_change` (also Sprint 050). Frozen normalizer + drift diagnostic (roadmap Sprints 054-055). Simulator's `spread_proxy → half-spread` calibration (Phase F, roadmap Sprint 073).

---

## notes

**Why `range_pct` divides by prior close and not current close.** Tech-arch §6 explicit: `(high - low) / close_{t-1}`. Using the prior close avoids a same-bar feedback loop (current close IS the endpoint of the range being measured). At v1 scale the difference is <1bp on normal bars but ~5-15bp on stress bars where close diverges from open significantly.

**Why `spread_proxy` is not calibrated here.** Spec calls out that `spread_proxy` is a raw feature; the simulator's cost model (§11) fits a `spread_scaler` × `spread_proxy` regression against real BBO data to produce a calibrated half-spread. Sprint 049 emits the raw ratio; Phase F (Sprint 073) calibrates.

**Why `realized_vol_30` is not annualized.** Spec §7.1: the tokenizer's vol normalization applies annualization when it forms the training-window vol denominator. Emitting realized_vol_30 as a per-bar std keeps the feature layer's units consistent with `log_return` (also per-bar). Annualizing here would double-apply the scaling factor in the tokenizer.

**`eps = 1e-12` for `bar_shape`.** SPY 15-min bars almost always show a nonzero range; the epsilon is a defensive floor for the ~5-10 rows across an 8-year corpus that show `high == low` (halts, thin overnight sessions crossing the boundary, single-print bars). The alternative — `pl.when(high == low).then(None)` — throws away the row entirely; the +eps keeps the value at 0 (correct: a bar that opens and closes at the same price has `bar_shape = 0`).

---

## plan-mode review checklist

- [x] Files under hard rule 6 (one code + one test file).
- [x] No new emit sites (FEATURE_COMPUTED / FEATURE_COMPUTATION_FAILED already declared).
- [x] Observation contract (functional-band): nine feature tests (six arithmetic + one flat-bar edge + one non-target skip + one realized_vol_30 reason). Read-back distribution check on training window.
- [x] Determinism budget bit-deterministic (same aligned parquet + code = byte-identical features parquet).
- [x] Ships all six spec §6 target features — no scope reduction.

---

## close (2026-08-14)

Landed. Six target features live on target__SPY across both windows. Training-window read-back (54,262 rows): bar_shape mean 0.022 std 0.52 range [-1, 1] (slight up-bias reflects 8-year bull); range_pct median 15 bps max 5.81% (COVID / 2018 vol-spike bars); volume_z_100 mean 0.013 std 1.04 after 100-bar burn-in; dollar_volume median $448M max $10.4B; spread_proxy median 15 bps; realized_vol_30 median 0.129% max 2.57% (2020-03 crash). Test-window read-back (10,166 rows): matching shapes and honest ranges. Failure counts: training 481,013 (rolling-window burn-ins + step-function macro rolling collapses dominate); test 93,260. Test count 315 → 324 (+9 feature tests: six arithmetic + flat-bar survival + non-target skip + realized_vol_30 reason). Four tools green. Tokenizer unchanged (target log_return unaffected by adding features). Phase B step 1 of 8 clears; Sprint 050 (cross-asset features per symbol + VIX-specific vix_level/vix_change) opens next.
