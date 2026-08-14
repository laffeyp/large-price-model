# Sprint 041 -- pre-GPU review-driven correctness fixes

---

```yaml
---
id: 041
status: closed
phase: 2
pass_kind: functional
determinism_budget: bit-deterministic
---
```

---

## scope

`reviews/pre-gpu-deploy-holistic-review.md` (2026-08-13) flagged four hard blockers, four ratification gaps, three watch items across sprints 001-040. Sprint 041 verifies every claim against the code, fixes the mechanical items in a single sprint, surfaces the architectural items to `BLACKBOARD § Surfaced for review` with verification notes, and leaves the deep-architectural decisions to explicit Architect ratification before Sprint 042 (remote GPU provision).

Fixes landed in this sprint:
1. `config_hash` was hashing the data instead of the config across `scripts/{train,baselines,bucketize,features}.py` — silent reproducibility break. All four fixed to `hashlib.sha256(args.config.read_bytes()).hexdigest()`.
2. `WINDOW_SAMPLED.start_position` was `int(step)` — a dishonest proxy. `WindowSampler.sample()` now returns real starts on `WindowBatch.starts`, and the trainer emits `batch.starts[0]` (the first-batch window's start position in the token stream).
3. `EPOCH_COMPLETED.epoch` was hard-coded to `1`. Now computes `ceil(tokens_consumed / len(train_tokens))` where `tokens_consumed = n_steps * batch_size * context_len`. For the 200-step W&B smoke this reports `epoch=3` instead of `epoch=1`; for a 300-step run it reports `epoch=4`.

Surfaced to `BLACKBOARD § Surfaced` (seven new entries; verification notes on each):
- Frozen normalizer missing AND normalization-drift diagnostic missing (§2.2 + product-spec line 251 addition surfaced by user).
- Fixed EST DST bug (§2.4) with nuance: current pipeline is internally consistent because ALL timestamps flow through the same offset; VIX `known_at` is drift-affected during EDT months.
- Test-look guard not auto-wired (§2.3).
- Channel scope 3 vs ~19 (§3.1).
- Model-size + context-length sweeps missing (§3.4).
- Twelve unemitted vocabulary tags (§4.3).
- Device handling absent (§6).

RoPE (§3.2) and baseline ladder (§3.3) were already on the Surfaced list from `reviews/sprints-030-033-ml-pipeline-review.md`; this sprint's verification confirmed both still hold.

## halt-and-articulate

**Review-response sprint pattern.** Not a feature sprint. Reads a fresh review, verifies each claim by grep, fixes the mechanical items, surfaces the rest. No new subsystems land. The eight Surfaced entries carry verification evidence (line numbers, actual grep counts) so a future Reviewer can trace each finding to code without re-verifying.

**Review overstatements corrected honestly.** §2.2 says the rolling z-score "creates a per-bar leak from the val partition into its own normalization." Verified `polars.rolling_mean(window_size=20)` uses a trailing/backward window — causal per bar, no future leak. The architectural gap (rolling vs training-fit expanding + frozen) is real; the leak claim is not. Surfaced entry names the correction.

§2.4 says fixed EST is "a correctness bug for any training run on 2015-2022 data." Verified: because both cache bar timestamps AND grid timestamps flow through the same `US_EASTERN_OFFSET`, the alignment self-consistency holds — no relative drift within the SPY intraday channel. VIX INDEX_DATA's `known_at` IS drift-affected during EDT months (~7 months/year, ~1 hour late). External time sources (macro releases in real US Eastern) would break everything. Surfaced entry states the nuance.

**Hard rule 6 stretch.** Files touched: `scripts/train.py`, `scripts/baselines.py`, `scripts/bucketize.py`, `scripts/features.py` (four CLIs, config_hash fix), `src/price_space_llm/model/dataset.py` (WindowBatch.starts field), `src/price_space_llm/model/trainer.py` (WINDOW_SAMPLED + EPOCH_COMPLETED fixes), `tests/test_trainer.py` (two new tests), `BLACKBOARD.md` (seven Surfaced entries). Bundled because each fix is a single-line correction and splitting into eight commits would obscure the review-response shape.

## signal contract

### Emit-site behavior changes

- `WINDOW_SAMPLED.start_position` now carries a real token-stream index from `batch.starts[0]` (`WindowSampler.sample` returns starts on `WindowBatch`). Previously `int(step)`. Live smoke on real 2015-2022 tokens: first three step emissions carry start_position `2088`, `4703`, `4322` (random draws within `[0, 43,368-64-1]` at seed 41).
- `EPOCH_COMPLETED.epoch` now carries `ceil(tokens_consumed / len(train_tokens))`. Previously constant `1`. Live smoke: 300 steps at batch 8, context 64, train_tokens 43,368 → 153,600 tokens consumed / 43,368 = 3.54 → `epoch=4`.
- `SESSION_INIT.config_hash` (from `script_session`) and `CONFIG_RESOLVED.config_hash` (from `load_config`) now both equal `sha256(args.config.read_bytes())` for four CLIs. Verified against live trace: both fields report `54db82ff...` matching `shasum -a 256 configs/experiment/v1.json`.

### New emit sites

None.

## artifact contract

### Files modified

- `scripts/train.py` — config_hash = sha256 of config file bytes; data_hash = sha256 of tokens parquet. Added `--config` existence check.
- `scripts/baselines.py`, `scripts/bucketize.py`, `scripts/features.py` — same config_hash / data_hash pattern.
- `src/price_space_llm/model/dataset.py` — `WindowBatch` gains `starts: tuple[int, ...]` field; `WindowSampler.sample()` returns real starts.
- `src/price_space_llm/model/trainer.py` — WINDOW_SAMPLED emits `batch.starts[0]`; EPOCH_COMPLETED computes effective epoch via `math.ceil`.
- `tests/test_trainer.py` — two new tests: `test_window_sampled_start_position_is_a_real_start` (asserts start_positions lie in `[0, max_valid_start]` and are distinct across steps), `test_epoch_completed_reports_effective_epoch` (asserts epoch=4 for the 800-token / 10-step / batch-4 / context-64 combination).
- `BLACKBOARD.md` — seven new Surfaced entries with verification notes.

### Command exit codes

- ruff, ruff format, mypy, pytest all green.
- Test count 284 → 286 (+2: start_position honesty + epoch counter honesty).

### Live smoke

50-step run on real 2015-2022 tokens (seed 41):
```
train: 50 steps in 0.55s; final_train_loss=3.3661; checkpoints=2; params=208256
```

Verified from trace `logs/train-.../signals.jsonl`:
- SESSION_INIT.config_hash = `54db82ff38c898f9...` (= shasum of configs/experiment/v1.json)
- CONFIG_RESOLVED.config_hash = `54db82ff38c898f9...` (matches SESSION_INIT)
- SESSION_INIT.data_hash = `e66bea82fb145485...` (= shasum of tokens parquet — different from config)
- First 3 WINDOW_SAMPLED: start_position = 2088, 4703, 4322 (real token-stream indices in `[0, 43303]`)
- EPOCH_COMPLETED.epoch = 1 (50 steps × 8 × 64 = 25,600 tokens / 43,368 train tokens = 0.59 → ceil = 1)

300-step run verified `epoch=4` in EPOCH_COMPLETED payload.

---

## observation contract

Required (`pass_kind: functional`). Every mechanical fix verified against a live trace on real tokens. Two new tests lock the invariants:
- `test_window_sampled_start_position_is_a_real_start` verifies start_positions are real token indices.
- `test_epoch_completed_reports_effective_epoch` verifies the ceil computation matches for 800 tokens / 10 steps / batch 4 / context 64 → epoch=4.

Config hash separation verified by direct sha256 comparison against `configs/experiment/v1.json`.

---

## honest audit

**What landed.** Four silent correctness bugs across CLIs. Two payload lies in the trainer's declared emit surface. All fixed with one-line changes and live-trace verification.

**What did not land.** No architectural changes. Frozen normalizer, DST correction, test-look wiring, channel expansion, RoPE, MLP+GRU/TCN baselines, sweep infrastructure, device handling all filed to Surfaced with verification evidence. Each needs Architect ratification (which path) or a dedicated sprint (which scope) before Sprint 042 (remote GPU provision) opens.

**What the review overstated.** §2.2's "per-bar leak" claim is not what the rolling-window causal implementation does; the architectural gap (rolling vs training-frozen expanding) is real. §2.4's "correctness bug for any training run" overstates the current 3-channel pipeline's exposure — the internal self-consistency of alignment holds under the fixed offset; the exposure is real for the VIX known_at labels during EDT months and for any future external-time-sourced channel.

**What the review missed** (parallel spec re-read audit surfaced during this sprint):

- Product-spec line 251 requires a normalization-drift diagnostic on holdout: "plot the normalized-feature distribution on the holdout against training. Track it as a failure mode." Diagnostic has no signal home in the current vocabulary and no plotting code. Rolled into the §2.2 Surfaced entry — one gap, two artifacts owed.

- **Nineteen additional spec-vs-code gaps** filed as a single BLACKBOARD Surfaced entry with severity ranking (1 SEVERE, 8 HIGH, 5 MEDIUM, 4 LOW). Highlights:
  - **SEVERE:** the transformer input is discrete bucket-IDs (`nn.Embedding(vocab_size, d_model)`), not the continuous per-channel state the spec §7.2 `MarketStateEmbedder` prescribes. Even fixing the 3-vs-19 channel gap would not matter — the current model consumes no channels at all. The transformer is fundamentally target-only-on-bucket-ids.
  - **HIGH:** aligned parquet is close-only (no OHLCV); missing three "load-bearing" columns per channel (missing_mask, age_since_known_at, observed_at_this_grid_step); `is_overnight_gap` flag absent; `bucket_stats.json` schema missing `bucket_train_mean` (simulator cannot decode outer buckets); `TargetOnlyBaseline` is a marginal-frequency predictor not the spec's zeroed-channel ablation; `REQUIRED_DELTA_PCT` targets `magnitude_weighted` not `gru_tcn`; optimizer is Adam not AdamW (no cosine, no warmup, no bf16); no simulator subsystem at all; no `experiments/logbook.csv` writer.

  **Aggregate reading.** Between the pre-GPU review and this audit, at least three specification claims are structurally unmeasurable in the current code: the target-only baseline gate (bad baseline shape), the gru_tcn baseline gate (baseline absent), and the multi-channel-lift claim (transformer consumes bucket-ids only). None are fixable by tuning; each needs a code shift. Sprint 042 (remote GPU) is not the right next sprint. A model-architecture-align sprint (or several) is.

**Review discipline honored.** Every fix carries the sprint tag (`Sprint 041:`) in the source comment so a future Reviewer can trace the change back to this review-response cycle. Nothing silent.

---

## notes

**Why `WindowBatch.starts` instead of returning starts separately.** The batch is the natural unit; the trainer already unpacks `batch.inputs` and `batch.targets`; adding `batch.starts` keeps the caller shape uniform and keeps the sampler's contract single-return.

**Why `epoch = ceil(tokens_consumed / train_tokens)` and not `floor`.** A partial epoch (e.g., 0.59 of a pass) is still meaningfully "epoch 1 in progress." The ceil-with-max-1 guard names it that way. When n_steps × batch × context < train_tokens, we report `epoch=1` even though only a fraction of the corpus was seen — matches vocabulary intent that a run always has at least one epoch even if incomplete.

**Why hash the config file bytes and not the resolved config object.** The config file bytes are stable across resolution (no dependency on load_config's Pydantic parsing). Two runs with byte-identical config files are guaranteed to have the same config_hash, independent of parser version. Sprint 028's `load_config` already computes its own `CONFIG_RESOLVED.config_hash` from file bytes — this sprint aligns `SESSION_INIT.config_hash` to the same computation so the two emit sites tell the same story.

**What was NOT changed.** The features.py, bucketize.py, baselines.py `config_hash` fix uses the same pattern but their `data_hash` still reads the input parquet's bytes into memory. For the 2015-2022 aligned parquet (~54,262 rows × 5 cols × 8 bytes ≈ 2 MB) that is cheap. For a full-corpus 65k-row × 20-column parquet it will land at ~10 MB — still cheap. Not worth streaming.

---

## plan-mode review checklist

- [x] Review claims verified individually against code before fixing.
- [x] Fixes landed only for mechanical items with clear one-line remediation.
- [x] Deep-architectural items surfaced with verification notes, not silently fixed.
- [x] Review overstatements named honestly in the sprint card.
- [x] User-flagged spec addition (normalization-drift diagnostic) rolled into the normalizer Surfaced entry.
- [x] Hard rule 6 stretch articulated.
- [x] Determinism budget bit-deterministic (config_hash + honesty fixes deterministic per seed).

---

## close (2026-08-13)

Landed. Four config_hash bugs fixed across CLIs; two payload lies in the trainer corrected. Seven architectural gaps from the pre-GPU review plus nineteen additional gaps from the parallel spec audit surfaced to BLACKBOARD with file/line evidence and severity ranking.

**Sprint 042 is not "remote GPU provision" anymore.** The audit shows the current transformer consumes bucket-IDs, not the multi-channel state the spec defines. Provisioning a GPU to train this architecture would spend money to demonstrate a model the spec never approved. The next sprint is architectural: either land the spec's `MarketStateEmbedder` + per-channel `nn.Linear` fusion path, or file a Decision explicitly re-scoping v1 to the bucket-ID-only variant with a rationale that names what the sub-model tests and what it does not.
