"""Sprint 063: experiments/logbook.csv writer per tech-arch §13."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from price_space_llm.logbook import LogbookEntry, append_run, read_logbook

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "register_run.py"


def _sample_entry(run_id: str = "test-run") -> LogbookEntry:
    return LogbookEntry(
        date="2026-08-16",
        run_id=run_id,
        branch="main",
        git_sha="abc123",
        notes="unit test",
        target="SPY",
        model_size="xs",
        context_len=64,
        patch_size=1,
        head_type="categorical",
        n_buckets=32,
        train_loss=3.5,
        val_nll=3.2,
        val_ece=0.04,
        val_brier=0.09,
        val_rps=0.06,
        val_dir_acc=0.53,
        held_out_sharpe=float("nan"),
        held_out_sharpe_se=float("nan"),
        lambda_risk=0.5,
        alpha_mag_weight=0.0,
        touched_test=False,
    )


def test_append_creates_file_and_header(tmp_path: Path):
    path = tmp_path / "logbook.csv"
    append_run(_sample_entry(), path)
    rows = read_logbook(path)
    assert len(rows) == 1
    assert rows[0]["run_id"] == "test-run"
    assert rows[0]["target"] == "SPY"


def test_append_is_append_only(tmp_path: Path):
    """Two appends → two rows; no rewrite of prior."""
    path = tmp_path / "logbook.csv"
    append_run(_sample_entry("first"), path)
    append_run(_sample_entry("second"), path)
    rows = read_logbook(path)
    assert len(rows) == 2
    assert rows[0]["run_id"] == "first"
    assert rows[1]["run_id"] == "second"


def test_read_logbook_missing_file_returns_empty(tmp_path: Path):
    rows = read_logbook(tmp_path / "does-not-exist.csv")
    assert rows == []


def test_header_matches_schema_order(tmp_path: Path):
    path = tmp_path / "logbook.csv"
    append_run(_sample_entry(), path)
    with path.open("r", encoding="utf-8") as f:
        header = f.readline().strip().split(",")
    expected = [
        "date",
        "run_id",
        "branch",
        "git_sha",
        "notes",
        "target",
        "model_size",
        "context_len",
        "patch_size",
        "head_type",
        "n_buckets",
        "train_loss",
        "val_nll",
        "val_ece",
        "val_brier",
        "val_rps",
        "val_dir_acc",
        "held_out_sharpe",
        "held_out_sharpe_se",
        "lambda_risk",
        "alpha_mag_weight",
        "touched_test",
    ]
    assert header == expected


def test_register_run_cli_appends_row(tmp_path: Path):
    """Sprint 063: scripts/register_run.py --run-id ... appends one row."""
    logbook = tmp_path / "logbook.csv"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--run-id",
            "cli-test",
            "--target",
            "SPY",
            "--context-len",
            "64",
            "--train-loss",
            "3.5",
            "--val-nll",
            "3.2",
            "--logbook-path",
            str(logbook),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    rows = read_logbook(logbook)
    assert len(rows) == 1
    assert rows[0]["run_id"] == "cli-test"
    assert rows[0]["val_nll"] == "3.2"
