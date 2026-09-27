# Changelog

## 2026-09-27 — Baseline correction and held-out guard (Sprints 118-119)

The Phase H margin was overstated. Tuned and early-stopped over five seeds, the target-history baselines reach linear 3.256, GRU 3.219 and MLP 3.212 on validation log-loss; the transformer's 3.180 beats them by 2.3, 1.2 and 1.0 percent, not the 3.29 percent reported against linear at 3.289. The baselines were not undertrained: at the project's learning rate linear peaks at step 800 and overfits after. Script, data and table in `reports/baseline-convergence.md`. Separately, `scripts/train.py` now refuses held-out token files, including through a symlink; the README's reproduce command had pointed at `tokens.latest.pt` while that link targeted the held-out window.

## 2026-08-26 — Phase H close (Sprint 117)

This phase closed. Across five seeds, a causal decoder transformer over fifteen-minute SPY bars beats a linear baseline on validation log-loss by 3.29 percent on average. A rule that trades on the sign of the model's mean forecast captures none of that gain. The improvement lives in the shape of the output distribution, not the mean. The held-out window was read; two of the three permitted looks are spent. Full breakdown in `reports/phase-h-close.md`.

## Phases E through G (Sprints 073 through 106)

Ablation configs. Cost-calibration and simulator infrastructure. Held-out guards. AWS setup scripts. Vocabulary bumps to v0.6 and v0.7. All landed in a single commit at phase close.

## Phases A through D (Sprints 001 through 068)

Package scaffold and signal emitter. Vocabulary session (v0.1 through v0.5). Ingestion, alignment, features, tokenizer, model, baselines, evaluator, training loop, held-out infrastructure.
