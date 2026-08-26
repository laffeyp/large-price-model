# Sprint 110 -- model-size sweep on M5 Max via MPS (roadmap 084)

---

```yaml
---
id: 110
status: closed
phase: H
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Four training runs at xs/sm/md/lg, `--device mps`, real training budget (10K steps, 2K warmup, cosine to 10% peak, weight_decay=0.1, seed=0, eval_every=500). Emit the full training tag surface for every run. Report the val_nll curve at every size + the checkpoint tree. Roadmap 084.

The sprint answers one question: how does val_nll scale with parameter count on this corpus + this feature set? The answer feeds Sprint 111's context-length sweep at the winning size.

## deliverables

- Four training runs launched sequentially:
  - `xs` (d_model=128, n_layers=4, n_heads=2, ~819K params)
  - `sm` (d_model=192, n_layers=6, n_heads=3, ~2.7M params)
  - `md` (d_model=384, n_layers=8, n_heads=6, ~14.3M params)
  - `lg` (d_model=512, n_layers=8, n_heads=8, ~25.3M params)
- Each run: `10_000` steps, `warmup=2_000`, `eval_every=500`, `seed=0`, `--device mps`, no bf16 (MPS autocast support for bf16 is not the point of this sprint; fp32 is fine and reproducible), `keep_top_k=3`.
- Per-run trace at `logs/sprint110-sweep-{size}/train-.../signals.jsonl`. Per-run checkpoints at `artifacts/checkpoints/train-.../*.pt`.
- Per-run entry in `experiments/logbook.csv` via `scripts/register_run.py`.

## tests (+0 net)

The training path is well-covered by existing tests. Zero new test additions — the sprint's output is data, not code.

## artifact contract

Files produced (transient, not committed):

- `logs/sprint110-sweep-xs/train-.../signals.jsonl` and one per size.
- `artifacts/checkpoints/train-tokens.latest-...-*.pt` for each size × step.
- `artifacts/sprint110-sweep-report.md` -- summary of the four runs' val_nll curves.
- `experiments/logbook.csv` -- four appended rows.

Content assertions:

- Each trace's tail line reports `EPOCH_COMPLETED` or equivalent close-of-run marker.
- Each run's final `val_nll < log(V) = log(32) ≈ 3.466` (must beat uniform prior).
- Val_nll monotonically-non-increasing across the four sizes (bigger = better, roughly, though noise possible at xs).

## signal contract

Every existing training tag fires per run: `SESSION_INIT`, `CONFIG_RESOLVED`, `WINDOW_SAMPLED` × 10000, `TRAINING_STEP_COMPLETED` × 10000, `CHECKPOINT_WRITTEN` × 20 (10000/500), `EPOCH_COMPLETED`, `SESSION_COMPLETE`. Zero new tags.

## observation contract

- Wall-clock estimate: xs ~7 min, sm ~9 min, md ~12 min, lg ~14 min. Total ~45 min sequential.
- Determinism check: seed=0 across all four runs; re-running any one should reproduce val_nll bit-identically (per Sprint 109's cross-device determinism finding).
- Final val_nll ordering (expected): lg < md < sm ≤ xs. If xs beats sm, that indicates one of: underfitting on the bigger model in 10K steps, or the wrong hyperparameter for that size.

## commands

```bash
for size in xs sm md lg; do
    PSLM_SKIP_EC2_CHECK=1 uv run python scripts/train.py \
        --tokens-pt data/tokenized/tokens.latest.pt \
        --model-size $size \
        --n-steps 10000 \
        --warmup-steps 2000 \
        --eval-every 500 \
        --keep-top-k 3 \
        --device mps \
        --seed 0 \
        --logs-dir logs/sprint110-sweep-$size \
        --checkpoint-dir artifacts/checkpoints
done
```

## notes

- MPS at 10K steps: forget bf16. `--device mps` with default fp32 is fine.
- If any run diverges (TRAINING_DIVERGED emit), that's a real signal, not a rerun candidate.
- Sprint 111 opens next: context-length sweep at the winning size.
