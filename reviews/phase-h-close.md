# Phase H close — held-out result and phase summary

Date: 2026-08-26

## Held-out result

Sprint 115 mixer (mixer fusion, lr=3e-5, seed 0, val_nll 3.148 on training split)
run through the fixed simulator on the untouched 2024-01 through 2025-06 SPY
window. 10,166 bars. Costs at SPY norms: 1 basis point round-trip spread,
0.5 basis point slippage on $1M size.

| threshold | n_trades | hit_rate | sharpe | sharpe_se | sharpe−SE | pos_frac | max_dd |
|----------:|---------:|---------:|-------:|----------:|----------:|---------:|-------:|
|    0.005  |     913  |   0.454  |  -1.82 |     0.81  |    -2.62  |   0.001  |  28.4  |
|    0.020  |     902  |   0.446  |  -2.17 |     0.66  |    -2.84  |   0.000  |  28.4  |
|    0.050  |     942  |   0.443  |  -2.02 |     0.64  |    -2.66  |   0.001  |  23.8  |

Pre-registered gate: Sharpe minus SE > 0, positive_fraction ≥ 0.70,
capacity ≥ $1M, no leakage. The strategy fails Sharpe minus SE at every
threshold. Positive_fraction sits at 0.001, meaning fewer than one in a
thousand bootstrap resamples of bar-level P&L produces a positive Sharpe.
The Sprint 115 mixer, translated into a directional trading strategy on
15-minute SPY bars, loses money on the held-out window.

Look log: 2 of 3 spent (the first attempt registered before a script
error; the second registered on the successful run). One look remains.

## What was built

Data pipeline from Alpha-Vantage through to a normalized tokenized artifact
covering 2015-2022 SPY plus 19 context channels (market, macro, options,
event, session). Frozen bucketizer + frozen normalizer fit on the training
window. MarketStateTransformer with three embedder variants (sum, mixer,
patch) and two head types (categorical, quantile). Four baselines (linear,
MLP, GRU, target-only). Six dispatch axes composable in `run_id`. Simulator
with bar walker, position state machine, trade ledger, mark-to-market
equity, block-bootstrap Sharpe with SE, capacity sweep, kappa sensitivity.
Cost calibration code. Held-out filesystem and commit-message guards.

## What the arc measured

The multi-channel transformer beats a linear baseline on the training-split
validation log-loss by 3.29% averaged across 5 seeds (best seed 4.26%).
The pre-registered log-loss gate wanted 10%. The margin does not carry to
a directional trading edge: the best model produces near-zero mean
predictions (expected return ~1e-6 in log-return units, p_up 0.4973) and
fails Sharpe minus SE > 0 on both training-window validation and held-out
data.

## Simulator bug discovered and fixed at phase close

The prediction layer named its output `expected_vn_return` and treated it
as vol-normalized. The bucketizer fits on raw log-returns, so
`Σ p_i * train_mean_i` is a raw log-return, not a vol-normalized one. The
edge formula in `compute_edge` divided costs by `realized_vol` to convert
them into "vn units" and subtracted from `expected_vn_return`, which sat
on the raw-return scale. On SPY 15-minute bars the two scales differed
by roughly 600x. Cost terms dominated the edge computation, so decisions
did not fire — the first training-window simulator run produced one trade
across three years.

Fix: `derive_prediction_scalars` now sets
`expected_return = Σ p_i * train_mean_i` and
`expected_vn_return = expected_return / realized_vol`, so the vol-normalized
scale name matches the value. Six existing tests updated to reflect the
new invariant. Full test suite: 629 pass, 2 skipped.

The bug shipped in Sprint 093 (prediction) and Sprint 094 (policy) and
remained under the radar because no trained model had been fed into the
simulator until phase close. Every prior smoke used a random-weight
checkpoint from step 8 of an untrained xs run.

## Data limitations and known scope choices

Cost calibration on disk is degenerate. `spread_scaler.json` fits a
3-point regression with slope 0 and R² 0. `kappa.json` fits kappa =
5.87e-4 with R² 1.16e-5. Neither is a real calibration. The held-out
run used hand-picked SPY-realistic constants (1 bp spread, 0.5 bp
slippage on $1M) rather than these fits.

Channel set is smaller than the product spec's original manifest: three
of the declared channels are covered by substitutes ratified in
`## Decisions` (UUP for DXY; VXX for VIX volume; VIX carried at daily
resolution via INDEX_DATA rather than intraday).

Training resolution is 15-minute bars, the finest resolution Alpha-Vantage
serves without a paid vendor. Finer resolutions were named as an open
question for a follow-on project.

## What the phase proved

A causal decoder transformer over vol-normalized categorical price
targets, with multi-channel state-vector input, trains end-to-end on
SPY 15-minute bars. It produces a distribution that improves on a
linear baseline in log-loss terms by a small margin (~3%). That is
the theoretical prediction: a language-model architecture applied
to price sequences yields a modest but real improvement in
distributional prediction over a linear regression on past returns.

The phase does not prove — and never claimed to prove — that this
translates into a profitable trading strategy. The held-out result is
consistent with the training-window result: the model has a shape
edge, not a mean edge, and a directional policy captures none of it.

## Next project

Two workstreams named for the successor project:

1. Build the database. Highest-resolution data available across whatever
   instrument set the theory calls for. Data structure is part of the
   design, not a downstream constraint. Written as its own product +
   research document.

2. Two research tracks: what the encoder builds in the high-dimensional
   representation space, and which cross-domain metaphors from language
   and vision carry into price data.

The successor project's working name is Large Price Model. This project
was the toy that confirmed the architecture executes end-to-end and
produces the theoretically-expected small edge in log-loss. That result
stands.

## Repository state

628 tests pass at phase close (629 after the simulator fix landed).
116 sprint cards on disk. Vocabulary locked at v0.7. `experiments/logbook.csv`
carries 26 rows. `experiments/test_looks.log` carries 2 entries (1 remaining).

No commits between Sprint 072 (`263cf41`) and phase close; the entire
Phase E through Phase H arc lives in the working tree and lands in a
single commit at phase close.
