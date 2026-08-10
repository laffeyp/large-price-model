"""test_scanner.py — observation-contract tests via SignalCapture.

Per TECHNIQUES.md technique #38 (test fixtures from confirmed-good captures):
each test runs scan_dir against a fixture tree, snapshots the signal buffer,
and asserts on the snapshot. The artifact (the Python module) and the signal
trace (the buffer) are both verifiable — dual contract holds.
"""
import json
from pathlib import Path

from sdd import SignalVocabulary, SignalEmitter
from wordcount.scanner import scan_dir


FIXTURES = Path(__file__).parent / "fixtures" / "sample_tree"
VOCAB_PATH = Path(__file__).parent.parent / "signals" / "0.1.json"


def _make_emitter() -> SignalEmitter:
    raw = json.loads(VOCAB_PATH.read_text())
    schema = {
        tag["name"]: {
            "category": tag["category"],
            "payload": tag.get("payload", []),
            "note": tag.get("note", ""),
        }
        for tag in raw["tags"]
    }
    return SignalEmitter(SignalVocabulary(schema))


def test_scan_emits_expected_sequence():
    """The full sprint-002 observation contract."""
    emitter = _make_emitter()
    scan_dir(FIXTURES, emitter)
    sigs = emitter.snapshot()
    tags = [s.tag for s in sigs]

    # Per the sprint card's observation contract: exact tag counts.
    assert tags.count("SCAN_STARTED") == 1
    assert tags.count("DIR_ENTERED") == 2   # root + nested
    assert tags.count("FILE_COUNTED") == 2  # hello.txt + nested/world.md
    assert tags.count("FILE_SKIPPED") == 1  # image.png
    assert tags.count("SCAN_COMPLETE") == 1

    # SCAN_STARTED first, SCAN_COMPLETE last among scan-category.
    assert tags[0] == "SCAN_STARTED"
    assert tags[-1] == "SCAN_COMPLETE"

    # SCAN_COMPLETE payload aggregates match per-file emissions.
    complete = next(s for s in sigs if s.tag == "SCAN_COMPLETE")
    assert complete.payload["files_counted"] == 2
    assert complete.payload["files_skipped"] == 1


def test_skipped_file_has_reason_enum():
    """FILE_SKIPPED.reason matches one of the documented enum values."""
    emitter = _make_emitter()
    scan_dir(FIXTURES, emitter)
    skipped = [s for s in emitter.snapshot() if s.tag == "FILE_SKIPPED"]
    assert len(skipped) == 1
    assert skipped[0].payload["reason"] in {"binary_detected", "permission_denied", "decode_error"}


def test_each_file_appears_in_at_most_one_per_run():
    """Vocabulary invariant: FILE_COUNTED and FILE_SKIPPED are mutually exclusive per path."""
    emitter = _make_emitter()
    scan_dir(FIXTURES, emitter)
    sigs = emitter.snapshot()
    counted_paths = {s.payload["file_path"] for s in sigs if s.tag == "FILE_COUNTED"}
    skipped_paths = {s.payload["file_path"] for s in sigs if s.tag == "FILE_SKIPPED"}
    assert counted_paths.isdisjoint(skipped_paths)
