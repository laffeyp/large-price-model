# Baseline convergence — were the baselines undertrained?

Date: 2026-09-27 (Sprint 118). Data: `reports/baseline-convergence.json`. Script: `scripts/analysis/baseline_convergence.py`.

## The question

`fit_linear`, `fit_mlp` and `fit_gru` in `src/price_space_llm/baselines.py` default to 200 Adam steps at batch 32. A reader who sees those defaults, and the logbook row `LinearBaseline(64x32->32), n_steps=200`, can fairly suspect the transformer beat a baseline that never finished training. An outside audit of this repository made exactly that claim on 2026-09-27. This report answers it.

## Short answer

The linear baseline was not undertrained. At the project's learning rate (1e-3) it peaks near step 800 and gets worse with every step after:

| steps | 200 | 800 | 2,000 | 5,000 | 8,000 |
|---|---:|---:|---:|---:|---:|
| linear val NLL, lr 1e-3 | 3.3325 | **3.2886** | 3.3217 | 3.5020 | 3.6676 |

The model has 65,536 weights and 43,345 training windows. It overfits after about 25,600 samples (800 steps × 32). Training longer does not help it.

It was, however, under-tuned. A lower learning rate and early stopping find better baselines, and two nonlinear baselines the Phase H comparison never used do better still. The transformer still beats every one of them, by less than Phase H reported.

## Best achievable baselines

Each baseline was swept over learning rate {1e-3, 3e-4} and weight decay {0, 0.01, 0.1} (GRU: weight decay 0.1 only), scored every 100 steps (GRU: 200) on the validation windows, and stopped at its best step. That is the same selection rule the transformer runs used. The best configuration for each kind was then re-run at seeds 0-4.

| baseline | best config | best step | 5-seed mean | stdev | transformer ahead by |
|---|---|---:|---:|---:|---:|
| linear (64×32 one-hot → 32) | lr 3e-4, wd 0.1 | ~3,600 | 3.2556 | 0.0019 | 2.31% |
| GRU (128 hidden) | lr 3e-4, wd 0.1 | ~3,400 | 3.2189 | 0.0007 | 1.20% |
| MLP (128-64-32) | lr 3e-4, wd 0.1 | ~1,600 | 3.2120 | 0.0041 | **0.99%** |
| transformer (md, mixer, lr 3e-5) | Sprint 115/116 | ~8,000 | 3.1803 | 0.022 | — |

Chance, a uniform guess over 32 buckets, is log 32 = 3.4657.

Every transformer seed (3.148 to 3.205) beats every baseline seed. The worst transformer seed, 3.2054, is below the best MLP seed, 3.2076. The edge is real and consistent across seeds. It is about 0.03 nats per bar.

## What changes in the Phase H result

- The Phase H margin of 3.29% was measured against linear at 3.289, its 800-step optimum at lr 1e-3. Against the tuned linear the margin is 2.31%. Against the best baseline, an MLP, it is 0.99%.
- The README's "3.180 against a linear baseline at 3.333" paired the transformer with linear's 200-step number. That pairing overstated the gap. The README now carries the table above.
- Every baseline here sees only the target's own 64-bucket history. The transformer sees twenty channels and has a different architecture. The gap between them mixes both differences; this report does not say how much comes from the channels. The product spec names the test that would: the target-only ablation, the same transformer with the nineteen non-target channels zeroed. It has not been run on the normalized artifact (Sprint 113-A ran it on the un-normalized one).
- These are not the pre-registered baselines. `specs/product-spec-v4.md` defines the linear baseline on the transformer's own input tokens, the MLP on the last-position multi-channel state vector, and the GRU/TCN at about 1M parameters. The repository's `LinearBaseline`, `MLPBaseline` and `GRUBaseline` (65,568 / 273,664 / 107,296 parameters) read target bucket history only. The pre-registered gates (10% vs linear, 5% vs GRU/TCN, 5% vs target-only) were never measured, by Phase H or here.
- Nothing here touches the directional finding. The held-out simulator result (Sharpe −1.82 to −2.17) stands as reported.

## Scope and limits

- Validation is the last 20% of the 2015-2022 target stream: 10,789 windows, the same windows behind the transformer's pooled val NLL in `experiments/logbook.csv`. The held-out window (2024-01 to 2025-06) was not read. The script refuses any token file not named for 2015-01..2022-12.
- Both the baselines and the transformer were early-stopped and tuned on this one validation split. All numbers carry the same small optimistic bias. The comparison between them is fair; the absolute values are not out-of-sample.
- The grid is small: 6 configs per kind, 2 for GRU. A wider search could lower the baselines further. It is unlikely to raise them.

## Reproduce

```bash
uv run python scripts/analysis/baseline_convergence.py --output reports/baseline-convergence.json
```

About ten minutes on CPU (Apple M5 Max). The seed-0 row at lr 1e-3, wd 0 reproduces the logbook's 3.3325 at step 200 and the ledger's 3.2886 at step 800.
