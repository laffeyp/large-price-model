# Coverage review — does the vocabulary cover what the program will say?

**Reviewer:** Claude Code (Opus 4.7), acting in Agent role.
**Date:** 2026-08-09.
**Scope:** `signals/0.1.json` (Layers 0–10 + dual-contract audit) plus `signals/0.1-rationale.md`, evaluated against `specs/product-spec-v4.md` and `specs/technical-architecture-v4.md`.
**Frame:** For each stage of the pipeline the tech-arch defines, does the program have a tag to name what happens? For each pre-registered gate in the product-spec, does the vocabulary carry the signal that would verify it? For each documented failure mode, does the vocabulary have a home?
**Recommendation:** Do not sign Step 12 yet. Add the tags in §§1–4, tighten the payloads in §5, and answer the two design questions in §7. Then lock.

---

## 0. What round 4 does right

Ambient-stratum discipline is honest — BAR_PROCESSED carries only timestamp; ALIGNMENT_ROW_EMITTED carries timestamp + `missing_channels_count`. That is technique #6 correctly applied. The known_at schema is faithfully reflected (RAW_OBSERVATION_WRITTEN carries all four columns). Every incident tag has a `reason` enum with named values, so a Reviewer reading the trace can distinguish `history_too_short` from `frequency_mismatch` from `semantics_ambiguous` from `missing_fraction_high`. The Layer-5 allowed_set per `run_kind` cleanly separates what a probe process may emit from what a train process may emit — that is the state-machine the pipeline actually runs. The three merges (P-001, P-002, P-003) removed the domain-decomposition slop cleanly.

The remaining question is coverage — not discipline. What the program will observe, and whether the vocabulary has the words for it.

## 1. Pre-registered gates with no signal home

The product-spec pre-registers gates. Some pass through the current vocabulary; some do not.

**`TRAINING_DIVERGED` / `TRAINING_NAN` — missing.** Product-spec §"Success gates for v1" first bullet: "Training completes without NaN, divergence, or gradient explosion." This is gate #1. When NaN loss appears at step N, the current vocabulary records it as a `train_loss` field of value `NaN` inside TRAINING_STEP_COMPLETED — an ambient event tagged as normal. No incident-stratum tag fires. A Report reader has to compute `isnan(train_loss)` to notice. The gate exists in the spec; the signal does not exist in the vocabulary. This is exactly the "gate nobody has watched fail is not a gate" trap from Addendum D that BLACKBOARD's comprehension affirmation names as binding.

Add: `TRAINING_DIVERGED` (category: `train`, stratum: `incident`) with `reason ∈ {nan_loss, gradient_explosion, loss_plateau, val_metric_diverged}`, payload `run_id`, `step`, `train_loss`, `grad_norm`, `val_nll_at_last_eval`.

**`MANIFEST_STALE` / `MANIFEST_MISSING` — missing.** Tech-arch §4.1: "align.py opens `channel_coverage.json`, checks its `generated_at` timestamp against the channel-config mtime, and hard-fails if the probe is stale or missing." This is a hard runtime failure with a named cause. The vocabulary has CONFIG_VALIDATION_FAILED for Pydantic-side failures but no equivalent for the manifest-staleness gate. Currently the failure surfaces as SESSION_COMPLETE with `exit_code != 0` and a stderr string — the trace cannot distinguish it from a NaN divergence or an OOM.

Add: `MANIFEST_STALE_OR_MISSING` (category: `align`, stratum: `incident`), payload `manifest_path`, `manifest_generated_at`, `channel_config_mtime`, `reason ∈ {stale, missing, unparseable}`.

**`BUCKET_FREQUENCY_DRIFT_MEASURED` — missing.** Product-spec §"Regime evaluation" and tech-arch §10 both name this diagnostic explicitly: "the realized bucket-frequency histogram on validation and holdout, compared to training's target frequencies." Tech-arch §10 calls it a required diagnostic. The current METRIC_COMPUTED tag covers scalar metrics by name from an enum `{nll, ece, brier, rps, dir_acc, top1, top3}` — no member of that enum names the drift-diagnostic distribution. The diagnostic will run and W&B will show a histogram; nothing in the trace records that it ran.

Add: `BUCKET_FREQUENCY_DRIFT_MEASURED` (category: `evaluate`, stratum: `summary`), payload `run_id`, `split`, `train_frequency_by_bucket: list<float>`, `realized_frequency_by_bucket: list<float>`, `max_absolute_deviation: float`, `outer_bucket_ratio: float`. Optionally an incident sibling that fires when `max_absolute_deviation` exceeds a threshold — this is a first-class pre-registered diagnostic and belongs in the vocabulary rather than in a notebook.

**`SENSITIVITY_PLOT_GENERATED` — missing.** Product-spec §"Success gates for v1": "results include a Sharpe-vs-`kappa` sensitivity plot from 0.5× to 2× the point estimate." Explicit deliverable. No signal fires when the plot generates. Same category as bucket-frequency-drift — a required diagnostic that leaves no trace.

Add: `SENSITIVITY_PLOT_GENERATED` (category: `simulate` or `evaluate`, stratum: `summary`), payload with the array of `(kappa_multiplier, sharpe_point)` pairs; Layer-7 evidence constraint that `min(sharpe) > 0` gates the run.

## 2. Documented failure modes with no incident tag

Tech-arch names runtime failure modes the pipeline can experience. Several have no signal home.

**Retry-with-backoff on 429/5xx.** Tech-arch §4.2: `IngestionClient` does "retry-with-backoff on 429/5xx." A three-retry burst before success looks in the trace like three INGESTION_CALL_ISSUED events at ambient stratum — indistinguishable from three normal calls. A five-retry burst before falling back looks the same until SOURCE_FALLBACK_TRIGGERED fires. Debuggability gap.

Add: `INGESTION_CALL_RETRIED` (category: `ingest`, stratum: `incident`), payload `source`, `tool`, `attempt`, `status_code`, `backoff_seconds`, `reason ∈ {rate_limit, server_error, timeout, response_invalid}`.

**Rate-limit exhaustion without fallback.** Currently `rate_limit_exhausted` appears only as one value of `SOURCE_FALLBACK_TRIGGERED.reason`. Both `mcp_av` and `polygon` can be rate-limited without triggering a fallback (the rate limit is per-Source, not per-request-path). The condition has no dedicated tag.

Fold into `INGESTION_CALL_RETRIED` above, or add `INGESTION_RATE_LIMIT_HIT` as a distinct incident.

**FEATURE_COMPUTATION_FAILED.** A rolling window with too few valid rows, a `spread_proxy = 2 * |high - low| / (high + low)` where `high == low == 0`, or a divide-by-zero on `realized_vol_30` in a flat market — each yields NaN. The current vocabulary has FEATURE_COMPUTED (ambient) with no failure sibling. Failures propagate silently into the tokenized tensor and surface at training as loss-NaN — attributed to the training loop, not to the actual origin.

Add: `FEATURE_COMPUTATION_FAILED` (category: `feature`, stratum: `incident`), payload `timestamp`, `channel`, `feature_name`, `reason ∈ {insufficient_history, divide_by_zero, nan_input, downstream_error}`.

**Force-close at last bar of sim range.** Tech-arch §11.4 requires all positions closed by SIM_RUN_COMPLETED. Layer 4's window invariant enforces the constraint. But the *mechanism* — the last-bar forced close — has no signal distinct from a normal POSITION_CLOSED (which prints at the *next* bar's open). At the end of the sim range there is no next bar; the close must fire at the last bar's close price. That is a distinct decision. Currently the trace shows a POSITION_CLOSED that looks identical to a mid-sim exit.

Add: `POSITION_FORCE_CLOSED` (category: `simulate`, stratum: `event`), payload `timestamp`, `close_price`, `reason ∈ {sim_range_end, session_boundary_forced_close}`. Or extend POSITION_CLOSED with a `close_kind` enum. Either is fine; one is required.

**W&B upload silence.** WandbTracker operator (Layer 6) has empty `emits[]`. Reliability diagrams and predicted-distribution charts (tech-arch §9.3) are pre-registered deliverables. If the W&B connection drops or the upload 502s, no signal fires. This is the soundfield "mock backend ran for sprints because no runtime signal said 'I'm a mock'" pattern applied to a live external service.

Add: `WANDB_UPLOAD_FAILED` (category: `evaluate`, stratum: `incident`), payload `artifact_kind ∈ {reliability_diagram, predicted_distribution_chart, sensitivity_plot, per_step_scalar, checkpoint_ref}`, `error`. Optionally `WANDB_INITIALIZED` (event) so the successful case has a trace.

## 3. Foreign-key gap in SIM_RUN_STARTED

SIM_RUN_STARTED carries `run_id` (the sim's own), `split`, `date_range_start`, `date_range_end`, `checkpoint_step: int`, `cost_calibration_run_id: str`. `checkpoint_step` is an integer indexing `artifacts/{run_id}/step_{step}.pt`. But *which* `run_id`? The sim mints its own `run_id` at SESSION_INIT; the checkpoint came from a training TrainingRun's `run_id`. The signal alone does not name the training run.

Add: `checkpoint_run_id: str` (required) to SIM_RUN_STARTED payload. Rationale-doc note: once the v0.2 `Run` entity unifies run_id, both `checkpoint_run_id` and `cost_calibration_run_id` become `entity_ref<Run>` and the FK-resolution rate climbs.

## 4. Payload fields the docs name but the tags miss

**CHECKPOINT_WRITTEN payload — missing `val_top1` and `val_top3`.** Tech-arch §9.3 lists both alongside NLL/ECE/Brier/RPS/dir_acc as per-eval logged metrics. Current payload has `val_nll`, `val_ece`, `val_brier`, `val_rps`, `val_dir_acc` only. Two-line fix.

**DECISION_MADE payload — missing hysteresis-adjusted threshold.** Tech-arch §11.4: "Opposite-direction signals require `|edge| > threshold + hysteresis * threshold` to flip." The decision reason `hysteresis_hold` fires when the *adjusted* threshold blocked the flip. Current payload has `threshold` (the base) but not the adjusted value the decision actually compared against. A debugger asking "why didn't we flip long-to-short at bar N when edge = -0.5?" has to reconstruct `threshold * (1 + hysteresis)` from the ExperimentConfig. Fine if that's acceptable; better to include `effective_threshold` in the payload.

**POSITION_OPENED timestamp — decision bar or fill bar?** Tech-arch §11.4: "Entries and exits print at the next bar's open." So the fill occurs at bar T+1 while the decision was at bar T. POSITION_OPENED.timestamp is unspecified between the two. A payload note or a split into `decision_bar_ts` and `fill_bar_ts` removes ambiguity. Same for POSITION_CLOSED.

## 5. `capacity_usd` overloads two distinct quantities

SIM_RUN_COMPLETED payload has `capacity_usd: float`. Tech-arch §11.5 describes capacity as coming from "a capacity sweep" — a series of simulation runs at incrementing position sizes, finding "the largest position size at which Sharpe stays positive." That is a multi-run output; a single SIM_RUN_COMPLETED cannot naturally hold it.

Either the payload field is the sweep's final answer (in which case SIM_RUN_COMPLETED fires only for the sweep-driving run and not for the per-size runs, which is currently unspecified), or it is the single-run implied capacity (in which case the sweep output has no signal home).

Two clean fixes:
- Add `CAPACITY_SWEEP_COMPLETED` (category: `simulate`, stratum: `summary`) with payload `points: list<{size_usd: float, sharpe: float, sharpe_se: float}>` and `capacity_usd: float` derived. Have SIM_RUN_COMPLETED drop the `capacity_usd` field.
- Or rename the SIM_RUN_COMPLETED field to `implied_capacity_at_this_size_usd` and add a note that the sweep result lives in a separate signal or artifact.

## 6. The domain-lifecycle strata asymmetry

`align_run` and `sim_run` are domain-lifecycle strata with their own boundary tag pairs (ALIGNMENT_RUN_STARTED/COMPLETED, SIM_RUN_STARTED/COMPLETED). `train_run`, `eval_run`, `calibrate_run` are not — they open and close with SESSION_INIT / SESSION_COMPLETE bearing `run_kind`. The rationale doc notes the choice ("adding nested boundary tags for every kind would be ceremony") and defends it.

The defense is fine. But the asymmetry has downstream consequences the doc does not spell out: Layer-4 window invariants exist for `align_run` and `sim_run` (ALIGNMENT_ROW_EMITTED cadence bounded by align_run's window) but no equivalent for train (no analogous cadence check on WINDOW_SAMPLED bounded by a train_run). Layer-5's allowed_set for `process_session where run_kind=train` is the whole process; there is no nested sub-scope. If a training run ever needs to distinguish "warmup phase" from "main phase," or "epoch 0" from "epoch N," the nested-session mechanism used for align and sim will not be there.

Not a v0.1 gap. Add a rationale-doc sentence naming it as a future v0.2 candidate: if a training-phase distinction ever becomes a real need, `train_run` gets promoted from run_kind-attribute to a domain-lifecycle stratum with boundary tags, matching the align/sim precedent.

## 7. Sweep-as-entity has no home

The model-size sweep and the context-length sweep are first-class experimental deliverables (product-spec §"Success gates for v1": "The model-size sweep is reported as a curve"). Each sweep-point is a separate TrainingRun; the *sweep* — four TrainingRuns sharing config family, seed, and tokenized dataset — is a virtual entity that must be reconstructed by post-hoc join across TrainingRuns.

Two designs:
- Accept the reconstruction: rationale-doc note ("sweeps are post-hoc joins across TrainingRuns via config family; no dedicated entity in v0.1").
- Promote: add a `SweepRun` entity with `sweep_kind ∈ {model_size, context_len, bucket_count}` and a `SWEEP_COMPLETED` summary tag. Each contributing TrainingRun carries `parent_sweep_id`.

The choice depends on how much of the reporting flow is going to run through signals versus through notebooks. If the sweep report is a notebook artifact, the reconstruction is fine. If the sweep result needs to appear in a Signal Report at phase close, the entity is needed.

This is an Architect design question, not a review defect. Answer it in the rationale doc before lock.

## 8. Bookkeeping the ambient discipline correctly demands

Ambient tags carry the minimum needed to reconstruct the sequence, not the full state. That is technique #6 correctly applied. But it means a Reviewer working from the trace file alone cannot reconstruct much of the pipeline's behavior — they need to open the aligned parquet, the checkpoint, the metrics JSON.

The observation contract in WORKING_AGREEMENT.md § "Observation contract environment" names this correctly: "signal-in-trace + artifact-on-disk + exit-code + W&B log line." The rationale doc's dual-contract audit section carries it. But a fresh Reviewer at Sprint 15 who opens `logs/sim-2026-11-15/signals.jsonl` and finds only `BAR_PROCESSED  t=...` for hours of trace may not immediately grasp that the semantic content lives one layer over. Add a rationale-doc sentence naming this explicitly: "Ambient-stratum tags are pointers, not payloads. Where they fire tells the story; what happened at that firing lives in the paired artifact."

## 9. Ratification recommendation

Do not sign Step 12 yet. Add the following, then lock:

**Four new tags (all `NEW_TAG_PROPOSED` shells, filed against v0.1 pre-lock):**

- `TRAINING_DIVERGED` (train / incident)
- `MANIFEST_STALE_OR_MISSING` (align / incident)
- `BUCKET_FREQUENCY_DRIFT_MEASURED` (evaluate / summary)
- `SENSITIVITY_PLOT_GENERATED` (evaluate or simulate / summary)

**Three new tags for runtime failure modes:**

- `INGESTION_CALL_RETRIED` (ingest / incident)
- `FEATURE_COMPUTATION_FAILED` (feature / incident)
- `POSITION_FORCE_CLOSED` (simulate / event) — or extend POSITION_CLOSED with a `close_kind` enum
- `WANDB_UPLOAD_FAILED` (evaluate / incident)

**Payload fixes:**

- Add `checkpoint_run_id: str` (required) to SIM_RUN_STARTED.
- Add `val_top1` and `val_top3` to CHECKPOINT_WRITTEN.
- Add `effective_threshold: float` to DECISION_MADE.
- Disambiguate `timestamp` on POSITION_OPENED / POSITION_CLOSED (either split into `decision_bar_ts` + `fill_bar_ts` or add a payload note).

**One design decision to resolve before lock:**

- `capacity_usd` on SIM_RUN_COMPLETED — is it the sweep result or the single-run implied capacity? Either add `CAPACITY_SWEEP_COMPLETED` and drop the field, or rename the field.

**Two rationale-doc additions:**

- The asymmetry in domain-lifecycle strata (align/sim have them; train/eval/calibrate do not) is defensible but should be named explicitly, with the promotion path to v0.2 noted.
- The sweep-as-entity question (§7) needs the Architect's answer written into the rationale doc so future readers know whether to expect a SweepRun entity in v0.2.
- One sentence naming the ambient-payload minimalism convention: "where they fire tells the story; what happened lives in the paired artifact."

**Every finding here is a coverage gap, not a discipline violation.** The Layer-0-through-Layer-10 mechanics are clean; the four review-pass rounds against rounds 1–3 fixed the discipline problems. What remains is the smaller and more empirical question of whether the vocabulary — as a schema — covers what the program will actually observe and needs to report. Twelve gaps, none catastrophic, all addressable in a single revision pass before lock.

The founding act is real work. Address these, then sign.
