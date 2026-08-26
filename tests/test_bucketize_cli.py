"""Sprint 090: --n-buckets override on scripts/bucketize.py CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FEATURES_PARQUET = REPO_ROOT / "data" / "features" / (
    "features-align-2015-01-2022-12-0000000000000000-0000000000000000.parquet"
)


def _run_bucketize(tmp_path: Path, n_buckets: int) -> Path:
    """Invoke scripts/bucketize.py --n-buckets N; return path to fresh bucket_stats.json."""
    logs_dir = tmp_path / "logs"
    output_dir = tmp_path / "tokenized"
    stats_dir = tmp_path / "stats"
    stats_dir.mkdir()
    stats_path = stats_dir / "bucket_stats.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "bucketize.py"),
            "--features",
            str(FEATURES_PARQUET),
            "--output-dir",
            str(output_dir),
            "--bucket-stats",
            str(stats_path),
            "--training-start",
            "2015-01-02",
            "--training-end",
            "2022-12-30",
            "--n-buckets",
            str(n_buckets),
            "--format",
            "parquet",
            "--logs-dir",
            str(logs_dir),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    return stats_path


def test_bucketize_override_16_produces_15_edges(tmp_path: Path):
    """--n-buckets 16 produces a bucket_stats.json with 15 edges."""
    if not FEATURES_PARQUET.exists():
        pytest.skip(f"features parquet not on disk: {FEATURES_PARQUET}")
    stats_path = _run_bucketize(tmp_path, 16)
    # The bucketize script writes versioned files under stats_dir. Locate the .latest.
    latest = stats_path.with_name(stats_path.stem + ".latest" + stats_path.suffix)
    assert latest.exists()
    payload = json.loads(latest.read_text(encoding="utf-8"))
    assert payload["n_buckets"] == 16
    assert len(payload["edges"]) == 15


def test_bucketize_override_64_produces_63_edges(tmp_path: Path):
    """--n-buckets 64 produces a bucket_stats.json with 63 edges."""
    if not FEATURES_PARQUET.exists():
        pytest.skip(f"features parquet not on disk: {FEATURES_PARQUET}")
    stats_path = _run_bucketize(tmp_path, 64)
    latest = stats_path.with_name(stats_path.stem + ".latest" + stats_path.suffix)
    assert latest.exists()
    payload = json.loads(latest.read_text(encoding="utf-8"))
    assert payload["n_buckets"] == 64
    assert len(payload["edges"]) == 63
