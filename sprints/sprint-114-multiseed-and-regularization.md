# Sprint 114 -- multi-seed sprint113-C + regularization sweep

---

```yaml
---
id: 114
status: closed
phase: H
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Two probes on md-sum-normalized. Both cheap. Both settle open questions from Sprint 113.

**Probe A: multi-seed.** Sprint 113-C was one seed. Rerun the identical config at seeds 1-4 (seed 0 already done). Get mean, stdev of pooled val_nll across 5 seeds. Determines whether the +2.8% margin over linear is real or seed noise.

**Probe B: regularization sweep.** Sprint 113-C hit best val_nll at step 2000 (end of warmup) then overfit catastrophically. Try wd ∈ {0.5, 1.0, 5.0} to stretch the descent past step 2000. If any wd lets the model train stably to step 20K, the true val_nll may go below 3.1976.

Config for both: md, n_steps=20000, warmup=2000, lr=1e-4, batch=8, eval_every=1000, keep_top_k=3, --device mps, sum fusion, normalized artifact. Distinct run_ids via automatic hp fingerprint (Sprint 113b).

## deliverables

- 4 seed runs (seeds 1-4; seed 0 already done as sprint113-C).
- 3 wd runs (wd=0.5, 1.0, 5.0 at seed 0).
- Per-run evaluate against 2015-2022 val + register in logbook.
- Report at `artifacts/sprint114-report.md` with multi-seed noise floor + wd effect.

## expected outcomes

- Multi-seed: pooled val_nll mean somewhere near 3.20, stdev < 0.02. If stdev is > 0.05, +2.8% margin is noise and we need to widen the seed budget.
- Reg sweep: at least one wd extends best-checkpoint step beyond 2000. Best pooled val_nll below 3.20. If none: overfitting isn't fixed by weight decay alone; need dropout or shorter training with LR decay tuning.

## commands

```bash
# Multi-seed (4 runs)
for seed in 1 2 3 4; do
  PSLM_SKIP_EC2_CHECK=1 uv run python scripts/train.py \
    --tokens-pt data/tokenized/tokens.latest.pt \
    --model-size md --n-steps 20000 --warmup-steps 2000 --lr 1e-4 \
    --eval-every 1000 --keep-top-k 3 --device mps --seed $seed \
    --weight-decay 0.1 --fusion sum \
    --run-id-tag sprint114-seed \
    --logs-dir logs/sprint114-seed-$seed \
    --checkpoint-dir artifacts/checkpoints
done

# Regularization sweep (3 runs)
for wd in 0.5 1.0 5.0; do
  PSLM_SKIP_EC2_CHECK=1 uv run python scripts/train.py \
    --tokens-pt data/tokenized/tokens.latest.pt \
    --model-size md --n-steps 20000 --warmup-steps 2000 --lr 1e-4 \
    --eval-every 1000 --keep-top-k 3 --device mps --seed 0 \
    --weight-decay $wd --fusion sum \
    --run-id-tag sprint114-wd \
    --logs-dir logs/sprint114-wd-$wd \
    --checkpoint-dir artifacts/checkpoints
done
```

Total: 7 runs sequential, ~22 min each = ~2.5 hours.

## notes

- Sprint 115 depends on this sprint's verdict. If multi-seed confirms +2.8% and wd sweep finds a stable regime, Sprint 115 = mixer at lower LR + full-size sweep on the winning wd.
- If multi-seed reveals big variance, Sprint 115 = wider seed budget + investigation.
- If wd sweep doesn't fix overfitting, Sprint 115 = dropout hooks in the model.
