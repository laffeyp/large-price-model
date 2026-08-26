# Sprint 116 -- multi-seed mixer lr=3e-5

---

```yaml
---
id: 116
status: closed
phase: H
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Sprint 115 hit +4.26% below linear at md-mixer-lr-3e-5 on seed 0. Sprint 113's +2.77% seed-0 headline turned out to be near the top of a 5-seed distribution centered at +1.87%. Sprint 116 tests whether Sprint 115's +4.26% is real or seed-lucky.

## deliverables

- 4 mixer runs at seeds 1-4, identical config to sprint115-mixer-3e-5.
- Per-run evaluate + register in logbook.
- Report `artifacts/sprint116-report.md` with 5-seed mean, stdev, per-regime picture.

## config

Identical to sprint115-mixer-3e-5: md, fusion=mixer, mixer_dim=96, mixer_n_heads=2, n_steps=20000, warmup=2000, lr=3e-5, wd=0.1, batch=8, eval_every=1000, --device mps.

## commands

```bash
for seed in 1 2 3 4; do
  PSLM_SKIP_EC2_CHECK=1 uv run python scripts/train.py \
    --tokens-pt data/tokenized/tokens.latest.pt \
    --model-size md --n-steps 20000 --warmup-steps 2000 --lr 3e-5 \
    --eval-every 1000 --keep-top-k 3 --device mps --seed $seed \
    --weight-decay 0.1 --fusion mixer \
    --run-id-tag sprint116-mixer-seed \
    --logs-dir logs/sprint116-mixer-seed-$seed \
    --checkpoint-dir artifacts/checkpoints
done
```

Wall-clock: 4 × ~27 min = ~2 hours.

## expected outcomes

- Mean pooled val_nll across 5 seeds (0+1+2+3+4) somewhere in [3.14, 3.22].
- Stdev < 0.04 (tighter than sum's 0.056 would be a nice bonus).
- 5-seed mean margin vs linear ≥ +2% (i.e., not seed-lucky).

If mean ≥ +2%, Sprint 117 opens: longer training on mixer-3e-5 (50K steps + peak-LR-scheduled) or full-size sweep on mixer.
If mean < +2%, mixer isn't reliably better than sum; retreat to sum + investigate whether the fusion gain is worth the complexity.

## notes

- Every checkpoint carries `fusion=mixer` in its config now (Sprint 115 fix). No backfill needed for these.
- Wall-clock estimate assumes MPS behaves; mixer runs have been ~1600s vs ~1200s for sum.
