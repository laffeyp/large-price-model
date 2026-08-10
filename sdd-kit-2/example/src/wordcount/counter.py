"""counter.py — pure file-counting logic.

Per WORKING_AGREEMENT.md canonical home registry: count_file lives here. Pure
function; no I/O beyond reading the named file. No signal emission.
"""
from __future__ import annotations
from enum import Enum
from pathlib import Path

from wordcount.types import Counts


class SkipReason(Enum):
    BINARY_DETECTED = "binary_detected"
    PERMISSION_DENIED = "permission_denied"
    DECODE_ERROR = "decode_error"


_NULL_SCAN_BYTES = 1024


def _looks_binary(raw: bytes) -> bool:
    """Heuristic: any null byte in the first 1024 bytes → binary.

    Matches the convention used by file(1) and most line-oriented tools.
    Not perfect (UTF-16 starts with a null for ASCII-range chars) but adequate
    for this project's scope. See BLACKBOARD.md ## Deferred for the case where
    this needs refinement.
    """
    return b"\x00" in raw[:_NULL_SCAN_BYTES]


def count_file(path: Path) -> Counts | SkipReason:
    """Count bytes / lines / words / chars in one file.

    Returns Counts on success, SkipReason on skip. Never raises for the
    skip-reasons enumerated in SkipReason; raises for unanticipated errors
    (caller should let those propagate — they're bugs, not skip conditions).
    """
    try:
        raw = path.read_bytes()
    except PermissionError:
        return SkipReason.PERMISSION_DENIED

    if _looks_binary(raw):
        return SkipReason.BINARY_DETECTED

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return SkipReason.DECODE_ERROR

    return Counts(
        bytes=len(raw),
        lines=text.count("\n"),
        words=len(text.split()),
        chars=len(text),
    )
