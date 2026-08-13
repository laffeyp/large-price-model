"""Tests for the WandbSink context manager.

Every test uses `WANDB_MODE=disabled` (via the WandbConfig `mode` field) so
`wandb.init` returns a stub run and `wandb.log` no-ops. No network, no on-disk
run directories, no credential needed.

Failure paths are covered by monkeypatching `wandb.log` to raise a real
`wandb.errors.Error`, verifying the sink emits `WANDB_UPLOAD_FAILED` with
the correct `artifact_kind`.
"""

from pathlib import Path

import pytest
import wandb
from wandb.errors import Error as WandbError

from price_space_llm.signals import StrictSignalEmitter, load_vocabulary
from price_space_llm.wandb_sink import WandbConfig, WandbSink


def _fresh_emitter(max_buffer: int = 1024) -> StrictSignalEmitter:
    return StrictSignalEmitter(load_vocabulary(), max_buffer=max_buffer)


def _disabled_cfg(tmp_path: Path, name: str = "unit-test") -> WandbConfig:
    return WandbConfig(
        project="price-space-llm-tests",
        run_name=name,
        config={"vocab_size": 32, "context_len": 64},
        mode="disabled",
        dir=tmp_path / "wandb",
    )


def test_sink_context_manager_opens_and_closes_cleanly(tmp_path: Path):
    e = _fresh_emitter()
    with WandbSink(_disabled_cfg(tmp_path), e, run_id="wandb-test") as sink:
        assert sink is not None
    # In disabled mode, `wandb.init` returns a stub run; no WANDB_UPLOAD_FAILED.
    tags = [s.tag for s in e.snapshot()]
    assert "WANDB_UPLOAD_FAILED" not in tags


def test_sink_log_step_no_fail_path_in_disabled_mode(tmp_path: Path):
    e = _fresh_emitter()
    with WandbSink(_disabled_cfg(tmp_path), e, run_id="wandb-test") as sink:
        sink.log_step(
            1, {"train_loss": 3.5, "lr": 3e-4, "grad_norm": 1.2, "throughput_tokens_per_sec": 100.0}
        )
        sink.log_step(
            2, {"train_loss": 3.2, "lr": 3e-4, "grad_norm": 1.0, "throughput_tokens_per_sec": 105.0}
        )
    tags = [s.tag for s in e.snapshot()]
    assert "WANDB_UPLOAD_FAILED" not in tags


def test_sink_log_checkpoint_no_fail_path_in_disabled_mode(tmp_path: Path):
    e = _fresh_emitter()
    with WandbSink(_disabled_cfg(tmp_path), e, run_id="wandb-test") as sink:
        sink.log_checkpoint(
            5,
            tmp_path / "ckpt.pt",
            {
                "val_nll": 3.4,
                "val_ece": 0.05,
                "val_brier": 0.9,
                "val_rps": 0.2,
                "val_dir_acc": 0.55,
                "val_top1": 0.06,
                "val_top3": 0.15,
            },
        )
    tags = [s.tag for s in e.snapshot()]
    assert "WANDB_UPLOAD_FAILED" not in tags


def test_sink_emits_wandb_upload_failed_on_log_step_wandb_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Real wandb.errors.Error raised from log_step → WANDB_UPLOAD_FAILED emit with
    artifact_kind=per_step_scalar."""
    e = _fresh_emitter()

    def fake_log(*args, **kwargs):
        raise WandbError("simulated network drop")

    with WandbSink(_disabled_cfg(tmp_path), e, run_id="wandb-test") as sink:
        monkeypatch.setattr(wandb, "log", fake_log)
        sink.log_step(7, {"train_loss": 3.1})

    fails = [s for s in e.snapshot() if s.tag == "WANDB_UPLOAD_FAILED"]
    assert len(fails) == 1
    assert fails[0].payload["artifact_kind"] == "per_step_scalar"
    assert "log_step=7" in fails[0].payload["error"]
    assert "simulated network drop" in fails[0].payload["error"]


def test_sink_emits_wandb_upload_failed_on_log_checkpoint_wandb_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Real wandb.errors.Error from log_checkpoint → artifact_kind=checkpoint_ref."""
    e = _fresh_emitter()

    def fake_log(*args, **kwargs):
        raise WandbError("simulated auth drop")

    with WandbSink(_disabled_cfg(tmp_path), e, run_id="wandb-test") as sink:
        monkeypatch.setattr(wandb, "log", fake_log)
        sink.log_checkpoint(11, tmp_path / "ckpt.pt", {"val_nll": 3.0})

    fails = [s for s in e.snapshot() if s.tag == "WANDB_UPLOAD_FAILED"]
    assert len(fails) == 1
    assert fails[0].payload["artifact_kind"] == "checkpoint_ref"
    assert "checkpoint step=11" in fails[0].payload["error"]


def test_sink_swallows_wandb_error_at_init(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """wandb.init failure → WANDB_UPLOAD_FAILED emit; subsequent log calls no-op silently."""
    e = _fresh_emitter()

    def fake_init(*args, **kwargs):
        raise WandbError("simulated init failure")

    monkeypatch.setattr(wandb, "init", fake_init)
    with WandbSink(_disabled_cfg(tmp_path), e, run_id="wandb-test") as sink:
        sink.log_step(1, {"train_loss": 3.5})
        sink.log_checkpoint(1, tmp_path / "ckpt.pt", {"val_nll": 3.4})

    fails = [s for s in e.snapshot() if s.tag == "WANDB_UPLOAD_FAILED"]
    # One init failure; downstream log_* calls no-op because self._run is None.
    assert len(fails) == 1
    assert fails[0].payload["artifact_kind"] == "per_step_scalar"
    assert "init:" in fails[0].payload["error"]
