# Sprint 111 -- linear baseline per-regime diagnostic

---

```yaml
---
id: 111
status: closed
phase: H
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Sprint 110's pooled val_nll showed the 25M-param transformer losing to a 64-token linear baseline (3.40 vs 3.33). Per-regime metrics reversed the story: transformer wins big on low-vol, essentially chance on high-vol. Sprint 111 asks the natural next question: **does linear also lose all its edge on high-vol, or does linear beat the transformer everywhere?** If the transformer beats linear on low-vol, the pooled gate is wrong for this data.

## deliverables

- `scripts/analysis/linear_per_regime.py` -- new. Trains a `LinearBaseline(64×32→32)` on the training partition of the 2015-2022 tokens parquet, predicts on val, splits val by the same regime thresholds Sprint 110's eval used (`low<0.000849, mid<0.001535`), reports per-regime val_nll + top-1 + dir-acc. Uses `experiments/logbook.csv` conventions for output.
- `artifacts/sprint111-linear-per-regime.json` -- new. Structured result: `{regime: {nll, top1, dir_acc, n_examples}}` for linear and per size for transformer (from Sprint 110's eval jsons).
- `artifacts/sprint111-comparison-report.md` -- new. Head-to-head table: linear vs xs/sm/md/lg on each regime, per metric.

## observation contract

Three possible outcomes and their meaning:

1. **Transformer beats linear on low-vol; linear beats transformer on mid/high-vol.** Pooled gate is wrong for this data. Sprint 112's longer training probe still worth it, but the winning strategy may be regime-conditional. File a spec-review amendment proposal to gate on low-vol regime.
2. **Linear beats transformer on every regime, pooled and per-regime.** Sprint 112's longer training probe is the correct next move. The pooled failure is real; the transformer just needs more training.
3. **Transformer beats linear on every regime, pooled and per-regime, but the low-vol edge dominates.** Unlikely given the pooled numbers, but if true, indicates a bug in the eval pooling. Investigate.

## tests (+0)

The diagnostic script is one-off analysis. No pytest additions.

## commands

```bash
uv run python scripts/analysis/linear_per_regime.py \
    --tokens data/tokenized/tokenize-features-align-2015-01-2022-12-0000000000000000-0000000000000000-0000000000000000.parquet \
    --features data/features/features-align-2015-01-2022-12-0000000000000000-0000000000000000.parquet \
    --training-start 2015-01-01 --training-end 2022-12-31 \
    --output artifacts/sprint111-linear-per-regime.json
```

Wall-clock: fit + eval on 60K rows at context_len=64: probably 5-10 minutes on MPS.

## notes

- The linear baseline's `fit_linear` from `src/price_space_llm/baselines.py` is called directly. Only the val-split code needs new plumbing to bin by regime.
- Use `torch.use_deterministic_algorithms(True, warn_only=True)` + `seed=0` so the number is reproducible.
- No changes to `src/price_space_llm/` proper; the analysis lives under `scripts/analysis/`.
- After Sprint 111 closes, Sprint 112 opens the longer-training probe at md.
