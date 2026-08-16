"""Tests for the training loop -- emit surface, divergence policy, checkpoint writes."""

from pathlib import Path

import pytest
import torch

from price_space_llm.model.trainer import (
    TrainerConfig,
    TrainingDiverged,
    run_training,
)
from price_space_llm.model.transformer import TransformerConfig
from price_space_llm.signals import StrictSignalEmitter, load_vocabulary


def _fresh_emitter(max_buffer: int = 16384) -> StrictSignalEmitter:
    return StrictSignalEmitter(load_vocabulary(), max_buffer=max_buffer)


def _synthetic_tokens(n: int = 800, vocab_size: int = 32) -> list[int]:
    return [i % vocab_size for i in range(n)]


def _small_model_cfg(vocab_size: int = 32, context_len: int = 64) -> TransformerConfig:
    return TransformerConfig(
        vocab_size=vocab_size,
        context_len=context_len,
        d_model=16,
        n_layers=2,
        n_heads=2,
        dropout=0.0,
    )


def _small_trainer_cfg(n_steps: int = 6, eval_every: int = 3) -> TrainerConfig:
    return TrainerConfig(
        n_steps=n_steps,
        batch_size=4,
        lr=1e-3,
        eval_every=eval_every,
        seed=0,
    )


def test_run_training_emits_expected_tag_sequence(tmp_path: Path):
    e = _fresh_emitter()
    result = run_training(
        tokens=_synthetic_tokens(800),
        trainer_cfg=_small_trainer_cfg(n_steps=6, eval_every=3),
        model_cfg=_small_model_cfg(),
        emitter=e,
        run_id="test-train",
        checkpoint_dir=tmp_path / "ckpt",
    )
    tags = [s.tag for s in e.snapshot()]
    assert tags.count("WINDOW_SAMPLED") == 6
    assert tags.count("TRAINING_STEP_COMPLETED") == 6
    # eval_every=3 with n_steps=6 → 2 checkpoints.
    assert tags.count("CHECKPOINT_WRITTEN") == 2
    assert tags.count("EPOCH_COMPLETED") == 1
    assert result.n_checkpoints == 2
    assert result.final_step == 6


def test_run_training_writes_checkpoint_files(tmp_path: Path):
    e = _fresh_emitter()
    result = run_training(
        tokens=_synthetic_tokens(800),
        trainer_cfg=_small_trainer_cfg(n_steps=4, eval_every=2),
        model_cfg=_small_model_cfg(),
        emitter=e,
        run_id="test-ckpt",
        checkpoint_dir=tmp_path / "ckpt",
    )
    # Exclude the `-latest.pt` symlink from Sprint 036 versioning.
    ckpts = sorted(p for p in (tmp_path / "ckpt").glob("*.pt") if not p.name.endswith("-latest.pt"))
    assert len(ckpts) == 2
    assert result.checkpoint_dir == str(tmp_path / "ckpt")


def test_checkpoint_payload_carries_all_six_val_metrics(tmp_path: Path):
    e = _fresh_emitter()
    run_training(
        tokens=_synthetic_tokens(800),
        trainer_cfg=_small_trainer_cfg(n_steps=3, eval_every=3),
        model_cfg=_small_model_cfg(),
        emitter=e,
        run_id="test-metrics",
        checkpoint_dir=tmp_path / "ckpt",
    )
    ckpt = next(s for s in e.snapshot() if s.tag == "CHECKPOINT_WRITTEN")
    for field in [
        "val_nll",
        "val_ece",
        "val_brier",
        "val_rps",
        "val_dir_acc",
        "val_top1",
        "val_top3",
    ]:
        assert field in ckpt.payload
        assert isinstance(ckpt.payload[field], float)


def test_run_training_emits_diverged_and_raises_on_nan_loss(tmp_path: Path, monkeypatch):
    """Force NaN by monkeypatching cross_entropy; trainer must emit + raise."""
    from price_space_llm.model import trainer as trainer_mod

    # Monkeypatch cross_entropy to return NaN once, then behave normally.
    calls = {"n": 0}
    real_ce = trainer_mod.F.cross_entropy

    def fake_ce(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return trainer_mod.torch.tensor(float("nan"), requires_grad=True)
        return real_ce(*args, **kwargs)

    monkeypatch.setattr(trainer_mod.F, "cross_entropy", fake_ce)

    e = _fresh_emitter()
    with pytest.raises(TrainingDiverged, match="NaN"):
        run_training(
            tokens=_synthetic_tokens(800),
            trainer_cfg=_small_trainer_cfg(n_steps=2, eval_every=1),
            model_cfg=_small_model_cfg(),
            emitter=e,
            run_id="test-nan",
            checkpoint_dir=tmp_path / "ckpt",
        )
    diverged = next(s for s in e.snapshot() if s.tag == "TRAINING_DIVERGED")
    assert diverged.payload["reason"] == "nan_loss"


def test_window_sampled_start_position_is_a_real_start(tmp_path: Path):
    """Sprint 041 §4.1: WINDOW_SAMPLED.start_position carries a real token-stream index
    (the first-batch entry's start), not the training step number.
    """
    e = _fresh_emitter()
    tokens = _synthetic_tokens(800)
    run_training(
        tokens=tokens,
        trainer_cfg=_small_trainer_cfg(n_steps=5, eval_every=10),
        model_cfg=_small_model_cfg(),
        emitter=e,
        run_id="test-start",
        checkpoint_dir=tmp_path / "ckpt",
    )
    windows = [s for s in e.snapshot() if s.tag == "WINDOW_SAMPLED"]
    assert len(windows) == 5
    max_valid_start = len(tokens) - _small_model_cfg().context_len - 1
    for w in windows:
        start = int(w.payload["start_position"])
        assert 0 <= start <= max_valid_start
    # Distinct starts across steps (probabilistic on random sampler, but 5 draws from
    # a 735-wide space collide only ~1.4% of the time; failure = seed change).
    starts = [int(w.payload["start_position"]) for w in windows]
    assert len(set(starts)) >= 4  # allow one duplicate at the tail


def test_epoch_completed_reports_effective_epoch(tmp_path: Path):
    """Sprint 041 §4.2: EPOCH_COMPLETED.epoch = ceil(tokens_consumed / train_tokens).
    Small smoke: 800 tokens, train_frac 0.8 -> 640 train tokens; batch 4 * context 64
    per step = 256 tokens/step; 10 steps = 2560 tokens; ceil(2560/640) = 4.
    """
    e = _fresh_emitter()
    run_training(
        tokens=_synthetic_tokens(800),
        trainer_cfg=_small_trainer_cfg(n_steps=10, eval_every=20),
        model_cfg=_small_model_cfg(),
        emitter=e,
        run_id="test-epoch",
        checkpoint_dir=tmp_path / "ckpt",
    )
    ec = next(s for s in e.snapshot() if s.tag == "EPOCH_COMPLETED")
    assert ec.payload["epoch"] == 4


def test_run_training_is_deterministic_with_seed(tmp_path: Path):
    """Same seed → same final train loss."""
    e1 = _fresh_emitter()
    r1 = run_training(
        tokens=_synthetic_tokens(800),
        trainer_cfg=_small_trainer_cfg(n_steps=5, eval_every=10),  # no checkpoints
        model_cfg=_small_model_cfg(),
        emitter=e1,
        run_id="det-1",
        checkpoint_dir=tmp_path / "ckpt1",
    )
    e2 = _fresh_emitter()
    r2 = run_training(
        tokens=_synthetic_tokens(800),
        trainer_cfg=_small_trainer_cfg(n_steps=5, eval_every=10),
        model_cfg=_small_model_cfg(),
        emitter=e2,
        run_id="det-2",
        checkpoint_dir=tmp_path / "ckpt2",
    )
    assert abs(r1.final_train_loss - r2.final_train_loss) < 1e-4


# Sprint 057: AdamW + cosine + bf16 + deterministic ---------------------------


def test_build_adamw_param_group_split():
    """Sprint 057: 2D+ params get weight_decay, 1D params (biases + LayerNorm) get 0."""
    from price_space_llm.model.trainer import build_adamw_with_param_groups

    model = torch.nn.Sequential(torch.nn.Linear(4, 8), torch.nn.LayerNorm(8))
    opt = build_adamw_with_param_groups(model, lr=3e-4, weight_decay=0.1, betas=(0.9, 0.95))
    assert len(opt.param_groups) == 2
    decay_group = opt.param_groups[0]
    no_decay_group = opt.param_groups[1]
    assert decay_group["weight_decay"] == 0.1
    assert no_decay_group["weight_decay"] == 0.0
    # Linear weight (2D) in decay; Linear bias + LayerNorm weight + bias (1D) in no-decay.
    assert len(decay_group["params"]) == 1
    assert len(no_decay_group["params"]) == 3


def test_cosine_with_warmup_lr_shape():
    """Sprint 057: linear warmup then cosine decay to base_lr * min_frac."""
    from price_space_llm.model.trainer import cosine_with_warmup_lr

    warmup, total, base, min_frac = 100, 1000, 3e-4, 0.1
    assert (
        cosine_with_warmup_lr(
            0, warmup_steps=warmup, total_steps=total, base_lr=base, min_frac=min_frac
        )
        == 0.0
    )
    # Halfway through warmup.
    lr_50 = cosine_with_warmup_lr(
        50, warmup_steps=warmup, total_steps=total, base_lr=base, min_frac=min_frac
    )
    assert abs(lr_50 - base * 0.5) < 1e-9
    # At end of warmup.
    lr_warm = cosine_with_warmup_lr(
        warmup, warmup_steps=warmup, total_steps=total, base_lr=base, min_frac=min_frac
    )
    assert abs(lr_warm - base) < 1e-9
    # At total_steps.
    lr_end = cosine_with_warmup_lr(
        total, warmup_steps=warmup, total_steps=total, base_lr=base, min_frac=min_frac
    )
    assert abs(lr_end - base * min_frac) < 1e-9
    # Beyond total_steps clamps to min.
    lr_over = cosine_with_warmup_lr(
        total + 100, warmup_steps=warmup, total_steps=total, base_lr=base, min_frac=min_frac
    )
    assert abs(lr_over - base * min_frac) < 1e-9


def test_run_training_feats_adamw_smoke(tmp_path: Path):
    """Sprint 057: run_training_feats with AdamW + cosine completes 4 steps."""
    from price_space_llm.model import MarketStateTransformerConfig, run_training_feats
    from price_space_llm.model.dataset import TokenizedArtifact

    n = 400
    torch.manual_seed(0)
    artifact = TokenizedArtifact(
        features={"target__SPY": torch.randn(n, 4), "market_context__VIX": torch.randn(n, 3)},
        targets=torch.randint(0, 32, (n,), dtype=torch.int64),
        vol=torch.zeros(n, dtype=torch.float32),
        timestamps=torch.arange(n, dtype=torch.int64),
        is_overnight_gap=None,
        mask=torch.ones(n, dtype=torch.bool),
        channel_names=("market_context__VIX", "target__SPY"),
        meta={},
    )
    cfg = MarketStateTransformerConfig(
        vocab_size=32,
        context_len=64,
        channel_dims={"target__SPY": 4, "market_context__VIX": 3},
    )
    trainer_cfg = TrainerConfig(
        n_steps=4,
        batch_size=2,
        lr=3e-4,
        eval_every=4,
        seed=0,
        warmup_steps=2,  # tiny for a 4-step smoke
        weight_decay=0.1,
        deterministic=False,  # skip global deterministic flag inside the test
    )
    e = _fresh_emitter()
    result = run_training_feats(
        artifact=artifact,
        trainer_cfg=trainer_cfg,
        model_cfg=cfg,
        emitter=e,
        run_id="adamw-smoke",
        checkpoint_dir=tmp_path / "ckpts",
    )
    assert result.final_step == 4
    # LR emits differ across steps due to warmup ramp + cosine decay.
    lrs = [s.payload["lr"] for s in e.snapshot() if s.tag == "TRAINING_STEP_COMPLETED"]
    assert len(lrs) == 4
    assert lrs[0] < lrs[1]  # warmup ramp on step 1 vs 2
    assert lrs[-1] > 0
