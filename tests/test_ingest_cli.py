"""Subprocess-driven tests for scripts/ingest.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ingest.py"


def _write_manifest(tmp_path: Path, entries: list[dict]) -> Path:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "generated_at": None,
                "channels": {f"{e['channel']}__{e['symbol']}": e for e in entries},
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _run(
    tmp_path: Path, manifest: Path, extra: list[str] | None = None
) -> subprocess.CompletedProcess:
    args = [
        sys.executable,
        str(SCRIPT),
        "--manifest",
        str(manifest),
        "--start-month",
        "2024-06",
        "--cache-dir",
        str(tmp_path / "cache"),
        "--logs-dir",
        str(tmp_path / "logs"),
        "--fetcher",
        "mock",
    ]
    if extra:
        args.extend(extra)
    return subprocess.run(args, cwd=tmp_path, capture_output=True, text=True, check=False)


def test_cli_writes_trace_and_cache_for_accepted_channels(tmp_path: Path):
    manifest = _write_manifest(
        tmp_path,
        [
            {"channel": "target", "symbol": "SPY", "source": "mcp_av", "verdict": "accepted"},
            {
                "channel": "market_context",
                "symbol": "USO",
                "source": "mcp_av",
                "verdict": "accepted",
            },
        ],
    )
    result = _run(tmp_path, manifest)
    assert result.returncode == 0, result.stderr

    trace = tmp_path / "logs" / "ingest-mock-2024-06-0000000000000000" / "signals.jsonl"
    assert trace.exists(), f"missing trace at {trace}\nstderr: {result.stderr}"
    lines = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    tags = [line["tag"] for line in lines]
    assert tags.count("INGESTION_CALL_ISSUED") == 2
    assert tags.count("RAW_OBSERVATION_WRITTEN") == 2
    assert tags[0] == "SESSION_INIT"
    assert tags[-1] == "SESSION_COMPLETE"

    cache_files = list((tmp_path / "cache").rglob("*.json"))
    assert len(cache_files) == 2


def test_cli_second_run_is_full_cache_hit(tmp_path: Path):
    manifest = _write_manifest(
        tmp_path,
        [{"channel": "target", "symbol": "SPY", "source": "mcp_av", "verdict": "accepted"}],
    )
    _run(tmp_path, manifest)
    result = _run(tmp_path, manifest)
    assert result.returncode == 0

    trace = tmp_path / "logs" / "ingest-mock-2024-06-0000000000000000" / "signals.jsonl"
    lines = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    tags = [line["tag"] for line in lines]
    # SESSION_INIT truncates prior sink, so the trace holds only the second session:
    # SESSION_INIT + INGESTION_CALL_CACHED + SESSION_COMPLETE
    assert tags == ["SESSION_INIT", "INGESTION_CALL_CACHED", "SESSION_COMPLETE"]


def test_cli_skips_dropped_channels(tmp_path: Path):
    manifest = _write_manifest(
        tmp_path,
        [
            {"channel": "target", "symbol": "SPY", "source": "mcp_av", "verdict": "accepted"},
            {
                "channel": "market_context",
                "symbol": "VIX",
                "source": "mcp_av",
                "verdict": "dropped",
            },
        ],
    )
    result = _run(tmp_path, manifest)
    assert result.returncode == 0

    trace = tmp_path / "logs" / "ingest-mock-2024-06-0000000000000000" / "signals.jsonl"
    lines = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    tags = [line["tag"] for line in lines]
    assert tags.count("INGESTION_CALL_ISSUED") == 1  # only SPY


def test_cli_alphavantage_requires_api_key(tmp_path: Path, monkeypatch):
    manifest = _write_manifest(
        tmp_path,
        [{"channel": "target", "symbol": "SPY", "source": "mcp_av", "verdict": "accepted"}],
    )
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    result = _run(tmp_path, manifest, extra=["--fetcher", "alphavantage"])
    # The extra flag replaces --fetcher mock; _run adds mock first, --fetcher last wins
    # in argparse, so this test is testing the last-wins behavior; the second --fetcher
    # alphavantage takes effect.
    assert result.returncode == 1
    assert "ALPHAVANTAGE_API_KEY" in result.stderr


def test_cli_empty_manifest_exits_one(tmp_path: Path):
    manifest = _write_manifest(tmp_path, [])
    result = _run(tmp_path, manifest)
    assert result.returncode == 1
    assert "no accepted channels" in result.stderr


def test_cli_month_range_produces_call_per_month_per_channel(tmp_path: Path):
    """--start-month 2024-06 --end-month 2024-08 with 2 channels → 6 fetches."""
    manifest = _write_manifest(
        tmp_path,
        [
            {"channel": "target", "symbol": "SPY", "source": "mcp_av", "verdict": "accepted"},
            {
                "channel": "market_context",
                "symbol": "USO",
                "source": "mcp_av",
                "verdict": "accepted",
            },
        ],
    )
    result = _run(tmp_path, manifest, extra=["--end-month", "2024-08"])
    assert result.returncode == 0, result.stderr
    trace = tmp_path / "logs" / "ingest-mock-2024-06_2024-08-0000000000000000" / "signals.jsonl"
    assert trace.exists()
    lines = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    tags = [line["tag"] for line in lines]
    # 3 months x 2 channels = 6 fetches
    assert tags.count("INGESTION_CALL_ISSUED") == 6
    assert tags.count("RAW_OBSERVATION_WRITTEN") == 6

    cache_files = list((tmp_path / "cache").rglob("*.json"))
    assert len(cache_files) == 6


def test_cli_month_range_rejects_backwards_range(tmp_path: Path):
    manifest = _write_manifest(
        tmp_path,
        [{"channel": "target", "symbol": "SPY", "source": "mcp_av", "verdict": "accepted"}],
    )
    result = _run(tmp_path, manifest, extra=["--end-month", "2024-05"])  # < start_month
    assert result.returncode == 1
    assert "precedes" in result.stderr


def test_cli_single_month_run_id_omits_end_suffix(tmp_path: Path):
    """--start-month 2024-06 alone → run_id contains 2024-06, not 2024-06_2024-06."""
    manifest = _write_manifest(
        tmp_path,
        [{"channel": "target", "symbol": "SPY", "source": "mcp_av", "verdict": "accepted"}],
    )
    result = _run(tmp_path, manifest)
    assert result.returncode == 0
    trace = tmp_path / "logs" / "ingest-mock-2024-06-0000000000000000" / "signals.jsonl"
    assert trace.exists()
