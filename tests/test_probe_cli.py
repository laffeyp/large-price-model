"""Subprocess-driven tests for scripts/probe_channels.py."""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "probe_channels.py"


def _write_config(tmp_path: Path, channels: list[dict]) -> Path:
    cfg = tmp_path / "channels.json"
    cfg.write_text(json.dumps({"channels": channels}), encoding="utf-8")
    return cfg


def _run(
    tmp_path: Path,
    config: Path,
    extra: list[str] | None = None,
) -> subprocess.CompletedProcess:
    args = [
        sys.executable,
        str(SCRIPT),
        str(config),
        "--logs-dir",
        str(tmp_path / "logs"),
        "--manifest",
        str(tmp_path / "data" / "manifests" / "channel_coverage.json"),
    ]
    if extra:
        args.extend(extra)
    return subprocess.run(args, cwd=tmp_path, capture_output=True, text=True, check=False)


def test_cli_writes_jsonl_trace_and_exits_two_on_drop(tmp_path: Path):
    cfg = _write_config(
        tmp_path,
        [
            {"channel": "target", "symbol": "SPY", "source": "mcp_av"},
            {"channel": "market_context", "symbol": "VIX", "source": "mcp_av"},
            {"channel": "market_context", "symbol": "USO", "source": "mcp_av"},
        ],
    )
    result = _run(tmp_path, cfg)
    assert result.returncode == 2, result.stderr

    trace = tmp_path / "logs" / "probe-0000000000000000" / "signals.jsonl"
    assert trace.exists(), f"missing trace at {trace}; stderr:\n{result.stderr}"

    lines = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["tag"] == "SESSION_INIT"
    assert lines[0]["run_kind"] == "probe"
    assert lines[-1]["tag"] == "SESSION_COMPLETE"
    # process_session's internal exit; CLI wraps and returns 2 separately.
    assert lines[-1]["exit_code"] == 0

    # Signal counts: 3 channels * 5 CHANNEL_PROBED = 15;
    # + 1 CHANNEL_REJECTED (USO); + 3 CHANNEL_COVERAGE_ASSESSED;
    # + 1 SESSION_INIT + 1 SESSION_COMPLETE = 21 total.
    assert len(lines) == 21
    assert lines[-1]["n_signals_emitted"] == 21

    manifest = tmp_path / "data" / "manifests" / "channel_coverage.json"
    assert manifest.exists()
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    assert doc["channels"]["market_context__USO"]["verdict"] == "dropped"
    assert doc["channels"]["target__SPY"]["verdict"] == "accepted"

    assert "probe:" in result.stderr


def test_cli_exits_zero_when_all_accepted(tmp_path: Path):
    cfg = _write_config(
        tmp_path,
        [
            {"channel": "target", "symbol": "SPY", "source": "mcp_av"},
            {"channel": "market_context", "symbol": "VIX", "source": "mcp_av"},
        ],
    )
    result = _run(tmp_path, cfg)
    assert result.returncode == 0, result.stderr


def test_cli_returns_one_on_missing_config(tmp_path: Path):
    missing = tmp_path / "does-not-exist.json"
    args = [sys.executable, str(SCRIPT), str(missing)]
    result = subprocess.run(args, cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "config not found" in result.stderr
