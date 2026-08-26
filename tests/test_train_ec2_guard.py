"""Sprint 107: scripts/train.py refuses to run on EC2 without PSLM_AUTHORIZED_GPU_RUN=1."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TRAIN = REPO_ROOT / "scripts" / "train.py"


def _run(env: dict[str, str]) -> tuple[int, str]:
    base_env = {"PATH": os.environ["PATH"]}
    base_env.update(env)
    proc = subprocess.run(
        ["uv", "run", "python", str(TRAIN), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=base_env,
    )
    return proc.returncode, proc.stderr


def test_train_blocks_on_faked_ec2_metadata_without_auth_env():
    """Fake EC2 metadata via AWS_EC2_INSTANCE_ID; auth env not set → exit 1."""
    code, stderr = _run({"AWS_EC2_INSTANCE_ID": "i-abc123"})
    assert code == 1
    assert "PSLM_AUTHORIZED_GPU_RUN" in stderr
    assert "i-abc123" in stderr


def test_train_passes_on_faked_ec2_metadata_with_auth_env():
    """Fake EC2 metadata + auth env set → guard passes; --help lands and exits 0."""
    code, _ = _run({
        "AWS_EC2_INSTANCE_ID": "i-abc123",
        "PSLM_AUTHORIZED_GPU_RUN": "1",
    })
    assert code == 0


def test_train_passes_off_ec2():
    """No EC2 metadata → guard is a no-op; --help succeeds."""
    code, _ = _run({"PSLM_SKIP_EC2_CHECK": "1"})
    assert code == 0


def test_train_still_blocks_on_ec2_with_stale_sprint_env_var():
    """Sprint 108 rename check: the old SPRINT_107_AUTHORIZED_RUN env var no longer bypasses.

    Defensive test — proves the rename is a real replacement, not an alias.
    """
    code, stderr = _run({
        "AWS_EC2_INSTANCE_ID": "i-abc123",
        "SPRINT_107_AUTHORIZED_RUN": "1",  # stale name; guard must ignore it.
    })
    assert code == 1
    assert "PSLM_AUTHORIZED_GPU_RUN" in stderr
