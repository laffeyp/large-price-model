"""test_cli.py — end-to-end CLI test.

Runs main(argv) directly (not via subprocess) so the in-memory SignalEmitter
is accessible if needed. The JSONL sink test verifies cross-session signal
trace persistence — the only path that survives the process boundary.
"""
import json
import os
import sys
from io import StringIO
from pathlib import Path
import tempfile

import pytest

from wordcount.__main__ import main


FIXTURES = Path(__file__).parent / "fixtures" / "sample_tree"


def _run_main(argv, monkeypatch):
    """Helper: capture stdout/stderr while running main(argv)."""
    stdout_buf = StringIO()
    stderr_buf = StringIO()
    monkeypatch.setattr(sys, "stdout", stdout_buf)
    monkeypatch.setattr(sys, "stderr", stderr_buf)
    # Run from the example/ directory so signals/0.1.json resolves.
    example_dir = Path(__file__).parent.parent
    monkeypatch.chdir(example_dir)
    exit_code = main(argv)
    return exit_code, stdout_buf.getvalue(), stderr_buf.getvalue()


def test_cli_exit_code_2_when_files_skipped(monkeypatch):
    exit_code, stdout, stderr = _run_main([str(FIXTURES)], monkeypatch)
    assert exit_code == 2
    # stdout is the JSON report
    report = json.loads(stdout)
    assert report["files_counted"] == 2
    assert report["files_skipped"] == 1


def test_cli_stderr_summary_matches_tone_canon(monkeypatch):
    _, _, stderr = _run_main([str(FIXTURES)], monkeypatch)
    # Lowercase first word; no exclamation; mentions counts.
    assert "scanned" in stderr
    assert "!" not in stderr
    assert "skipped" in stderr
    assert "words" in stderr


def test_cli_jsonl_sink_well_formed(monkeypatch):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        sink_path = f.name
    try:
        exit_code, _, _ = _run_main(
            [str(FIXTURES), f"--signals-out={sink_path}"], monkeypatch
        )
        assert exit_code == 2

        lines = Path(sink_path).read_text().splitlines()
        # Per sprint 003 observation contract: 10 lines.
        # SESSION_INIT + 7 scan signals + REPORT_EMITTED + SESSION_COMPLETE.
        assert len(lines) == 10

        # First line is SESSION_INIT; last line is SESSION_COMPLETE.
        first = json.loads(lines[0])
        last = json.loads(lines[-1])
        assert first["tag"] == "SESSION_INIT"
        assert last["tag"] == "SESSION_COMPLETE"
        assert last["exit_code"] == 2

        # Each line parses independently as JSON.
        for line in lines:
            json.loads(line)
    finally:
        os.unlink(sink_path)


def test_cli_exit_code_1_on_missing_path(monkeypatch):
    exit_code, _, stderr = _run_main(["/nonexistent/path/xyz123"], monkeypatch)
    assert exit_code == 1
    assert "does not exist" in stderr
