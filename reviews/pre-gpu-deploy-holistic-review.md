# Pre-GPU-deploy holistic review — sprints 001-040

**Reviewer:** Claude Code (Opus 4.7), acting in Agent role.
**Date:** 2026-08-13.
**Scope:** the whole runnable pipeline. All 40 sprints, `signals/0.3.json` (56 tags), both v4 specs, every module in `src/price_space_llm/`, every `scripts/*.py`, both configs, the test suite (284 tests). Dimensions: original intent (product-spec v4 + tech-arch v4), correctness, SDD discipline, code style.
**Verdict:** **do not launch a real training run yet.** The smoke path works; the ship path is not what the spec pre-registered. Four hard blockers below, four gaps that need explicit ratification, three watch items. Fix the blockers, ratify the gaps, then spend GPU money.

---

## 1. The bottom line

The v4 specs pre-register a specific v1 model: 15-minute multi-channel market state, ≥19 channels including target OHLCV + 7 cross-asset + 5 macro + 2 options + event, RoPE positional embeddings, a required 4-point model-size sweep (1M/3M/10M/30M), a required 4-point context-length sweep (64/128/256/512), five prescribed baselines including MLP and GRU/TCN, four prescribed architecture ablations, a bar-by-bar simulator with cost model, and pre-registered numeric gates on Sharpe/ECE/capacity/baselines.

The current code trains a **208K-parameter model on 3 channels (SPY + VIX + USO) at a single context length (64) with no simulator, no MLP baseline, no GRU/TCN baseline, no size sweep, no context sweep, no architecture ablations, and a frozen normalizer that neither exists in code nor emits its declared tags**. The smoke on 54,210 real tokens works and shows learning (loss 3.5866 → 3.2697, val NLL 3.244 vs random ln(32)=3.4657). That is a genuine smoke, not the ship.

A GPU spend on this configuration produces a number, not evidence for the pre-registered claim. The claim rides on the multi-channel bet; three channels do not test it. Fix the below first.

---

## 2. Four hard blockers (fix before GPU spend)

### 2.1 `config_hash` and `data_hash` are the same value in `scripts/train.py`

`scripts/train.py:75-77`:
```python
tokens_bytes = args.tokens.read_bytes()
config_hash = hashlib.sha256(tokens_bytes).hexdigest()
data_hash = hashlib.sha256(tokens_bytes).hexdigest()
```

Both fields hash the tokens parquet. The `config_hash` field on `SESSION_INIT` and `CONFIG_RESOLVED` is meant to identify the experiment config; `data_hash` identifies the data. Two runs with different `configs/experiment/v1.json` but the same tokens parquet will report identical `config_hash`. Reproducibility silently broken.

Second, subtler bug: `SESSION_INIT` fires first from `script_session` (line 80) with the wrong `config_hash`; `CONFIG_RESOLVED` fires next from `load_config` (line 89) with the RIGHT `config_hash` — sha256 of the JSON file bytes per `config.py`. A trace reader sees two different values for the same claim, both legal sha256 strings, no validator flags it.

**Fix:** `config_hash = hashlib.sha256(args.config.read_bytes()).hexdigest()`. Same fix pattern for any other CLI that computes a config_hash for `SESSION_INIT`. Grep every script.

### 2.2 The frozen normalizer prescribed by tech-arch §6 does not exist

Tech-arch §"Feature normalization": *"v1 uses an expanding-window causal z-score computed on the training partition only, then frozen. At inference and on validation and test, the frozen scaler is used as-is."* The frozen state must persist to `artifacts/{run_id}/normalizers.pt` and downstream reads never recompute.

`features/compute.py` computes a per-bar `rolling_z_score_20`. That is a per-bar rolling window, not an expanding-window-on-training-then-frozen state. No file at `artifacts/{run_id}/normalizers.pt` exists. Nothing in `src/` writes one. The `NORMALIZER_FITTED` and `NORMALIZER_STATE_WRITTEN` tags declared in `signals/0.3.json` fire from zero call sites.

Consequence: train-vs-eval distribution shift is not controlled the way the spec says it will be. Any evaluator running against a val partition sees a rolling z-score whose window includes val bars — a per-bar leak from the val partition into its own normalization. Small in aggregate, real per bar.

**Fix:** either (a) implement expanding-window training-partition-only fit + frozen persistence to `normalizers.pt` per §6 and wire the two emit sites, or (b) ratify the deviation explicitly in a rationale-doc entry and add a v0.4 vocabulary bump that renames or removes the two normalizer tags. Silence is not an option — the spec makes a specific promise the code does not keep.

### 2.3 Test-look guard is not wired into any evaluation script

`src/price_space_llm/testlook.py::register_test_look` is a clean guard: three-look budget, append-only log, `TEST_LOOK_BUDGET_EXHAUSTED` on overrun. `scripts/register_test_look.py` invokes it. **Nothing invokes it automatically.**

BLACKBOARD line 122 (Sprint 034 note): *"register_test_look is not yet wired into any live evaluation script; when multi-month tokens open a test partition, scripts/evaluate_test.py (or an extension of scripts/evaluate.py) invokes it — noted in the sprint card for the future sprint."*

Sprint 039 opened the test partition (10,166 rows for 2024-01 through 2025-06). The guard is not the guard until an evaluate/simulate script calls it before touching those rows. Currently a human running `scripts/evaluate.py` against a test-window tokens parquet does not trip the guard, does not append to the log, does not consume a look-count. The 3-look budget is enforced by human memory alone.

This is exactly the "gate nobody has watched fail is not a gate" trap from Addendum D. Product-spec §"Success gates for v1" pre-registers a 3-look budget as a hard gate. That gate is currently ceremonial.

**Fix:** any script that reads the test partition (currently the evaluate CLI when `--split test` is passed; will include the simulator CLI) calls `register_test_look()` before opening the tokens parquet. Reads bail with exit 2 on `TestLookBudgetExhausted`. Wire this before any GPU-driven held-out evaluation.

### 2.4 Fixed-offset EST (-5 hours) is DST-wrong for ~7 months of every year

`src/price_space_llm/ingestion/alphavantage.py:32`: `US_EASTERN_OFFSET = timedelta(hours=-5)` — fixed EST. `alignment/join.py` and the INDEX_DATA `value_time` computation (Sprint 038) both use this offset.

Filed to drift-watchlist twice: Sprint 024 and Sprint 025. Deferred pending `zoneinfo("America/New_York")` adoption. **This is a correctness bug for any training run on 2015-2022 data**: US Eastern time is EDT (UTC-4) from ~March through ~November each year, EST (UTC-5) otherwise. The fixed offset puts every DST-period bar an hour off its real UTC timestamp. For 8 years of training data that spans DST every year, ~55% of bars carry incorrect UTC timestamps.

Consequences:
- Macro release `known_at` timestamps computed with US Eastern → UTC arithmetic land in the wrong 15-min UTC grid bar. `join_asof(strategy="backward")` selects the wrong prior release for the affected months.
- SPY bars from Alpha-Vantage's TIME_SERIES_INTRADAY (US Eastern) shift by one hour into the next UTC bar for DST months. Every hour-boundary bar is misaligned.
- The `known_at` for INDEX_DATA closes (Sprint 038 stamps `value_time = latest.date + 16:00 US/Eastern → UTC` under fixed -5) puts VIX closes at 21:00 UTC year-round when the real close during EDT is 20:00 UTC. VIX values held into the next day's bars are off by one bar's worth of forward-fill.

The BLACKBOARD Sprint 025 entry named this as "verdict-safe today because probe cares about coverage window" — that reasoning does not extend to training. A model trained on time-misaligned features and time-misaligned macro releases learns the wrong associations.

**Fix:** adopt `zoneinfo("America/New_York")` (stdlib, 3.9+), replace `US_EASTERN_OFFSET` and `timezone(US_EASTERN_OFFSET)` call sites, re-run alignment and features on the corrected data. This is not a large sprint (mechanical replacement plus one test that a March bar and a November bar both round-trip correctly). It is a large data-correctness delta.

---

## 3. Four gaps that need explicit ratification

Each of the below is a spec-vs-code divergence. Each is defensible if named; none is defensible silent.

### 3.1 Channel coverage vs product-spec's declared channels

`configs/channels/v1.json` names three channels: target SPY, market_context VIX, market_context USO.

Product-spec §"Channels tokenized at every 15-minute timestep" names roughly 19: target OHLCV, market context (QQQ, IWM, VIX, TLT, DXY, GLD, USO — 7), macro (CPI, Fed funds, 10Y, unemployment, NFP — 5), options (put/call ratio, options volume — 2), event (earnings, FOMC, CPI release, options expiry — ≥4), plus session flags. The target-only ablation "whole thesis rides on this comparison." With only VIX+USO as context, the ablation compares 208K-param transformer vs 208K-param target-only-transformer over a 2-channel corpus. The multi-channel claim the product ships on is untested.

**Ratify or expand.** Either (a) expand the channel manifest to the spec's declared set and re-run the operational pull, or (b) file a Decision explicitly reducing v1 scope to a smaller channel set for a first honest end-to-end run, with a follow-on sprint plan to reach spec scope before pre-registered gate evaluation. Right now the code silently ships a scope the spec never approved.

### 3.2 RoPE positional embeddings

Prior review (`reviews/sprints-030-033-ml-pipeline-review.md §2`) flagged this. `model/transformer.py:37` uses `nn.Embedding(config.context_len, config.d_model)` for absolute learned positional embeddings. Tech-arch §8: *"positional information uses rotary embeddings. RoPE gives relative positional structure through a rotation applied inside the attention product without a learned absolute-position table."* Still unfixed.

**Ratify or land RoPE.** Same recommendation as before. Silence still not an option.

### 3.3 Baseline ladder missing MLP; GRU/TCN deferred without a scheduled home

Product-spec §Baselines: five required (linear, MLP, GRU/TCN, target-only, magnitude-weighted). `baselines.py` implements three (linear, target-only, magnitude-weighted). Sprint 033 named GRU/TCN deferred; MLP silently absent.

Success-gate "Val NLL ≥5% lower than GRU/TCN baseline" is unmeasurable until GRU/TCN exists. Success-gate parity across the five-baseline ladder is unmeasurable until MLP exists.

**Ratify or schedule.** File both to Deferred with revisit trigger "sprint before first held-out evaluation of the pre-registered baseline-comparison gates."

### 3.4 Size sweep and context sweep are single points, not sweeps

Product-spec §Model: sweep 1M/3M/10M/30M parameters. Product-spec §Training: sweep 64/128/256/512 context length. Both are pre-registered as "required v1 experiment" — reported as curves before any single checkpoint is anointed.

Current code trains one point: 208K parameters (below the smallest sweep point) at context_len=64 (the smallest sweep point). Both sweeps are unwired. `TransformerConfig`'s dataclass defaults hardcode d_model=64, n_layers=4, n_heads=4; no CLI knob to sweep.

**Ratify or schedule.** File a plan: which sprint runs the size sweep (needs GPU), which sprint runs the context-length sweep (also needs GPU), which sprint reports the two curves (needed to pick the v1 default checkpoint). Product-spec says both are required. Without them, the v1 default checkpoint has no justification.

---

## 4. Three watch items (fix within the next few sprints)

### 4.1 `WINDOW_SAMPLED.start_position` is dishonest

`model/trainer.py:158` emits `start_position=int(step)`. The dataset actually samples random starts (`dataset.py:62` `torch.randint`). Real starts computed then discarded before the emit. Same shape as Sprint 020's `_error_shim` — one that the previous retraction discipline says to flag as Surfaced. Prior review (`sprints-030-033-ml-pipeline-review.md §4`) flagged this; still unfixed.

**Fix:** expose the actual start(s) from `WindowSampler.sample()` via the returned `WindowBatch`; emit the first-batch start position (or emit per window inside the batch if the vocabulary intent is per-window).

### 4.2 `EPOCH_COMPLETED.epoch=1` hard-coded

`trainer.py:256`. Fine for a 50-step smoke. Wrong for a real GPU run that spans multiple epochs. Filed to Deferred as of Sprint 032 review. Fix before the first multi-epoch training run.

### 4.3 Ten declared vocabulary tags with zero emit sites

`SIM_RUN_STARTED`, `SIM_RUN_COMPLETED`, `BAR_PROCESSED`, `PREDICTION_EMITTED`, `DECISION_MADE`, `POSITION_OPENED`, `POSITION_CLOSED`, `TRADE_LEDGERED`, `SIGNAL_DROPPED`, `SENSITIVITY_PLOT_GENERATED`, `CAPACITY_SWEEP_COMPLETED`. Plus `NORMALIZER_FITTED` and `NORMALIZER_STATE_WRITTEN` (§2.2). Twelve declared tags, zero emitters — the simulator subsystem plus the frozen normalizer. Correct absence today (those operators don't exist) but the mismatch is worth surfacing to Deferred so the next reader sees the gap named.

---

## 5. What the discipline got right

**Every retraction on the record.** BLACKBOARD line 11 (Sprint 040) corrects a false halt on `WANDB_UPLOAD_FAILED` allowed_set membership before any file touched. BLACKBOARD line 21 (Sprint 035) retracts an earlier "AV publishes 15-min only" framing with live probe evidence. BLACKBOARD line 15 (Sprint 023) retracts the Sprint 020 `_error_shim` misframing. Each named "I was wrong; here is the correction."

**Every scope stretch named on the card, not in the notes.** Sprint 031 articulated three stretches (hard rule 6, v0.4 candidate, context_len reduction). Sprint 039's card explicitly names the scope-cap ("no trainer touched, no cost calibration re-run on full window, no baselines, no evaluation, no W&B, no GPU") before executing.

**Every ingest-category signal fires from live code.** IngestionClient (Sprint 021) with 5 tags. Probe (Sprint 016 + 023 rewire) with 4 tags. Alignment (Sprint 025+037+038) with 4 tags. Features (Sprint 026) with 2 tags. Config (Sprint 028) with 2 tags. Tokenizer (Sprint 030) with 4 tags. Training (Sprint 031+032 un-lie) with 7 tags. Evaluation (Sprint 032) with 4 tags. Baselines (Sprint 033) with 1 tag. Testlook (Sprint 034) with 2 tags. Cost calibration (Sprint 035) with 3 tags. W&B (Sprint 040) with 1 tag. Total ≈ 39 tag types with live emit sites in `src/`.

**Two causality invariants proven at two layers with dedicated tests.** Sprint 025's `join_asof(strategy="backward")` verified by `test_backward_join_never_leaks_future_data`. Sprint 031's causal-mask verified by `test_causal_mask_prevents_look_ahead`. Both toggle a downstream value and assert earlier outputs unchanged.

**Six Hypothesis property tests.** Sprint 025's alignment invariants (2), Sprint 030's tokenizer edges (2), Sprint 032's metrics (2). Right-shaped tests for algebraic properties.

**Storage integrity landed before the big pull.** Sprint 036 shipped versioned artifacts + sha256 sidecars + freshness policy + cache-index BEFORE Sprint 039 wrote 116 fresh cache rows. Deliberate ordering, not retrofitted.

**Cost-neutrality principle codified.** WORKING_AGREEMENT gained the rule that the Agent does not treat API cost or tier price as a design constraint. Removes an entire class of drift where "let's not fetch that because it costs $" leads to silently-shrunk scope.

---

## 6. Code-style notes (all minor, none pre-deploy)

- Extensive use of `@dataclass(slots=True, frozen=True, kw_only=True)` — matches the 2026 practices briefing.
- No `# type: ignore` without an error code that I saw across the recent modules.
- `nn.TransformerEncoder(..., is_causal=True)` dispatches to Flash Attention on GPU — correct usage.
- `torch.Generator` explicitly threaded through samplers for determinism. Good.
- `os.symlink` used in `artifacts.py:64` — Windows-hostile (same caveat as the vocab symlink). Not a blocker; note in a README.
- `_check_ece` last-bin edge inclusion in `metrics.py:107` matches Guo 2017 correctly.
- `_ols_no_intercept` in `kappa.py:80` uses float64 for numerical stability. Right call.
- `WindowSampler.sample()` builds batches with a Python list comprehension over `torch.stack` — CPU-friendly, GPU-suboptimal (many small tensor allocations). On the GPU run, batch construction may want vectorizing via `torch.gather` on a starts tensor. Not a correctness issue; a throughput one.
- `run_training` does not call `.to(device)` anywhere. Model and tensors live on CPU as-is. Adding `--device cuda` (or auto-detect) needs to move the model, batches, and generator's device consistently. **Not a blocker for the 50-step CPU smoke; blocker for the GPU run.** Add before GPU launch.

---

## 7. Pre-deploy punch list

**Must fix before launching a real training run on AWS GPU:**

1. **Fix `config_hash` in `scripts/train.py`** to hash the config file, not the tokens (§2.1). Grep every other script for the same pattern.
2. **Land the frozen normalizer** (`normalizers.pt`, training-partition-only fit, frozen for val/test) or ratify the deviation from tech-arch §6 (§2.2).
3. **Wire the test-look guard into the evaluate CLI** so any test-partition read consumes a look automatically (§2.3).
4. **Adopt `zoneinfo("America/New_York")`** and re-run the operational pull for the 2015-2022 training window (§2.4). This is the largest of the four but the correctness stakes are highest.
5. **Add `--device {cpu,cuda}` handling to `scripts/train.py`** with correct `.to(device)` calls on model, batches, and generator (§6).

**Ratify explicitly (Architect decision, not Agent) before real training:**

6. Channel-set reduction from spec's ~19 to code's 3 (§3.1). File a Decision naming which channels ship in the first real run and which are deferred.
7. RoPE substitute or land (§3.2).
8. MLP and GRU/TCN baseline plan (§3.3).
9. Size sweep and context sweep plan (§3.4).

**Watch (address in the next sprints, not blocking):**

10. `WINDOW_SAMPLED.start_position` real value (§4.1).
11. `EPOCH_COMPLETED.epoch` real counter (§4.2).
12. Twelve declared-but-not-emitted vocabulary tags surface to Deferred (§4.3).

The smoke path is honest, the discipline is holding, and 40 sprints of accumulated trace evidence sit on disk. What is not yet honest is the ship path. Fix the four blockers, ratify the four gaps, then the GPU spend has a claim to defend.
