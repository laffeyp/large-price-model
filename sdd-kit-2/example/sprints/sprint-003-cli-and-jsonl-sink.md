# Sprint 003 — CLI entrypoint + JSONL signal sink

---

```yaml
---
id: 003
status: closed
phase: 1
pass_kind: functional
---
```

---

## scope

Author `src/wordcount/__main__.py` (the CLI entrypoint) and `src/wordcount/report.py` (the JSON report formatter). The CLI accepts a directory path + optional `--signals-out=PATH` flag; runs `scan_dir`; emits `SESSION_INIT` first and `SESSION_COMPLETE` last; emits `REPORT_EMITTED` after writing the JSON; flushes the signal buffer to JSONL if `--signals-out` is provided.

Two files, one concept (CLI assembly + sink). Within sprint sweet spot.

---

## prerequisites

- 001 (vocabulary lock + scaffold)
- 002 (counter + scanner)

---

## context_files

- `sdd-kit-2/AGENTS.md`
- `sdd-kit-2/TECHNIQUES.md` (Section 2 → CLI / command-line — specifically: exit codes as contract; stdout for data, stderr for narration; flag-driven instrumentation)
- `sdd-kit-2/lib/sdd.py` (the `SignalCapture.as_json()` method for sink)
- `signals/0.1.json`
- `BLACKBOARD.md`
- `WORKING_AGREEMENT.md`
- `src/wordcount/scanner.py` (the scanner this sprint will wire up)
- `src/wordcount/types.py`

---

## signal contract

### Emits

- `SESSION_INIT` (`root_path`, `vocab_version`, `config_signals_out`) — first signal in every run
- `SESSION_COMPLETE` (`exit_code`, `elapsed_seconds`) — last signal in every run
- `REPORT_EMITTED` (`output_format`, `byte_count`, `destination`) — after the JSON report is written
- (Plus all signals from sprint 002 fire transitively via the wired-up `scan_dir`.)

### Consumes

- `scanner.scan_dir` (from sprint 002)
- `signals/0.1.json` (loaded by `__main__.py`)

### Invariants

- `SESSION_INIT` is the first signal in every capture.
- `SESSION_COMPLETE` is the last signal in every capture.
- `REPORT_EMITTED.byte_count` equals the size of bytes written to destination.
- Exit code 0 ⇔ `files_skipped == 0`; exit code 2 ⇔ `files_skipped > 0`; exit code 1 ⇔ unrecoverable error (root path doesn't exist, etc.).

---

## artifact contract

### Files created

- `src/wordcount/__main__.py`
- `src/wordcount/report.py`
- `tests/test_cli.py`
- `tests/test_report.py`

### Files modified

- None.

### Content assertions

- `src/wordcount/__main__.py` defines `def main(argv: list[str] | None = None) -> int`.
- `src/wordcount/__main__.py` has the `if __name__ == "__main__": sys.exit(main())` idiom.
- `src/wordcount/report.py` defines `def format_json_report(scan_result: dict) -> str` and produces output that `json.loads` round-trips.
- `tests/test_cli.py` includes a test that runs `main(["./tests/fixtures/sample_tree/", "--signals-out=/tmp/wc_trace.jsonl"])`, asserts exit code 2 (because the binary file is skipped), and asserts the JSONL file contains a SESSION_INIT line first and a SESSION_COMPLETE line last.

### Command exit codes

- `python -m pytest tests/ -v` returns 0 (all sprints' tests pass)
- `python -m wordcount tests/fixtures/sample_tree/` returns 2 (because of the skipped binary)
- `python -m wordcount /nonexistent/path/` returns 1

---

## observation contract

### Input fixtures

- `tests/fixtures/sample_tree/` (from sprint 002 — 2 text files + 1 binary)

### CLI driving steps

```
python -m wordcount tests/fixtures/sample_tree/ --signals-out=/tmp/wc_trace.jsonl > /tmp/wc_report.json
```

### Expected log substrings

- Stderr contains substring `"skipped:"` exactly 1 time (for the binary file).
- Stderr contains substring `"scanned"` exactly 1 time (in the closing summary).

### Expected runtime signals

The JSONL trace at `/tmp/wc_trace.jsonl` contains, in order:

- Line 1: `SESSION_INIT` with `root_path` matching the absolute path of `tests/fixtures/sample_tree/`.
- Lines 2–8: the 7 scan-category signals from sprint 002's observation contract (SCAN_STARTED, 2x DIR_ENTERED, 2x FILE_COUNTED, 1x FILE_SKIPPED, SCAN_COMPLETE) in sorted-entry order (hello.txt → image.png → nested → nested/world.md).
- Line 9: `REPORT_EMITTED(output_format="json", byte_count=N, destination="stdout")`.
- Line 10: `SESSION_COMPLETE(exit_code=2, ...)`.

(Total 10 lines.)

### Expected output

- `/tmp/wc_report.json` parses as JSON.
- The report's top-level keys include `files_counted`, `files_skipped`, `total_bytes`, `total_words`, `total_lines`.
- `report["files_counted"] == 2` and `report["files_skipped"] == 1`.

---

## done criteria

The CLI runs end-to-end on `tests/fixtures/sample_tree/`, produces a JSON report on stdout, emits the full signal trace to JSONL when `--signals-out` is set, and returns the right exit code based on skip-count. All sprint 001-003 tests pass.

---

## notes

Per WORKING_AGREEMENT.md tone canon: lowercase first word in error messages, no exclamation marks, no emoji. The stderr summary line should read like: `"scanned 2 files, skipped 1 file (binary_detected), 25 words, 8 lines, in 0.012s"`.

`--signals-out=PATH` writes one JSON object per line (JSONL format) so it composes into Unix pipelines. Per TECHNIQUES.md Section 2 → CLI → "Flag-driven instrumentation": the signal sink is optional and side-effect-only; the CLI's main path doesn't depend on its presence.

If `--signals-out` is omitted, the signal trace lives only in the in-memory deque and is lost when the process exits. The Rubber Duck Pass at this sprint's close uses the JSONL trace from the test run, not the in-memory state.
