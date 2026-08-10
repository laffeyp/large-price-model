# Round-5 review — coverage-recast against `signals/0.1.json`

**Reviewer:** Claude Code (Opus 4.7), acting in Agent role.
**Date:** 2026-08-09.
**Scope:** The round-5 recast of `signals/0.1.json` and `signals/0.1-rationale.md` against `reviews/vocab-0.1-coverage-review.md`. Counts pre-recast: 46 tags, 39 evidence constraints, 46 dual-contract pairings. Counts post-recast: 54 tags, 54 evidence constraints, 54 dual-contract pairings.
**Recommendation:** Fix five bookkeeping stalenesses (§1) and answer one open class of missing constraints (§3). Then sign Step 12.

---

## 0. What landed cleanly

Every one of the twelve coverage-review findings is addressed in the artifacts. Eight new tags (TRAINING_DIVERGED, MANIFEST_STALE_OR_MISSING, BUCKET_FREQUENCY_DRIFT_MEASURED, SENSITIVITY_PLOT_GENERATED, INGESTION_CALL_RETRIED, FEATURE_COMPUTATION_FAILED, WANDB_UPLOAD_FAILED, CAPACITY_SWEEP_COMPLETED) each carry a typed payload, a note, and a source citation. Each got assigned to an emitting operator (TrainingLoop → TRAINING_DIVERGED, AlignmentJoin → MANIFEST_STALE_OR_MISSING, IngestionClient → INGESTION_CALL_RETRIED, FeaturePipeline → FEATURE_COMPUTATION_FAILED, Evaluator → BUCKET_FREQUENCY_DRIFT_MEASURED, Simulator → SENSITIVITY_PLOT_GENERATED + CAPACITY_SWEEP_COMPLETED, WandbTracker → WANDB_UPLOAD_FAILED). Each was added to the appropriate run_kind allowed_set. Each has a dual-contract anchor. The four payload fixes (`checkpoint_run_id`, `val_top1`/`val_top3`, `effective_threshold`, `decision_bar_ts`/`fill_bar_ts`/`close_kind`) and the `capacity_usd` → `implied_capacity_at_this_size_usd` rename all applied cleanly. The rationale doc gained the three requested sections (pointers-not-payloads, domain-lifecycle asymmetry, sweep-as-signal-not-entity), each anchored to the review finding that surfaced it.

Two forced_next rules got added at Layer 5 (MANIFEST_STALE_OR_MISSING → SESSION_COMPLETE; TRAINING_DIVERGED → SESSION_COMPLETE), matching the tech-arch's hard-fail semantics. The MANIFEST tag correctly lives at the process_session level rather than inside align_run — it fires *before* ALIGNMENT_RUN_STARTED opens the nested session, and the forced_next skips straight to close. That placement is right.

## 1. Five bookkeeping stalenesses

Adding eight tags to a vocabulary means eight rows added in a dozen places. Five of the audit-trail scans did not re-run after the recast.

**1.1 `_reachability_check.reachable_from_session_init` still lists 46 tags** (`signals/0.1.json` line 3162). The eight new tags are absent from the list even though they appear in the updated allowed_sets. They *are* reachable — the check will PASS on re-run — but the recorded audit says the tags weren't checked. Append the eight tag names.

**1.2 Layer 6 `_layer` note says "23 operators named"** (line 3226) while the operator list holds 24 and `BLACKBOARD.md` line 15 says 24. `_halt_check_step_7` gives `operator_count: 24` and `tag_count: 46` — the operator count is right, the tag count is stale (should be 54). Fix both.

**1.3 Layer 4 halt check `_halt_check_step_5`** says "all 10 ambient tags have cadence entries above." That count is still accurate — the new tags are incident and summary, no new ambient — but the check should note that it re-ran and confirmed no cadence-conflicts against the two new forced_next rules.

**1.4 Layer 5 halt check `_halt_check_step_6`** says "PASSES" — was authored before the recast. Re-run the reachability, cycle, and rule-conflict scans against the enlarged tag set and re-record the PASSES verdict with the updated tag count.

**1.5 Dual-contract audit `n_behavior_tags_audited: 46`** — needs to become 54. The 8 new pairings are present in the pairings array but the counter and any consumer that reads the counter (a Report generator, a test) will read 46.

None of these five is a defect in what round 5 built; each is a stale-audit-record that will confuse a Reviewer six months from now.

## 2. Two Layer-taxonomy slips

**2.1 Cadence entries on two incident tags.** Layer 4 gained cadence rules for INGESTION_CALL_RETRIED (line 2793) — "0 in a healthy run" — and FEATURE_COMPUTATION_FAILED (line 2800) — "0 in a healthy pipeline". Cadence at Layer 4 is defined for ambient-stratum tags with regular firing rates. What these two entries actually assert is an *expected count* on incident-stratum tags: "count should be zero, non-zero surfaces to Report." That is a Layer-7 evidence constraint (`kind: expected_count` or `kind: healthy_run_count`), not a Layer-4 cadence. Move them to Layer 7, or add `expected_count` as a legitimate cadence-kind variant with a rationale-doc note that this is a project-specific extension.

**2.2 New pairing cardinality `1 : N`.** CAPACITY_SWEEP_COMPLETED ↔ SIM_RUN_STARTED/COMPLETED at cardinality "1 sweep : N per-size sim runs" (line 2846). BOOTSTRAP's pairing invariants in the seed examples are 1:1 or 1:2. This is 1:N, which is legitimate but not previously used. Add a rationale-doc sentence naming the new cardinality shape so a future Reader does not treat it as a typo.

## 3. The numeric-gate class the eight new tags did not close

The coverage review's finding 1 was: "product-spec pre-registers gates that have no signal home." Round 5 gave the *signals* homes — TRAINING_DIVERGED, MANIFEST_STALE_OR_MISSING, BUCKET_FREQUENCY_DRIFT_MEASURED, SENSITIVITY_PLOT_GENERATED. That closes half the class. The other half is the *numeric thresholds* those signals should carry.

Product-spec §"Success gates for v1" pre-registers these numeric passes:

- **Held-out capacity ≥ $1M.** CAPACITY_SWEEP_COMPLETED.capacity_usd holds the value; Layer 7 line 4025 requires the field's presence and defines its computation but does not enforce `capacity_usd >= 1_000_000`. No gate on the number.
- **Held-out Sharpe `Sharpe − 1·SE > 0`.** SIM_RUN_COMPLETED payload has sharpe_point and sharpe_se; no Layer-7 constraint enforces `sharpe_point - sharpe_se > 0`.
- **Held-out Sharpe stronger gate `Sharpe > 0.5`.** No Layer-7 constraint.
- **Block-bootstrap `≥ 70%` of blocks positive.** Layer 7 line 3713 has a range spec whose *note* says "gate requires ≥ 0.70" — but the spec itself only requires `[0, 1]`. The gate is documented but not enforced.
- **Validation ECE `< 0.05`.** No Layer-7 constraint on METRIC_COMPUTED.value when name = 'ece'.
- **Val NLL `≥ 10% lower` than 1-layer linear baseline.** No cross-run comparison constraint.
- **Val NLL `≥ 5% lower` than GRU/TCN baseline.** Same.
- **Val NLL `≥ 5% lower` than target-only ablation.** Same.

For SENSITIVITY_PLOT_GENERATED the round-5 recast *did* add two numeric gates (line 4030-4045: `min_sharpe > 0` and `sharpe_crosses_zero_in_range == False`). That is the shape the other seven gates should take.

This is the same coverage-review finding one layer over. The eight signal tags said "we can see when it fails." The eight numeric constraints would say "we know what failure looks like." Currently the vocabulary can emit a Sharpe of 0.3 with SE of 0.4 (product-spec: fails the `Sharpe - SE > 0` gate) and the trace records it as a normal summary. A Report reader has to compute the gate themselves.

Two of these gates (val NLL versus baselines) are cross-run comparisons — a constraint on METRIC_COMPUTED.value cannot enforce them because the reference value lives in another run. Those either need a new tag (`BASELINE_COMPARISON_ASSESSED` with the deltas) or a rationale-doc note explicitly deferring them to a Report-time computation. Either is honest; silence is not.

## 4. Three semantic questions the recast surfaced

**4.1 `TRAINING_DIVERGED.reason: loss_plateau` needs a source.** The Layer-4 forced_next rule (line 2814) asserts: "if TRAINING_DIVERGED fires, TrainingLoop halts; no CHECKPOINT_WRITTEN or EPOCH_COMPLETED follows." Two of the enum values are numerical failures (nan_loss, gradient_explosion) — the loop clearly cannot continue past those. `val_metric_diverged` is a plausible early-stop trigger. But `loss_plateau` is a design choice: some training loops early-stop on plateau, some run to the fixed step budget. Tech-arch §9 defines the epoch as "a fixed step budget" and does not name plateau-halting as a mechanism. The vocabulary asserts halting; the tech-arch does not say the loop halts on plateau. Either cite a WORKING_AGREEMENT decision, or drop `loss_plateau` from the enum until the training loop's early-stop policy is decided.

**4.2 `FEATURE_COMPUTATION_FAILED` needs a downstream-consequence note.** The tag fires per (channel, timestamp, feature_name). What happens next is unspecified. Options: the AlignedRow's `missing_mask_{channel}` bit flips true (re-using existing AS_OF_JOIN_MISS semantics); the bar is dropped; the whole run halts. The vocabulary does not say. A rationale-doc sentence resolves it: "FEATURE_COMPUTATION_FAILED is a diagnostic; the downstream row carries `missing_mask` true for the affected channel. Systemic failures (many features failing for one channel across many bars) should surface via CHANNEL_REJECTED at the next probe run."

**4.3 Incident-halting asymmetry needs a rationale-doc sentence.** MANIFEST_STALE_OR_MISSING and TRAINING_DIVERGED both `forced_next → SESSION_COMPLETE`. WANDB_UPLOAD_FAILED does not halt. INGESTION_CALL_RETRIED does not halt. FEATURE_COMPUTATION_FAILED does not halt. That is honest — an observability degradation is not a correctness failure — but the asymmetry is not named. Add: "Incidents split on whether they name a correctness gate. Manifest-staleness and training-divergence halt; the pipeline cannot produce a valid artifact if the manifest is stale or the loss is NaN. W&B-upload-failure, ingestion-retry, and feature-computation-failure degrade observability or completeness but do not invalidate the run. The forced_next rules encode the distinction."

## 5. The trajectory

Round 1 invented vocabulary; round 2 invented meta-vocabulary; round 3 broke layer dependency order twice; round 4 fixed the mechanism uniformly; round 5 answered the coverage question. Round 5's remaining slips are, in order of magnitude:

- Five stale audit-record counters (§1) — half-hour to fix.
- Two Layer-taxonomy slips (§2) — a move and a rationale-doc sentence.
- One missing class of numeric-gate constraints (§3) — the largest item, six-to-eight new Layer-7 entries plus one rationale-doc note on the two cross-run gates.
- Three semantic questions (§4) — one deletion or citation, two rationale-doc sentences.

None is a defect in what round 5 built. All are small-and-final. The vocabulary can carry every observation the program will make; the remaining edits sharpen how the vocabulary reads pass/fail against the pre-registered gates and how a Reviewer six months from now reconstructs why a design choice was made.

## 6. Ratification recommendation

Fix §1 (five audit-record refreshes), §2 (move the two miscategorized cadence entries, add rationale-doc sentence on the 1:N pairing), and §4 (one enum-value citation-or-deletion, two rationale-doc sentences on downstream consequences and halting asymmetry). Then decide §3: either add the seven-plus Layer-7 numeric-gate constraints now, or add a rationale-doc entry naming them as a deliberate v0.1-Report-time deferral with the intent to add in v0.2 alongside the first held-out sim run. Both are defensible; silence is not.

After those edits, Step 12 signs: Architect stamps the rationale doc, sets `locked_at` and `locked_by` in `version_metadata`, writes the closing entry to `## Built`, and Sprint 1 dispatches.

The founding act closes here.
