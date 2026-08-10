"""__main__.py — wordcount CLI entrypoint.

Per WORKING_AGREEMENT.md canonical home registry: main() lives here. Wires
SignalVocabulary + SignalEmitter from sdd-kit-2/lib/sdd.py against the
scanner, writes the JSON report to stdout, optionally dumps the signal trace
to JSONL.

Per AGENTS.md hard rule 5 (comprehension-as-prerequisite) the main() function
emits SESSION_INIT first and SESSION_COMPLETE last unconditionally — those
are the bookends every replay anchors against.

Exit codes per WORKING_AGREEMENT.md:
- 0: success, no files skipped
- 1: unrecoverable error (root path doesn't exist, etc.)
- 2: partial — some files skipped
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

# Import sdd from the kit's lib/ folder. Projects vendor or symlink as
# appropriate; the example assumes lib/ is on PYTHONPATH.
from sdd import SignalVocabulary, SignalEmitter, SignalCapture
from wordcount.scanner import scan_dir
from wordcount.report import format_json_report


def _load_vocabulary(path: Path) -> SignalVocabulary:
    """Load signals/0.1.json and adapt to SignalVocabulary's schema dict."""
    raw = json.loads(path.read_text())
    schema = {}
    for tag in raw.get("tags", []):
        schema[tag["name"]] = {
            "category": tag.get("category", "event"),
            "payload": tag.get("payload", []),
            "note": tag.get("note", ""),
        }
    return SignalVocabulary(schema)


def _parse_args(argv: list[str]) -> tuple[Path, Path | None]:
    """Tiny arg parser. Avoids argparse to keep the example small.

    Usage: python -m wordcount <root> [--signals-out=PATH]
    """
    root = None
    signals_out = None
    for arg in argv:
        if arg.startswith("--signals-out="):
            signals_out = Path(arg.split("=", 1)[1])
        elif arg.startswith("--"):
            raise SystemExit(f"unknown flag: {arg}")
        else:
            if root is not None:
                raise SystemExit("only one root path accepted")
            root = Path(arg)
    if root is None:
        raise SystemExit("usage: python -m wordcount <root> [--signals-out=PATH]")
    return root, signals_out


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    root, signals_out = _parse_args(argv)

    if not root.exists():
        sys.stderr.write(f"path does not exist: {root.absolute()}\n")
        return 1
    if not root.is_dir():
        sys.stderr.write(f"path is not a directory: {root.absolute()}\n")
        return 1

    # Vocabulary lives at signals/0.1.json relative to project root. The
    # CLI assumes it's launched from the project root.
    vocab_path = Path("signals/0.1.json")
    if not vocab_path.exists():
        sys.stderr.write(f"vocabulary not found: {vocab_path.absolute()}\n")
        return 1

    vocabulary = _load_vocabulary(vocab_path)
    emitter = SignalEmitter(vocabulary)

    start = time.monotonic()

    emitter.emit(
        "SESSION_INIT",
        root_path=str(root.absolute()),
        vocab_version="0.1",
        config_signals_out=str(signals_out.absolute()) if signals_out else "",
    )

    scan_dir(root, emitter)

    # Reconstruct scan-result aggregates from the SCAN_COMPLETE signal in the
    # buffer. Per technique #52 (operator-chain category alignment), the
    # summary signal is authoritative.
    snapshot = emitter.snapshot()
    scan_complete = next(s for s in snapshot if s.tag == "SCAN_COMPLETE")
    scan_result = dict(scan_complete.payload)

    report = format_json_report(scan_result)
    report_bytes = report.encode("utf-8")
    sys.stdout.write(report)
    sys.stdout.flush()

    # Per sprint 003 Rubber Duck observation: emit REPORT_EMITTED AFTER the
    # write so byte_count reflects what was actually written.
    emitter.emit(
        "REPORT_EMITTED",
        output_format="json",
        byte_count=len(report_bytes),
        destination="stdout",
    )

    # Stderr summary line per WORKING_AGREEMENT.md tone canon.
    skipped_phrase = ""
    if scan_result["files_skipped"]:
        skipped_phrase = f", skipped {scan_result['files_skipped']} file(s)"
    sys.stderr.write(
        f"scanned {scan_result['files_counted']} files{skipped_phrase}, "
        f"{scan_result['total_words']} words, "
        f"{scan_result['total_lines']} lines, "
        f"in {scan_result['elapsed_seconds']}s\n"
    )

    exit_code = 2 if scan_result["files_skipped"] else 0

    emitter.emit(
        "SESSION_COMPLETE",
        exit_code=exit_code,
        elapsed_seconds=round(time.monotonic() - start, 4),
    )

    # JSONL sink (flag-driven instrumentation per TECHNIQUES.md Section 2 → CLI).
    if signals_out:
        with signals_out.open("w", encoding="utf-8") as f:
            for sig in emitter.snapshot():
                f.write(json.dumps(sig.to_dict()) + "\n")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
