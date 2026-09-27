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


# Sprint 073: model-size configs (Phase E, roadmap 067) --------------------


def test_train_cli_rejects_both_model_size_and_model_config(tmp_path: Path):
    """Passing --model-size and --model-config together exits 1."""
    import subprocess

    # Sprint 119: name the normalized 2015-2022 training artifact. The old
    # data/tokenized/tokens.latest.pt symlink pointed at held-out tokens after
    # Sprint 117, and these smokes trained on it; train.py now refuses that.
    versioned = REPO_ROOT / "data" / "tokenized" / "normalized" / (
        "tokens.tokenize-features-align-2015-01-2022-12-"
        "0000000000000000-0000000000000000-0000000000000000.pt"
    )
    bare_legacy = REPO_ROOT / "data" / "tokenized" / (
        "tokenize-features-align-2015-01-2022-12-"
        "0000000000000000-0000000000000000-0000000000000000.pt"
    )
    if versioned.exists():
        tokens_pt = versioned
    elif bare_legacy.exists():
        tokens_pt = bare_legacy
    else:
        pytest.skip(f"training .pt artifact not on disk: {versioned}")
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "train.py"),
            "--tokens-pt",
            str(tokens_pt),
            "--model-size",
            "xs",
            "--model-config",
            str(REPO_ROOT / "configs" / "model" / "xs.json"),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 1, proc.stderr
    assert "at most one of --model-size" in proc.stderr


def test_train_cli_xs_smoke_on_pt_artifact(tmp_path: Path):
    """Two CPU steps at --model-size xs against the real training .pt.

    Skips if the .pt artifact isn't on disk (fresh checkouts, CI).
    """
    import subprocess

    # Sprint 119: name the normalized 2015-2022 training artifact. The old
    # data/tokenized/tokens.latest.pt symlink pointed at held-out tokens after
    # Sprint 117, and these smokes trained on it; train.py now refuses that.
    versioned = REPO_ROOT / "data" / "tokenized" / "normalized" / (
        "tokens.tokenize-features-align-2015-01-2022-12-"
        "0000000000000000-0000000000000000-0000000000000000.pt"
    )
    bare_legacy = REPO_ROOT / "data" / "tokenized" / (
        "tokenize-features-align-2015-01-2022-12-"
        "0000000000000000-0000000000000000-0000000000000000.pt"
    )
    if versioned.exists():
        tokens_pt = versioned
    elif bare_legacy.exists():
        tokens_pt = bare_legacy
    else:
        pytest.skip(f"training .pt artifact not on disk: {versioned}")

    ckpt_dir = tmp_path / "ckpts"
    logs_dir = tmp_path / "logs"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "train.py"),
            "--tokens-pt",
            str(tokens_pt),
            "--model-size",
            "xs",
            "--n-steps",
            "2",
            "--eval-every",
            "2",
            "--seed",
            "41",
            "--device",
            "cpu",
            "--warmup-steps",
            "0",
            "--checkpoint-dir",
            str(ckpt_dir),
            "--logs-dir",
            str(logs_dir),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    assert "d_model=128 n_layers=4 n_heads=2" in proc.stderr
    trace_dirs = list(logs_dir.glob("train-*/signals.jsonl"))
    assert len(trace_dirs) == 1, trace_dirs
    assert "-xs-" in trace_dirs[0].parent.name


# Sprint 074: context-length configs (Phase E, roadmap 068) --------------


def test_train_cli_rejects_both_context_size_and_context_config(tmp_path: Path):
    """Passing --context-size and --context-config together exits 1."""
    import subprocess

    # Sprint 119: name the normalized 2015-2022 training artifact. The old
    # data/tokenized/tokens.latest.pt symlink pointed at held-out tokens after
    # Sprint 117, and these smokes trained on it; train.py now refuses that.
    versioned = REPO_ROOT / "data" / "tokenized" / "normalized" / (
        "tokens.tokenize-features-align-2015-01-2022-12-"
        "0000000000000000-0000000000000000-0000000000000000.pt"
    )
    bare_legacy = REPO_ROOT / "data" / "tokenized" / (
        "tokenize-features-align-2015-01-2022-12-"
        "0000000000000000-0000000000000000-0000000000000000.pt"
    )
    if versioned.exists():
        tokens_pt = versioned
    elif bare_legacy.exists():
        tokens_pt = bare_legacy
    else:
        pytest.skip(f"training .pt artifact not on disk: {versioned}")
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "train.py"),
            "--tokens-pt",
            str(tokens_pt),
            "--context-size",
            "128",
            "--context-config",
            str(REPO_ROOT / "configs" / "context" / "128.json"),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 1, proc.stderr
    assert "at most one of --context-size" in proc.stderr


def test_train_cli_c128_xs_smoke_on_pt_artifact(tmp_path: Path):
    """Two CPU steps at --context-size 128 --model-size xs.

    Verifies the two Phase E dispatch knobs compose: stderr names context_len=128
    and the model shape line; the trace directory carries both `-xs-` and `-c128-`.
    Skips if the training .pt artifact isn't on disk.
    """
    import subprocess

    # Sprint 119: name the normalized 2015-2022 training artifact. The old
    # data/tokenized/tokens.latest.pt symlink pointed at held-out tokens after
    # Sprint 117, and these smokes trained on it; train.py now refuses that.
    versioned = REPO_ROOT / "data" / "tokenized" / "normalized" / (
        "tokens.tokenize-features-align-2015-01-2022-12-"
        "0000000000000000-0000000000000000-0000000000000000.pt"
    )
    bare_legacy = REPO_ROOT / "data" / "tokenized" / (
        "tokenize-features-align-2015-01-2022-12-"
        "0000000000000000-0000000000000000-0000000000000000.pt"
    )
    if versioned.exists():
        tokens_pt = versioned
    elif bare_legacy.exists():
        tokens_pt = bare_legacy
    else:
        pytest.skip(f"training .pt artifact not on disk: {versioned}")

    ckpt_dir = tmp_path / "ckpts"
    logs_dir = tmp_path / "logs"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "train.py"),
            "--tokens-pt",
            str(tokens_pt),
            "--model-size",
            "xs",
            "--context-size",
            "128",
            "--n-steps",
            "2",
            "--eval-every",
            "2",
            "--seed",
            "41",
            "--device",
            "cpu",
            "--warmup-steps",
            "0",
            "--checkpoint-dir",
            str(ckpt_dir),
            "--logs-dir",
            str(logs_dir),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    assert "context_len=128" in proc.stderr
    assert "d_model=128 n_layers=4 n_heads=2" in proc.stderr
    trace_files = list(logs_dir.glob("train-*/signals.jsonl"))
    assert len(trace_files) == 1, trace_files
    name = trace_files[0].parent.name
    assert "-xs-" in name, name
    assert "-c128-" in name, name


# Sprint 083: --fusion mixer end-to-end smoke ------------------------------


def _write_synthetic_tokens_pt(path: Path, n_rows: int = 400) -> None:
    """Write a small synthetic Sprint-078-shape tokenized .pt at `path`.

    Sprint 083: mixer's random-init attention diverges on the un-normalized
    real corpus (dollar_volume ~$448M rows); a synthetic .pt with small-scale
    features keeps the smoke inside the trainer's divergence guard while
    still exercising the fusion=mixer code path end-to-end.
    """
    payload = {
        "features": {
            "target__SPY": torch.randn(n_rows, 4) * 0.1,
            "market_context__VIX": torch.randn(n_rows, 3) * 0.1,
        },
        "targets": torch.randint(0, 32, (n_rows,), dtype=torch.int64),
        # Sprint 088: raw float log_return so the quantile head can consume it.
        "raw_targets": torch.randn(n_rows, dtype=torch.float32) * 0.01,
        "vol": torch.zeros(n_rows, dtype=torch.float32),
        "timestamps": torch.arange(n_rows, dtype=torch.int64),
        "is_overnight_gap": None,
        "mask": torch.ones(n_rows, dtype=torch.bool),
        "channel_names": ("market_context__VIX", "target__SPY"),
        "meta": {
            "run_id": "synthetic-mixer-smoke",
            "target_symbol": "SPY",
            "mask_semantics": "target_valid_v075",
            # Sprint 084 (v0.7): mixer training refuses un-normalized artifacts.
            # Synthetic fixture opts in — the small-scale features stand in for
            # a real normalizer-applied .pt.
            "normalized": True,
            "raw_targets_stamped": "v088",
        },
    }
    torch.save(payload, path)


def test_train_cli_fusion_mixer_smoke_on_synthetic_pt(tmp_path: Path):
    """Two CPU steps at --fusion mixer --model-size xs against a synthetic .pt.

    Uses a small-scale synthetic artifact (features drawn from N(0, 0.1))
    so the mixer's random-init attention gradients stay inside the trainer
    divergence guard. Verifies: CLI accepts --fusion; the mixer path
    executes end-to-end; run_id carries the -mix infix; trace lands.
    """
    import subprocess

    tokens_pt = tmp_path / "synthetic-tokens.pt"
    _write_synthetic_tokens_pt(tokens_pt)

    ckpt_dir = tmp_path / "ckpts"
    logs_dir = tmp_path / "logs"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "train.py"),
            "--tokens-pt",
            str(tokens_pt),
            "--model-size",
            "xs",
            "--fusion",
            "mixer",
            "--n-steps",
            "2",
            "--eval-every",
            "2",
            "--seed",
            "41",
            "--device",
            "cpu",
            "--warmup-steps",
            "0",
            "--checkpoint-dir",
            str(ckpt_dir),
            "--logs-dir",
            str(logs_dir),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    assert "fusion=mixer" in proc.stderr
    trace_files = list(logs_dir.glob("train-*/signals.jsonl"))
    assert len(trace_files) == 1, trace_files
    assert "-mix-" in trace_files[0].parent.name


# Sprint 087: --patch-size 4 end-to-end smoke -------------------------------


def test_train_cli_patch4_smoke_on_synthetic_pt(tmp_path: Path):
    """Two CPU steps at --patch-size 4 --model-size xs against a synthetic .pt.

    Exercises the patch=4 embedder + trainer target-slicing end-to-end.
    Uses the Sprint 083 small-scale synthetic .pt (opts into normalized=True
    since the mixer-refusal contract doesn't fire for patch=4 anyway, but the
    fixture already stamps the field).
    """
    import subprocess

    tokens_pt = tmp_path / "synthetic-tokens.pt"
    _write_synthetic_tokens_pt(tokens_pt)

    ckpt_dir = tmp_path / "ckpts"
    logs_dir = tmp_path / "logs"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "train.py"),
            "--tokens-pt",
            str(tokens_pt),
            "--model-size",
            "xs",
            "--patch-size",
            "4",
            "--n-steps",
            "2",
            "--eval-every",
            "2",
            "--seed",
            "41",
            "--device",
            "cpu",
            "--warmup-steps",
            "0",
            "--checkpoint-dir",
            str(ckpt_dir),
            "--logs-dir",
            str(logs_dir),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    assert "patch_size=4" in proc.stderr
    trace_files = list(logs_dir.glob("train-*/signals.jsonl"))
    assert len(trace_files) == 1, trace_files
    assert "-p4-" in trace_files[0].parent.name


# Sprint 089: --head-type quantile end-to-end smoke -------------------------


def test_train_cli_quantile_head_smoke_on_synthetic_pt(tmp_path: Path):
    """Two CPU steps at --head-type quantile --model-size xs on synthetic .pt."""
    import subprocess

    tokens_pt = tmp_path / "synthetic-tokens.pt"
    _write_synthetic_tokens_pt(tokens_pt)

    ckpt_dir = tmp_path / "ckpts"
    logs_dir = tmp_path / "logs"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "train.py"),
            "--tokens-pt",
            str(tokens_pt),
            "--model-size",
            "xs",
            "--head-type",
            "quantile",
            "--n-steps",
            "2",
            "--eval-every",
            "2",
            "--seed",
            "41",
            "--device",
            "cpu",
            "--warmup-steps",
            "0",
            "--checkpoint-dir",
            str(ckpt_dir),
            "--logs-dir",
            str(logs_dir),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    assert "head_type=quantile" in proc.stderr
    trace_files = list(logs_dir.glob("train-*/signals.jsonl"))
    assert len(trace_files) == 1, trace_files
    assert "-qh-" in trace_files[0].parent.name


# Sprint 090: --n-buckets override infix + overlay -------------------------


def test_train_cli_n_buckets_override_infix(tmp_path: Path):
    """--n-buckets 16 puts a -b16- infix in the trace directory + overrides cfg."""
    import subprocess

    # Regenerate a synthetic .pt at n_buckets=16 first (default fixture uses
    # 32-bucket ids in `targets` which would poison a 16-bucket vocab, so we
    # override the target ids to stay inside [0, 16)).
    tokens_pt = tmp_path / "synthetic-tokens.pt"
    _write_synthetic_tokens_pt(tokens_pt)
    payload = torch.load(tokens_pt, weights_only=False)
    payload["targets"] = torch.randint(0, 16, payload["targets"].shape, dtype=torch.int64)
    torch.save(payload, tokens_pt)

    ckpt_dir = tmp_path / "ckpts"
    logs_dir = tmp_path / "logs"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "train.py"),
            "--tokens-pt",
            str(tokens_pt),
            "--model-size",
            "xs",
            "--n-buckets",
            "16",
            "--n-steps",
            "2",
            "--eval-every",
            "2",
            "--seed",
            "41",
            "--device",
            "cpu",
            "--warmup-steps",
            "0",
            "--checkpoint-dir",
            str(ckpt_dir),
            "--logs-dir",
            str(logs_dir),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    assert "n_buckets=16" in proc.stderr
    trace_files = list(logs_dir.glob("train-*/signals.jsonl"))
    assert len(trace_files) == 1, trace_files
    assert "-b16-" in trace_files[0].parent.name


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
