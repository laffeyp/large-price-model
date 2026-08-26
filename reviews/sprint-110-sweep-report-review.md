# Verify — `artifacts/sprint110-sweep-report.md`

**Reviewer:** Claude Code (Opus 4.7), acting in Agent role.
**Date:** 2026-08-24.
**Scope:** the 120-line first-sweep report. Arithmetic checked. Interpretations compared against product-spec-v4 pre-registered gates + Sprint 041/061 baseline-shape audit. One headline interpretation stands. Three carry either an attribution error, a missing-baseline caveat that should escalate, or a missed trajectory-analysis signal that changes the conclusion.

---

## 1. Arithmetic — clean

- **Chance NLL = log(32) = 3.4657.** Correct for a 32-class uniform predictor.
- **Chance top-1 = 3.1%.** `1/32 = 3.125%`; reported as `3.1%` under one-decimal rounding. Correct.
- **Chance dir-acc = 50%.** Binary direction; correct.
- **Pooled val_nll weighted by n_examples.** Spot-check on lg: `(1826 × 3.155 + 2629 × 3.409 + 6334 × 3.466) / 10789 = 3.3990`. Report says `3.3993`. Delta 0.0003 = rounding on the 3-decimal regime numbers. Matches.
- **Percent-vs-baseline convention.** The report uses positive = improvement, negative = regression. Consistent across every row. `lg -1.99% vs linear` = `(3.3993 - 3.3331) / 3.3331 = +1.99%` transformer-worse-than-linear, correctly reported as failure.
- **Divergence threshold.** `TrainerConfig.grad_clip = 1.0`; Sprint 057 divergence rule is `grad_norm > grad_clip * 10 = 10.0`. The v2 sm entry reports `grad_norm 10.9 > 10`, tripping the guard. Correct.

Every number checked ties out.

---

## 2. Interpretation A — target-only gate is not evaluated (report should escalate the caveat)

The report reads:

> Val NLL ≥5% lower than target-only → every size **FAILS** (target-only is a marginal-frequency predictor; the spec review from Sprint 041 flagged this baseline as meaningless)

The report acknowledges the shape problem in a parenthetical and still labels the gate FAILS. That is misleading. The correct classification is *not evaluated in this sweep*, not *fails*.

The spec's target-only gate (product-spec-v4 line 155) reads: *"Validation NLL at least 5% lower than the target-only ablation on identical data. The summation embedder is mathematically equivalent to one linear projection of the concatenated feature vector, so this ablation — not any orthogonality diagnostic — is what settles whether the extra channels contribute."*

Product-spec §Baselines defines "target-only ablation" as *"same architecture as the default transformer, every non-target channel zeroed at the embedder."* Sprint 061 landed the correct helper (`zero_non_target_features(artifact, target_symbol)`) that composes with `run_training_feats` to produce exactly this ablation.

The sweep evaluated the transformer against `TargetOnlyBaseline` — the legacy marginal-frequency predictor Sprint 041's parallel audit flagged as shape-wrong. Comparing 3.4624 (xs) against 3.4798 (marginal) says nothing about whether the extra channels contribute; it says the transformer beats the marginal-frequency baseline by 0.50% (barely; likely inside noise on a 10K-example val set).

**The target-only gate remains unmeasured until a sweep runs `run_training_feats(zero_non_target_features(artifact, "SPY"), ...)` at each size and compares val_nll against the same-size multi-channel run.** That comparison is the direct test of the multi-channel-lift claim the whole thesis rides on. Sprint 111 should schedule it.

Report fix: rewrite the target-only line as *"Val NLL ≥5% lower than target-only ablation → NOT EVALUATED (the sweep compared against the legacy marginal-frequency `TargetOnlyBaseline`, not the spec's `zero_non_target_features` shape landed in Sprint 061). Sprint 111 candidate: run zeroed-channel sweep at each size and evaluate the gate against the correct baseline."*

---

## 3. Interpretation B — the v2 trajectory analysis was missed

The report treats v2 (lr=3e-4) as "reference (diverged)" and moves on. The v2 numbers, taken as interim best-val-nll before divergence, tell a different story than the report reads:

| size | v2 best val_nll (before divergence) | vs linear 3.3331 |
|---|---|---|
| xs | 3.29 | +1.3% better |
| sm | 3.26 | +2.2% better |
| md | 3.18 | **+4.5% better** |
| lg | 3.28 | +1.6% better |

v2's md was tracking toward the pre-registered ≥10% linear gate when it diverged at step 12000. v2's lg had shown 3.28 as its best; less impressive but still positive vs linear. The v3 (lr=1e-4) numbers underperform v2's interim bests at every size except xs — the lower LR closed the divergence risk at the cost of the improvement trajectory.

The report's finding 2 offers two reads: *"under-training"* (option a — needs more steps) or *"signal ceiling"* (option b — 15-min bars are noise-dominated). The v2 trajectory is a third read the report does not name: **the LR schedule needs re-tuning, not the training budget or the feature set.** Concretely: v3 dropped the peak LR by 3× to close divergence; a middle ground (lr=1.5e-4 or lr=2e-4 with longer warmup and tighter grad_clip) may keep the v2 trajectory without the divergence.

That third read matters because options a and b both point to more expensive experiments (100K+ steps or replace the whole feature set); the third read points to a much cheaper next sprint (re-run one size — md — at three intermediate LRs and see whether the trajectory reaches the linear gate). The report should name this.

Report addition: *"finding 2c — LR re-tuning. v2's md hit 3.18 val_nll before divergence at step 12000; that is 4.5% better than linear, on track for the 10% gate. Sprint 111 candidate: re-run md at lr ∈ {1.5e-4, 2e-4} with tighter grad_clip or longer warmup and see whether stabler training preserves the v2 trajectory."*

---

## 4. Interpretation C — regime-conditional gate proposal is a live discipline question

The report ends:

> if the low-vol edge holds vs linear, propose an amendment to the pre-registered gate framing to regime-conditional

Moving goalposts after seeing the data is the class of thing pre-registration exists to prevent. The report frames this correctly as a *candidate* work item, which is honest. But two clarifications should land in the report before an amendment proceeds:

- The amendment cannot retire the pre-registered pooled gate. Product-spec §"Success gates for v1" reads the pooled Sharpe / NLL / ECE gates as the v1 success criteria. Any per-regime addition sits alongside the pooled gate, not in place of it. The pooled gate's failure is the pre-registered claim's failure.
- The amendment must route through the Architect and land in a Decision entry with reasoning. Not a Signal Report finding. Not a reviewer's discretion. Product-spec is the pre-registration document; amending it after seeing results requires the Architect to write the amendment into `## Decisions` with an explicit reason, ideally with the pre-registered gate marked "failed as measured; amended per Decision YYYY-MM-DD."

The report's phrasing *"propose an amendment"* implies this correctly. Worth making the routing explicit so the amendment does not read as a discretionary reinterpretation.

---

## 5. Real signal the report caught cleanly

Three findings are correctly interpreted and honest:

- **Signal concentrated in low-vol.** lg low-vol NLL 3.155 vs chance 3.466 = 0.31 nats improvement, 9% below chance. Top-1 5× chance. Dir-acc up to 60%. Per-regime numbers back the claim.
- **High-vol is essentially unlearnable at this horizon.** Every size sits at NLL ≈ chance on high-vol (n=6334, 58.7% of val by weight). Top-1 2.6% (below chance's 3.125%) across all sizes. The report reads this correctly.
- **Monotonic size scaling with plateau; md wins on cost/benefit.** Gain per doubling: xs→sm 0.034 nats, sm→md 0.022, md→lg 0.007. Diminishing returns from md to lg despite 2× params. Correct read.

One statistical note the report understates: **xs 60.0% low-vol dir-acc vs sm/md/lg's 53% at n=1826 is not noise.** Bernoulli std of proportion at 50% and n=1826 is `sqrt(0.25/1826) = 1.17%`. A 7-percentage-point delta is ~6 sigma. That is a real signal, not a candidate for the noise hypothesis. The report says *"worth investigating"* but names both real-effect and noise as candidates. The math rules out noise. The investigation should focus on why: smaller model finding a directional feature the bigger models over-parameterize away, or an artifact of how xs's confident-but-wrong predictions land at the argmax boundary between up and down buckets.

---

## 6. Attribution slips

Two citations should tighten:

- **"Sprint 084's pre-registered 10% linear gate"** (finding 2). Sprint 084 was the v0.7 vocab-bump sprint (normalized-artifact contract). The pre-registered 10% linear gate is `product-spec-v4.md §"Success gates for v1"`, line 153. Not Sprint 084.
- **"Per Sprint 041, meaningless as a gate"** (target-only table). Sprint 041's parallel audit flagged the shape gap; Sprint 061 (`zero_non_target_features` helper) is the fix. The report should cite both: *"flagged in Sprint 041 review; fixed in Sprint 061; this sweep uses the pre-Sprint-061 legacy shape."*

---

## 7. Missing context in the report

Three items a Reviewer at Sprint 112+ will want but the report does not carry:

- **No training curves.** The report presents best val_nll at eval step, per size. It does not show whether training was still descending at step 20K or had plateaued. The "under-training" hypothesis (finding 2a) is distinguishable from the "signal ceiling" hypothesis (finding 2b) by inspecting the val_nll trajectory — a still-descending curve favors more steps; a plateaued curve does not. The traces at `logs/sprint110-sweep-{xs,sm,md,lg}/` carry the raw signals; a small script over the JSONL trace would produce the curve.
- **Why MPS not AWS.** Sprint 107 provisioned the AWS scaffold. Sprint 110 ran on M5 Max MPS. The report does not name the reason. If AWS was skipped for cost reasons, that is a live cost-neutrality question the Architect should see explicit. If MPS was faster (plausible; the M5 Max is capable), that is also worth naming so Sprint 111 does not default to AWS on the assumption that GPU always beats local. Add one line: *"MPS chosen over AWS for this sweep because of {reason}."*
- **Which checkpoint was evaluated per size.** The report says *"each size's best checkpoint against the 2015-2022 val split."* Sprint 058's `keep_top_k=3` retains three checkpoints per run. Was the evaluated checkpoint the training-side best-val-nll, or the eval-side best among the retained three? The two can differ. Sprint 097's evaluator emit surface distinguishes them; the report should cite which the numbers come from.

---

## 8. Pre-registered gates — the score as the report should report it

Rewriting the gate table with the caveats above:

| gate (product-spec §"Success gates for v1") | reads as | measured value | verdict |
|---|---|---|---|
| Val NLL ≥10% lower than 1-layer linear | pooled | lg -1.99% | **FAIL** |
| Val NLL ≥5% lower than GRU/TCN baseline | pooled | not in this sweep | **NOT EVALUATED** |
| Val NLL ≥5% lower than target-only ablation | pooled | (wrong baseline shape used) | **NOT EVALUATED** |
| Val ECE < 0.05 | pooled | not reported | **NOT EVALUATED** |
| Sharpe > 0.5 | held-out | held-out gate | **NOT EVALUATED** (Sprint 111+) |
| Sharpe − 1·SE > 0 | held-out | held-out gate | **NOT EVALUATED** |
| Block bootstrap ≥ 70% positive | held-out | held-out gate | **NOT EVALUATED** |
| Held-out capacity ≥ $1M | held-out | held-out gate | **NOT EVALUATED** |

The pre-registered gate set has ~15 items in the spec. Sprint 110's sweep tested one and it failed. The others are either held-out (require Sprint 111+ and burn a test-look) or require additional training runs (GRU/TCN baseline, correct target-only ablation, ECE reporting on the pooled val split).

The linear-gate failure is a real result. The rest of the pre-registered set is not yet an evaluated pass or fail.

---

## 9. Recommendations for the report

1. Rewrite the target-only gate line to NOT EVALUATED (§2 above).
2. Add finding 2c — the LR re-tuning read from v2's trajectory (§3 above).
3. Add one line naming why MPS not AWS (§7 above).
4. Add one line naming which checkpoint was evaluated per size (§7 above).
5. Add training curves as a companion artifact (`artifacts/sprint110-curves.md` or similar) to distinguish plateau from still-descending (§7 above).
6. Tighten the two attribution slips (§6 above).
7. Compute the p-value on the xs 60% vs bigger-size 53% dir-acc gap; report it as "not noise" rather than "worth investigating" (§5 above).
8. Frame the regime-conditional gate proposal as *"amendment to product-spec-v4 §Success gates requiring Architect Decision entry"* rather than *"candidate work"* (§4 above).

---

## 10. Bottom line

Arithmetic is clean. The two headline findings — signal concentrated in low-vol, monotonic size scaling with plateau — are real and correctly interpreted. The pre-registered linear gate fails as measured; that is honest.

Three interpretations need adjustment:

- The target-only gate is not measured. It should be labeled NOT EVALUATED, not FAIL.
- The v2 trajectory analysis was missed. v2's md hit 3.18 val_nll at step 12000 before divergence — 4.5% better than linear, on track for the 10% gate before the LR blew up. That is a cheap-to-test hypothesis (re-tune LR on md) the report currently does not name.
- The regime-conditional gate proposal must route through an Architect Decision, not a discretionary reinterpretation. The report gets close but should make the routing explicit.

Two attribution slips (Sprint 084 vs product-spec, Sprint 041 vs Sprint 061) and three missing-context items (training curves, MPS-vs-AWS reason, which-checkpoint) round out the punch list.

The report is honest about a genuine v1 finding: the transformer at 20K steps and lr=1e-4 does not clear the pre-registered pooled linear gate. That finding stands and belongs on the record. Sprint 111 either amends the pre-registration through a proper Decision, re-tunes the LR to test whether v2's trajectory reaches the gate, or runs the correct target-only ablation to measure what the sweep did not.
