"""report.py — JSON report formatter.

Pure formatter; no I/O. Per WORKING_AGREEMENT.md canonical home registry:
format_json_report lives here.
"""
from __future__ import annotations
import json


def format_json_report(scan_result: dict) -> str:
    """Render a scan-result dict as pretty-printed JSON.

    scan_result shape (per the SCAN_COMPLETE payload):
        {
            "files_counted": int,
            "files_skipped": int,
            "total_bytes": int,
            "total_words": int,
            "total_lines": int,
            "elapsed_seconds": float,
        }

    The output is `json.dumps(scan_result, indent=2, sort_keys=True)` plus a
    trailing newline (so the byte count is stable across platforms — see the
    REPORT_EMITTED invariant in signals/0.1.json).
    """
    return json.dumps(scan_result, indent=2, sort_keys=True) + "\n"
