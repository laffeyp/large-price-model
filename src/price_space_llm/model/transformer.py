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
    """

    vocab_size: int
    context_len: int
    channel_dims: dict[str, int]  # {channel__symbol: F_c}
    d_model: int = 64
    n_layers: int = 4
    n_heads: int = 4
    dropout: float = 0.1


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
        self.embedder = MarketStateEmbedder(config.channel_dims, config.d_model)
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
            enable_nested_tensor=False,
        )
        self.ln_final = nn.LayerNorm(config.d_model)
        self.lm_head = nn.Linear(config.d_model, config.vocab_size, bias=False)

    def forward(self, feats: dict[str, Tensor]) -> Tensor:
        state = self.embedder(feats)  # (B, T, D)
        _b, t, _d = state.shape
        if t > self.config.context_len:
            raise ValueError(f"input length {t} exceeds context_len {self.config.context_len}")
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
