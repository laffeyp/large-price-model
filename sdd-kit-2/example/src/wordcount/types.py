"""types.py — canonical home for the Counts dataclass.

Per WORKING_AGREEMENT.md canonical home registry: this is the sole declaration
of Counts. Other modules import; they do not redeclare.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Counts:
    """Per-file count result. Immutable; tests rely on equality.

    bytes:  total byte size of the file on disk.
    lines:  count of `\\n`-terminated lines in the decoded text.
    words:  whitespace-split word count (matches `wc -w` semantics).
    chars:  count of unicode characters in the decoded text.
    """
    bytes: int
    lines: int
    words: int
    chars: int
