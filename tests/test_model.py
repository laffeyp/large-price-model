"""Tests for the transformer model + window sampler."""

from pathlib import Path

import polars as pl
import pytest
import torch

from price_space_llm.model.dataset import (
    TokenizedArtifact,
    WindowBatchFeats,
    WindowSampler,
    WindowSamplerFeats,
    load_tokens,
    load_tokens_pt,
    split_tokens,
)
from price_space_llm.model.transformer import (
    MarketStateEmbedder,
    MarketStateTransformer,
    MarketStateTransformerConfig,
    PriceSpaceLLM,
    TransformerConfig,
)

# Transformer -------------------------------------------------------------


def _cfg(context_len: int = 16, vocab_size: int = 32) -> TransformerConfig:
    return TransformerConfig(
        vocab_size=vocab_size,
        context_len=context_len,
        d_model=16,
        n_layers=2,
        n_heads=2,
        dropout=0.0,
    )


def test_forward_shape_matches_input():
    model = PriceSpaceLLM(_cfg(context_len=8, vocab_size=32))
    tokens = torch.randint(0, 32, (4, 8))
    logits = model(tokens)
    assert logits.shape == (4, 8, 32)


def test_forward_rejects_length_greater_than_context_len():
    model = PriceSpaceLLM(_cfg(context_len=8))
    with pytest.raises(ValueError, match="exceeds context_len"):
        model(torch.randint(0, 32, (2, 16)))


def test_causal_mask_prevents_look_ahead():
    """Output at position t must not change when tokens at positions > t change.

    Freeze model to eval and disable dropout; toggle a downstream token; assert
    logits at earlier positions are identical.
    """
    torch.manual_seed(0)
    model = PriceSpaceLLM(_cfg(context_len=8, vocab_size=8))
    model.eval()

    base = torch.tensor([[1, 2, 3, 4, 5, 6, 7, 0]])
    perturbed = base.clone()
    perturbed[0, -1] = 7  # change ONLY the last token

    with torch.no_grad():
        logits_base = model(base)
        logits_pert = model(perturbed)

    # Positions 0..6 must be identical -- they cannot see position 7.
    for pos in range(7):
        assert torch.allclose(logits_base[0, pos], logits_pert[0, pos], atol=1e-6), (
            f"look-ahead leakage at position {pos}"
        )
    # Position 7 CAN differ (it sees itself).
    assert not torch.allclose(logits_base[0, 7], logits_pert[0, 7], atol=1e-6)


def test_num_parameters_scales_with_layers():
    small = PriceSpaceLLM(
        TransformerConfig(vocab_size=32, context_len=16, d_model=16, n_layers=1, n_heads=2)
    )
    large = PriceSpaceLLM(
        TransformerConfig(vocab_size=32, context_len=16, d_model=16, n_layers=4, n_heads=2)
    )
    assert large.num_parameters() > small.num_parameters()


# WindowSampler -----------------------------------------------------------


def _synthetic_tokens(n: int) -> list[int]:
    return [i % 32 for i in range(n)]


def test_sampler_batch_shape_matches_batch_size_and_context_len():
    tokens = _synthetic_tokens(200)
    g = torch.Generator()
    g.manual_seed(0)
    sampler = WindowSampler(tokens, context_len=32, batch_size=4, generator=g)
    batch = sampler.sample()
    assert batch.inputs.shape == (4, 32)
    assert batch.targets.shape == (4, 32)


def test_sampler_target_is_input_shifted_by_one():
    tokens = _synthetic_tokens(100)
    g = torch.Generator()
    g.manual_seed(0)
    sampler = WindowSampler(tokens, context_len=8, batch_size=2, generator=g)
    batch = sampler.sample()
    # targets[:, i] == inputs[:, i+1] for i in 0..T-2; verify the shift.
    assert torch.equal(batch.targets[:, :-1], batch.inputs[:, 1:])


def test_sampler_rejects_too_few_tokens():
    with pytest.raises(ValueError, match="need at least"):
        WindowSampler(
            _synthetic_tokens(10), context_len=32, batch_size=2, generator=torch.Generator()
        )


def test_sampler_is_deterministic_with_seed():
    tokens = _synthetic_tokens(200)
    g1 = torch.Generator()
    g1.manual_seed(42)
    g2 = torch.Generator()
    g2.manual_seed(42)
    s1 = WindowSampler(tokens, context_len=16, batch_size=4, generator=g1)
    s2 = WindowSampler(tokens, context_len=16, batch_size=4, generator=g2)
    assert s1.peek_starts() == s2.peek_starts()


def test_split_tokens_contiguous():
    tokens = list(range(100))
    train, val = split_tokens(tokens, train_frac=0.8)
    assert train == list(range(80))
    assert val == list(range(80, 100))


def test_split_tokens_rejects_out_of_range_frac():
    with pytest.raises(ValueError, match="train_frac"):
        split_tokens([1, 2, 3], train_frac=0.0)
    with pytest.raises(ValueError, match="train_frac"):
        split_tokens([1, 2, 3], train_frac=1.0)


# load_tokens -------------------------------------------------------------


def test_load_tokens_drops_nulls(tmp_path: Path):
    df = pl.DataFrame({"target__SPY__bucket_id": [1, None, 2, 3]})
    path = tmp_path / "tokens.parquet"
    df.write_parquet(path)
    tokens = load_tokens(path, "SPY")
    assert tokens == [1, 2, 3]


def test_load_tokens_raises_on_missing_column(tmp_path: Path):
    df = pl.DataFrame({"other__col": [1]})
    path = tmp_path / "tokens.parquet"
    df.write_parquet(path)
    with pytest.raises(ValueError, match="no column"):
        load_tokens(path, "SPY")


# load_tokens_pt (Sprint 052) --------------------------------------------


def _write_pt(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "tokens.pt"
    torch.save(payload, p)
    return p


def _sample_payload(n_rows: int = 8) -> dict:
    return {
        "features": {
            "target__SPY": torch.zeros((n_rows, 4), dtype=torch.float32),
            "market_context__QQQ": torch.zeros((n_rows, 3), dtype=torch.float32),
        },
        "targets": torch.tensor([0, 1, 2, 3, -100, 5, 6, 7], dtype=torch.int64),
        "vol": torch.zeros(n_rows, dtype=torch.float32),
        "timestamps": torch.arange(n_rows, dtype=torch.int64),
        "is_overnight_gap": None,
        "mask": torch.ones(n_rows, dtype=torch.bool),
        "channel_names": ("market_context__QQQ", "target__SPY"),
        "meta": {"run_id": "test", "target_symbol": "SPY"},
    }


def test_load_tokens_pt_roundtrip(tmp_path: Path):
    """Sprint 052: written .pt round-trips through load_tokens_pt to TokenizedArtifact."""
    path = _write_pt(tmp_path, _sample_payload(n_rows=8))
    artifact = load_tokens_pt(path)
    assert isinstance(artifact, TokenizedArtifact)
    assert set(artifact.features.keys()) == {"target__SPY", "market_context__QQQ"}
    assert artifact.targets.shape == (8,)
    assert artifact.mask.dtype == torch.bool
    assert artifact.is_overnight_gap is None
    assert artifact.channel_names == ("market_context__QQQ", "target__SPY")
    assert artifact.meta["run_id"] == "test"


def test_load_tokens_pt_raises_on_missing_field(tmp_path: Path):
    """Sprint 052: reader validates every required field."""
    payload = _sample_payload(n_rows=4)
    del payload["mask"]
    path = _write_pt(tmp_path, payload)
    with pytest.raises(ValueError, match="missing required field 'mask'"):
        load_tokens_pt(path)


def test_load_tokens_pt_preserves_feature_shapes(tmp_path: Path):
    """Per-channel tensor shapes survive the write/read round-trip."""
    payload = _sample_payload(n_rows=8)
    payload["features"]["target__SPY"] = torch.arange(8 * 4, dtype=torch.float32).reshape(8, 4)
    path = _write_pt(tmp_path, payload)
    artifact = load_tokens_pt(path)
    assert artifact.features["target__SPY"].shape == (8, 4)
    assert float(artifact.features["target__SPY"][3, 2]) == 3 * 4 + 2


# MarketStateEmbedder (Sprint 053) ----------------------------------------


def test_market_state_embedder_output_shape():
    """MarketStateEmbedder(feats) returns Tensor[B, T, d_model]."""
    emb = MarketStateEmbedder({"target__SPY": 10, "market_context__VIX": 4}, d_model=64)
    feats = {
        "target__SPY": torch.randn(2, 8, 10),
        "market_context__VIX": torch.randn(2, 8, 4),
    }
    out = emb(feats)
    assert out.shape == (2, 8, 64)


def test_market_state_embedder_sum_equals_concat_projection():
    """Sum invariance: Σ_c W_c x_c equals a concat-then-project on the same data."""
    torch.manual_seed(0)
    channel_dims = {"a": 3, "b": 5}
    d_model = 4
    emb = MarketStateEmbedder(channel_dims, d_model=d_model)
    # Build a matching W_concat from the module's per-channel weights.
    w_a = emb.projections["a"].weight  # (4, 3)
    b_a = emb.projections["a"].bias  # (4,)
    w_b = emb.projections["b"].weight
    b_b = emb.projections["b"].bias
    x_a = torch.randn(1, 2, 3)
    x_b = torch.randn(1, 2, 5)
    sum_form = emb({"a": x_a, "b": x_b})
    # Manual: W_a x_a + W_b x_b + (b_a + b_b)
    manual = x_a @ w_a.T + x_b @ w_b.T + b_a + b_b
    assert torch.allclose(sum_form, manual, atol=1e-6)


def test_market_state_embedder_rejects_unknown_channel():
    emb = MarketStateEmbedder({"a": 3}, d_model=4)
    with pytest.raises(ValueError, match="unexpected channels"):
        emb({"a": torch.randn(1, 2, 3), "b": torch.randn(1, 2, 5)})


def test_market_state_transformer_forward_shape():
    """MarketStateTransformer(feats) returns Tensor[B, T, vocab_size]."""
    cfg = MarketStateTransformerConfig(
        vocab_size=32,
        context_len=64,
        channel_dims={"target__SPY": 10, "market_context__VIX": 4},
        d_model=64,
    )
    model = MarketStateTransformer(cfg)
    feats = {
        "target__SPY": torch.randn(2, 16, 10),
        "market_context__VIX": torch.randn(2, 16, 4),
    }
    logits = model(feats)
    assert logits.shape == (2, 16, 32)


# WindowSamplerFeats (Sprint 053) -----------------------------------------


def _sample_artifact(n_rows: int = 200) -> TokenizedArtifact:
    return TokenizedArtifact(
        features={
            "target__SPY": torch.arange(n_rows * 4, dtype=torch.float32).reshape(n_rows, 4),
            "market_context__VIX": torch.randn(n_rows, 3),
        },
        targets=torch.randint(0, 32, (n_rows,), dtype=torch.int64),
        vol=torch.zeros(n_rows, dtype=torch.float32),
        timestamps=torch.arange(n_rows, dtype=torch.int64),
        is_overnight_gap=None,
        mask=torch.ones(n_rows, dtype=torch.bool),
        channel_names=("market_context__VIX", "target__SPY"),
        meta={"run_id": "test"},
    )


def test_window_sampler_feats_batch_shapes():
    """Each per-channel tensor has shape [B, T, F_c]; targets is [B, T]."""
    artifact = _sample_artifact(n_rows=200)
    gen = torch.Generator()
    gen.manual_seed(0)
    sampler = WindowSamplerFeats(artifact, context_len=16, batch_size=4, generator=gen)
    batch = sampler.sample()
    assert isinstance(batch, WindowBatchFeats)
    assert batch.feats["target__SPY"].shape == (4, 16, 4)
    assert batch.feats["market_context__VIX"].shape == (4, 16, 3)
    assert batch.targets.shape == (4, 16)


def test_window_sampler_feats_target_is_shifted_by_one():
    """Sprint 053: targets are artifact.targets[start+1 : start+1+context_len].
    Reconstruct one window from a fixed start and check the shift."""
    artifact = _sample_artifact(n_rows=200)
    gen = torch.Generator()
    gen.manual_seed(0)
    sampler = WindowSamplerFeats(artifact, context_len=8, batch_size=1, generator=gen)
    batch = sampler.sample()
    start = batch.starts[0]
    expected_targets = artifact.targets[start + 1 : start + 1 + 8]
    assert torch.equal(batch.targets[0], expected_targets)


def test_window_sampler_feats_rejects_mismatched_lengths():
    """A channel with a different row count than the first channel raises."""
    features: dict[str, torch.Tensor] = {
        "a": torch.zeros((100, 4), dtype=torch.float32),
        "b": torch.zeros((99, 4), dtype=torch.float32),
    }
    artifact = TokenizedArtifact(
        features=features,
        targets=torch.zeros(100, dtype=torch.int64),
        vol=torch.zeros(100, dtype=torch.float32),
        timestamps=torch.zeros(100, dtype=torch.int64),
        is_overnight_gap=None,
        mask=torch.zeros(100, dtype=torch.bool),
        channel_names=("a", "b"),
        meta={},
    )
    with pytest.raises(ValueError, match=r"length 99 != 100"):
        WindowSamplerFeats(artifact, context_len=8, batch_size=1, generator=torch.Generator())


def test_run_training_feats_completes_two_step_smoke(tmp_path: Path):
    """Sprint 053: run_training_feats runs two steps against a synthetic
    artifact and returns a valid TrainerResult."""
    from price_space_llm.model import run_training_feats
    from price_space_llm.model.trainer import TrainerConfig
    from price_space_llm.signals import StrictSignalEmitter, load_vocabulary

    artifact = _sample_artifact(n_rows=500)
    cfg = MarketStateTransformerConfig(
        vocab_size=32,
        context_len=64,
        channel_dims={"target__SPY": 4, "market_context__VIX": 3},
        d_model=64,
    )
    trainer_cfg = TrainerConfig(n_steps=2, batch_size=2, lr=1e-3, eval_every=2, seed=0)
    emitter = StrictSignalEmitter(load_vocabulary(), max_buffer=16384)
    result = run_training_feats(
        artifact=artifact,
        trainer_cfg=trainer_cfg,
        model_cfg=cfg,
        emitter=emitter,
        run_id="test-feats-smoke",
        checkpoint_dir=tmp_path / "ckpts",
    )
    assert result.final_step == 2
    assert result.n_parameters > 0
