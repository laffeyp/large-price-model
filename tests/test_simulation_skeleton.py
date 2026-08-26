"""Sprint 092: simulator skeleton — bar walker + SIM_* emits."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from price_space_llm.signals import StrictSignalEmitter, load_vocabulary
from price_space_llm.simulation import SimResult, run_simulation_skeleton

REPO_ROOT = Path(__file__).resolve().parents[1]


def _fresh_emitter(max_buffer: int = 8192) -> StrictSignalEmitter:
    return StrictSignalEmitter(load_vocabulary(), max_buffer=max_buffer)


def _write_synthetic_aligned(path: Path, n_rows: int, start: datetime | None = None) -> None:
    """Write a synthetic aligned parquet with the minimum column set the skeleton reads."""
    base = start or datetime(2020, 1, 1, 14, 45, tzinfo=UTC)
    grid_ts = [base + timedelta(minutes=15 * i) for i in range(n_rows)]
    df = pl.DataFrame({"grid_ts": grid_ts})
    df.write_parquet(path)


def test_run_simulation_skeleton_emits_full_tag_sequence(tmp_path: Path):
    """SIM_RUN_STARTED, BAR_PROCESSED N times, SIM_RUN_COMPLETED in order."""
    aligned = tmp_path / "align-synthetic.parquet"
    _write_synthetic_aligned(aligned, n_rows=3)
    e = _fresh_emitter()
    result = run_simulation_skeleton(
        aligned,
        split="train",
        date_range_start=date(2020, 1, 1),
        date_range_end=date(2020, 1, 2),
        emitter=e,
        run_id="test-sim-3bars",        checkpoint_step=0,
        checkpoint_run_id="test-ckpt",
        cost_calibration_run_id="test-cal",

    )
    tags = [s.tag for s in e.snapshot()]
    assert tags == [
        "SIM_RUN_STARTED",
        "BAR_PROCESSED",
        "BAR_PROCESSED",
        "BAR_PROCESSED",
        "SIM_RUN_COMPLETED",
    ]
    assert result.n_bars_processed == 3


def test_run_simulation_skeleton_filters_by_date_range(tmp_path: Path):
    """A range covering only some of the aligned parquet's rows walks only those."""
    aligned = tmp_path / "align-multiday.parquet"
    # 3 bars on 2020-01-01 (14:45, 15:00, 15:15 UTC), 3 bars on 2020-01-02, 3 on 2020-01-03.
    base = datetime(2020, 1, 1, 14, 45, tzinfo=UTC)
    grid_ts: list[datetime] = []
    for day in range(3):
        for hr_slot in range(3):
            grid_ts.append(base + timedelta(days=day, minutes=15 * hr_slot))
    pl.DataFrame({"grid_ts": grid_ts}).write_parquet(aligned)

    e = _fresh_emitter()
    result = run_simulation_skeleton(
        aligned,
        split="train",
        date_range_start=date(2020, 1, 2),
        date_range_end=date(2020, 1, 2),  # single day, inclusive
        emitter=e,
        run_id="test-sim-oneday",        checkpoint_step=0,
        checkpoint_run_id="test-ckpt",
        cost_calibration_run_id="test-cal",

    )
    bar_events = [s for s in e.snapshot() if s.tag == "BAR_PROCESSED"]
    assert len(bar_events) == 3
    assert result.n_bars_processed == 3


def test_run_simulation_skeleton_returns_sim_result_with_zeroed_metrics(tmp_path: Path):
    """Every summary field on SimResult is 0/0.0; notes names the skeleton scope."""
    aligned = tmp_path / "align-tiny.parquet"
    _write_synthetic_aligned(aligned, n_rows=2)
    e = _fresh_emitter()
    result = run_simulation_skeleton(
        aligned,
        split="train",
        date_range_start=date(2020, 1, 1),
        date_range_end=date(2020, 1, 2),
        emitter=e,
        run_id="test-sim-zeros",        checkpoint_step=0,
        checkpoint_run_id="test-ckpt",
        cost_calibration_run_id="test-cal",

    )
    assert isinstance(result, SimResult)
    assert result.n_trades == 0
    assert result.sharpe_point == 0.0
    assert result.sharpe_se == 0.0
    assert result.block_bootstrap_positive_fraction == 0.0
    assert result.max_drawdown == 0.0
    assert result.time_to_recovery_bars == 0
    assert result.implied_capacity_usd == 0.0
    assert "skeleton" in result.notes


def test_run_simulation_skeleton_raises_on_missing_grid_ts(tmp_path: Path):
    """Aligned parquet without grid_ts is a schema error, not a silent no-op."""
    aligned = tmp_path / "align-badcols.parquet"
    pl.DataFrame({"other_col": [1, 2, 3]}).write_parquet(aligned)
    e = _fresh_emitter()
    with pytest.raises(ValueError, match="grid_ts"):
        run_simulation_skeleton(
            aligned,
            split="train",
            date_range_start=date(2020, 1, 1),
            date_range_end=date(2020, 1, 2),
            emitter=e,
            run_id="test-sim-badcols",            checkpoint_step=0,
            checkpoint_run_id="test-ckpt",
            cost_calibration_run_id="test-cal",

        )


def test_simulate_cli_smoke_on_synthetic_parquet(tmp_path: Path):
    """CLI end-to-end: writes trace with SIM_RUN_STARTED + SIM_RUN_COMPLETED."""
    # Sprint 081: heldout_guard requires a known dated-artifact filename shape.
    # Use `align-YYYY-MM-...` so parquet_range_starts_in_heldout resolves cleanly.
    aligned = tmp_path / "align-2020-01-synthetic.parquet"
    _write_synthetic_aligned(aligned, n_rows=4)
    logs_dir = tmp_path / "logs"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "simulate.py"),
            "--aligned",
            str(aligned),
            "--split",
            "train",
            "--date-range-start",
            "2020-01-01",
            "--date-range-end",
            "2020-01-02",
            "--logs-dir",
            str(logs_dir),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    trace_files = list(logs_dir.glob("simulate-*/signals.jsonl"))
    assert len(trace_files) == 1
    trace = trace_files[0].read_text().splitlines()
    tags = [line for line in trace if '"tag":' in line]
    assert any('"SIM_RUN_STARTED"' in line for line in tags)
    assert any('"BAR_PROCESSED"' in line for line in tags)
    assert any('"SIM_RUN_COMPLETED"' in line for line in tags)


def test_simulate_cli_refuses_heldout_without_ack(tmp_path: Path):
    """A heldout-shaped filename with --split test and no ack exits nonzero."""
    heldout_shape = tmp_path / "align-2024-06-synthetic.parquet"
    _write_synthetic_aligned(heldout_shape, n_rows=2)
    logs_dir = tmp_path / "logs"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "simulate.py"),
            "--aligned",
            str(heldout_shape),
            "--split",
            "test",
            "--date-range-start",
            "2024-06-01",
            "--date-range-end",
            "2024-06-01",
            "--logs-dir",
            str(logs_dir),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 2, proc.stderr
    assert "heldout" in proc.stderr.lower()
