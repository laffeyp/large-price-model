# Sprint 115 -- peak LR sweep + mixer retry at lower LR

---

```yaml
---
id: 115
status: closed
phase: H
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Sprint 114 showed weight decay doesn't fix the overfitting at step 2000. Best-checkpoint lands consistently at end-of-warmup; peak LR at 1e-4 kills training immediately after. Sprint 115 tests whether lower peak LR extends the descent, and finishes the mixer probe Sprint 113 owed but couldn't run.

**Probe A: peak LR sweep on sum-normalized md.** lr ∈ {5e-5, 3e-5, 1e-5}. Same warmup=2000, wd=0.1, seed=0, 20K steps. Best-checkpoint step and pooled val_nll characterize whether the transformer can descend past step 3000 under gentler dynamics.

**Probe B: mixer retry.** Sprint 113-D diverged at step 1688 with lr=1e-4 on normalized data. Retry at lr ∈ {3e-5, 1e-5}. Same warmup=2000, wd=0.1, seed=0, 20K steps.

## deliverables

- 3 lr runs (5e-5, 3e-5, 1e-5) at md-sum-normalized.
- 2 mixer runs (3e-5, 1e-5) at md-mixer-normalized.
- Per-run evaluate + register in logbook.
- Report at `artifacts/sprint115-report.md`.

## expected outcomes

- Peak LR: at least one lr extends best-checkpoint step past 3000 and reaches pooled val_nll below 3.19. If all three cliff at step 2000, the training-dynamics problem is deeper than LR.
- Mixer: at least one lr survives 20K steps. Comparison pooled val_nll to best sum-normalized run tells us if cross-channel attention adds anything.

## commands

```bash
# Probe A: peak LR sweep at md sum-normalized
for lr in 5e-5 3e-5 1e-5; do
  PSLM_SKIP_EC2_CHECK=1 uv run python scripts/train.py \
    --tokens-pt data/tokenized/tokens.latest.pt \
    --model-size md --n-steps 20000 --warmup-steps 2000 --lr $lr \
    --eval-every 1000 --keep-top-k 3 --device mps --seed 0 \
    --weight-decay 0.1 --fusion sum \
    --run-id-tag sprint115-lr \
    --logs-dir logs/sprint115-lr-$lr \
    --checkpoint-dir artifacts/checkpoints
done

# Probe B: mixer at lower LR
for lr in 3e-5 1e-5; do
  PSLM_SKIP_EC2_CHECK=1 uv run python scripts/train.py \
    --tokens-pt data/tokenized/tokens.latest.pt \
    --model-size md --n-steps 20000 --warmup-steps 2000 --lr $lr \
    --eval-every 1000 --keep-top-k 3 --device mps --seed 0 \
    --weight-decay 0.1 --fusion mixer \
    --run-id-tag sprint115-mixer \
    --logs-dir logs/sprint115-mixer-$lr \
    --checkpoint-dir artifacts/checkpoints
done
```

Total: 5 runs sequential, ~22 min each = ~2 hours.

## notes

- Sprint 116 depends on this sprint's verdict.
  - If lower LR fixes overfitting and mixer wins → Sprint 116 = full-size sweep on winning config.
  - If lower LR doesn't help → Sprint 116 = warmup-length sweep or dropout hooks.
  - If mixer beats sum meaningfully → Sprint 116 also runs multi-seed on mixer at winning LR.
