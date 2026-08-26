# Sprint 087 -- PatchEmbedder (patch_size=4) end-to-end

---

```yaml
---
id: 087
status: closed
phase: E
pass_kind: architecture
determinism_budget: statistically-deterministic
---
```

## scope

Land the patch=4 ablation infrastructure per tech-arch § 10. Roadmap item 070. Third of the four Phase E ablation embedders (sum ← Sprint 053; mixer ← Sprint 083; patch=4 ← this sprint; quantile head ← Sprint 088). Same shape as the fusion sprint — a config knob picks the embedder; the trainer's target-alignment code adapts.

Spec text (tech-arch § 10):

> At the winning size × context configuration, compare `patch_size = 1` (default) against `patch_size = 4`. A patch of size 4 concatenates the four consecutive bars ending at position `t` into a single feature vector of length `Σ_c 4 · F_c`, projects the concatenation into one `d_model` state via a per-channel `nn.Linear(4 · F_c, d_model)` (or equivalent), and reduces sequence length by 4×. The target aligned with the resulting position is the bucket for the bar immediately following the last of the four packed bars.

## deliverables

- `PatchEmbedder(nn.Module)` in `src/price_space_llm/model/transformer.py`: per-channel `nn.Linear(patch_size * F_c, d_model)`. Forward reshape: `[B, T, F_c]` → `[B, T // patch_size, patch_size * F_c]` → per-channel linear → sum across channels → `[B, T // patch_size, d_model]`. Raises `ValueError` on `T % patch_size != 0`; raises on unexpected channel keys.
- `MarketStateTransformerConfig.patch_size: int = 1` (Literal {1, 4} accepted; 2 or others rejected via a Literal-enum-shape check at construction — matches spec's declared set).
- `MarketStateTransformer` picks embedder: `patch_size == 1` → uses existing `fusion` axis (sum or mixer); `patch_size > 1` → uses `PatchEmbedder` and ignores `fusion` (patching is orthogonal to per-timestep fusion — the packed vector already carries `patch_size * n_channels * F_c` features per output position). Position embedding sized to `context_len // patch_size`. Forward output shape `[B, T // patch_size, vocab_size]`.
- Trainer target alignment: new `_patch_targets(targets, patch_size)` helper — `targets[:, patch_size-1::patch_size]`. Applied in both `run_training_feats`'s training loss path and its `_compute_val_metrics_feats` path. Sprint 053 target semantics: `targets_sampled = artifact.targets[start+1 : start+1+context_len]`, so for patched position `p` the correct target is at slice index `(p+1)*patch_size - 1` = every `patch_size`-th target starting at `patch_size-1`.
- `scripts/train.py --patch-size {1,4}` flag (default 1); `-p4` run_id infix when `patch_size==4` (composes with `-{size}`, `-c{N}`, `-mix`).
- CONFIG_RESOLVED payload does NOT gain `patch_size` in this sprint; captured in the `## Named on card` follow-up for a v0.8 vocab bump alongside any other Phase E axes that need it. Recoverable via `run_id + git SHA` in the interim.

## tests (+5)

1. `test_patch_embedder_output_shape` — synthetic feats `[B=2, T=16, F_c=4]`, patch_size=4 → output `[2, 4, d_model]`.
2. `test_patch_embedder_rejects_non_divisible_context` — `T=15, patch_size=4` raises `ValueError` naming the divisibility constraint.
3. `test_patch_embedder_rejects_extra_channels` — matches other embedders' train-time-drift-is-loud discipline.
4. `test_market_state_transformer_patch4_output_shrunk` — build with `patch_size=4`, `context_len=64` → forward `[B=1, T=64]` produces `[1, 16, V]`; embedder instance is `PatchEmbedder`.
5. `test_train_cli_patch4_smoke_on_synthetic_pt` — end-to-end 2 CPU steps at `--patch-size 4 --model-size xs` on the Sprint 083 synthetic .pt (opts into `normalized=True`); expects exit 0, `-p4` infix in trace directory, `patch_size=4` in stderr shape line.

## context files

- `src/price_space_llm/model/transformer.py`
- `src/price_space_llm/model/trainer.py`
- `src/price_space_llm/model/__init__.py`
- `scripts/train.py`
- `tests/test_model.py`
- `tests/test_train_device.py`
- `specs/technical-architecture-v4.md` § 10

## artifact contract

Files created or modified:

- `src/price_space_llm/model/transformer.py` — modified: `PatchEmbedder` class; `MarketStateTransformerConfig.patch_size`; selector in `MarketStateTransformer.__init__`; position embedding sized to `context_len // patch_size`.
- `src/price_space_llm/model/trainer.py` — modified: `_patch_targets` helper; applied in the train + val paths.
- `src/price_space_llm/model/__init__.py` — modified: export `PatchEmbedder`.
- `scripts/train.py` — modified: `--patch-size {1,4}` flag; `-p4` run_id infix; config threading.
- `tests/test_model.py` — modified: +4 tests.
- `tests/test_train_device.py` — modified: +1 CLI smoke.

Content assertions:

- `grep -q "class PatchEmbedder" src/price_space_llm/model/transformer.py`
- `grep -q "\\-\\-patch-size" scripts/train.py`

## signal contract

Emits: none new. Full training tag surface fires on both patch=1 (existing) and patch=4 (new) runs. `CONFIG_RESOLVED` payload does not yet carry `patch_size`; a v0.8 vocab bump consolidates this + any other Phase E axes into `CONFIG_RESOLVED` when the next vocab-bump sprint opens.

## observation contract

REQUIRED — new model architecture; downstream training produces a different weight shape and shrunk sequence.

- **Input:** synthetic .pt with `normalized=True`.
- **Expected:** exit 0; stderr `patch_size=4` shape line; trace directory carries `-p4` infix; full training tag surface fires.
- **Expected behavior:** training-side loss reads targets sliced to patch positions (`targets[:, 3::4]` for patch=4).

## commands

```
uv run ruff check .
uv run mypy
uv run pytest -q
```

## notes

- 4 code files + 2 test files. Same shape as Sprint 083's ablation-infrastructure scope class. Under the vocab-bump-scope precedent for "one algorithmic-variant per sprint" the multi-file count is accepted.
- Patching is orthogonal to `fusion={sum,mixer}`; picking `patch_size=4` overrides the fusion axis and uses `PatchEmbedder`. Named on the card so the sweep script (Sprint 084+) does not attempt patch=4 × mixer combinations.
- Named on card: v0.8 vocab bump adds `patch_size` (and any other Phase E axis not yet in `CONFIG_RESOLVED`) as required payload; Sprint 089 or 090 candidate.
