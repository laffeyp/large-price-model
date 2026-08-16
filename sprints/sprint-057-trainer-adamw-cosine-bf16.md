# Sprint 057 -- trainer: AdamW + cosine LR + bfloat16 + warmup + deterministic

---

```yaml
---
id: 057
status: closed
phase: 3
pass_kind: functional
determinism_budget: statistically-deterministic
---
```

---

## scope

Closes review § 3 aggregate-audit HIGH item: *"Optimizer is Adam; no AdamW, no cosine schedule, no 2000-step warmup, no bf16. `model/trainer.py:151`. Spec § 9.2 explicit on all four."*

Tech-arch § 9.2 requirements:
- AdamW, `lr=3e-4`, `betas=(0.9, 0.95)`, `weight_decay=0.1` on 2D params only.
- Cosine LR decay to 10% of peak after 2000-step warmup.
- `bfloat16` mixed precision via `torch.amp.autocast`.
- Grad clip 1.0 (already shipped).
- `torch.use_deterministic_algorithms(True, warn_only=True)` + `CUBLAS_WORKSPACE_CONFIG=:4096:8` env var.

Sprint 057 wires all of these into `run_training_feats` (the Sprint 053 market-state path). The legacy `run_training` (bucket-ID path) stays on Adam for baseline back-compat; a follow-up sprint migrates it when the baselines land on the feats path.

### Deliverables

- `TrainerConfig` gains: `warmup_steps: int = 2000`, `lr_min_frac: float = 0.1`, `weight_decay: float = 0.1`, `betas: tuple[float, float] = (0.9, 0.95)`, `bf16: bool = False` (opt-in for CPU/MPS smoke; auto-enabled on cuda in the trainer).
- New helper `build_adamw_with_param_groups(model, weight_decay, lr, betas)` — splits parameters into 2D+ (decay) vs 1D + norm (no decay) groups per spec.
- New helper `cosine_with_warmup_lr(step, warmup_steps, total_steps, base_lr, min_frac)` — returns the LR at `step`. Linear warmup for the first `warmup_steps`; cosine decay to `base_lr * min_frac` afterward.
- `run_training_feats` uses AdamW + per-step LR schedule + bf16 autocast (when device is cuda OR bf16 flag is set) + `torch.use_deterministic_algorithms(True, warn_only=True)`.
- Trainer prints `torch.use_deterministic_algorithms` note on stderr on start; sets `CUBLAS_WORKSPACE_CONFIG` env var if unset.

## halt-and-articulate

**Deterministic algorithms + rolling-mean/std interactions.** Some PyTorch ops (scatter, sort with duplicates on certain devices) lack deterministic implementations and would raise under `torch.use_deterministic_algorithms(True)`. `warn_only=True` downgrades those to a warning so training continues; test coverage on cuda would surface any surprise crash. On MPS + CPU the flag has narrower coverage; documentation is thin. Sprint 057 sets it best-effort; the CUBLAS env var only matters on cuda.

**bf16 on MPS is not supported.** MPS backend rejects bfloat16 autocast in current torch versions. The trainer defaults `bf16=False`; explicit `--bf16` flag on `scripts/train.py` fails loud on MPS if opted in. Auto-enable on cuda only.

## signal contract

### Emits

No new emit sites. Existing `TRAINING_STEP_COMPLETED.lr` already carries the per-step learning rate; Sprint 057 makes that value dynamic (was constant `trainer_cfg.lr`).

### Invariants

- `build_adamw_with_param_groups(model)` returns two param groups: 2D+ params get `weight_decay=cfg.weight_decay`; 1D params (biases + LayerNorm gains) get `weight_decay=0.0`.
- `cosine_with_warmup_lr(step=0, ..., base_lr=3e-4)` returns 0 (warmup starts at step 0). At `step=warmup_steps` returns `base_lr`. At `step=total_steps` returns `base_lr * min_frac`.
- `TRAINING_STEP_COMPLETED.lr` at step > warmup shows a decreasing value across successive checkpoints.
- Existing `run_training_feats` tests keep passing (back-compat via new-arg defaults matching current behavior when the caller doesn't set them).

## artifact contract

### Files (3 — under hard rule 6)

- `src/price_space_llm/model/trainer.py` — extend `TrainerConfig`; add `build_adamw_with_param_groups` + `cosine_with_warmup_lr`; wire into `run_training_feats`.
- `scripts/train.py` — new CLI knobs `--warmup-steps`, `--weight-decay`, `--bf16` (default False), `--deterministic` (default True).
- `tests/test_trainer.py` — new tests: param-group split; cosine warmup shape (0 at step 0, peak at warmup_steps, min at total_steps); 2-step smoke with new optimizer completes.

### Command exit codes

- ruff, ruff format, mypy: green.
- pytest: 373 → 380+.
- `scripts/train.py --tokens-pt ... --n-steps 4 --eval-every 4` runs on the real training .pt with AdamW + cosine.

### Live smoke

Run 4-step smoke on real training .pt with new optimizer:
- Trainer log line names AdamW + weight_decay.
- Per-step `TRAINING_STEP_COMPLETED.lr` values differ across steps (warmup ramp).
- Checkpoint carries the new optimizer state shape.

---

## observation contract

Required (`pass_kind: functional`). Unit tests cover the param-group split + LR schedule shape; live smoke fires 4 steps against the real training artifact.

---

## honest audit

**What lands.** Spec-compliant optimizer + LR schedule on the market-state path. `torch.use_deterministic_algorithms` best-effort. Param-group split gives correct weight-decay semantics.

**What does not land.** bf16 auto-enable on cuda (opt-in via flag; auto path lands when a cuda smoke lives on the CI). Legacy `run_training` (bucket-ID) still uses Adam. Retiring the legacy path is a cleanup sprint.

---

## notes

**Why weight_decay = 0.1 on 2D only.** Standard practice: biases + LayerNorm scales are per-neuron scalars whose regularization pulls them toward zero rather than a beneficial small value. Every reference GPT-family recipe applies weight decay to matrices only.

**Why bf16 not fp16.** bf16 matches float32's exponent range so gradient magnitudes don't require loss-scaling. Simpler + more numerically stable on transformer forward passes. Cuda A100/H100 support bf16 natively.

**Why not scale grad clip to bf16.** The clip fires on the L2 norm of the raw gradient after autocast unscale (torch handles this in `clip_grad_norm_` automatically). Clip value stays 1.0.

---

## plan-mode review checklist

- [ ] Files under hard rule 6 (3).
- [ ] No new emit sites.
- [ ] Observation contract: unit tests + 4-step live smoke.
- [ ] Determinism budget statistically-deterministic (same seed = same batches; float ops within numerical noise; deterministic algorithms best-effort).
- [ ] Closes review § 3 HIGH: AdamW + cosine + warmup + bf16 opt-in + deterministic mode wired on the market-state training path.
