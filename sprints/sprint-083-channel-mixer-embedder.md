# Sprint 083 -- ChannelMixerEmbedder (cross-channel attention fusion)

---

```yaml
---
id: 083
status: closed
phase: E
pass_kind: architecture
determinism_budget: statistically-deterministic
---
```

## scope

Land the channel-aware fusion embedder per tech-arch § 10 code sketch. Sibling to `MarketStateEmbedder` (Sprint 053 linear-sum fusion). Roadmap item 069. Same interface — `dict[str, Tensor[B, T, F_c]] -> Tensor[B, T, d_model]` — so `MarketStateTransformer` can swap embedders via a config knob. Sprint 087 architecture-ablation sweep runs both against each other on the GPU; Sprint 083 lands the machinery.

Spec text (tech-arch § 10):

> The mixer produces one embedding per channel per timestep from the same `W_c` projections, runs one causal-attention block with `d_model = 64–128` and 1 layer across the `n_channels` embeddings at each timestep, then reduces to a single `state_t` (either the target channel's output or a pooled output) which feeds into the same temporal transformer. Parameter counts are matched to linear fusion by adjusting the mixer's hidden width.

## deliverables

- `ChannelMixerEmbedder(nn.Module)` in `src/price_space_llm/model/transformer.py` matching the tech-arch code sketch byte-for-byte on the load-bearing lines: per-channel `nn.Linear(F_c, mixer_dim)`, `nn.MultiheadAttention(mixer_dim, n_heads, batch_first=True)`, mean-pool across channels, `nn.Linear(mixer_dim, d_model)`. Deterministic channel iteration via `self.channel_order` frozen at construction.
- `MarketStateTransformerConfig` gains `fusion: Literal["sum", "mixer"] = "sum"` + `mixer_dim: int = 96` + `mixer_n_heads: int = 2`. Default `"sum"` preserves Sprint 053-078 checkpoints and every existing test smoke.
- `MarketStateTransformer.__init__` picks embedder by `cfg.fusion`.
- `scripts/train.py` gains `--fusion {sum,mixer}` (default `sum`), `--mixer-dim N`, `--mixer-n-heads N`. When `--fusion mixer` present, `run_id` picks up a `-mix` suffix so per-fusion checkpoints and traces do not collide.

## tests (+5)

1. `test_channel_mixer_embedder_output_shape` — synthetic `feats` dict; output tensor is `[B, T, d_model]`.
2. `test_channel_mixer_embedder_rejects_extra_channels` — extra key in feats raises `ValueError`, matching `MarketStateEmbedder`'s train-time-drift-is-loud discipline.
3. `test_channel_mixer_embedder_deterministic_with_seed` — two forward passes on the same input under the same seed produce byte-identical outputs.
4. `test_market_state_transformer_fusion_mixer_uses_channel_mixer` — build with `fusion="mixer"`; `type(model.embedder) is ChannelMixerEmbedder`.
5. `test_train_cli_mixer_smoke_on_pt_artifact` — end-to-end 2 CPU steps at `--fusion mixer --model-size xs` against the real 2015-2022 training .pt (`tokens.latest.pt`); expects exit 0, stderr shape line names the mixer, trace directory carries `-mix` infix. Skips if .pt absent.

## context files

- `src/price_space_llm/model/transformer.py`
- `src/price_space_llm/model/__init__.py`
- `scripts/train.py`
- `tests/test_model.py`
- `tests/test_train_device.py`
- `specs/technical-architecture-v4.md` § 10

## artifact contract

Files created or modified:

- `src/price_space_llm/model/transformer.py` — modified: `ChannelMixerEmbedder` class + `MarketStateTransformerConfig.fusion / mixer_dim / mixer_n_heads` + embedder selection in `MarketStateTransformer.__init__`.
- `src/price_space_llm/model/__init__.py` — modified: exports `ChannelMixerEmbedder`.
- `scripts/train.py` — modified: `--fusion` + `--mixer-dim` + `--mixer-n-heads`; `-mix` run_id suffix; kwargs threaded through.
- `tests/test_model.py` — modified: +4 tests.
- `tests/test_train_device.py` — modified: +1 CLI smoke.

Content assertions:

- `grep -q "class ChannelMixerEmbedder" src/price_space_llm/model/transformer.py`
- `grep -q "\\-\\-fusion" scripts/train.py`

## signal contract

Emits: none new. The two fusion paths share every existing training tag (SESSION_INIT, CONFIG_RESOLVED, WINDOW_SAMPLED, TRAINING_STEP_COMPLETED, CHECKPOINT_WRITTEN, EPOCH_COMPLETED, SESSION_COMPLETE, TOKENIZED_ARTIFACT_WRITTEN from v0.6). `CONFIG_RESOLVED.typed_payload` in v0.6 does not carry a `fusion` field; the fusion is recoverable from `run_id` (`-mix` infix present ⇒ mixer) + git SHA. A v0.7 vocab bump adding `fusion` + `mixer_dim` + `mixer_n_heads` to `CONFIG_RESOLVED` is a candidate follow-up; deferred per hard rule 6 (vocab bump is its own concept). Filed to drift-watchlist alongside the v0.6 candidate for `d_model / n_layers / n_heads`.

## observation contract

REQUIRED — new model architecture; downstream training produces a different weight shape.

- **Input:** `uv run python scripts/train.py --tokens-pt data/tokenized/tokens.latest.pt --fusion mixer --model-size xs --n-steps 2 --eval-every 2 --seed 41 --device cpu --warmup-steps 0`.
- **Expected artifact:** one checkpoint at `artifacts/checkpoints/…-mix-…-step2.pt`; one trace file with `-mix-` in the directory name.
- **Expected behavior:** full training tag surface fires; final_train_loss stays finite; param count larger than the sum-fusion baseline (mixer adds attention weights + output projection).
- **Expected trace:** SESSION_INIT → CONFIG_RESOLVED → 2×WINDOW_SAMPLED → 2×TRAINING_STEP_COMPLETED → CHECKPOINT_WRITTEN → EPOCH_COMPLETED → SESSION_COMPLETE.

## commands

```
uv run ruff check .
uv run mypy
uv run pytest -q
uv run python scripts/train.py --tokens-pt data/tokenized/tokens.latest.pt --fusion sum --model-size xs --n-steps 2 --eval-every 2 --seed 41 --device cpu --warmup-steps 0 --checkpoint-dir /tmp/ckpt-083-sum --logs-dir /tmp/logs-083-sum
uv run python scripts/train.py --tokens-pt data/tokenized/tokens.latest.pt --fusion mixer --model-size xs --n-steps 2 --eval-every 2 --seed 41 --device cpu --warmup-steps 0 --checkpoint-dir /tmp/ckpt-083-mix --logs-dir /tmp/logs-083-mix
```

## notes

- 3 code files (`model/transformer.py`, `model/__init__.py`, `scripts/train.py`) + 2 test files. Under hard rule 6.
- Backward compatibility: default `fusion="sum"` preserves Sprint 053-078 semantics. Every existing test smoke passes without touching the new flags.
- Follow-ups named on card: (a) v0.7 vocab bump exposing `fusion / mixer_dim / mixer_n_heads` on `CONFIG_RESOLVED` (drift-watchlist candidate); (b) parameter-count matching between sum and mixer fusions per spec's "matched to linear fusion" — Sprint 087 architecture-ablation runner tunes `mixer_dim` per size to match; not this sprint.
- Reduction is mean-pool per spec's second alternative ("or a pooled output"). Target-channel alternative deferred; mean-pool is what the spec's code sketch shows.
