# Sprint 089 -- quantile head + pinball loss (roadmap 071)

---

```yaml
---
id: 089
status: closed
phase: E
pass_kind: architecture
determinism_budget: statistically-deterministic
---
```

## scope

Fourth of the four Phase E ablation embedders per tech-arch § 10. Categorical 32-bucket head (default) versus nine-quantile head trained with pinball loss. Backbone identical. Roadmap item 071. Sprint 088 landed the `raw_targets` foundation.

## deliverables

- `N_QUANTILES = 9` + `QUANTILE_LEVELS = (0.1, 0.2, …, 0.9)` module constants in `src/price_space_llm/model/transformer.py`.
- `MarketStateTransformerConfig.head_type: str = "categorical"` (Literal {"categorical", "quantile"}; unknown raises at construction).
- `MarketStateTransformer`: `lm_head` = `nn.Linear(d_model, vocab_size)` for categorical (existing); `nn.Linear(d_model, N_QUANTILES)` for quantile. Forward output shape `[B, T', vocab_size]` or `[B, T', N_QUANTILES]`.
- `pinball_loss(preds, targets_float, quantile_levels)` helper in `src/price_space_llm/model/trainer.py`. Standard formula: `L_q(t, p) = max(q*(t - p), (q - 1)*(t - p))`. Skips NaN targets (`targets != targets` mask).
- `QuantileHeadRequiresRawTargets(RuntimeError)` in `model/trainer.py`; `run_training_feats` raises when `model_cfg.head_type == "quantile"` and `artifact.raw_targets is None`. Fail-loud shape matches Sprint 084's `UnnormalizedArtifactRefused`.
- `WindowSamplerFeats` in `model/dataset.py` returns `raw_targets` alongside `targets` when `artifact.raw_targets` is present. Existing categorical callers ignore the new field.
- `run_training_feats` train + val loss path branches on `head_type`; quantile branch consumes `_patch_targets(batch.raw_targets, patch_size)` and computes `pinball_loss`; val emits pinball into `val_nll` slot with the other six val_* fields set to 0.0 (named on card as an honest gap; quantile-specific val metrics are Sprint 088-follow-up territory).
- `scripts/train.py --head-type {categorical,quantile}` flag + `-qh` run_id infix.

## tests (+6)

1. `test_pinball_loss_zero_on_perfect_prediction` — targets equal predictions for every quantile → loss 0.
2. `test_pinball_loss_symmetric_at_median` — quantile 0.5 with prediction below/above target by the same delta → equal loss.
3. `test_pinball_loss_ignores_nan_targets` — NaN targets skip the term.
4. `test_market_state_transformer_quantile_head_output_shape` — `head_type="quantile"` → forward output `[B, T', 9]`.
5. `test_market_state_transformer_rejects_unknown_head_type` — `head_type="unknown"` raises at construction.
6. `test_run_training_feats_refuses_quantile_without_raw_targets` — artifact with `raw_targets=None` + `head_type="quantile"` raises `QuantileHeadRequiresRawTargets`.

Plus one CLI smoke (`test_train_cli_quantile_head_smoke_on_synthetic_pt`) that requires synthetic fixture updates to stamp `raw_targets` on the .pt fixture; land in same test file.

## context files

- `src/price_space_llm/model/transformer.py`
- `src/price_space_llm/model/trainer.py`
- `src/price_space_llm/model/dataset.py`
- `src/price_space_llm/model/__init__.py`
- `scripts/train.py`
- `tests/test_model.py`
- `tests/test_train_device.py`
- `specs/technical-architecture-v4.md` § 10

## observation contract

REQUIRED — quantile head produces a different output shape and consumes a different target field.

- **Input:** synthetic .pt with `raw_targets` stamped + `normalized=True`.
- **Expected:** exit 0; stderr `head_type=quantile`; `-qh` in trace directory; full training tag surface fires.
- **Expected behavior:** train and val loss paths use `pinball_loss` on raw float targets; `CHECKPOINT_WRITTEN` payload carries a `val_nll` = pinball value; other val_* fields = 0.0.

## commands

```
uv run ruff check .
uv run mypy
uv run pytest -q
```

## notes

- 5 code files + 2 test files. Over hard rule 6's ≤2 code ceiling; matches Sprint 087 (patch) shape at scope-class-ablation-infrastructure. Named as one concept: "quantile head end-to-end."
- CONFIG_RESOLVED payload does NOT gain `head_type` this sprint; v0.8 vocab bump absorbs `head_type` + `patch_size` together in a later sprint. Recoverable via `run_id` + git SHA in the interim.
- Val metrics gap: quantile head's `CHECKPOINT_WRITTEN` payload sets the six categorical val_* fields to 0.0. Named on card; the downstream evaluator (Sprint 090+ candidate) reads `checkpoint_kind` and skips categorical metrics for quantile checkpoints.
- Follow-up: mask-aware evaluator + quantile-specific metrics (calibration by quantile crossing rate, mean absolute deviation per quantile) — Sprint 090+ candidate.
