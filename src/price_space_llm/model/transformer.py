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
