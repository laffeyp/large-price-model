"""Small causal decoder transformer over bucket_id tokens.

Tech-arch §9: `d_model=64`, `n_layers=4`, `n_heads=4`. Causal mask makes
the attention at position t see only positions 0..t; look-ahead
leakage impossible by construction (mirrors the alignment invariant
from Sprint 025 at the model layer).

Sprint 031 hardcodes the architecture. When a second architecture
appears, a v0.4 vocabulary lock adds `n_layers`, `n_heads`, `d_model`
to `CONFIG_RESOLVED.typed_payload` and the model shape becomes
reproducible from the trace alone. Filed to drift-watchlist.
"""

from dataclasses import dataclass

import torch
from torch import Tensor, nn


@dataclass(slots=True, frozen=True, kw_only=True)
class TransformerConfig:
    vocab_size: int
    context_len: int
    d_model: int = 64
    n_layers: int = 4
    n_heads: int = 4
    dropout: float = 0.1


class PriceSpaceLLM(nn.Module):
    """Causal decoder with token + position embeddings + N transformer blocks + LM head."""

    def __init__(self, config: TransformerConfig) -> None:
        super().__init__()
        self.config = config
        self.token_embedding = nn.Embedding(config.vocab_size, config.d_model)
        self.position_embedding = nn.Embedding(config.context_len, config.d_model)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=config.d_model,
            nhead=config.n_heads,
            dim_feedforward=config.d_model * 4,
            dropout=config.dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.blocks = nn.TransformerEncoder(
            encoder_layer,
            num_layers=config.n_layers,
            # enable_nested_tensor + norm_first=True is a no-op path in torch; opt out silently.
            enable_nested_tensor=False,
        )
        self.ln_final = nn.LayerNorm(config.d_model)
        self.lm_head = nn.Linear(config.d_model, config.vocab_size, bias=False)

    def forward(self, tokens: Tensor) -> Tensor:
        """tokens: (B, T) int64 in [0, vocab_size). Returns logits (B, T, vocab_size)."""
        _b, t = tokens.shape
        if t > self.config.context_len:
            raise ValueError(f"input length {t} exceeds context_len {self.config.context_len}")
        positions = torch.arange(t, device=tokens.device)
        tok_emb = self.token_embedding(tokens)  # (B, T, D)
        pos_emb = self.position_embedding(positions)  # (T, D)
        x = tok_emb + pos_emb.unsqueeze(0)  # (B, T, D)

        # Causal mask: shape (T, T), True at positions to be masked out.
        # nn.TransformerEncoder attends over the full sequence unless we mask.
        mask = torch.triu(
            torch.ones(t, t, dtype=torch.bool, device=tokens.device),
            diagonal=1,
        )
        x = self.blocks(x, mask=mask, is_causal=True)
        x = self.ln_final(x)
        logits: Tensor = self.lm_head(x)  # (B, T, vocab_size)
        return logits

    def num_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters())


# Sprint 053: multi-channel market-state path per tech-arch § 7.2 ----------


@dataclass(slots=True, frozen=True, kw_only=True)
class MarketStateTransformerConfig:
    """Config for the market-state model. Same trunk hyperparameters as the
    bucket-ID `TransformerConfig`, plus `channel_dims` frozen at construction
    so config_hash sufficiency holds (see sprint card notes).

    Sprint 083: `fusion` selects the embedder — `"sum"` (default, Sprint 053
    linear sum) or `"mixer"` (cross-channel attention per tech-arch § 10).
    `mixer_dim` and `mixer_n_heads` shape the mixer only; ignored when
    `fusion == "sum"`.
    """

    vocab_size: int
    context_len: int
    channel_dims: dict[str, int]  # {channel__symbol: F_c}
    d_model: int = 64
    n_layers: int = 4
    n_heads: int = 4
    dropout: float = 0.1
    fusion: str = "sum"  # Literal["sum", "mixer"] — enforced at construction
    mixer_dim: int = 96
    mixer_n_heads: int = 2
    # Sprint 087: patch_size ∈ {1, 4} per tech-arch § 10. `4` overrides fusion
    # and swaps in `PatchEmbedder`; `1` uses the fusion axis unchanged.
    patch_size: int = 1
    # Sprint 089: head_type ∈ {"categorical", "quantile"} per tech-arch § 10.
    # Quantile head consumes float raw_targets + pinball loss; categorical
    # (default) consumes bucket-ID targets + cross-entropy.
    head_type: str = "categorical"


class MarketStateEmbedder(nn.Module):
    """Per-channel `nn.Linear(F_c, d_model)` summed into one `d_model` vector per bar.

    Tech-arch § 7.2. Sum invariance vs concat: `Σ_c W_c x_c = W_concat [x_1; ...; x_n]`;
    both forms carry identical parameter count and produce identical outputs. Summation
    is used here so per-channel projections stay separate `nn.Linear` modules — a
    target-only ablation can zero one channel's weights without touching batch layout.
    """

    def __init__(self, channel_dims: dict[str, int], d_model: int) -> None:
        super().__init__()
        if not channel_dims:
            raise ValueError("MarketStateEmbedder requires at least one channel")
        self._channel_dims = dict(channel_dims)
        self._d_model = d_model
        self.projections = nn.ModuleDict(
            {key: nn.Linear(f_c, d_model) for key, f_c in channel_dims.items()}
        )

    @property
    def channel_dims(self) -> dict[str, int]:
        return dict(self._channel_dims)

    def forward(self, feats: dict[str, Tensor]) -> Tensor:
        """Sum per-channel `Linear(F_c, d_model)` projections into `Tensor[B, T, d_model]`.

        Every key in `feats` must appear in `self._channel_dims`. Missing channels
        raise `KeyError`. Extra channels raise `ValueError` so a train-time channel
        set drift is loud, not silent.
        """
        extra = set(feats.keys()) - set(self._channel_dims.keys())
        if extra:
            raise ValueError(f"MarketStateEmbedder got unexpected channels: {sorted(extra)}")
        first_key = next(iter(self._channel_dims.keys()))
        first_x = feats[first_key]
        b, t, _ = first_x.shape
        out = torch.zeros(b, t, self._d_model, device=first_x.device, dtype=first_x.dtype)
        for key in self._channel_dims:
            proj = self.projections[key]
            out = out + proj(feats[key])
        return out


class ChannelMixerEmbedder(nn.Module):
    """Sprint 083: cross-channel attention fusion per tech-arch § 10.

    Same interface as `MarketStateEmbedder` — `dict[str, Tensor[B, T, F_c]]
    → Tensor[B, T, d_model]` — so `MarketStateTransformer` can swap embedders
    via a config knob.

    Per-channel `nn.Linear(F_c, mixer_dim)` projects each channel; the stacked
    per-channel embeddings feed one `nn.MultiheadAttention` block across the
    channel axis at each timestep (no mask — channels have no order); a
    mean-pool across channels reduces to `[B, T, mixer_dim]`; a final linear
    lifts to `d_model`. Byte-for-byte on the load-bearing lines per the
    tech-arch code sketch. Time causality is preserved by the outer temporal
    transformer; the mixer is deliberately bidirectional across channels.
    """

    def __init__(
        self,
        channel_dims: dict[str, int],
        d_model: int,
        mixer_dim: int = 96,
        n_heads: int = 2,
    ) -> None:
        super().__init__()
        if not channel_dims:
            raise ValueError("ChannelMixerEmbedder requires at least one channel")
        self._channel_dims = dict(channel_dims)
        self._d_model = d_model
        self._mixer_dim = mixer_dim
        self.channel_order: list[str] = list(channel_dims.keys())
        self.projections = nn.ModuleDict(
            {name: nn.Linear(dim, mixer_dim) for name, dim in channel_dims.items()}
        )
        self.attn = nn.MultiheadAttention(mixer_dim, n_heads, batch_first=True)
        self.out = nn.Linear(mixer_dim, d_model)

    @property
    def channel_dims(self) -> dict[str, int]:
        return dict(self._channel_dims)

    def forward(self, feats: dict[str, Tensor]) -> Tensor:
        extra = set(feats.keys()) - set(self._channel_dims.keys())
        if extra:
            raise ValueError(f"ChannelMixerEmbedder got unexpected channels: {sorted(extra)}")
        # Per-channel projection: list of [B, T, mixer_dim].
        per_ch = [self.projections[name](feats[name]) for name in self.channel_order]
        # Stack along a new "channel" axis: [B, T, n_channels, mixer_dim].
        stacked = torch.stack(per_ch, dim=2)
        b, t, c, d = stacked.shape
        # One attention pass across channels at each timestep.
        x = stacked.reshape(b * t, c, d)
        mixed, _ = self.attn(x, x, x, need_weights=False)
        mixed = mixed.reshape(b, t, c, d)
        # Reduce to one state per timestep — mean pool across channels.
        state = mixed.mean(dim=2)  # [B, T, mixer_dim]
        out: Tensor = self.out(state)  # [B, T, d_model]
        return out


# Sprint 089: quantile head (roadmap 071).
N_QUANTILES = 9
QUANTILE_LEVELS: tuple[float, ...] = tuple(round(0.1 * i, 1) for i in range(1, 10))


class PatchEmbedder(nn.Module):
    """Sprint 087: patch-fusion embedder per tech-arch § 10.

    Packs `patch_size` consecutive bars per channel into a single feature
    vector of length `patch_size * F_c`, projects per-channel via
    `nn.Linear(patch_size * F_c, d_model)`, and sums across channels — same
    output-side interface as `MarketStateEmbedder` (Sprint 053) except the
    sequence length shrinks by `patch_size`.

    Input:  `feats: dict[str, Tensor[B, T, F_c]]` with `T % patch_size == 0`.
    Output: `Tensor[B, T // patch_size, d_model]`.

    Target alignment (handled by the trainer, not this module): for patched
    position `p`, the target is the bar immediately after the last packed
    bar — i.e., `targets[start + (p+1) * patch_size]`.
    """

    def __init__(
        self,
        channel_dims: dict[str, int],
        d_model: int,
        patch_size: int,
    ) -> None:
        super().__init__()
        if not channel_dims:
            raise ValueError("PatchEmbedder requires at least one channel")
        if patch_size < 1:
            raise ValueError(f"patch_size must be positive; got {patch_size}")
        self._channel_dims = dict(channel_dims)
        self._d_model = d_model
        self._patch_size = patch_size
        self.projections = nn.ModuleDict(
            {
                key: nn.Linear(patch_size * f_c, d_model)
                for key, f_c in channel_dims.items()
            }
        )

    @property
    def channel_dims(self) -> dict[str, int]:
        return dict(self._channel_dims)

    @property
    def patch_size(self) -> int:
        return self._patch_size

    def forward(self, feats: dict[str, Tensor]) -> Tensor:
        extra = set(feats.keys()) - set(self._channel_dims.keys())
        if extra:
            raise ValueError(f"PatchEmbedder got unexpected channels: {sorted(extra)}")
        first_key = next(iter(self._channel_dims.keys()))
        first_x = feats[first_key]
        b, t, _ = first_x.shape
        if t % self._patch_size != 0:
            raise ValueError(
                f"PatchEmbedder requires T divisible by patch_size={self._patch_size}; "
                f"got T={t}"
            )
        t_patched = t // self._patch_size
        out = torch.zeros(
            b, t_patched, self._d_model, device=first_x.device, dtype=first_x.dtype
        )
        for key in self._channel_dims:
            x = feats[key]  # [B, T, F_c]
            f_c = x.shape[2]
            # Pack `patch_size` consecutive bars into one vector: [B, T//p, p*F_c].
            packed = x.reshape(b, t_patched, self._patch_size * f_c)
            out = out + self.projections[key](packed)
        return out


class MarketStateTransformer(nn.Module):
    """Causal decoder over per-bar market-state vectors from a MarketStateEmbedder.

    Sprint 053. Consumes `feats: dict[str, Tensor[B, T, F_c]]` produced by
    `WindowSamplerFeats` reading a Sprint 052 `.pt` artifact. Output shape matches
    the bucket-ID `PriceSpaceLLM.forward`: `Tensor[B, T, vocab_size]` — so loss and
    metrics code paths downstream reuse cleanly.
    """

    def __init__(self, config: MarketStateTransformerConfig) -> None:
        super().__init__()
        self.config = config
        # Sprint 087: patch_size ∈ {1, 4}. patch_size > 1 → PatchEmbedder
        # (overrides fusion; patching is orthogonal to per-timestep fusion).
        # patch_size == 1 → fusion axis picks between sum (Sprint 053) and
        # mixer (Sprint 083).
        if config.patch_size not in (1, 4):
            raise ValueError(
                f"MarketStateTransformerConfig.patch_size must be 1 or 4; "
                f"got {config.patch_size!r}"
            )
        if config.context_len % config.patch_size != 0:
            raise ValueError(
                f"MarketStateTransformerConfig.context_len={config.context_len} "
                f"must be divisible by patch_size={config.patch_size}"
            )
        embedder: nn.Module
        if config.patch_size > 1:
            embedder = PatchEmbedder(
                config.channel_dims, config.d_model, patch_size=config.patch_size
            )
        elif config.fusion == "sum":
            embedder = MarketStateEmbedder(config.channel_dims, config.d_model)
        elif config.fusion == "mixer":
            embedder = ChannelMixerEmbedder(
                config.channel_dims,
                config.d_model,
                mixer_dim=config.mixer_dim,
                n_heads=config.mixer_n_heads,
            )
        else:
            raise ValueError(
                f"MarketStateTransformerConfig.fusion must be 'sum' or 'mixer'; "
                f"got {config.fusion!r}"
            )
        self.embedder = embedder
        # Sprint 087: position embedding sized to the shrunk sequence length.
        # patch_size=1 preserves Sprint 053 behavior.
        self.position_embedding = nn.Embedding(
            config.context_len // config.patch_size, config.d_model
        )
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=config.d_model,
            nhead=config.n_heads,
            dim_feedforward=config.d_model * 4,
            dropout=config.dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.blocks = nn.TransformerEncoder(
            encoder_layer,
            num_layers=config.n_layers,
            enable_nested_tensor=False,
        )
        self.ln_final = nn.LayerNorm(config.d_model)
        # Sprint 089: head selection. Categorical → vocab_size logits + CE.
        # Quantile → N_QUANTILES=9 quantile predictions + pinball loss.
        if config.head_type == "categorical":
            self.lm_head = nn.Linear(config.d_model, config.vocab_size, bias=False)
        elif config.head_type == "quantile":
            self.lm_head = nn.Linear(config.d_model, N_QUANTILES, bias=False)
        else:
            raise ValueError(
                f"MarketStateTransformerConfig.head_type must be 'categorical' or "
                f"'quantile'; got {config.head_type!r}"
            )

    def forward(self, feats: dict[str, Tensor]) -> Tensor:
        state = self.embedder(feats)  # (B, T', D) where T' = T // patch_size
        _b, t, _d = state.shape
        max_positions = self.config.context_len // self.config.patch_size
        if t > max_positions:
            raise ValueError(
                f"post-embedder length {t} exceeds context_len // patch_size = {max_positions}"
            )
        positions = torch.arange(t, device=state.device)
        pos_emb = self.position_embedding(positions)  # (T, D)
        x = state + pos_emb.unsqueeze(0)  # (B, T, D)
        mask = torch.triu(
            torch.ones(t, t, dtype=torch.bool, device=state.device),
            diagonal=1,
        )
        x = self.blocks(x, mask=mask, is_causal=True)
        x = self.ln_final(x)
        logits: Tensor = self.lm_head(x)
        return logits

    def num_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters())
