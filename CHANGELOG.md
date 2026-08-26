# Changelog

## 2026-08-26 — Phase H close (Sprint 117)

This phase closed. Across five seeds, a causal decoder transformer over fifteen-minute SPY bars beats a linear baseline on validation log-loss by 3.29 percent on average. A rule that trades on the sign of the model's mean forecast captures none of that gain. The improvement lives in the shape of the output distribution, not the mean. The held-out window was read; two of the three permitted looks are spent. Full breakdown in `reviews/phase-h-close.md`.

The phase close also found and fixed a scale bug in the simulator. `derive_prediction_scalars` set `expected_vn_return` to a raw log-return while `compute_edge` treated it as vol-normalized. On SPY fifteen-minute bars the two scales differ by about 600x. Six tests updated. Full suite 629 pass.

## Phases E through G (Sprints 073 through 106)

Ablation configs. Cost-calibration and simulator infrastructure. Held-out guards. AWS setup scripts. Vocabulary bumps to v0.6 and v0.7. All landed in a single commit at phase close.

## Phases A through D (Sprints 001 through 068)

Package scaffold and signal emitter. Vocabulary session (v0.1 through v0.5). Ingestion, alignment, features, tokenizer, model, baselines, evaluator, training loop, held-out infrastructure.
