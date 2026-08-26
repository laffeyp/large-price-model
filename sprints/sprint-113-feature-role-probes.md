# Sprint 113 -- feature-role probes: target-only + mixer-fusion

---

```yaml
---
id: 113
status: closed
phase: H
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Sprint 112 confirmed under-training was part of the linear-vs-transformer gap but the true story is more nuanced. Sprint 113 asks the harder question: **are the 20 non-target channels adding predictive value, or is the model failing to use them?**

Two probes side by side.

## probes

**A: target-only.** Same architecture as md-longtrain (14.3M params, sum fusion). Non-target channels zeroed via `zero_non_target_features` before training. Transformer sees only `target__SPY` features. Answers: **does the sum-fusion transformer use the multi-channel input at all?** If target-only ≈ full-channel, the answer is no.

**B: mixer-fusion.** Same features as md-longtrain but `ChannelMixerEmbedder` (Sprint 083) instead of sum. Cross-channel attention lets the model reweight channels per bar. Answers: **does a better fusion extract signal the sum drowns?** If mixer > sum, features carry signal but the current model misused them.

Both at md, `n_steps=20000`, `lr=1e-4`, `warmup=2000`, `wd=0.1`, `seed=0`, `--device mps`. Same schedule as Sprint 110 v3 md (stable, no divergence). 20K keeps each run ~22 min; both together ~45 min.

Distinct `--run-id-tag` values (`target-only` and `mixer-fusion`) prevent Sprint 112-style checkpoint collisions.

## observation contract

Four outcome regions:

| target-only vs full | mixer vs full | interpretation |
|---|---|---|
| ≈ | ≈ | Channels genuinely add no usable signal; go 1-min (Sprint 114). |
| < | ≈ | Non-target channels help under sum fusion but the sum doesn't extract more with a better fusion. Sub-hypothesis: the target dominates; cross-channel adds a marginal amount that mixer can't further exploit. |
| ≈ | > | Sum was drowning weak channels; features carry signal but need mixer fusion. Real win. |
| < | > | Both stories partly true; features carry signal, sum extracts some, mixer extracts more. |
| > | any | Non-target channels are actively harmful. Curate features aggressively. |

## deliverables

- Two training runs (target-only, mixer-fusion) via existing scripts.
- Two evaluate.py runs for pooled + per-regime val metrics.
- Two logbook rows via `register_from_trace.py`.
- One report at `artifacts/sprint113-feature-role-report.md` comparing both probes vs Sprint 112 md-longtrain (full sum) and vs linear@800.
- Experiment ledger updated with both runs.

## tests (+0)

Analysis sprint. `--target-only` + `--run-id-tag` code changes covered by existing `test_train_device.py` invocations that exercise the same code path; no dedicated new tests required for a one-flag pass-through.

## commands

```bash
# Probe A: target-only, seed=0
PSLM_SKIP_EC2_CHECK=1 uv run python scripts/train.py \
    --tokens-pt data/tokenized/tokens.latest.pt \
    --model-size md --n-steps 20000 --warmup-steps 2000 --lr 1e-4 \
    --eval-every 1000 --keep-top-k 3 --device mps --seed 0 \
    --weight-decay 0.1 \
    --target-only --run-id-tag target-only \
    --logs-dir logs/sprint113-target-only \
    --checkpoint-dir artifacts/checkpoints

# Probe B: mixer fusion, seed=0
PSLM_SKIP_EC2_CHECK=1 uv run python scripts/train.py \
    --tokens-pt data/tokenized/tokens.latest.pt \
    --model-size md --n-steps 20000 --warmup-steps 2000 --lr 1e-4 \
    --eval-every 1000 --keep-top-k 3 --device mps --seed 0 \
    --weight-decay 0.1 \
    --fusion mixer --run-id-tag mixer-fusion \
    --logs-dir logs/sprint113-mixer-fusion \
    --checkpoint-dir artifacts/checkpoints
```

Total wall-clock: ~50 min sequential.

## notes

- Sprint 112 tech-debt now paid: `--run-id-tag` prevents collisions.
- 20K steps is enough to compare against Sprint 110 v3 md's 20K number (3.406 pooled). No need for longtrain here; the question is about fusion+features, not schedule.
- Sprint 114 depends on this sprint's verdict. If features are genuinely useless at 15-min, Sprint 114 opens the 1-min corpus probe. If mixer wins, Sprint 114 runs mixer-longtrain.
