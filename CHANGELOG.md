# Changelog

## 2026-08-26 — Phase H close (Sprint 117)

Research build reached its terminal result. A causal decoder transformer over 15-minute SPY bars beats a linear baseline on validation log-loss by 3.29% (five-seed mean); a downstream reader that decodes the distribution into a directional signal captures none of that edge. The improvement lives in the shape of the output distribution, not the mean. Held-out window read once, per the 3-look budget; two of three looks spent. Full breakdown in `reviews/phase-h-close.md`.

Simulator scale bug found and fixed at phase close: `derive_prediction_scalars` set `expected_vn_return` to a raw log-return while `compute_edge` treated it as vol-normalized. On SPY 15-min bars the two scales differed by ~600x. Fixed; six tests updated; full suite 629 pass.

## Phases E through G (Sprints 073 through 106)

Ablation configs, cost-calibration and simulator infrastructure, held-out guards, AWS scaffolding, vocabulary bumps to v0.6 and v0.7. Landed in a single commit at phase close per the audit-trail commit discipline.

## Phases A through D (Sprints 001 through 068)

Package scaffold and signal emitter. Vocabulary session (v0.1 through v0.5). Ingestion, alignment, features, tokenizer, model, baselines, evaluator, training loop, held-out infrastructure.
