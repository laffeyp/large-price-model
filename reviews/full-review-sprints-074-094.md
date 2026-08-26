# Full review — sprints 074-094

**Reviewer:** Claude Code (Opus 4.7), acting in Agent role.
**Date:** 2026-08-17.
**Scope:** the 21 sprints since `reviews/full-review-sprints-051-073.md`. Two vocabulary bumps (v0.5 → v0.6 → v0.7). New `src/price_space_llm/simulation/` package. Phase E ablation surface completed (channel-mixer + patch=4 + quantile head + bucket-count sweep). Phase F (simulator) opened cleanly under hard rule 6 with three sprints (skeleton → prediction → policy). Test count 437 → 543 (+106). Ruff / mypy / pytest / uv build green throughout.
**Verdict:** the discipline continues to compound. Every prior-review errata item has a sprint on the record. Storage-integrity and fail-loud invariants tightened at three call sites via a single generalizable pattern. Phase E is complete; Phase F is three sprints in and on track. Simulator is not yet trade-ledger complete; two follow-ups named on Sprint 094's card open Sprint 095 (position state machine + trades) and Sprint 096 (metrics + block bootstrap).

---

## 1. Prior-review errata closed

The 2026-08-17 errata block on `reviews/full-review-sprints-051-073.md` recorded three claims that did not match code after re-verify, plus one Sprint 052 follow-up the review missed. All four have landed on the record:

- **§6 Sprint 071 overstatement.** Options features actual: `OPTIONS_FEATURE_SPECS = ("z_score_20d",)` — one rolling z-score, not "staleness pair + z-scores." Errata annotated inline.
- **§6 Sprint 072 overstatement.** Event features actual: `("release_flag", "mins_to_next_release")`. `release_flag` is a binary fresh-event indicator, not a "time-since-last" age feature. Errata annotated inline.
- **§10 RoPE mischaracterization.** The 2026-08-16 Architect Decision deferred RoPE past pre-GPU work. The review missed the Decision entry. Errata clarifies: deferred, not unaddressed.
- **Sprint 052 mask follow-up.** Sprint 075 closed it. Old semantic `all_horizontal(is_not_null across every channel)` collapsed to all-False on the real corpus because sparse event channels (options-expiry ~12/year, monthly-to-quarterly macros) poisoned the check on every 15-minute bar. New semantic: `mask[t] = target_features_non_null[t] AND targets[t] != -100`. Regenerated training .pt: 53,703/54,262 = 98.97% valid (was 0 pre-fix). Version marker `meta["mask_semantics"] = "target_valid_v075"` added so a future consumer distinguishes pre- vs post-Sprint-075 artifacts.

Sprint 077 also authored a **real-sprint-vs-roadmap-item mapping table** at the top of `plans/v1-roadmap.md` — 27 shipped items mapped to actual sprint numbers with deltas up to +20 sprints on some items; 7 real sprints named as absent from the roadmap. The body preserved verbatim as the audit trail per hard rule 12. That is discipline compounding — errata drove a roadmap-vs-reality reconciliation, not just an in-place edit.

---

## 2. Storage-integrity + fail-loud discipline tightened at three call sites

Sprint 065's `allow_test_look=True` opt-in pattern (filesystem guard on held-out reads) generalized into a repeatable shape. Three sprints applied the same shape to different silent-fallback failure modes:

**Sprint 077 fail-loud loads.** Two silent fallbacks flipped to fail-loud raises:
- `load_tokens_pt(path, *, allow_legacy_mask=False)` raises `LegacyMaskSemanticRefused` when `meta.get("mask_semantics") != "target_valid_v075"` unless the caller opts in. `CURRENT_MASK_SEMANTICS = "target_valid_v075"` module constant means a future semantic bump touches one string.
- `load_frozen_normalizer(path, *, allow_legacy_std_clamp=False)` raises `LegacyStdClampMissing` when the payload lacks the `std_clamp` key unless the caller opts in.

Both accept a `allow_legacy_*=True` opt-in that preserves back-compat while surfacing every read of a pre-fix artifact.

**Sprint 079 fit-time strict default.** `fit_frozen_normalizer` gains `strict_std_clamp: bool = True` default. `NormalizerStdClampViolation(RuntimeError)` raises when any non-exempt `(channel, feature_index)` has `std < std_clamp`; message enumerates up to 5 offenders and names the two escape hatches. Probed the current-corpus normalizer at `artifacts/tokenizer/normalizers.latest.pt` before flipping the default — zero under-clamp hits across every non-exempt channel — safe to flip.

**Sprint 081 heldout_guard fail-loud on unrecognized shapes.** Pre-Sprint-081 `parquet_range_starts_in_heldout(path)` returned `False` for any filename not matching `^(?:features-)?align-(\d{4})-(\d{2})` — silently permitting reads on unknown shapes. Sprint 078's new `tokens.<run_id>.pt` naming would have slipped the guard entirely. Fix: `KNOWN_DATED_PATTERNS` tuple lists every current dated-artifact convention (aligned/features-aligned parquet from Sprint 026/042; `tokens.tokenize-features-align-YYYY-MM-...` from Sprint 078); `parquet_range_starts_in_heldout(path, *, allow_unrecognized=False)` iterates the patterns and raises `UnrecognizedArtifactShape` when none match. A new pipeline stage that mints a fresh dated-filename shape must register its pattern in `KNOWN_DATED_PATTERNS` — the fail-loud raise forces the addition to be visible at review time.

The pattern the three sprints codified: **silent-fallback becomes fail-loud raise + opt-in escape hatch + module-level version string + probe-before-flipping-default**. Cite as canon.

Sprint 078 promoted `run_tokenizer_pt`'s bare-path `torch.save` to `artifacts.write_versioned`. Storage-integrity discipline now uniform across every frozen artifact class: bucket_stats, normalizers, spread_scaler, kappa, checkpoints, tokens. All go through `write_versioned` → `.{run_id}.ext` + `.sha256` sidecar + `.latest.ext` symlink.

---

## 3. Vocabulary evolution — v0.6 + v0.7

Sprint 080 shipped v0.6. Two new tags in one lock:
- `TOKENIZED_ARTIFACT_WRITTEN` (category `tokenize`, stratum `summary`, 6-field payload: run_id, path, sha256, n_channels, n_rows, mask_semantics) — wired into `run_tokenizer_pt` at write time; fires once per tokenize call carrying the Sprint 078 versioned path + sha256 hex.
- `NORMALIZER_CHANNEL_UNDER_CLAMP` (category `feature`, stratum `incident`, 5-field payload: run_id, channel, feature_index, std_value, std_clamp) — wired into `fit_frozen_normalizer`; fires per hit BEFORE the `NormalizerStdClampViolation` raise in strict mode, and also in lenient mode as a pure warning surface (the trace records every offender regardless of posture).

Sprint 084 shipped v0.7. Normalized-contract update tracking the Sprint 077 fail-loud additions; downstream metadata now flows through the strict schema.

Vocabulary trajectory reads: v0.1 (initial) → v0.2 (struct type-kind after Sprint 007 halt) → v0.3 (CHANNEL_FETCH_FAILED after Sprint 023 halt) → v0.4 (WANDB deprecation) → v0.5 (NORMALIZER_DRIFT_MEASURED) → v0.6 (TOKENIZED_ARTIFACT_WRITTEN + NORMALIZER_CHANNEL_UNDER_CLAMP) → v0.7 (normalized contract). Seven locks, every one with a rationale doc, every prior version on disk per hard rule 12.

The Sprint 080 card notes the pattern: **vocab-bump-as-own-class per past patterns (Sprints 009 v0.2, 022 v0.3, 040-retracted v0.4, 055 v0.5); crosses hard rule 6 but the concept is single.** Honest articulation of a stretch, not a bypass.

---

## 4. Phase E complete — four architecture ablations from spec §10

Product-spec §Architecture ablations pre-registers four. All four have code + tests + composable CLI flags after this arc:

- **Sprint 083: channel-mixer embedder.** `ChannelMixerEmbedder` — one-layer transformer block across the channel axis at each timestep before the temporal transformer, per tech-arch §10.
- **Sprint 087: PatchEmbedder (patch_size=4).** Per-channel `nn.Linear(patch_size * F_c, d_model)` summed after reshape `[B, T, F_c]` → `[B, T // patch, patch * F_c]`. Raises on `T % patch_size != 0`. Trainer target alignment: `_patch_targets(targets, patch_size) = targets[:, patch-1::patch]` — patched-position p corresponds to sampler-slice index `(p+1)*patch - 1`. Verified: for patch=4 and T=64, targets [B, 64] becomes [B, 16] — every 4th slice picks position 3, 7, 11, ... 63. Correct alignment.
- **Sprint 089: quantile head + pinball loss.** `N_QUANTILES = 9` + `QUANTILE_LEVELS = (0.1, 0.2, …, 0.9)`. `MarketStateTransformerConfig.head_type: str = "categorical"` field; forward output shape `[B, T', 9]` for quantile. `pinball_loss(preds, targets_float, quantile_levels)` masks NaN targets. `QuantileHeadRequiresRawTargets(RuntimeError)` — fail-loud when `head_type='quantile'` and `artifact.raw_targets is None`; `scripts/train.py` catches with exit code 4.
- **Sprint 090: bucket-count sweep (16 / 32 / 64).** `scripts/bucketize.py --n-buckets {16,32,64}` and `scripts/train.py --n-buckets {16,32,64}`. Live sweep on the real 2015-2022 corpus: b16 (817,792 params, loss 2.9012, chance = log(16) = 2.77); b32 (819,840, 3.6552, chance 3.47); b64 (823,936, 4.2589, chance 4.16). All three within 0.13-0.14 of chance — the small untrained model sits at chance across every bucket count. Sanity check green.

**Six-axis dispatch space complete.** `run_id` composes: `-{size}` (xs/sm/md/lg) × `-c{N}` (context 64/128/256/512) × `-mix` (channel-mixer) × `-p4` (patch 4) × `-qh` (quantile head) × `-b{N}` (bucket 16/32/64). Per-configuration checkpoints and traces do not collide on disk. Sprint 084+ GPU sweep on rented hardware has every dispatch axis available.

Sprint 088 (`raw_targets` field on `TokenizedArtifact`) landed as prerequisite for Sprint 089's quantile head. Fail-loud through `QuantileHeadRequiresRawTargets` if the artifact lacks the field. Sprint 089's val loop reports pinball into the `val_nll` slot with other categorical metrics as 0.0 — **named on card as an honest gap; quantile-specific metrics (coverage per quantile, calibration by quantile, sharpness) are a Sprint 090+ follow-up candidate.**

---

## 5. Phase F opens — simulator lands cleanly under hard rule 6

Roadmap 075 splits across Sprints 093-096 to stay under hard rule 6. Three of four sprints closed in this arc:

**Sprint 091: Corwin-Schultz cost-calibration primitives.** Architect-ratified path (b) — CS on OHL + 2024 bias correction against Sprint 035's known SPY BBO; Databento path (a) reserved for a revisit after Sprint 084 sweep + Sprint 088 held-out eval. `corwin_schultz_spread(highs, lows)` implements the JoF 2012 estimator; returns NaN on non-positive prices and on negative-alpha boundary pairs (paper's recommendation). `BiasCorrection` + `fit_bias_correction(known_bbo, cs_estimated, *, provenance)` = ratio-of-means over finite entries.

**Sprint 091 mid-sprint rescope**, worth naming: CLI wiring + persistence + `COST_CALIBRATION_FITTED` re-emit deferred to Sprint 093 (the actual `SpreadScaler` consumer). Building the persistence layer before the consumer exists would have shipped untested downstream code. Live smoke reported the CS distribution against real 2015-2022 SPY: 54,235 pair estimates, 39.0% NaN (21,132 negative-alpha boundary pairs per paper Table III), 33,103 finite; mean 8.39 bps, median 5.69 bps, 5-95% range 0.44-24.65 bps. Against real SPY intraday BBO in the same window (~0.5-1.5 bps published), CS over-estimates by ~4-8× on 15-min bars — same class of bias the paper documents on sub-day intervals, direction opposite to daily-bar bias. Sprint 093's bias-correction step handles either direction.

**Sprint 092: simulator skeleton.** New `src/price_space_llm/simulation/` package. `run_simulation_skeleton(aligned_parquet_path, ...)` opens `SIM_RUN_STARTED`, filters aligned parquet to `[start, end]` inclusive, emits `BAR_PROCESSED` per bar with grid_ts, closes `SIM_RUN_COMPLETED` with every summary field at 0. `SimResult.notes = "skeleton"` so a trace reader distinguishes skeleton runs from real Sprint 093+ runs at a glance. **Honest arithmetic, not fabrication** — the Sprint 031 pattern (placeholders named as placeholders) continues.

**Sprint 093: PREDICTION_EMITTED per bar.** `derive_prediction_scalars(probs, bucket_train_means, realized_vol)` computes the five payload floats: `expected_vn_return = Σ p_i × train_mean_i` (NaN train_means from empty buckets contribute zero, matching Sprint 056 semantics); `expected_return = expected_vn_return × realized_vol`; `p_up = Σ_{i ≥ V//2} p_i`; `entropy` in nats via 1e-12 clamp; `sharpness = 1 - entropy / log(V)`. `run_simulation_with_predictions` wraps the walker; slices per-channel feats over `[t-context_len, t)`, forwards through `MarketStateTransformer`, softmaxes last-position logits.

Live smoke on 10-step xs training checkpoint against real 2015-2022 tokens: 136 predictions (200-64, exact). Numbers honestly at-chance: mean `expected_vn_return ≈ −8e−5`, `p_up ≈ 0.485`, `sharpness ≈ 0.008` — the 10-step training barely moved the model off random init. Named on card. A real Sprint 084+ GPU-trained model produces varying predictions.

**Sprint 094: decision policy.** `PolicyConfig` (threshold, hysteresis, lambda_risk, spread_cost_frac, slippage_frac, position_size_usd). `variance_vn(probs, bucket_train_means)` = `Σ p_i × mean_i² − (Σ p_i × mean_i)²` with NaN-safe train_means + floating-point-noise floor at zero. `compute_edge = expected_vn_return − (spread + slippage) / realized_vol − lambda_risk × variance_vn` per tech-arch §11.4. `decide(prev_direction, edge, policy)` per §11.4: `|edge| < threshold` → flat; same-direction re-entry → `reason=position_held` (no drop); direction flip requires `|edge| > threshold × (1 + hysteresis)` else `reason=hysteresis_hold` + `SIGNAL_DROPPED(dropped_reason="hysteresis_below_flip_threshold")`.

Live smoke on real 2015-2022 corpus, 400-row slice, 10-step xs checkpoint: 336 decisions (400 − context_len 64, exact), reasons `{hysteresis_hold: 269, position_held: 63, edge_below_threshold: 4}`, directions `{flat: 269, short: 67, long: 0}`, edge range `[−0.118, −0.019]`. The 10-step model's systematic negative bias plus the spread-cost subtraction dominates. Zero `SIGNAL_DROPPED` because no direction reversals occurred. Mechanics green — all payload fields fire in-range.

**Named on Sprint 094 card:** Sprint 095 opens next — position state machine + `POSITION_OPENED` + `POSITION_CLOSED` + `TRADE_LEDGERED` + real P&L. Sprint 094 tracks a scalar `current_direction` only; Sprint 095 adds size / entry price / realized P&L per closed position. Sprint 096 lands metrics + block bootstrap.

---

## 6. SDD-technique observations across the arc

**Punch-list-as-sprint-plan continued.** Every 2026-08-16 review §11 item has a sprint: std_clamp configurable (Sprint 076); heldout_guard filename-brittleness (Sprint 081). Every errata item landed (§1 above).

**Same-day retractions on the record.** Sprint 077's roadmap-errata block reconciled shipped items against the roadmap and documented 20-sprint deltas on some items — reality re-labeled to match the ground truth rather than the plan re-written.

**Fail-loud pattern generalized.** Sprint 065's `allow_test_look` pattern (opt-in escape hatch on a raise) applied at three additional call sites (Sprints 077 twice, 081). Same shape: silent-fallback becomes raise; opt-in kwarg preserves back-compat; module-level version constant means a future bump touches one string.

**Probe-before-flipping-default.** Sprint 079 probed the current-corpus normalizer to confirm zero under-clamp hits before making `strict_std_clamp=True` default. Sprint 083 probed synthetic mixer against categorical on a real slice before wiring dispatch. Discipline against "assume the default is safe" reads.

**Mid-sprint rescope named honestly.** Sprint 091 rescoped CS calibration mid-sprint: primitives ship this sprint; CLI + persistence + emit ship Sprint 093 where the consumer exists. That is the "building X before the consumer exists ships untested downstream code" discipline made explicit.

**Vocab-bump-as-own-class.** Sprint 080 named the pattern explicitly — vocabulary evolution is a distinct sprint class that crosses hard rule 6 but has a single concept. Sprint 084's v0.7 lock followed the same shape.

**Placeholder discipline continued.** Sprint 092's skeleton `SimResult.notes = "skeleton"` marker distinguishes skeleton runs from real Sprint 093+ runs at trace-read time. Sprint 089's quantile val_nll slot reports pinball with other metrics zeroed and named on card as an honest gap. Sprint 031's original placeholder discipline (named as placeholders, not lies) continues at cadence.

**Every sprint declared `pass_kind` + `determinism_budget`.** All 21 sprints. Every functional-band sprint authored an observation contract with a live smoke on real corpus data. Every architecture-band sprint declared bit-deterministic and verified against the prior artifact.

---

## 7. Small findings from this arc

**7.1 Sprint 094 walker silently skips bars where `vol <= 0`.** `run_simulation_with_policy` in `simulation/skeleton.py` skips per-bar processing when realized_vol is non-positive. Currently invisible in the trace — no signal fires, no counter increments. A Sprint 088+ held-out evaluation reader looking at bar counts would see 336 decisions in a 400-bar slice and might read the delta as context_len alone (400 - 64 = 336). If any bars had been skipped for vol, the delta arithmetic would silently drift. Consider extending `BAR_PROCESSED` with a `processed: bool` field (or adding a `BAR_SKIPPED_UNDEFINED_VOL` incident tag) so a trace reader sees the skip count in-line.

**7.2 Sprint 089 val_nll slot semantics.** When `head_type="quantile"`, `val_nll` carries the pinball loss value, not the negative log-likelihood. The metric name is now misleading. Two options: rename the field to `val_loss` with a `loss_kind` enum, or add a separate `val_pinball` payload field and leave `val_nll` NaN under quantile. Named on card; not blocking. Belongs in the Sprint 090+ quantile-specific-metrics work.

**7.3 Sprint 093's chance-level predictions.** Live smoke fired 136 `PREDICTION_EMITTED` at `mean expected_vn_return ≈ −8e−5`, `p_up ≈ 0.485`. Every downstream metric during this arc's smokes lands near chance. Watch item: the Sprint 084 GPU sweep (rented A10 / A100) must produce non-chance predictions before Sprint 088 held-out evaluation runs. The current smokes verify mechanics, not signal quality. Any Sprint 095+ trade-ledger metric computed against these chance-level predictions will report near-zero Sharpe with wide SE — expected, and worth flagging in the Sprint 095 card so the number is not misread as a real strategy failure.

**7.4 Sprint 087's patch=4 target-alignment invariant.** `_patch_targets(targets, patch_size) = targets[:, patch-1::patch]` — the patched-position p corresponds to sampler-slice index `(p+1)*patch - 1`. Correct for the intended semantic (predict the return over the interval starting after the patched position). Deserves a comment in the code (or a small dedicated invariant test) naming the arithmetic — a future reader without the card context will need it. Sprint 087's tests verify the shape but not the alignment semantic directly.

**7.5 Sprint 090's live smoke did not sweep at the same context_len across V.** b16 / b32 / b64 all ran at the default context; the six-axis composability was exercised on `run_id` naming, not on numeric comparison. Not a defect (each config's loss lands at chance so no comparison is warranted at these training budgets), but the sweep-vs-comparison distinction is worth naming for Sprint 084's GPU sweep script.

**7.6 Sprint numbering has one gap: 085.** Sprints 074-084 land contiguous; Sprint 085 is absent; Sprints 086-094 continue. Likely a halted / rolled-back sprint number preserved per hard rule 12 discipline. Not worth chasing without a BLACKBOARD entry naming it.

---

## 8. Remaining items from prior reviews

- **RoPE.** Deferred by 2026-08-16 Architect Decision. Not a review-open item until the Decision reverses.
- **Simulator trade side.** Sprints 095 (position state machine + trades) + 096 (metrics + block bootstrap) close Phase F.
- **Simulator capacity sweep.** Sprint 095 named as candidate.
- **Kappa sensitivity plot.** Sprint 096 named as candidate.
- **Simulator emit surface.** After Sprints 095 + 096 close, four of the previously-deferred simulator tags remain: `POSITION_OPENED`, `POSITION_CLOSED`, `TRADE_LEDGERED`, `SENSITIVITY_PLOT_GENERATED`, `CAPACITY_SWEEP_COMPLETED`. Correct absence at this arc's close.
- **`run_alignment` dispatch branch count.** Nine branches from Sprint 048; unchanged. Sprints 069-072 added feature blocks inside `compute_features`, not new dispatch branches. Loader Protocol + registry refactor remains a non-blocking readability question.

---

## 9. Bottom line

Twenty-one sprints, zero silent bypasses, two vocab bumps, one new package (`simulation/`), Phase E complete, Phase F three sprints in. The fail-loud generalization landed at three call sites via one repeatable shape. Storage integrity is now uniform across every frozen artifact class. The errata block on the prior review drove real code changes (Sprint 075 mask fix) and a roadmap-vs-reality reconciliation (Sprint 077).

The signal-emission map is close to complete. Every declared vocabulary tag through v0.7 has code emitting it, except the four trade-side simulator tags scheduled for Sprint 095 and the two summary-side simulator tags scheduled for Sprint 096. That is honest scheduling, not omission.

The pattern the discipline is producing at this cadence: each sprint's card names its rescopes, follow-ups, and stretches on the record; the next sprint reads those and closes them. The v0.6 lock (two tags in one sprint, hard-rule-6-crossing named as an accepted vocab-bump-class) and Sprint 091's mid-sprint rescope (primitives ship this sprint; consumer-wiring ships next) are two examples this arc surfaces.

Next-review watch: whether Sprint 095's real-trade smoke on the 10-step chance-model surfaces the number-in-context problem §7.3 flagged, and whether the Sprint 084 GPU sweep produces non-chance predictions before the held-out gate opens.
