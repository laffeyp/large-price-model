# Review — sprints 030-033, the ML pipeline lands

**Reviewer:** Claude Code (Opus 4.7), acting in Agent role.
**Date:** 2026-08-12.
**Scope:** Sprint 030 (tokenizer), Sprint 031 (transformer + trainer), Sprint 032 (evaluation), Sprint 033 (baselines). Read: `src/price_space_llm/tokenizer/bucketize.py` (289 lines), `src/price_space_llm/model/{transformer,trainer,dataset}.py` (440 lines total), `src/price_space_llm/evaluation/{metrics,regimes,evaluate}.py` (501 lines total), `src/price_space_llm/baselines.py` (313 lines), plus the four sprint cards and 68 new tests. Test count 130 → 210.
**Verdict:** on track. Signal-emission coverage is now near-complete. One real spec deviation (RoPE), one silently-missing pre-registered baseline (MLP), one small dishonesty in a payload field, three watch items.

---

## 1. What went right

**Every vocabulary tag the four sprints touch fires from live code.** Tokenizer: BUCKETIZER_FITTED, BUCKET_STATS_WRITTEN, BUCKET_ASSIGNED (×519), MARKET_STATE_TOKEN_EMITTED (×520). Trainer: WINDOW_SAMPLED (×50), TRAINING_STEP_COMPLETED (×50), CHECKPOINT_WRITTEN (×2), EPOCH_COMPLETED, TRAINING_DIVERGED (both branches guarded). Evaluator: REGIME_LABELS_FROZEN, METRIC_COMPUTED (×42), BUCKET_FREQUENCY_DRIFT_MEASURED, METRIC_SNAPSHOT_WRITTEN (×2). Baselines: BASELINE_COMPARISON_ASSESSED (×3). Zero placeholder emissions, zero fabricated fields. That is the Sprint 020 lesson applied straight through.

**Sprint 032 un-lied Sprint 031's placeholders across the sprint boundary.** Sprint 031 shipped CHECKPOINT_WRITTEN with `val_ece = val_brier = val_rps = 0.0` and named them on the card as placeholders. Sprint 032 refactored `trainer._compute_val_metrics` to import `evaluation.metrics.compute_metric_set` — the identical function the offline evaluator uses. Same code path; same numbers. The step-25 re-run reports `ece=0.067, brier=0.982, rps=0.180`. This is the Addendum D1 discipline (signals cannot grade themselves) applied prospectively: one metric implementation, two consumers, no drift.

**Sprint 033 shares the same metric code path for baseline comparison.** `baselines.py` imports `compute_metric_set` from the evaluator module. Baseline val NLL and transformer val NLL travel through identical arithmetic. Apples-to-apples by construction, not by promise.

**Two causality invariants proven at two layers.** Sprint 025 test asserted `join_asof(strategy="backward")` never leaks future data at the alignment layer. Sprint 031 added `test_causal_mask_prevents_look_ahead` — toggle a downstream token, assert earlier logits are byte-identical at the model layer. Same discipline, two altitudes.

**Hypothesis property tests are landing where they earn their keep.** Sprint 030: `test_edges_are_strictly_increasing` (100 random distributions, zero counter-examples) and `test_bucket_assignment_is_quantile_consistent` (100 shapes, bucket-balance holds within 3× uniform). Sprint 032: two more Hypothesis tests on the metrics. Six property tests total across the project. All the OOPSLA-2025 evidence about PBT ROI (roughly 50× mutation kill vs unit tests) says these are the highest-leverage tests the project holds.

**Sprint 030's Rubber Duck caught a real bug.** First pass named `scripts/tokenize.py`, which shadowed the stdlib `tokenize` module and produced a `most likely due to a circular import` error on every subprocess CLI test. Renamed to `bucketize.py`; filed to drift-watchlist ("check new script names against `sys.stdlib_module_names` before landing"). Honest report of a mistake the code smell would have kept from a Reviewer.

**Sprint 031 articulated three stretches on the sprint card, not in the notes.** Hard rule 6 (four code files + script + two test files bundled — inseparable smoke path); v0.3 vocab has no `n_layers`/`n_heads`/`d_model` on CONFIG_RESOLVED, so model shape is only reproducible via source not trace (filed v0.4 candidate); `context_len` dropped 128 → 64 because June 2024's 104 val tokens are smaller than the sampler needs at 128. That is the round-1 recommendation ("stretches trigger halt-or-articulate, not sprint-note rationalisation") applied.

---

## 2. One real spec deviation

**Positional embeddings — learned absolute, not RoPE.** Tech-arch §8: *"the default block is causal, pre-LayerNorm, GELU, dropout 0.1, rotary positional embeddings"* and §Model glossary: *"positional information uses rotary embeddings. RoPE gives relative positional structure through a rotation applied inside the attention product without a learned absolute-position table."*

`model/transformer.py:37` uses `nn.Embedding(config.context_len, config.d_model)` for positions and `model/transformer.py:64` adds them to token embeddings — the classic learned-absolute pattern. RoPE is not present anywhere in the module. The tech-arch is explicit that RoPE is the choice and names *why* (no learned absolute-position table). Sprint 031's card does not name the substitution.

Two paths:
- **Land RoPE now.** PyTorch has no built-in RoPE; the reference implementation is ~30 lines applied inside the attention `q, k` computation. Requires ditching `nn.TransformerEncoder` and writing the block manually (nn.TransformerEncoder doesn't expose the attention math). Meaningful sprint of its own.
- **Ratify the deviation.** Update tech-arch or file a rationale-doc entry naming learned-absolute as the v1 substitute, RoPE as a v2 upgrade. The learned-absolute choice is defensible on a 519-token corpus where the position table cost is trivial.

Either path is fine. Silence is not. The tech-arch explicitly promises RoPE; the code silently ships without it. File the deviation.

---

## 3. One silently-missing pre-registered baseline

**Product-spec §Baselines names five, Sprint 033 shipped three, Sprint 033 named one as deferred.**

Product-spec's required baseline set: (a) 1-layer linear, (b) 3-layer MLP, (c) small causal sequence model (GRU or TCN), (d) target-only ablation, (e) magnitude-weighted loss ablation.

Sprint 033 shipped: linear, target-only, magnitude-weighted (a, d, e). Named deferred: gru_tcn (c). The MLP baseline (b) is silently absent. The sprint card says: *"gru_tcn deferred to a later sprint (needs GRU + TCN stack, own hyperparams)"* — no mention of MLP.

Not a scope defect if the intent is to bundle MLP into the same later sprint; is a discipline defect if the omission is unnoticed. Either way, MLP needs a home. File to Deferred with revisit trigger "sprint that adds gru_tcn" or "sprint that closes the pre-registered baseline ladder."

---

## 4. One small payload dishonesty

**`trainer.py:158`: `emitter.emit("WINDOW_SAMPLED", ..., start_position=int(step), ...)`** with the inline comment *"deterministic proxy; sampler returns starts per-batch."*

The v0.3 vocabulary payload for WINDOW_SAMPLED declares `start_position: int` and the tag's semantic intent (per the tag's `note` and Sprint 016's usage) is *the window's actual start position in the token stream*. Sprint 031 substitutes the training-step number, which is a different quantity. A trace reader who sees `start_position=25` cannot tell whether they are looking at a window starting at token 25 or at training step 25.

The comment names the substitution but the emitted field is dishonest — it purports to be one thing and is another. This is a smaller version of the Sprint 020 `_error_shim` pattern.

Two fixes, both cheap:
- Route the batch's real starting positions out through `WindowSampler.sample()` and emit the first-batch start position; use `0` (or a null-equivalent) for later windows in the batch.
- Rename the payload field. `WINDOW_SAMPLED` fires per training step, not per window, so consider whether the vocabulary intent matches. If it should fire per window inside a batch, the tag fires 4× less than it should.

Halt-or-articulate applies: this is a signal-side untruth. File as Surfaced.

---

## 5. Three watch items

**5.1 EPOCH_COMPLETED hard-codes `epoch=1`.** `trainer.py:256`: `emitter.emit("EPOCH_COMPLETED", run_id=run_id, epoch=1, ...)`. One emission per run, regardless of `n_steps`. The vocabulary intent is per epoch; the trainer emits per run. Fine for the smoke (50 steps, one virtual epoch). Wrong when a real run spans multiple epochs — either the loop needs an outer epoch counter, or the tag's semantics need clarifying in the rationale doc.

**5.2 `_compute_val_metrics` samples 4 batches instead of exhausting the val partition.** `trainer.py:216`. The offline evaluator (Sprint 032) is exhaustive; the checkpoint-time val metrics are samples. Two consumers, two implementations, potential divergence. On a 104-token val partition at batch_size=8 context_len=64, four batches may or may not cover the full val set. Verify by asserting `metrics.n_examples` from `_compute_val_metrics` equals `evaluate` module's val-partition count on the same checkpoint. If they disagree, the checkpoint's val_nll and the offline val_nll are different numbers under the same name.

**5.3 PyTorch bridge-mapping ceremony absent.** Sprint 031 adopted `torch>=2.13` + `numpy>=2.4` and Sprint 025 adopted `polars>=1.43.2` + `pyarrow>=25.0.1` and Sprint 028 adopted `pydantic>=2` and Sprint 019 adopted `httpx>=0.27` — none of these triggered a `bridge_mapping_required` halt, despite WORKING_AGREEMENT listing them all as stubs. The Alpha-Vantage MCP did trigger one (Sprint 018), because its live shape differed from documented shape.

The de-facto rule appears to be: real-network SDKs whose surface needs live discovery halt; well-documented pure-library SDKs whose surface is trustworthy from docs do not. That is defensible and matches what a senior engineer would do. But it is nowhere written down. Either codify (WORKING_AGREEMENT gains a distinction between "discovery-halting" and "documented-safe" bridge mappings) or the next reviewer will read the pattern as bypass.

---

## 6. Small code observations

- `transformer.py:38-52` uses `nn.TransformerEncoder` with `enable_nested_tensor=False` and `is_causal=True`. The `is_causal` flag lets PyTorch dispatch to Flash Attention when available. Good use of the built-in.
- `transformer.py:20` uses `@dataclass(slots=True, frozen=True, kw_only=True)` — the 2026-modern config pattern from the practices briefing. Adopted consistently across the new modules.
- `trainer.py:143` uses `torch.optim.Adam`, not `AdamW`. Tech-arch does not specify. Modern transformer practice is AdamW (decoupled weight decay). Inherited choice worth naming in a rationale-doc entry when the sprint that runs a real training budget lands.
- `trainer.py:183`: divergence threshold `grad_norm > trainer_cfg.grad_clip * 10`. Magic multiplier. Reasonable heuristic. Should be either a `TrainerConfig` field or explicitly documented.
- `evaluation/metrics.py:107` — the `compute_ece` last-bin edge inclusion (`<=` on the top bin) matches Guo et al. 2017 correctly. Small correctness detail that a lot of ECE implementations get wrong.
- `evaluation/metrics.py:157` — `compute_bucket_frequency_drift` returns 0.0 for `outer_ratio` when train tails sum to zero. Reasonable pathological-case fallback; a rationale-doc entry naming the branch would help a Reviewer understand why zero is honest and not a lie.
- Model size is 208,256 parameters. Product-spec's model-size sweep table names xs=1M/sm=3M/md=10M/lg=30M as the four sweep points. 208K is below xs. This is a smoke config, not a sweep point. When the sprint that runs the size sweep lands, the smoke config should either graduate to one of the four sweep points or the smoke config should be excluded from the sweep report.

---

## 7. Punch list

**File as Surfaced now (no sprint required):**

- **Positional embeddings.** Learned-absolute in code; RoPE in the tech-arch. Either land RoPE or ratify the deviation in a rationale-doc entry (§2).
- **WINDOW_SAMPLED.start_position semantics.** Currently populated with the step number, not the actual window start position. File a decision: rename, refactor, or ratify (§4).
- **MLP baseline absent from Sprint 033.** Silently missing from the pre-registered baseline ladder. File to Deferred with revisit trigger (§3).
- **EPOCH_COMPLETED.epoch hard-coded to 1.** File to Deferred with revisit trigger "sprint that runs multi-epoch training" (§5.1).
- **Bridge-mapping ceremony rule.** Codify the discovery-halt vs documented-safe distinction in WORKING_AGREEMENT, or add halts retroactively (§5.3).

**Consider in the next architecture-band sprint:**

- Extract `grad_clip * 10` divergence threshold into `TrainerConfig` (§6).
- Adopt AdamW at the sprint that runs a real training budget (§6).
- Assert `_compute_val_metrics` and offline evaluator agree on val_nll for the same checkpoint (§5.2).

**On-track summary:** the four sprints delivered the tokenizer → model → trainer → evaluator → baselines chain end-to-end, with the metric code path shared across trainer / evaluator / baselines by construction, causality proven at two layers, real signals emitting throughout, and one honest cross-sprint un-lie of a Sprint 031 placeholder. The remaining items are small — one spec deviation, one silent omission, one payload dishonesty, three watch items. None blocks the next sprint (cost calibration or simulator per tech-arch §11, subject to the BBO-source Deferred).
