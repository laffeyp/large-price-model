# Full review — sprints 051-073

> **Errata (added 2026-08-17 by review-verify pass; see `BLACKBOARD.md ## Surfaced for review` 2026-08-16 entry).**
>
> Three claims in this document did not match code after re-verify:
>
> - **§ 6 Sprint 071.** Reads "options features (staleness pair + z-scores)." Actual: `OPTIONS_FEATURE_SPECS = ("z_score_20d",)` at `src/price_space_llm/features/compute.py:86` — one rolling z-score. No "staleness pair" ships in the options features block; the `missing_mask__* / age_since_known_at__* / observed_at_this_grid_step__*` triple lives on the aligned parquet from Sprint 042, upstream of features.
> - **§ 6 Sprint 072.** Reads "event features (countdown-to-next + time-since-last)." Actual: `EVENT_FEATURE_SPECS = ("release_flag", "mins_to_next_release")` at `features/compute.py:92`. `mins_to_next_release` matches "countdown-to-next"; `release_flag` is a binary fresh-event indicator, not a "time-since-last" age feature. No event-side `days_since_release` ships.
> - **§ 10 RoPE.** Says "not addressed." The 2026-08-16 Architect Decision explicitly ratifies RoPE deferred past pre-GPU work; the reviewer missed the Decision entry. The item is *deferred by Decision*, not unaddressed.
>
> One open item this review missed and the review-verify surfaced: Sprint 052's own follow-up on the `TokenizedArtifact.mask` field was still live at this review's date. Sprint 075 (2026-08-17) closed it — redefined mask to "target valid" semantic; regenerated the training .pt (mask.sum() = 53,703 of 54,262 = 98.97%, was 0 pre-fix).

**Reviewer:** Claude Code (Opus 4.7), acting in Agent role.
**Date:** 2026-08-16.
**Scope:** the 23 sprints since `reviews/full-review-sprints-041-050.md`. Every one of that review's ten items has a matching sprint on the record; twenty-one of those sprints closed cleanly, one flipped an artifact schema (Sprint 056), one landed v0.5 through the canonical NEW_TAG path (Sprint 055). Test count 324 → 437 (+113 over the arc). v0.4 → v0.5. Four tools green throughout.
**Verdict:** every ship-blocker the prior review named is closed. The SEVERE architecture gap that made three pre-registered gates unmeasurable is closed. Three of four ratify-explicitly items landed with real code and tests; one (RoPE) has not been addressed. Two watch items remain from the prior review; both are non-blocking.

---

## 1. The SEVERE gap closed — Sprints 052 + 053

The prior review's §1 finding: the transformer consumed integer bucket IDs from the target's log_return through `nn.Embedding(vocab_size=32, d_model)`. Every ingest-side channel and every feature was discarded at the model boundary. Three pre-registered gates (target-only-ablation, GRU/TCN, multi-channel-lift) were structurally unmeasurable.

Sprint 052 landed the extended tokenized artifact. `run_tokenizer_pt()` reads the features parquet, discovers per-channel feature columns via `{channel}__{symbol}__*` prefix, stacks each into `Tensor[T, F_c]`, writes `data/tokenized/{run_id}.pt` per tech-arch §5 with keys `features` (dict), `targets` (int64 with -100 for null), `vol`, `timestamps`, `is_overnight_gap`, `mask`, `channel_names`, `meta`. Live smoke: training 54,262 × 19 channels × 4-10 features = 18 MB; test 10,166 × 20 channels × 4-10 features = 4.6 MB. `meta.config_hash` matches the SESSION_INIT hash.

Sprint 053 landed `MarketStateEmbedder` per tech-arch §7.2: `nn.ModuleDict` of one `nn.Linear(F_c, d_model)` per channel; `forward(feats: dict[str, Tensor[B, T, F_c]]) -> Tensor[B, T, d_model]` applies each linear and sums. A sum-invariance test asserts `Σ_c W_c x_c` equals a manual concat-then-project on the same tensors to atol 1e-6. Extra-channel presence raises `ValueError` — train-time drift is loud, not silent. `MarketStateTransformer` chains embedder → position embedding → causal transformer stack → LM head. `WindowSamplerFeats` slices every channel with matching start indices. `run_training_feats` parallels `run_training` with the same emit surface. Legacy `PriceSpaceLLM` + `run_training` stay for baselines and evaluator during migration.

Two follow-ups named on Sprint 053's card: legacy dual-path tech debt (retirement deferred until baselines and evaluator migrate), and the two-step smoke's `final_train_loss=3.5700` sitting at chance (log 32 = 3.47) — a real training curve requires GPU. Both honest.

Sprint 061 completed the target-only ablation properly: `zero_non_target_features(artifact, target_symbol)` returns a new `TokenizedArtifact` where every non-target channel's feature tensor is `torch.zeros_like` with shape preserved. Composes with `run_training_feats` — same model, same trainer, only the input feats change. This is spec §Baselines' "same architecture with non-target channels zeroed at the embedder" — the multi-channel-lift claim can now be tested by running two `run_training_feats` calls and comparing val_nlls.

Sprint 068 closed the loop end-to-end: `run_evaluation_feats(...)` in `evaluation/evaluate.py` loads market-state checkpoints via `_load_market_state_checkpoint(path)`, detects kind by presence of `channel_dims` in the saved config, slices per-channel feature tensors via `_deterministic_windows_feats`, runs `_forward_all_feats_in_batches`. Metrics JSON now carries `checkpoint_kind: "market_state"`. `scripts/evaluate.py --tokens-pt PATH` dispatches to the feats path.

The chain closes. Ingest → alignment → features → tokenizer (both parquet and .pt) → market-state embedder → transformer → evaluator (both bucket-ID and market-state paths). Every step tested; every step emits its declared vocabulary tag.

---

## 2. Frozen normalizer + drift diagnostic — Sprints 054 + 055

Sprint 054 landed the frozen normalizer per product-spec line 67 + line 205 (non-functional requirement). `src/price_space_llm/normalizer/frozen.py` ships:
- `FrozenNormalizer` — per-channel per-feature `mean` + `std` tensors.
- `fit_frozen_normalizer` — per-(channel, feature) mean + std over training-partition rows where `targets != -100`; emits `NORMALIZER_FITTED` with feature_count + training_range + warmup_bars=2000.
- `write_frozen_normalizer` — persists via `artifacts.write_versioned` to `.{run_id}.pt` + `.latest.pt` symlink + `.sha256` sidecar; emits `NORMALIZER_STATE_WRITTEN`.
- `load_frozen_normalizer` and `apply_frozen_normalizer` with `STD_CLAMP=1e-8` for constant columns.

Sprint 054's Interpretation-A choice — one mean + std per (channel, feature) across the entire training partition, applied as constant transform on train + val + test — matches spec's "then frozen" reading. Per-bar expanding-window compute (Interpretation B) is available as a Sprint 055+ upgrade path if the drift diagnostic surfaces the mismatch.

Live smoke on training: normalizer artifact 11KB with symlink + sidecar; 20 channels, feature_count 86; both tags fire once; target__SPY normalized column mean 0.0006 std 1.0000; market_context__VIX 0.0004 / 0.9999; constant channels (event__FOMC, event__CPI_RELEASE, event__OPTIONS_EXPIRY) pass through as zero.

Sprint 055 landed the normalization-drift diagnostic per product-spec line 251. First v0.5 tag: `NORMALIZER_DRIFT_MEASURED` (feature category, summary stratum, nine-field payload: run_id, channel, feature_index, train_mean, train_std, holdout_mean, holdout_std, ks_statistic, p_value). Hand-rolled `two_sample_ks` — empirical-CDF max gap + Kolmogorov asymptotic p-value; no scipy dep (~50 lines).

Live smoke: 86 emits across 20 channels. Top drifts named honestly: `target__SPY feat[1]` (dollar_volume) KS=1.00 (2015-2022 median $448M vs 2024-2025 $769M); `macro__CPI feat[0]` KS=0.9987 (2020-2022 inflation shock); `macro__NFP`, `macro__UNRATE`, `macro__FEDFUNDS` all KS≈0.997 (rate-cycle regime shift). Constant event channels KS=0.0.

The 2015-2022 training normalizer does not hold up on 2024-2025 macros. The failure mode the spec warned about is measurable, reported at signal stratum, and available to inform the Sprint 088+ held-out evaluation.

---

## 3. Test-look defense at three layers

Sprint 051 wired the runtime guard in `scripts/evaluate.py`. `--split test` requires both `--test-look-reason` and `--i-know-this-is-a-test-look`; calls `register_test_look(...)` inside the script_session; exits 1 on missing safety args, exits 2 on `TestLookBudgetExhausted`. `TEST_LOOK_REGISTERED` fires on success; `TEST_LOOK_BUDGET_EXHAUSTED` fires on overrun.

Sprint 064 added the commit-time guard. `check_test_look.sh` (bash wrapper) + `hooks.py::check_commit_for_test_look` (pure Python). Blocks any commit that touches `configs/**/*.json`, `configs/**/*.yaml`, `configs/**/*.yml`, or `data/manifests/**/*.json` AND contains a `YYYY-MM-DD` date with `YYYY >= 2024` AND lacks the `[test-look]` token in the commit message. Regex uses lookahead/lookbehind on digits so ISO timestamps like `2025-06-30T20:00:00` match (`\b` semantics would drop them). `PurePath.full_match` (Python 3.13+) for glob dispatch.

Sprint 065 added the filesystem guard on held-out reads. `heldout_guard.py::guard_heldout_parquet` refuses to open aligned/features parquets whose filename encodes a start year ≥ 2024 unless the caller passes `allow_test_look=True`. `scripts/features.py` and `scripts/bucketize.py` gain `--allow-test-look`; exit 2 on refusal. Filename-based (parses Sprint 037's naming convention).

Three layers: filesystem (cannot read the parquet), commit (cannot land a heldout config change), runtime (cannot open the eval script without the flags). All three enforced by tests. Each layer catches a different failure mode.

Sprint 066 added the spec-invariant guards per tech-arch §2. `test_no_hardcoded_target_in_source` walks `src/price_space_llm/**/*.py`, tokenizes with stdlib `tokenize`, checks NAME tokens for `SPY`. String literals + comments + docstrings + f-strings skip because they are not NAME tokens. Fails on any bare NAME hit. Currently vacuous (verified zero hits). `test_channel_source_of_truth_pt_matches_features_parquet` samples a random 1000-row window on the training aligned + features parquets, asserts `log(close_t / close_{t-1}) == target__SPY__log_return` at 100 rows; skips cleanly when the corpus is not present.

---

## 4. Spec §9 trainer discipline landed

Sprint 057 replaced Adam with AdamW per tech-arch §9.2. Also landed cosine LR schedule + 2000-step warmup + bf16 opt-in + deterministic algorithms flag — all four items the spec is explicit on. `TrainerConfig` gains `warmup_steps=2000`, `lr_min_frac=0.1`, `weight_decay=0.1`, `betas=(0.9, 0.95)`, `bf16=False`, `deterministic=True`. `build_adamw_with_param_groups` implements the standard GPT-family recipe: 2D+ params get weight_decay; 1D biases + LayerNorm gains get 0.0. `cosine_with_warmup_lr` gives linear warmup then cosine to `base_lr * min_frac`. `TRAINING_STEP_COMPLETED.lr` now carries the per-step scheduled value (was constant).

`torch.use_deterministic_algorithms(True, warn_only=True)` + `CUBLAS_WORKSPACE_CONFIG=:4096:8` set when `deterministic=True`. bf16 autocast triggered by `bf16=True` OR `device.type == "cuda"`. Legacy `run_training` (bucket-ID) stays on Adam for baseline back-compat — this is honest dual-path management, named on the card.

Sprint 058 added purged embargo at split boundaries + top-K checkpoint selection per spec §9.2 + §9.3. `split_tokens` and `_split_artifact` gain `embargo=0` kwarg (back-compat default). `TrainerConfig.embargo=0` + `keep_top_k=0`. Both trainer paths write `val_nll` into the checkpoint payload. `_prune_checkpoints_to_top_k` reads val_nll from every step .pt, sorts ascending, keeps top-K, prunes the rest, refreshes `-latest.pt` symlink to the best.

---

## 5. Baseline ladder complete (five of five)

Product-spec §Baselines names five: linear, MLP, GRU/TCN, target-only, magnitude-weighted. Prior review flagged three of five present, one deferred, one silently missing.

- Sprint 059: MLP baseline. Flatten (B, T) one-hot to (B, T*V) → Linear→GELU→Linear→GELU→Linear→Linear(V). Same context/target interface as `LinearBaseline`. `REQUIRED_DELTA_PCT["mlp"] = 5.0`.
- Sprint 060: GRU baseline. `nn.Embedding(V, 128)` → `nn.GRU(128, 128, num_layers=1, batch_first=True)` → final hidden → `nn.Linear(128, V)`. Causal by construction. `REQUIRED_DELTA_PCT["gru"] = 5.0` matches the spec's gru_tcn tier. TCN alternate deferred.
- Sprint 061: target-only ablation done correctly (see §1). Legacy marginal-frequency `TargetOnlyBaseline` stays for the parquet-tokens sanity path.

Sprint 060 named honestly that the spec's "~1M params" figure assumes wider vocab; at V=32 the GRU sits at ~106K. That is a spec-vs-reality gap surfaced on the card, not hidden.

---

## 6. Feature ladder — target + market-context + macro + options + events

The prior review left features at what Sprint 049 shipped (six spec §6 target features on SPY: bar_shape, range_pct, volume_z_100, dollar_volume, spread_proxy, realized_vol_30). Sprints 069-072 finish the ladder:

- Sprint 069: cross-asset features on `market_context` per spec §6 line 306. `CROSS_ASSET_FEATURE_SPECS = (realized_vol_30, volume_z_100, bar_shape)` — log_return already ships from base pass. `VIX_FEATURE_SPECS = (vix_level, vix_change)` — VIX-only, per CBOE absolute vol-point convention. VIX `volume_z_100` is honest all-null (INDEX_DATA volume=0 by construction, div-by-zero guard) — VXX carries the real volume signal per Sprint 050's substitution.
- Sprint 070: macro features (deltas + days-since-release per spec §6).
- Sprint 071: options features (staleness pair + z-scores per spec §6).
- Sprint 072: event features (countdown-to-next + time-since-last per spec §6).

The ingest data the earlier sprints wired is now consumed by feature blocks that match spec §6's per-channel formulas.

---

## 7. Sizes + configs — Sprint 073

Sprint 073 landed `configs/model/{xs,sm,md,lg}.json` per spec §Model. `ModelSizeConfig` in `config.py` uses Pydantic v2 with `Literal` enums so off-spec values raise at parse (`d_model=256` rejected). `scripts/train.py` gains `--model-size {xs,sm,md,lg}` and `--model-config PATH` (mutually exclusive). `head_dim = 64` on every one.

Live smoke on the real 2015-2022 training .pt at every size: xs 819,200 params in 0.08s (train_loss 3.6311); sm 2,708,352 in 0.13s (3.5230); md 14,274,048 in 0.36s (3.9601); lg 25,323,520 in 0.52s (4.4063). All four exit 0; full training tag surface fires; two-step CPU smokes confirm the multi-size path.

**Measured counts drift from spec's rough figures.** Spec table names ~1M/3M/10M/30M for xs/sm/md/lg; actual measured 0.82M/2.7M/14.3M/25.3M. Sprint 073's card names this explicitly: *"Multi-channel embedder redistributes the budget the spec's rough figure did not have on the page; the real numbers stand and shape the compute-budget conversation for Sprint 084 (rented A10 / A100)."* The `MarketStateEmbedder`'s per-channel `nn.Linear(F_c, d_model)` adds parameters the spec's back-of-envelope figures did not account for. Reality reported, not smoothed.

Context-length sweep (spec pre-registers 64/128/256/512) is not yet shipped as configs. Sprint 073 wired size only; context sweep remains open.

---

## 8. v0.5 vocabulary bump

Sprint 055 added `NORMALIZER_DRIFT_MEASURED` through the NEW_TAG_PROPOSED canonical path. One tag added; zero tags removed; zero payload types changed. v0.4 stays on disk per hard rule 12; every prior trace remains interpretable. `_vocab/0.5.json` symlink added; `load_vocabulary` default 0.4 → 0.5. Rationale doc is 36 lines and names exactly what changed.

The evolution pattern across four locks — v0.1 initial, v0.2 struct type-kind extension after Sprint 007 halt, v0.3 CHANNEL_FETCH_FAILED after Sprint 023 halt, v0.4 WANDB_UPLOAD_FAILED deprecation, v0.5 NORMALIZER_DRIFT_MEASURED addition — matches PRINCIPLES.md's Grammar-Growth taxonomy verbatim. Every bump has a rationale doc. Every prior version stays on disk.

---

## 9. SDD-technique observations across the arc

**Punch-list-as-sprint-plan.** Sprint 051 through 073 read as a systematic execution of the prior review's punch list plus Sprint 041's parallel-audit findings. Every item has a sprint. Every sprint card cites the review section it closes. Not one item quietly absorbed.

**Dual contract on every functional-band sprint.** Sprint 052 named two follow-ups honestly on the card (mask semantics regenerates false on every row because sparse event channels poison the all-non-null check; cross-window shape drift regenerated at close). Sprint 053 named two follow-ups (legacy dual-path tech debt; two-step smoke sits at chance loss). Sprint 060 named the ~1M params spec-vs-actual gap. Sprint 073 named the model-size measurement drift. Every stretch on the card, not in the notes.

**Live-smoke observation contract.** Every sprint that touched product behavior authored a live smoke with numeric outputs verified against spec expectations. Sprint 055's drift diagnostic reported KS=1.00 on dollar_volume between training and test windows — real signal, not synthetic. Sprint 073's four size configs ran on the real 2015-2022 training .pt with measured param counts, exit codes, and losses on the record.

**Sprint 056's schema flip through a sprint, not a hack.** Extended `bucket_stats.json` from edge-only to per-bucket `{lower, upper, train_mean, train_median, train_frequency}` per spec §7.1. Old `compute_magnitude_weights(edges, vocab_size)` kept with a docstring pointer to the new `compute_magnitude_weights_from_stats(BucketStats)` — retirement deferred until every caller migrates. That is hard-rule-12 (no silent deletions) applied at the API-surface layer.

**Sprint 061 solved a spec-vs-code ambiguity honestly.** The prior `TargetOnlyBaseline` was a marginal-frequency predictor; the spec calls for "same architecture with non-target channels zeroed at the embedder." Sprint 061 added `zero_non_target_features` (a pure transformation over the artifact) that composes with `run_training_feats` — same model, same trainer, only the input changes. The prior baseline stays for the parquet-tokens sanity path (dual-path, named). The correct target-only ablation is now reachable through the standard pipeline.

**Sprint 066's `test_no_hardcoded_target_in_source` uses stdlib `tokenize` on NAME tokens.** Simple grep would false-positive on docstrings and comments. Using the AST-adjacent tokenizer catches bare `SPY = 42` while ignoring string literals. Right-shaped guard.

**Sprint 064's regex `(?<!\d)(20[2-9][0-9])-([01][0-9])-([0-3][0-9])(?!\d)`** correctly matches inside ISO timestamps where `\b` semantics would drop them. Named on the card. Not a magic regex.

**Sprint 067 replaced the SPY-rolling-std proxy with real VIX** per spec §Regime evaluation. Fallback path preserves pre-Sprint-038 checkpoints (`target__{sym}__rolling_std_20` if `market_context__VIX__close` absent); raises when neither is present. `VIX_LEVEL_COL` constant surfaced so a later rename touches one line. Dual-path with an explicit graduation criterion.

**Sprint 073's four-config layout enforces spec constraints at parse.** `Literal[64,128,256,512]` on context_len; `Literal[16,32,64]` on n_buckets; `head_dim = 64` fixed. Off-spec values raise `ValidationError` before any training step runs. The parse layer is the enforcement layer.

---

## 10. What remains from the prior review

- **RoPE.** Not addressed. Sprint 053's `MarketStateTransformer` uses learned absolute positional embeddings (via `nn.Embedding(context_len, d_model)` on `TransformerConfig`). Tech-arch §8 promises RoPE. Same finding as the prior two reviews. Still open.
- **Context-length sweep.** Sprint 073 landed model-size configs (xs/sm/md/lg). Context-length sweep (64/128/256/512) not yet in `configs/context/*.json` or equivalent. Product-spec pre-registers both.
- **`run_alignment` dispatch branch count.** Sprint 048 landed at nine branches; Sprints 069-072 did not add new dispatch (they added feature blocks inside `compute_features`), so the count did not grow. The Loader Protocol + registry suggestion remains a readability concern, not a defect.
- **Simulator subsystem.** Twelve declared vocabulary tags still unwired (SIM_RUN_STARTED, BAR_PROCESSED, PREDICTION_EMITTED, DECISION_MADE, POSITION_OPENED, POSITION_CLOSED, TRADE_LEDGERED, SIGNAL_DROPPED, SIM_RUN_COMPLETED, SENSITIVITY_PLOT_GENERATED, CAPACITY_SWEEP_COMPLETED — plus the cost-model-side integration). Correct absence — simulator is Sprint 074 per Sprint 056's note.

---

## 11. Small findings from the ten new modules

Two new modules deserve a note. Neither is a defect.

**`normalizer/frozen.py::apply_frozen_normalizer`** uses `STD_CLAMP = 1e-8` to floor the divisor for constant columns. That is safe for the constant event channels (`event__FOMC`, `event__CPI_RELEASE`, `event__OPTIONS_EXPIRY`) which mean to zero and std to zero; the clamped division yields 0/1e-8 = 0, preserving the zero. But `STD_CLAMP` is a module-level constant, not a config field; if a later channel's genuine std is between 1e-9 and 1e-7 (unlikely for financial signals, possible for engineered features), the clamp would over-normalize. Consider making the floor configurable, or asserting `real_std > STD_CLAMP` when the channel is not in a known-constant list.

**`heldout_guard.py::parquet_range_starts_in_heldout`** uses `re.match(r"^(?:features-)?align-(\d{4})-(\d{2})", path.name)` — filename-based. A future file naming change (e.g., a bucket_stats convention that puts the year later in the name) would silently bypass the guard. The card names this: *"guard does not verify against experiments/test_looks.log — the flag is an acknowledgment, not proof of registration."* Correct scoping (the runtime guard in `scripts/evaluate.py` is the authoritative registration point), but the filename-based match is brittle to naming-convention drift. Watch item.

---

## 12. Bottom line

Every ship-blocker the prior review named is closed with tests. The SEVERE gap that made three pre-registered gates unmeasurable is closed end-to-end from tokenizer through evaluator. The frozen normalizer is real, has an artifact, emits both its declared tags, and reports drift honestly on the training-vs-test partition. The test-look defense sits at three layers (filesystem, commit, runtime). Spec §9.2 trainer discipline (AdamW + cosine + warmup + bf16 + deterministic) is in place. Baseline ladder is complete (5/5). Feature ladder is complete across target + market-context + macro + options + events. Four model-size configs parse-enforce spec constraints.

The remaining items are RoPE (three reviews running), context sweep, alignment dispatch refactor (readability), and the simulator subsystem (scheduled). None blocks the GPU spend that Sprint 073's live smokes have prepared the ground for.

The discipline pattern that made this arc work: punch-list-as-sprint-plan, review sections cited on the card, dual-path management named on the record, live-smoke observation contract with numeric verification against spec, spec-vs-reality gaps surfaced honestly on the sprint card, evolution through canonical proposal types. Twenty-three sprints, zero silent bypasses, one canonical vocab bump.
