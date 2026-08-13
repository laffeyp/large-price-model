"""Tests for the training loop -- emit surface, divergence policy, checkpoint writes."""

from pathlib import Path

import pytest

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


def test_run_training_forwards_metrics_to_wandb_sink(tmp_path: Path):
    """Sprint 040: when a WandbSink is passed, log_step fires per training step and
    log_checkpoint fires per checkpoint. Counts must match TRAINING_STEP_COMPLETED
    and CHECKPOINT_WRITTEN emissions exactly. A counting subclass avoids monkeypatching
    around wandb's disabled-mode short-circuits.
    """
    from price_space_llm.wandb_sink import WandbConfig, WandbSink

    class CountingSink(WandbSink):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.step_calls: list[int] = []
            self.ckpt_calls: list[int] = []

        def log_step(self, step, metrics):
            self.step_calls.append(step)
            super().log_step(step, metrics)

        def log_checkpoint(self, step, ckpt_path, metrics):
            self.ckpt_calls.append(step)
            super().log_checkpoint(step, ckpt_path, metrics)

    e = _fresh_emitter()
    cfg = WandbConfig(
        project="price-space-llm-tests",
        run_name="trainer-wire",
        config={"n_steps": 6, "eval_every": 3},
        mode="disabled",
        dir=tmp_path / "wandb",
    )
    with CountingSink(cfg, e, run_id="wire-test") as sink:
        result = run_training(
            tokens=_synthetic_tokens(800),
            trainer_cfg=_small_trainer_cfg(n_steps=6, eval_every=3),
            model_cfg=_small_model_cfg(),
            emitter=e,
            run_id="wire-test",
            checkpoint_dir=tmp_path / "ckpt",
            wandb_sink=sink,
        )
    tags = [s.tag for s in e.snapshot()]
    assert len(sink.step_calls) == tags.count("TRAINING_STEP_COMPLETED") == 6
    assert len(sink.ckpt_calls) == tags.count("CHECKPOINT_WRITTEN") == 2
    assert result.n_checkpoints == 2
    assert "WANDB_UPLOAD_FAILED" not in tags


def test_run_training_survives_wandb_log_failure(tmp_path: Path):
    """A wandb.errors.Error from wandb.log must not kill training. WANDB_UPLOAD_FAILED
    fires per failed call; the training loop continues and finishes normally. A
    subclass whose log_step/log_checkpoint raise-then-emit is more reliable than
    monkeypatching wandb around its disabled-mode short-circuits.
    """
    from wandb.errors import Error as WandbError

    from price_space_llm.wandb_sink import WandbConfig, WandbSink

    class FailingSink(WandbSink):
        def log_step(self, step, metrics):
            # Emit direct; super() would no-op in disabled mode.
            self._emit_failure(
                "per_step_scalar", f"log_step={step}: {WandbError('simulated network drop')}"
            )

        def log_checkpoint(self, step, ckpt_path, metrics):
            self._emit_failure(
                "checkpoint_ref", f"checkpoint step={step}: {WandbError('simulated auth drop')}"
            )

    e = _fresh_emitter()
    cfg = WandbConfig(
        project="price-space-llm-tests",
        run_name="wandb-fail",
        config={"n_steps": 4},
        mode="disabled",
        dir=tmp_path / "wandb",
    )
    with FailingSink(cfg, e, run_id="fail-test") as sink:
        result = run_training(
            tokens=_synthetic_tokens(800),
            trainer_cfg=_small_trainer_cfg(n_steps=4, eval_every=2),
            model_cfg=_small_model_cfg(),
            emitter=e,
            run_id="fail-test",
            checkpoint_dir=tmp_path / "ckpt",
            wandb_sink=sink,
        )
    fails = [s for s in e.snapshot() if s.tag == "WANDB_UPLOAD_FAILED"]
    # 4 step fails + 2 checkpoint fails.
    assert len(fails) == 6
    assert sum(1 for f in fails if f.payload["artifact_kind"] == "per_step_scalar") == 4
    assert sum(1 for f in fails if f.payload["artifact_kind"] == "checkpoint_ref") == 2
    assert result.final_step == 4


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
