# Sprint 084 -- v0.7 vocab bump + normalized-input contract

---

```yaml
---
id: 084
status: closed
phase: E
pass_kind: architecture
determinism_budget: bit-deterministic
---
```

## scope

Drain three drift-watchlist entries in one bump: the Sprint 073 `CONFIG_RESOLVED`-lacks-model-shape gap, the Sprint 083 `CONFIG_RESOLVED`-lacks-fusion gap, and the Sprint 083 mixer-diverges-on-un-normalized-features gap.

## deliverables

- `signals/0.7.json` (copy of 0.6 + six new required fields on `CONFIG_RESOLVED` + one on `TOKENIZED_ARTIFACT_WRITTEN` + version bump + Layer-9 update).
- `signals/0.7-rationale.md` (delta + migration + grammar-growth record).
- `src/price_space_llm/_vocab/0.7.json` (symlink).
- `load_vocabulary` default 0.6 → 0.7.
- `load_config(..., d_model, n_layers, n_heads, fusion, mixer_dim, mixer_n_heads)` populates the six new emit fields.
- `scripts/train.py` threads the resolved model + fusion axes into `load_config`.
- `run_tokenizer_pt` stamps `meta["normalized"] = (normalizer is not None)` on the payload; passes the value into `TOKENIZED_ARTIFACT_WRITTEN`.
- `UnnormalizedArtifactRefused` in `src/price_space_llm/model/trainer.py`; `run_training_feats` raises it when `model_cfg.fusion == "mixer"` and `artifact.meta.get("normalized", False) is False`.
- `scripts/train.py` catches the raise and exits 3 with a clear stderr message.
- Test fixture in `tests/test_train_device.py::_write_synthetic_tokens_pt` opts into `normalized=True` (the small-scale synthetic stands in for a real normalizer-applied .pt).
- `tests/test_signals.py::test_locked_vocabulary_loads_all_tags` version pointer bumped.

## tests +5

- `test_load_config_config_resolved_carries_model_architecture` — defaults populate the six new fields.
- `test_load_config_config_resolved_reflects_overrides` — kwargs land in the emit.
- `test_run_tokenizer_pt_stamps_normalized_false_without_normalizer` — un-normalized write → `meta['normalized']=False` + emit carries the same.
- `test_run_training_feats_refuses_unnormalized_on_mixer` — mixer refuses.
- `test_run_training_feats_permits_sum_on_unnormalized_artifact` — sum path unaffected.

## observation contract

Live smoke: regenerated the 2015-2022 training .pt through v0.7; `TOKENIZED_ARTIFACT_WRITTEN` fires with `"normalized": false`. `train.py --fusion mixer` on the same .pt exits 3 with the refusal message. `train.py --fusion sum` on the same .pt exits 0 unchanged. `CONFIG_RESOLVED` payload now includes `d_model=128 n_layers=4 n_heads=2 fusion=sum` on a real training run.
