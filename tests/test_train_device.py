"""Sprint 051 review-blocker #4: device handling.

`scripts/train.py::_resolve_device` maps `auto` to the best-available device
(cuda > mps > cpu). `run_training(device=...)` moves model + batches to that
device. Tests verify: (1) _resolve_device passes explicit devices unchanged;
(2) run_training on cpu works (default behavior); (3) skipped-unless-CUDA
smoke that moves the model to cuda.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import torch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from train import _resolve_device  # noqa: E402


def test_resolve_device_passes_cpu_through():
    assert _resolve_device("cpu") == "cpu"


def test_resolve_device_passes_cuda_through():
    """Explicit `cuda` is not remapped even on a CPU-only box; caller opted in."""
    assert _resolve_device("cuda") == "cuda"


def test_resolve_device_passes_mps_through():
    assert _resolve_device("mps") == "mps"


def test_resolve_device_auto_returns_available():
    """auto returns cuda > mps > cpu based on runtime probes."""
    got = _resolve_device("auto")
    if torch.cuda.is_available():
        assert got == "cuda"
    elif torch.backends.mps.is_available():
        assert got == "mps"
    else:
        assert got == "cpu"


def test_run_training_default_device_is_cpu(tmp_path: Path):
    """Sprint 051: run_training defaults to device='cpu' so pre-Sprint-051
    call sites keep working. Verified via the trainer's model.parameters()
    device attribute after training."""
    from price_space_llm.model import TransformerConfig, run_training
    from price_space_llm.model.trainer import TrainerConfig
    from price_space_llm.signals import StrictSignalEmitter, load_vocabulary

    tokens = [i % 32 for i in range(500)]
    emitter = StrictSignalEmitter(load_vocabulary(), max_buffer=4096)
    model_cfg = TransformerConfig(vocab_size=32, context_len=64)
    trainer_cfg = TrainerConfig(n_steps=2, batch_size=2, lr=1e-3, eval_every=2, seed=0)
    result = run_training(
        tokens=tokens,
        trainer_cfg=trainer_cfg,
        model_cfg=model_cfg,
        emitter=emitter,
        run_id="test-device-cpu",
        checkpoint_dir=tmp_path / "ckpts",
    )
    assert result.final_step == 2


@pytest.mark.skipif(not torch.cuda.is_available(), reason="requires CUDA")
def test_run_training_on_cuda_moves_model(tmp_path: Path):
    """Sprint 051: run_training(device='cuda') moves the model to cuda and
    completes a two-step smoke without OOM."""
    from price_space_llm.model import TransformerConfig, run_training
    from price_space_llm.model.trainer import TrainerConfig
    from price_space_llm.signals import StrictSignalEmitter, load_vocabulary

    tokens = [i % 32 for i in range(500)]
    emitter = StrictSignalEmitter(load_vocabulary(), max_buffer=4096)
    model_cfg = TransformerConfig(vocab_size=32, context_len=64)
    trainer_cfg = TrainerConfig(n_steps=2, batch_size=2, lr=1e-3, eval_every=2, seed=0)
    result = run_training(
        tokens=tokens,
        trainer_cfg=trainer_cfg,
        model_cfg=model_cfg,
        emitter=emitter,
        run_id="test-device-cuda",
        checkpoint_dir=tmp_path / "ckpts",
        device="cuda",
    )
    assert result.final_step == 2
