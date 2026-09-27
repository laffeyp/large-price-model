# Phase H close — held-out result and phase summary

Date: 2026-08-26

> Corrected 2026-09-27: the 3.29% log-loss margin below is against an untuned linear baseline. Against tuned baselines the margin is 1.0-2.3%. See "Correction" at the end and `reports/baseline-convergence.md`. The held-out trading result is unchanged.

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

## Data limitations and known scope choices

The cost calibration on disk was fit from three BBO snapshots collected during a live-vendor probe in April through June 2024. Three points cannot constrain a two-parameter regression, so `spread_scaler.json` reports slope 0 and R² 0. The kappa fit ran over 4063 minute-bar samples and produced kappa = 5.87e-4 with R² = 1.16e-5 — very low explanatory power. A larger calibration data set was not pursued because the 2026-08-17 Architect Decision ratified a Corwin-Schultz proxy path and deferred a full historical-BBO buy until first-run results existed. The held-out simulator run therefore used SPY-norm constants (1 basis point round-trip spread, 0.5 basis points slippage on a $1M order) in place of those fits.

Three of the declared channels are substitutes ratified in the project's Decisions log: UUP for DXY (Alpha-Vantage carries no intraday DXY), VXX for VIX volume (VIX is an index and has no traded volume), and VIX itself carried at daily resolution via INDEX_DATA (Alpha-Vantage refuses VIX at 15-minute cadence).

Training resolution is 15-minute bars, the finest Alpha-Vantage serves. Finer resolution requires a paid vendor. The 2026-08-14 Decision deferred that purchase to a follow-on project.

## What the phase proved

A causal decoder transformer trains end-to-end on SPY 15-minute bars. Across five seeds it beats a linear baseline on validation log-loss by 3.29% on average. The improvement lives in the shape of the output distribution, not the mean. A directional trading policy captures none of it, on either the training-window validation split or the held-out window.

## Next

Two directions.

1. Build the database. Highest-resolution data available across whatever instrument set the theory calls for. The shape of the data is part of the design.

2. Two research tracks: what the encoder builds in its representation, and which ideas from language and vision transfer to price data.

Written up separately.

## Repository state

629 tests pass at phase close. 116 sprint cards on disk. Vocabulary locked at v0.7. `experiments/logbook.csv`
carries 26 rows. `experiments/test_looks.log` carries 2 entries (1 remaining).

No commits between Sprint 072 (`263cf41`) and phase close; the entire
Phase E through Phase H arc lives in the working tree and lands in a
single commit at phase close.

## Correction — 2026-09-27 (Sprint 118)

The margins above are measured against linear at 3.289, its best step at lr 1e-3. Tuned and early-stopped over five seeds, the target-history baselines reach linear 3.256, GRU 3.219 and MLP 3.212. The transformer's 3.180 beats them by 2.31%, 1.20% and 0.99%, and every transformer seed beats every baseline seed. These baselines read target history only; the product spec's pre-registered baselines (linear and MLP on the multi-channel input, a ~1M-parameter GRU/TCN, a target-only ablation) were never built, so the pre-registered log-loss gates above were never measured. The linear baseline was not undertrained: at lr 1e-3 it peaks at step 800 and overfits after. Evidence in `reports/baseline-convergence.md`. The held-out simulator result above is unchanged.

The repository-state line "116 sprint cards on disk" counted 114; cards 040 and 079 were never written, and Sprint 117 has no card.
