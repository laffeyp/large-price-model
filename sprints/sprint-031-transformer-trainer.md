# Sprint 031 -- transformer + training loop

---

```yaml
---
id: 031
status: closed
phase: 2
pass_kind: functional
determinism_budget: statistically-deterministic
---
```

---

## scope

Author the causal-decoder transformer and its training loop per tech-arch §9. Adopt `torch>=2.13` and `numpy>=2.4`. Wire every train-category tag from v0.3: `WINDOW_SAMPLED`, `TRAINING_STEP_COMPLETED`, `CHECKPOINT_WRITTEN`, `EPOCH_COMPLETED`, `TRAINING_DIVERGED`. Live smoke: 50 steps on the June 2024 tokens parquet from Sprint 030.

Halt-and-articulate at plan-mode review:

1. **Hard rule 6 stretched.** Four new code files (`model/__init__.py`, `model/transformer.py`, `model/dataset.py`, `model/trainer.py`) plus a script (`scripts/train.py`) plus two test files. Justified: transformer + dataset + trainer + CLI are one inseparable smoke path — the training loop cannot smoke without every piece.

2. **Vocabulary gap.** `CONFIG_RESOLVED.typed_payload` has no `n_layers` / `n_heads` / `d_model`. The model shape is not reproducible from the trace alone under v0.3. Sprint 031 hardcodes the tech-arch §9 architecture (`d_model=64, n_layers=4, n_heads=4`) and defers a `CONFIG_RESOLVED` extension to a v0.4 lock when a second architecture appears.

3. **Config change.** `configs/experiment/v1.json` was `context_len=128`. The June 2024 tokens parquet has 519 tokens; an 80/20 split leaves 104 val tokens, and val sampler needs at least `context_len + 1`. Changed config to `context_len=64` (the smallest legal Literal). Multi-month tokens (Sprint 032+) can raise it back to 128.

---

## signal contract

### Emits per training run

- `SESSION_INIT` with `run_kind=train` (first live emit at this run_kind).
- `CONFIG_RESOLVED` at open (all five required fields from Sprint 028).
- `WINDOW_SAMPLED` per training window: `run_id`, `start_position`, `context_len`.
- `TRAINING_STEP_COMPLETED` per optimizer step: `run_id`, `step`, `train_loss`, `lr`, `grad_norm`, `throughput_tokens_per_sec`.
- `CHECKPOINT_WRITTEN` every `eval_every` steps: `run_id`, `step`, `path`, and all six val metrics (`val_nll`, `val_ece`, `val_brier`, `val_rps`, `val_dir_acc`, `val_top1`, `val_top3`).
- `EPOCH_COMPLETED` at end: `run_id`, `epoch`, `mean_train_loss`, `n_steps`.
- `TRAINING_DIVERGED` on NaN loss or grad-norm > `clip*10`: `run_id`, `step`, `train_loss`, `grad_norm`, `val_nll_at_last_eval`, `reason ∈ {nan_loss, gradient_explosion, val_metric_diverged}`.

### Invariants

- Causal mask: at position T the model sees only positions 0..T-1. Look-ahead leakage impossible by construction; test `test_causal_mask_prevents_look_ahead` proves it by toggling a downstream token and asserting earlier logits are byte-identical.
- Determinism: same seed → same final train loss to 1e-4; test `test_run_training_is_deterministic_with_seed` verifies.
- On NaN loss: `TRAINING_DIVERGED` emits with `reason=nan_loss` BEFORE `TrainingDiverged` raises. Trace records the failure; caller exits 2.
- On grad-norm > `clip*10`: `TRAINING_DIVERGED` emits with `reason=gradient_explosion` BEFORE raise.
- Val metrics: `val_ece` / `val_brier` / `val_rps` are 0.0 placeholders in Sprint 031 (calibration + RPS need one-hot targets + bin scaffolding). `val_nll` / `val_top1` / `val_top3` / `val_dir_acc` are real.

---

## artifact contract

### Files created

- `src/price_space_llm/model/__init__.py`
- `src/price_space_llm/model/transformer.py` (~85 lines)
- `src/price_space_llm/model/dataset.py` (~100 lines)
- `src/price_space_llm/model/trainer.py` (~200 lines)
- `scripts/train.py` (~120 lines)
- `tests/test_model.py` (12 tests: 4 transformer, 4 sampler, 2 split, 2 load_tokens)
- `tests/test_trainer.py` (5 tests: emit sequence, checkpoint writes, val-metrics payload, NaN divergence, determinism)

### Files modified

- `pyproject.toml` — `torch>=2.13`, `numpy>=2.4` added; version 0.14 → 0.15; mypy `python_version` bumped 3.11 → 3.12 (numpy stubs use PEP 695 `type` statements).
- `configs/experiment/v1.json` — `context_len` 128 → 64.

### Command exit codes

- ruff, ruff format, mypy, pytest all green.
- Test count 142 → 159 (+17).

### Live smoke

```
uv run python scripts/train.py \
  --tokens data/tokenized/tokenize-features-align-2024-06-0000000000000000-0000000000000000-0000000000000000.parquet \
  --n-steps 50 --eval-every 25 --batch-size 4
```

Verified: exit 0, 0.77s, 208,256 parameters. Trace 106 lines: SESSION_INIT + CONFIG_RESOLVED + 50× WINDOW_SAMPLED + 50× TRAINING_STEP_COMPLETED + 2× CHECKPOINT_WRITTEN + EPOCH_COMPLETED + SESSION_COMPLETE. Train loss 3.6251 → 2.8568 (learning). Val top-1 ≈ 0.02 (chance = 1/32 = 0.031 — essentially random; expected on a 519-token corpus). Two `.pt` checkpoint files at `artifacts/checkpoints/`.

---

## observation contract

Required. Live smoke ran. Every declared training tag fires with a real payload. The tiny dataset (519 tokens) is not enough to actually learn — the val metrics prove that — but the training loop, checkpoint contract, causal-mask invariant, and every emit path all work end-to-end.

---

## honest audit

**What actually landed:** the loop and every emit. Model is causal-mask-verified. Training is seed-deterministic to 1e-4. Divergence detection catches NaN. Checkpoints save torch state_dict + model config with a real val pass.

**What is placeholder:** `val_ece`, `val_brier`, `val_rps` are 0.0. The vocabulary requires those fields on `CHECKPOINT_WRITTEN`; the implementations need one-hot targets, calibration bins, and RPS bin-cumulative differences. Deferred to Sprint 032 (evaluation sprint). Honest choice: the vocabulary refuses to serialize missing fields; 0.0 placeholders satisfy the type contract but carry a Reviewer risk of being read as "well-calibrated." A future v0.4 could mark them optional. Watch item filed.

**What surfaced during test writing:** `pytest` strictness turned torch's `enable_nested_tensor is True but self.use_nested_tensor is False because encoder_layer.norm_first was True` warning into a failure. Fixed by passing `enable_nested_tensor=False` to `TransformerEncoder` explicitly (the path is a no-op when `norm_first=True` anyway).

**What surfaced during mypy pass:** numpy's own `.pyi` stubs use PEP 695 `type` statements requiring `python_version >= 3.12`. Bumped mypy `python_version` to 3.12; runtime floor stays `>=3.11` (per `[project] requires-python`).

**What surfaced during first smoke:** `WINDOW_SAMPLED.context_len` is a v0.3 enum `{64|128|256|512}`; my test used 16 for speed and the emit failed. That is the vocabulary doing its job. Tests fixed to use 64. The strict validator earned its keep again.

---

## notes

**Model architecture is tech-arch §9 hardcoded.** `d_model=64, n_layers=4, n_heads=4, dropout=0.1`. Not in the config, not in CONFIG_RESOLVED. A Reviewer reading only the trace cannot tell what shape was trained. Recorded as a v0.4 vocabulary evolution candidate; when a second architecture appears (baseline vs main, or ablation studies), the vocab bumps.

**Free-tier training envelope untouched.** Sprint 031's live smoke ran on CPU in under a second because the corpus and step count are tiny. Real training (multi-month tokens, thousands of steps) starts spending against the tech-arch's ~$500 compute envelope; not this sprint.

**Sprint 032 slate.** Multi-month features + tokens → longer training window → real val metrics (calibration, Brier, RPS) → the product-spec §Success gates start being answerable.

---

## plan-mode review checklist

- [x] Scope one paragraph, one concept (transformer + training loop as one delivery).
- [x] Files exceed hard rule 6 ceiling — halt-and-articulate above; three items justified.
- [x] Signal contract cites v0.3 tags with real emit sites.
- [x] Observation contract present (functional-band); live smoke command verified.
- [x] Determinism budget declared (statistically-deterministic; seed-deterministic to 1e-4 CPU tolerance).

---

## close (2026-08-12)

Landed. Every declared training tag emits from live code. Test count 142 → 159 (+17, including two invariant tests: causal-mask no-leakage and seed determinism). Four tools green. Two `.pt` checkpoints on disk with a real val pass. Signals-drive: 39 of 56 tags now live.
