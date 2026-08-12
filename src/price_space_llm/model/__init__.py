"""Causal decoder transformer over 15-min market-state tokens.

Reads the tokens parquet (from Sprint 030), samples random windows of
`context_len` bucket_ids, feeds through a small transformer decoder,
predicts the next bucket_id via 32-way softmax. All-position CE loss
per tech-arch §9.

Model architecture per tech-arch §9 (Sprint 031 hardcodes; a future
v0.4 vocabulary lock adds n_layers/n_heads/d_model to CONFIG_RESOLVED
when a second architecture appears):
- d_model = 64
- n_layers = 4
- n_heads = 4
- context_len from config (default 128)
- vocab_size = n_buckets from config (default 32)
"""

from price_space_llm.model.dataset import WindowSampler, load_tokens
from price_space_llm.model.trainer import TrainerResult, run_training
from price_space_llm.model.transformer import PriceSpaceLLM, TransformerConfig

__all__ = [
    "PriceSpaceLLM",
    "TrainerResult",
    "TransformerConfig",
    "WindowSampler",
    "load_tokens",
    "run_training",
]
