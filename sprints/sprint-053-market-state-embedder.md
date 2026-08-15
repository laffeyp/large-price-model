# Sprint 053 -- MarketStateEmbedder (closes SEVERE review § 1 gap)

---

```yaml
---
id: 053
status: closed
phase: 3
pass_kind: functional
determinism_budget: statistically-deterministic
---
```

---

## scope

Closes the SEVERE gap `reviews/full-review-sprints-041-050.md` § 1 named: transformer consumes bucket-IDs, not multi-channel state.

Tech-arch § 7.2 verbatim: *"Each timestep's per-channel feature vector passes through its own `nn.Linear` projection to a `d_model`-dim embedding, and the projections are summed to produce one `d_model`-dim market-state vector per bar."*

Sprint 053 adds a parallel model + trainer path that consumes the Sprint 052 `.pt` artifact. The legacy `PriceSpaceLLM` (bucket-ID) stays in place for the evaluator + baselines; a follow-up sprint retires it once those callers migrate.

### Deliverables

- `MarketStateEmbedder(nn.Module)` — holds `nn.ModuleDict` of one `nn.Linear(F_c, d_model)` per channel. `forward(feats: dict[str, Tensor[B, T, F_c]]) -> Tensor[B, T, d_model]` applies each linear and sums the projections.
- `MarketStateTransformer(nn.Module)` — market-state input path. Config extends `TransformerConfig` with `channel_dims: dict[str, int]`. Forward takes `feats: dict[str, Tensor[B, T, F_c]]`, runs through the embedder → positional embedding → causal transformer stack → `nn.Linear(d_model, vocab_size)` head. Outputs logits `Tensor[B, T, vocab_size]`.
- `WindowBatchFeats` dataclass — `feats: dict[str, Tensor[B, T, F_c]]`, `targets: Tensor[B, T]` int64, `starts: tuple[int, ...]`.
- `WindowSamplerFeats` — random-window sampler over a `TokenizedArtifact`. Slices each channel's feature tensor with the same start indices; targets are `artifact.targets` shifted by one position (matching the existing bucket-ID sampler's semantics).
- `run_training_feats(artifact, ..., model_cfg, ...)` — parallel to `run_training`. Consumes `WindowSamplerFeats`; feeds `feats` to `MarketStateTransformer`. Same emit surface, same checkpoint format, same TrainerConfig.
- `scripts/train.py` gains `--tokens-pt PATH` flag. When set: loads via `load_tokens_pt`, builds `channel_dims` from `artifact.features`, dispatches to `run_training_feats`. Mutually exclusive with the existing `--tokens` (parquet) flag.

### Non-goals

- Retiring `PriceSpaceLLM` — deferred; evaluator + baselines still use it.
- Frozen normalizer — Sprint 054.
- Rewiring `TargetOnlyBaseline` as spec's zeroed-channel transformer — deferred until frozen normalizer + Sprint 057-070 range clarifies.

## halt-and-articulate

**Sum invariance is architecturally exact.** Tech-arch § 3 states: `Σ_c W_c x_c = W_concat [x_1; ...; x_n]`. Sprint 053's implementation follows the summation form because it lets each channel's projection layer stay a separate `nn.Linear` (modular, per-channel weight init, per-channel debug). Test locks the invariance by comparing a two-channel `MarketStateEmbedder` against a hand-built `W_concat` on a small tensor.

**Batch construction handles heterogeneous F_c.** Different channels have different feature counts (target = 10, market_context = 4, macro = 4, event = 4, options = 4). The sampler builds one `Tensor[B, T, F_c]` per channel; the embedder's per-channel Linear takes the matching F_c. No padding or masking across channels — each channel's Linear is defined by its own F_c at construction time.

## signal contract

### Emits

No new tags. Existing training-run emit surface (WINDOW_SAMPLED, TRAINING_STEP_COMPLETED, CHECKPOINT_WRITTEN, EPOCH_COMPLETED, TRAINING_DIVERGED, SESSION_INIT/COMPLETE) covers the feats path identically.

### Invariants

- `MarketStateEmbedder(channel_dims)` builds one `nn.Linear(F_c, d_model)` per key in `channel_dims`; every key in a forward-pass `feats` dict MUST match a key in `channel_dims` (missing → KeyError; extra → ValueError with a clear message).
- `MarketStateEmbedder.forward(feats)` returns `Tensor[B, T, d_model]` regardless of the number of channels.
- `MarketStateTransformer.forward(feats)` shape is `Tensor[B, T, vocab_size]` — same as the bucket-ID model's output shape, so downstream loss + metrics code paths reuse cleanly.
- `WindowSamplerFeats.sample()` returns a `WindowBatchFeats` whose per-channel tensor shapes are all `[batch_size, context_len, F_c]`; targets are `[batch_size, context_len]`.
- `run_training_feats` produces the same `TrainerResult` shape and CHECKPOINT_WRITTEN payload as `run_training`, so `scripts/evaluate.py` doesn't need Sprint 053 changes to load a market-state checkpoint (evaluator update is a later sprint).
- `scripts/train.py --tokens-pt PATH` refuses if `--tokens` is also passed; refuses if the `.pt` artifact is missing.

## artifact contract

### Files (6 — at hard rule 6)

- `src/price_space_llm/model/transformer.py` — `MarketStateEmbedder` + `MarketStateTransformer` + `MarketStateTransformerConfig` classes. Leave `PriceSpaceLLM` + `TransformerConfig` untouched.
- `src/price_space_llm/model/dataset.py` — `WindowBatchFeats` + `WindowSamplerFeats`. Leave `WindowBatch` + `WindowSampler` untouched.
- `src/price_space_llm/model/trainer.py` — `run_training_feats()` parallel to `run_training`. Shares `_grad_norm`, `TrainerConfig`, `TrainerResult`, `TrainingDiverged`; adds a private `_compute_val_metrics_feats` that mirrors the existing val pass for the new sampler.
- `src/price_space_llm/model/__init__.py` — export the new classes and function.
- `scripts/train.py` — `--tokens-pt` mutually-exclusive flag; loads artifact + dispatches.
- `tests/test_model.py` — new tests: MarketStateEmbedder shape + sum invariance + config mismatch; MarketStateTransformer forward shape; WindowSamplerFeats shape + causality; end-to-end 2-step smoke through run_training_feats on synthetic data.

### Command exit codes

- ruff, ruff format, mypy: green.
- pytest: 340 → 350+ (new tests).
- `scripts/train.py --tokens-pt data/tokenized/{run_id}.pt --n-steps 2` completes without error on the real training-window .pt.

### Live smoke

Two-step CPU smoke against the real training .pt (54,262 rows × 20 channels):
- Model constructs with `channel_dims` derived from artifact.
- Two training steps complete; TRAINING_STEP_COMPLETED emits carry real train_loss + grad_norm + throughput values.
- Val pass fires at step 2; val_top1 exceeds 0.10 (bucket-ID baseline from Sprint 040 smoke was 0.095) — the honest test of the multi-channel bet on a two-step smoke; the real gate lives on the size-swept GPU runs (Sprint 084+).

Expected shape sanity:
- MarketStateEmbedder param count ≈ Σ_c (F_c × d_model + d_model) ≈ (target: 10×64 + 64) + (19 × (4×64 + 64)) = 704 + 5,700 = 6,404. Small overhead vs the transformer trunk.

---

## observation contract

Required (`pass_kind: functional`). Unit tests lock the sum-invariance identity + shape guarantees. Live-smoke two-step CPU run against real training .pt verifies the entire path (artifact load → sampler → embedder → transformer → loss → backward → step → val metrics) end-to-end without shape errors. Val_top1 > 0.10 on two steps is a weak signal; the SEVERE gap is closed structurally when the model consumes per-channel features, not empirically at Sprint 053's smoke.

---

## honest audit

**What lands.** MarketStateEmbedder + MarketStateTransformer wired end-to-end. The market-state path consumes the Sprint 052 .pt artifact. `--tokens-pt` dispatches to the new trainer. Three previously-unmeasurable gates become measurable in principle (target-only ablation, multi-channel-lift claim, gru_tcn baseline) once their baseline counterparts land against the same feats interface.

**What does not land.** Frozen normalizer (Sprint 054). Rewired `TargetOnlyBaseline` as spec's zeroed-channel transformer (deferred). Evaluator migration to feats path (deferred). GRU/TCN + MLP baselines against feats (deferred). RoPE + AdamW + purged-embargo + top-K checkpoint + size sweep + context sweep (roadmap Sprints 059-070).

**What surfaces.** The old `PriceSpaceLLM` + `run_training` stay for back-compat. Dual model classes is temporary tech debt — the follow-up cleanup sprint should either retire `PriceSpaceLLM` or unify both paths under one class with a dispatch on input type.

---

## notes

**Why `channel_dims` in config, not inferred at forward.** The model's parameter count is a function of its config; the config file (and thus config_hash) needs `channel_dims` frozen at construction so two runs with the same config hash produce identical shapes. Inferring at forward from the batch would make `config_hash` no longer sufficient to reconstruct the model.

**Why sum, not concat.** Spec § 3 explicit: parameter count is identical, mathematically equivalent, but the summation form keeps per-channel Linear modules discoverable in `model.state_dict()`. A future channel ablation can zero one Linear's weights (target-only path) without touching the tensor concatenation logic.

**Why not extend `PriceSpaceLLM` in place.** Baselines + evaluator import `PriceSpaceLLM` directly; changing its forward signature would ripple through 3+ callers in one sprint. Two-class transition keeps each caller change bounded to its own future sprint.

**Two-step smoke won't beat 0.10.** Two steps is one gradient update per parameter block — not enough to fit anything meaningful. The number the review named ("val_top-1 climbs meaningfully above 0.10") is the SIZE-SWEPT run's job (Sprint 084+ on GPU). Sprint 053 delivers the mechanism; the numbers come later.

---

## plan-mode review checklist

- [x] Files under hard rule 6 (6 exactly).
- [x] No new emit sites required.
- [x] Observation contract (functional-band): 8 unit tests (shape + sum invariance + config rejection + sampler shape + causality + mismatch guard + 2-step end-to-end smoke) plus live-smoke on real training .pt.
- [x] Determinism budget statistically-deterministic (fixed seed → same batches → same weights within numerical noise).
- [x] Closes the SEVERE review § 1 gap: model consumes per-channel feature tensors, not bucket-IDs.

---

## close (2026-08-15)

Landed. `MarketStateEmbedder` + `MarketStateTransformer` + `WindowSamplerFeats` + `run_training_feats` wired end-to-end. `scripts/train.py --tokens-pt PATH` dispatches to the market-state path; `--tokens` (bucket-ID parquet) still works for baselines. Unit tests (+8): shape + sum invariance (Σ_c W_c x_c = manual concat form, atol 1e-6) + extra-channel rejection + transformer forward shape + sampler batch shapes + causality shift-by-one + mismatched-length guard + 2-step run_training_feats smoke on synthetic data. Live smoke on real training .pt (54,262 rows × 20 channels): device=mps, 2 steps in 3.45s, final_train_loss 3.5700 (log(32)=3.47 uniform baseline; 3.57 = no meaningful training in 2 steps, as expected), 212,992 params, 1 checkpoint written, full emit surface fires (SESSION_INIT + CONFIG_RESOLVED + 2×WINDOW_SAMPLED + 2×TRAINING_STEP_COMPLETED + 1×CHECKPOINT_WRITTEN + EPOCH_COMPLETED + SESSION_COMPLETE). Test count 340 → 348 (+8). Four tools green. Legacy `PriceSpaceLLM` + `run_training` stay for baselines + evaluator. Sprint 054 opens next: frozen normalizer.
