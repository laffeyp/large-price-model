# Sprint 112 -- md longer-training probe vs stronger-regularization probe

---

```yaml
---
id: 112
status: closed
phase: H
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Sprint 111 established: linear beats md transformer on every regime. Two live hypotheses:

- **H1 (under-training).** 20K steps at lr=1e-4 isn't enough for 14M params to distill the auto-regressive bucket-ID signal linear captures at 200 steps.
- **H2 (overfitting on cross-channel noise).** 14M params on 43K training rows with 20 mostly-sparse feature channels over-parameterizes the target's simple auto-regressive structure. Cross-channel memorization then generalizes worse.

Sprint 112 fires one run for each hypothesis, side by side, and reads the result.

## deliverables

- **md-longtrain**: `--model-size md --n-steps 100000 --warmup-steps 2000 --lr 1e-4 --eval-every 2500 --weight-decay 0.1 --keep-top-k 3 --device mps --seed 0`. Tests H1. Wall-clock estimate: 22 min at 20K → ~110 min at 100K.
- **md-regularized**: `--model-size md --n-steps 20000 --warmup-steps 2000 --lr 1e-4 --eval-every 1000 --weight-decay 0.5 --keep-top-k 3 --device mps --seed 0`. Tests H2. Wall-clock ~22 min (same as Sprint 110 v3 md).
- Post-hoc `scripts/evaluate.py` on each winning checkpoint against 2015-2022 val, then per-regime comparison vs linear.
- `artifacts/sprint112-h1-vs-h2-report.md` -- diagnosis + recommendation for Sprint 113.
- Two rows appended to `experiments/logbook.csv` via `scripts/register_from_trace.py`.

## observation contract

Three possible outcomes:

1. **H1 confirmed.** md-longtrain closes the linear-pooled gap (pooled val_nll ≤ linear's 3.333); md-regularized doesn't. Sprint 113 = longer training on every size; the 20K-step Sprint 110 was under-trained.
2. **H2 confirmed.** md-regularized closes the gap; md-longtrain doesn't. Sprint 113 = regularization sweep, or the target-only ablation to test whether cross-channel is actively harmful.
3. **Neither closes the gap.** Deeper investigation needed. Candidates: target-only ablation (feed only target channel, zero everything else), or feature audit (are cross-asset/macro/options/event channels adding predictive signal at 15-min or just noise?).

Also possible: **both close it partially.** Then next sprint combines both.

## tests (+0)

Analysis sprint; no new test additions.

## commands

```bash
# H1: longer training
PSLM_SKIP_EC2_CHECK=1 uv run python scripts/train.py \
    --tokens-pt data/tokenized/tokens.latest.pt \
    --model-size md --n-steps 100000 --warmup-steps 2000 --lr 1e-4 \
    --eval-every 2500 --keep-top-k 3 --device mps --seed 0 \
    --weight-decay 0.1 \
    --logs-dir logs/sprint112-md-longtrain \
    --checkpoint-dir artifacts/checkpoints

# H2: stronger regularization
PSLM_SKIP_EC2_CHECK=1 uv run python scripts/train.py \
    --tokens-pt data/tokenized/tokens.latest.pt \
    --model-size md --n-steps 20000 --warmup-steps 2000 --lr 1e-4 \
    --eval-every 1000 --keep-top-k 3 --device mps --seed 0 \
    --weight-decay 0.5 \
    --logs-dir logs/sprint112-md-regularized \
    --checkpoint-dir artifacts/checkpoints
```

Total wall-clock: ~135 min sequential (110 for longtrain + 22 for regularized + 3 for evals).

## notes

- Both runs use seed=0 for cross-run comparability.
- Sprint 110's md at 20K steps hit best val_nll 3.30 at step 12000 then oscillated to 3.28-3.41 for the remaining 8K. If H1 is right, 100K should push meaningfully below 3.30. If H2 is right, longtrain will over-fit worse and val_nll will climb.
- Weight decay 0.5 is 5× the current default 0.1. Aggressive but defensible for testing H2. Stronger dropout is another lever if this doesn't help; the current model has no dropout hooks so weight decay is the primary regularization knob.
- Every run auto-registered via `scripts/register_from_trace.py`.
