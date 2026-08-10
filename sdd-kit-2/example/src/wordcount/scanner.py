"""scanner.py — directory traversal with signal emission.

Per WORKING_AGREEMENT.md canonical home registry: scan_dir lives here. Walks
the tree, calls counter, emits the scan-category signals declared in
signals/0.1.json.

Per sprint 002 Rubber Duck Pass observation #1: uses manual recursion (not
os.walk) so DIR_ENTERED fires explicitly for every directory entered,
including the root and every descendant.
"""
from __future__ import annotations
import time
from pathlib import Path

from wordcount.counter import count_file, SkipReason

# Type-only import (avoids hard dependency on lib.sdd at import time; tests
# inject a mock or the real SignalEmitter as appropriate).
from typing import Protocol


class _EmitterProtocol(Protocol):
    def emit(self, tag: str, **payload) -> None: ...


def scan_dir(root: Path, emitter: _EmitterProtocol) -> None:
    """Walk the tree rooted at `root`. Emit scan-category signals per the
    locked vocabulary. Returns None; the signal trace is the result.
    """
    start = time.monotonic()
    emitter.emit("SCAN_STARTED", root_path=str(root.absolute()))

    files_counted = 0
    files_skipped = 0
    total_bytes = 0
    total_words = 0
    total_lines = 0

    def _walk(directory: Path) -> None:
        nonlocal files_counted, files_skipped, total_bytes, total_words, total_lines
        entries = sorted(directory.iterdir())  # deterministic order for replay
        emitter.emit(
            "DIR_ENTERED",
            dir_path=str(directory.absolute()),
            entry_count=len(entries),
        )
        for entry in entries:
            if entry.is_dir():
                _walk(entry)
            elif entry.is_file():
                result = count_file(entry)
                if isinstance(result, SkipReason):
                    emitter.emit(
                        "FILE_SKIPPED",
                        file_path=str(entry.absolute()),
                        reason=result.value,
                    )
                    files_skipped += 1
                else:
                    emitter.emit(
                        "FILE_COUNTED",
                        file_path=str(entry.absolute()),
                        bytes=result.bytes,
                        lines=result.lines,
                        words=result.words,
                        chars=result.chars,
                    )
                    files_counted += 1
                    total_bytes += result.bytes
                    total_words += result.words
                    total_lines += result.lines

    _walk(root)

    emitter.emit(
        "SCAN_COMPLETE",
        files_counted=files_counted,
        files_skipped=files_skipped,
        total_bytes=total_bytes,
        total_words=total_words,
        total_lines=total_lines,
        elapsed_seconds=round(time.monotonic() - start, 4),
    )
