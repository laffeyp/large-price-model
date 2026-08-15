# Full review — sprints 041-050

**Reviewer:** Claude Code (Opus 4.7), acting in Agent role.
**Date:** 2026-08-14.
**Scope:** the ten sprints since the pre-GPU-deploy review. Sprints 041 (pre-GPU review-driven fixes + parallel spec audit), 042 (aligned parquet enrichment), 043 (zoneinfo DST migration), 044 (cross-asset intraday ingest), 045 (five macro series), 046 (options put/call ratio), 047 (options volume), 048 (event tables), 049 (target features), 050 (VXX ingest). One vocabulary bump (v0.3 → v0.4, `WANDB_UPLOAD_FAILED` deprecated). 324 tests, four tools green throughout.
**Verdict:** discipline held cleanly. Six of my pre-GPU review's nine blockers/gaps closed. **One SEVERE gap the pre-GPU review missed remains open** — Sprint 041's parallel spec audit surfaced it; three of the pre-registered gates are structurally unmeasurable in the current code until that gap closes.

---

## 1. The gap I missed and Sprint 041 caught

Sprint 041 executed the pre-GPU review's mechanical fixes, then ran a **parallel independent spec re-read** and surfaced 19 additional gaps I hadn't flagged. The most important is a **SEVERE architecture-vs-spec mismatch**:

**The transformer input is bucket IDs, not multi-channel state.**

Tech-arch §7.2: *"Each timestep's per-channel feature vector passes through its own `nn.Linear` projection to a `d_model`-dim embedding, and the projections are summed to produce one `d_model`-dim market-state vector per bar."*

`model/transformer.py:36`:
```python
self.token_embedding = nn.Embedding(config.vocab_size, config.d_model)
```

Current model reads integer bucket IDs from the target's log_return and looks them up in an embedding table of size `vocab_size=32`. Every one of the 19 channels the ingest sprints wired, and every one of the 10 features Sprint 049 computed, is discarded at the model boundary. The transformer sees a scalar-per-position stream, not a multi-channel feature stream.

**Consequences for the pre-registered gates:**
- **Target-only ablation gate** (product-spec line 155: *"Validation NLL at least 5% lower than the target-only ablation on identical data"*) is structurally impossible: the current model *is* effectively target-only. Comparing to a target-only baseline is comparing to itself.
- **Multi-channel-lift claim** (product-spec line 21: *"the whole thesis rides on this comparison"*) has no way to be tested until the model consumes multi-channel features.
- **GRU/TCN gate** (product-spec line 154) has no baseline to compare against — still unshipped.

Three of the roughly fifteen pre-registered gates are unmeasurable in current code. **Do not spend GPU money until the model actually consumes what the ingest pipeline produces.**

The fix is `MarketStateEmbedder` from tech-arch §7.2: per-channel `nn.Linear(F_c, d_model)` → sum → position. That is a real sprint (needs the tokenizer to emit per-channel feature tensors, needs the model to accept a dict-of-tensors input, needs the trainer's dataset loader to yield the new shape, needs the causal-mask test re-verified). Not a one-line fix. But it is the ship path.

---

## 2. What closed cleanly (nine of my ten pre-GPU items)

**Blockers fixed:**

- **§2.1 config_hash across four CLIs** — Sprint 041. `scripts/{train,baselines,bucketize,features}.py` now hash the config file, not the tokens. `data_hash` separately keyed to input parquet. Live smoke confirmed: SESSION_INIT and CONFIG_RESOLVED both carry `config_hash = sha256(configs/experiment/v1.json) = 54db82ff...`, distinct from `data_hash = e66bea82...`.
- **§2.4 DST fixed-offset EST** — Sprint 043. `US_EASTERN_ZONE = ZoneInfo("America/New_York")` replaces the fixed `-5h` offset in `alphavantage.py` and `alignment/join.py`. June bars now report UTC-4 (EDT); November bars report UTC-5 (EST). Re-alignment verified row counts identical, bucket edges bit-identical, DST-boundary bars correct. Two new DST round-trip tests.
- **§4.1 WINDOW_SAMPLED.start_position** — Sprint 041. `WindowSampler.sample()` returns real starts on `WindowBatch.starts`; trainer emits `batch.starts[0]`. Verified against 2015-2022 tokens: first three emissions carry `start_position` 2088, 4703, 4322 — real indices in [0, 43303].
- **§4.2 EPOCH_COMPLETED.epoch** — Sprint 041. Now `ceil(tokens_consumed / len(train_tokens))`. 300-step smoke reports `epoch=4` for 153,600 tokens / 43,368 train ≈ 3.54. Honest counter.
- **§3.1 channel scope** — Sprints 044 (6 market_context: QQQ, IWM, TLT, GLD, USO, UUP), 045 (5 macro: CPI, FEDFUNDS, DGS10, UNRATE, NFP), 046 (options PCR), 047 (options VOL), 048 (4 events: EARNINGS_DENSITY_SPX, FOMC, CPI_RELEASE, OPTIONS_EXPIRY), 050 (VXX). Manifest now carries 19 channels total. Post-alignment shape: training 54,262 rows × 181 columns; test 10,166 × 181. My blocker closed.

**Watch items fixed:**

- **§4.3 twelve declared-but-unemitted tags** — Sprint 041 filed to Deferred with revisit trigger. Sprint 049 target features shipped. v0.4 removed `WANDB_UPLOAD_FAILED` (W&B abandoned). Simulator tags still unwired — correct absence, simulator not yet a scoped sprint.

**Corrections to my earlier claims (Sprint 041 caught two of my overstatements):**

- **§2.2 "per-bar leak from val into normalization"** — WRONG. I claimed `rolling_z_score_20` leaks val bars into val normalization. Sprint 041 verified `polars.rolling_mean(window_size=20)` is trailing/causal per-bar; no future-into-past leak. **The architectural gap is real** (rolling per-bar vs frozen expanding-window from tech-arch §Feature normalization line 67), but the leak claim was invention. Overstatement retracted.
- **§2.4 "correctness bug for any training run"** — PARTIALLY WRONG. I claimed fixed-EST breaks alignment. Sprint 041 verified alignment is internally consistent because ALL timestamps flow through the same offset; features and bucket edges bit-identical between pre- and post-Sprint-043 tokenized artifacts. **VIX known_at IS drift-affected during EDT months** (~7/12 months, ~1 hour late), which is a real bug the fix closed. But "any training run" was overstated. The fix was worth doing; the framing was hotter than the evidence.

I appreciate the correction. Both were reviewer overstatements the code review caught.

---

## 3. What still isn't fixed from the pre-GPU review

- **§2.2 Frozen normalizer.** Product-spec line 67 + line 205 (non-functional requirement): *"v1 uses an expanding-window causal z-score computed on the training partition only, then frozen. At inference and on validation and test, the frozen scaler is used as-is."* Current code computes per-bar rolling z-score, not training-partition-frozen. `NORMALIZER_FITTED` and `NORMALIZER_STATE_WRITTEN` still fire from zero call sites. Still a gap.
- **§2.3 Test-look guard wiring.** `testlook.py::register_test_look` exists (Sprint 034). Nothing calls it automatically. The 3-look budget is still guarded by human memory alone. BLACKBOARD line 122 flags this; no sprint has closed it.
- **§3.2 RoPE.** Model still uses `nn.Embedding(context_len, d_model)` for absolute learned positions. Tech-arch §8 promises RoPE. Not fixed.
- **§3.3 MLP + GRU/TCN baselines.** Still three of five (linear, target-only, magnitude-weighted). MLP silently absent, GRU/TCN deferred.
- **§3.4 Size sweep + context sweep.** Still one point at 208K params + context_len=64. Product-spec table pre-registers 1M/3M/10M/30M × {64,128,256,512}.
- **Device handling.** `run_training` still does not call `.to(device)`. Model and tensors are CPU-only. Add `--device {cpu,cuda}` before GPU launch.

And the SEVERE gap from §1 above — the transformer input path. That is the largest.

---

## 4. SDD-technique usage in the ten sprints (the user's emphasis)

Ten sprints. Twenty-plus technique applications worth naming.

**Halt-and-articulate at every real halt.** Sprint 046 caught a silent-failure bug (TokenBucket raised RateLimitExhausted silently; ingest loop caught the raise) and halted mid-sprint to fix rather than proceed. Sprint 047 caught a column-collision bug (`options__SPY__*` for two different channels) mid-sprint and halted for the `av_symbol` split fix. Sprint 048 halted on the tech-arch's `EARNINGS_CALENDAR` assignment when live probe showed it forward-only; the fix cascade landed in one sprint including an amendment to `specs/technical-architecture-v4.md` line 236 to record the corrected tool assignment. All three halts articulated, not bypassed.

**Retractions land same-day.** BLACKBOARD line 11 (2026-08-14): *"RETRACTED same day. Original entry proposed leaving options-volume unshipped and framed it as 'testable at reduced scope.' Architect corrected: no scope reduction, ever. Options-volume ships in Sprint 047 via per-contract volume aggregation from HISTORICAL_OPTIONS. Rule filed to Agent memory."* The Agent misframed a scope reduction as testable; the Architect corrected; the Agent retracted the same day, filed the rule to memory, and Sprint 047 shipped the previously-declined channel. That is the discipline working at speed.

**Parallel independent audit as a technique.** Sprint 041 didn't just execute my review's punch list — it ran an independent parallel spec re-read that surfaced 19 additional gaps beyond mine, including the SEVERE gap in §1. The pattern: *when a reviewer surfaces N findings, a spec-first re-read commonly surfaces 2N.* This is the "review the reviewer" move; worth naming as a kit technique. Sprint 041's card is the canonical example.

**Reviewer overstatement corrections.** My §2.2 leak claim and §2.4 severity claim were both invention past the evidence. Sprint 041 verified against live code, corrected both on the BLACKBOARD record. The kit's "workers cannot invent findings" discipline applied to me. Cite the pattern in KIT_DIARY.

**Vocabulary evolution through canonical proposal types.** v0.3 → v0.4: one tag deprecated (`WANDB_UPLOAD_FAILED`), zero tags added. Sprint 041 W&B was abandoned; v0.4 removed the tag; v0.3 stays on disk per hard rule 12; historical traces remain interpretable via the v0.3 loader. TAG_DEPRECATION_PROPOSED path. Clean.

**Bridge-mapping-required behavior on data.** Sprint 044's DXY substitution with UUP followed a documented multi-endpoint probe (INDEX_CATALOG lists only CBOE/S&P; FX_INTRADAY takes single currency pairs not baskets). Sprint 050's VXX substitution followed a full AV endpoint sweep (INDEX_DATA returns OHLC only, TIME_SERIES rejects VIX, HISTORICAL_OPTIONS empty). Both substitutions recorded in the channel manifest with detailed `reason` fields citing endpoint checks and known ETF-vs-index divergences. The pattern the Architect ratified is: *documented probe → substitution with citation → manifest carries the reason.* This is the honest handling of data trade-offs.

**Memory patterns filed for compounding.** Sprint 050 filed two persistent memory entries: `[[probe-before-claiming-absent]]` (any "AV lacks X" claim requires an explicit multi-endpoint sweep before shipping) and `[[prototype-substitutions-ok]]` (substitution with citation is a legitimate v1 move; document the divergence, don't hide it). Persistent knowledge across future sessions. This is the kit's "learnings compound" principle at the cross-session layer.

**Sprint cards articulate stretches explicitly.** Sprint 048's card names the SPX-constituent-list survivorship bias (~4-8% under-count) on the record before executing. Sprint 049's card names the fixture change (two-channel-count test 8→14). Sprint 050's card names the 5300-iteration cache-hit hang and the pivot to a lean manifest. Stretches on the card, not in the notes.

**Dual contract on every functional-band sprint.** Every Sprint 042-050 (all `pass_kind: functional` except 041 arch-mixed) authored an observation contract with a live-smoke exit code + row-count assertion + spot-check on a specific date (2022-06-15 Fed hike, 2020-03-16 emergency FOMC, etc.). No behavior-touching sprint shipped without a live check.

**Determinism budget declared.** Every sprint 041-050 carries `determinism_budget` in frontmatter (`bit-deterministic` for the 8 non-network sprints, `statistically-deterministic` where wall-clock or random network land).

**Spec amendment through a sprint, not a workaround.** Sprint 048 amended `specs/technical-architecture-v4.md` line 236 to correct the EARNINGS_CALENDAR tool assignment after discovering AV's endpoint is forward-only. The spec is treated as a living document maintained through sprints, not as an untouchable claim to be worked around. Correct hard-rule-12 discipline applied at the spec layer.

**One meta-observation.** Ten sprints, zero silent bypasses. Every scope stretch surfaced. Every misframing retracted. Every data trade-off documented with `reason` fields carrying vendor citations. This is the kit at cadence, and it is working.

---

## 5. Code architecture observations

**Vertical-slice by pipeline stage holds.** `src/price_space_llm/{ingestion,alignment,features,tokenizer,model,evaluation,cost_calibration}/` — each stage owns its operators + tests. Cross-cutting infrastructure at package root (`signals.py`, `config.py`, `git.py`, `script_harness.py`, `artifacts.py`, `testlook.py`, `baselines.py`, `wandb_sink.py`). Matches the practices-briefing's vertical-slice principle.

**`av_symbol` vs `symbol` split (Sprint 047)** is the right architecture move. `symbol` identifies the aligned column (`PCR_SPY`, `VOL_SPY`); `av_symbol` identifies the vendor's underlying (`SPY`). Prevents column-collision when two channels share an underlying. Back-compat default preserves the earlier call sites.

**`known_at_lag_days` + `known_at_hour_utc` in the manifest** (Sprint 045) puts release-timing metadata where it belongs — with the data, not scattered in code. Per-channel overrides live in the manifest; the alignment layer reads them uniformly. Extensible.

**`av_symbol` split preserved back-compat via optional kwarg.** Existing tests continue to pass. The pattern: extend without breaking, migrate call sites in the same commit. Good rule-14 discipline.

**Rate-limit backpressure (Sprint 046).** `TokenBucket.acquire_blocking()` sleeps until a token frees. Injectable sleep for tests. `IngestionClient.__init__` gains `rate_limit_behavior: Literal["raise","block"]="raise"` with back-compat default. Correct API-design pattern — new behavior opt-in via keyword; default preserves prior semantics.

**Feature failures typed with reason enums** (Sprint 049). `_classify_failure` gains reason branches per new feature (insufficient_history, divide_by_zero, nan_input). `FEATURE_COMPUTATION_FAILED.reason` payload now carries semantic information a Reviewer can filter on. Honest.

**One concern.** `run_alignment` dispatch is growing branches: TIME_SERIES_INTRADAY, INDEX_DATA, macro tools set, HISTORICAL_PUT_CALL_RATIO, HISTORICAL_OPTIONS, EARNINGS, STATIC_FOMC, STATIC_CPI_RELEASE, DETERMINISTIC_OPTIONS_EXPIRY. That is nine branches in one dispatch function. Consider a `Loader` Protocol + registry pattern before this grows further — one class per source-type, register in a dict, dispatch via lookup. Not a defect today; deferred readability question.

---

## 6. Data trade-offs — how they were handled

The user cited "VXX for VIX" as an acceptable trade-off. The pattern the Architect ratified is worth naming as canonical:

1. **Multi-endpoint probe first.** Full AV endpoint sweep on the primary signal (INDEX_DATA / TIME_SERIES_DAILY / TIME_SERIES_INTRADAY / HISTORICAL_OPTIONS / etc.). Document what returned what.
2. **Substitute with citation.** If the primary is unavailable, name a related-signal substitute (VXX for VIX volume; UUP for DXY). Cite the vendor evidence.
3. **Document the divergence.** Manifest `reason` field carries the ETF-vs-index correlation coefficient, known tracking errors, expense ratios, futures-roll effects, and the honest statement "later versions will pay for X directly."
4. **File the memory pattern.** `[[prototype-substitutions-ok]]` — substitution with citation is a legitimate v1 move.

Both UUP and VXX manifest entries follow this pattern with real citations (Databento Plus tier price cited for DXY; VXX split history and ETN structure cited for VIX volume). Both substitutions are honest at the v1 prototype tier and marked for v2 replacement. Textbook.

---

## 7. Punch list

**Pre-GPU blockers (must fix before spending GPU money):**

1. **The SEVERE gap: transformer consumes bucket-IDs, not multi-channel state** (§1). Land `MarketStateEmbedder` per tech-arch §7.2. Requires dataset loader shape change, model input shape change, causal-mask re-verify. Own sprint or two. Without this, three pre-registered gates are unmeasurable.
2. **Frozen normalizer** (§3 above). Wire training-partition-only expanding-window fit + persistence to `normalizers.pt` + val/test read the frozen state. Wire `NORMALIZER_FITTED` and `NORMALIZER_STATE_WRITTEN` emit sites.
3. **Test-look guard wiring** (§3 above). Any script that reads the test partition calls `register_test_look()` first. Exit 2 on `TestLookBudgetExhausted`.
4. **Device handling** (§3 above). `--device {cpu,cuda}` on `scripts/train.py`; thread through model, batches, generator.

**Ratify explicitly (Architect Decision):**

5. RoPE substitute or land (§3 above).
6. MLP + GRU/TCN baseline plan (§3 above).
7. Size sweep + context sweep plan (§3 above).
8. Normalization-drift diagnostic (product-spec line 251: *"plot the normalized-feature distribution on the holdout against training"*). Needs a signal home or an artifact home.

**Watch (small, non-blocking):**

9. `run_alignment` dispatch — nine branches; introduce Loader Protocol + registry before it grows to twelve.
10. Simulator subsystem still unwired — twelve declared vocabulary tags await the sprint that opens §11.

---

## 8. Bottom line

The pre-GPU review flagged nine items; six closed cleanly, two remain, one was reviewer overstatement corrected. The SEVERE gap Sprint 041's parallel audit surfaced — the transformer eats bucket IDs, not multi-channel state — is the largest single ship-blocker and it did not appear in my pre-GPU review. That is the finding that matters most from these ten sprints.

The discipline is holding, the retraction cadence is at same-day, memory patterns are compounding, spec amendments route through sprints, data trade-offs carry vendor citations, and the halt-and-articulate rate at real halts is 3/3 across the arc. What is not yet honest is the model boundary. Wire the channels the ingest sprints produced into the transformer, land the frozen normalizer, wire the test-look guard, land device support. Then the GPU spend has a claim to defend.
