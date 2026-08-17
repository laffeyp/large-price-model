# Sprint 061 -- zero_non_target_features (target-only channel ablation helper)

---

```yaml
---
id: 061
status: closed
phase: 3
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Closes review § 3 HIGH item: *"TargetOnlyBaseline is a marginal-frequency predictor. Spec requires the same transformer architecture with non-target channels zeroed at the embedder."*

`zero_non_target_features(artifact, target_symbol)` returns a new `TokenizedArtifact` with every non-target channel's feature tensor replaced by `torch.zeros_like`. Sprint 086's baseline ladder feeds the zeroed artifact through the same `run_training_feats` + `MarketStateTransformer` path used for the primary run. Comparing the two val_nlls answers the spec's multi-channel-lift question directly.

## deliverables

- `zero_non_target_features` in `model/dataset.py` next to `_split_artifact` (both are TokenizedArtifact transforms).
- Exported from `model/__init__.py`.
- Tests: target unchanged; non-target zeroed with shape preserved; missing-target guard; composes cleanly with `run_training_feats`.

## honest audit

- **Old `TargetOnlyBaseline` (marginal-frequency) stays.** Not the spec's gate baseline. Sprint 061 does not delete it — it stays as a sanity check for the parquet-tokens path.
- **No new fit function required.** The zeroed artifact drops through `run_training_feats` unchanged. Sprint 086 will call `run_training_feats(zero_non_target_features(artifact, "SPY"), ...)` and compare val_nlls.

Tests +3. Count 388 → 391. Ruff + mypy + pytest green.
