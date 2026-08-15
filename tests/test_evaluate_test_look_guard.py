"""Sprint 051 review-blocker #3: --split test guard wiring on scripts/evaluate.py.

The register_test_look() call from Sprint 034 exists but nothing wired it into
evaluate.py. Sprint 051 adds a `--split test` flag that requires both
`--i-know-this-is-a-test-look` and `--test-look-reason`; on missing flags exit
1 before any file work; on budget exhaustion exit 2.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "evaluate.py"


def _run(tmp_path: Path, extra: list[str]) -> subprocess.CompletedProcess:
    args = [
        sys.executable,
        str(SCRIPT),
        "--checkpoint",
        str(tmp_path / "ckpt.pt"),
        "--tokens",
        str(tmp_path / "tokens.parquet"),
        "--features",
        str(tmp_path / "features.parquet"),
        "--logs-dir",
        str(tmp_path / "logs"),
        *extra,
    ]
    return subprocess.run(args, cwd=tmp_path, capture_output=True, text=True, check=False)


def test_split_test_without_safety_flag_exits_one(tmp_path: Path):
    """--split test without --i-know-this-is-a-test-look exits 1."""
    r = _run(tmp_path, ["--split", "test", "--test-look-reason", "smoke"])
    assert r.returncode == 1
    assert "--i-know-this-is-a-test-look" in r.stderr


def test_split_test_without_reason_exits_one(tmp_path: Path):
    """--split test with safety flag but empty reason exits 1."""
    r = _run(
        tmp_path,
        ["--split", "test", "--i-know-this-is-a-test-look", "--test-look-reason", "   "],
    )
    assert r.returncode == 1
    assert "--test-look-reason" in r.stderr


def test_split_val_ignores_test_look_flags(tmp_path: Path):
    """Default --split val does not require the safety args; the file-existence
    check still fires (checkpoint file absent → exit 1) but with a different
    reason than the test-look guard."""
    r = _run(tmp_path, [])  # default split=val
    assert r.returncode == 1
    assert "checkpoint not found" in r.stderr
    assert "i-know-this-is-a-test-look" not in r.stderr


def test_split_test_arg_ordering_precedes_file_check(tmp_path: Path):
    """The --split test guard fires before the file-existence check; asserting
    the guard's error text appears rather than 'checkpoint not found'."""
    r = _run(tmp_path, ["--split", "test"])
    assert r.returncode == 1
    assert "--i-know-this-is-a-test-look" in r.stderr
    assert "checkpoint not found" not in r.stderr
