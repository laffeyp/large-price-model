# Sprint 002 — counter + scanner with signal emission

---

```yaml
---
id: 002
status: closed
phase: 1
pass_kind: functional
---
```

---

## scope

Author `src/wordcount/counter.py` (the pure `count_file(path) -> Counts | SkipReason` function) and `src/wordcount/scanner.py` (the `scan_dir(root, emitter)` function that walks the tree, calls counter, emits the scan-category signals: `SCAN_STARTED`, `DIR_ENTERED`, `FILE_COUNTED`, `FILE_SKIPPED`, `SCAN_COMPLETE`). No CLI entrypoint yet; sprint 003 lands `__main__.py` + JSONL sink.

Two files, one concept (filesystem traversal with signal emission). Within sprint sweet spot per AGENTS.md hard rule 6.

---

## prerequisites

- 001 (vocabulary lock + scaffold)

---

## context_files

- `sdd-kit-2/AGENTS.md`
- `sdd-kit-2/lib/sdd.py` (the `SignalVocabulary`, `SignalEmitter` API)
- `signals/0.1.json` (the locked vocabulary)
- `BLACKBOARD.md` (current `## Decisions`)
- `WORKING_AGREEMENT.md` (canonical home registry — `count_file` lives in `counter.py`, `scan_dir` in `scanner.py`)
- `src/wordcount/types.py` (the `Counts` dataclass)

---

## signal contract

### Emits

- `SCAN_STARTED` (`root_path`)
- `DIR_ENTERED` (`dir_path`, `entry_count`) — one per directory the scanner enters
- `FILE_COUNTED` (`file_path`, `bytes`, `lines`, `words`, `chars`) — per countable file
- `FILE_SKIPPED` (`file_path`, `reason`) — per skipped file; `reason` ∈ `{binary_detected, permission_denied, decode_error}`
- `SCAN_COMPLETE` (`files_counted`, `files_skipped`, `total_bytes`, `total_words`, `total_lines`, `elapsed_seconds`) — exactly once

### Consumes

- `signals/0.1.json` (loaded by the test harness to construct the vocabulary)

### Invariants

- No out-of-vocabulary tags emitted.
- `SCAN_COMPLETE.files_counted` equals the count of `FILE_COUNTED` signals in the trace.
- `SCAN_COMPLETE.files_skipped` equals the count of `FILE_SKIPPED` signals in the trace.
- A file's path appears in at most one of `FILE_COUNTED` or `FILE_SKIPPED` per scan.

---

## artifact contract

### Files created

- `src/wordcount/counter.py`
- `src/wordcount/scanner.py`
- `tests/test_counter.py`
- `tests/test_scanner.py`
- `tests/fixtures/sample_tree/` (3 files: 2 text, 1 binary)

### Files modified

- None.

### Content assertions

- `src/wordcount/counter.py` defines `def count_file(path: Path) -> Counts | SkipReason`.
- `src/wordcount/counter.py` defines `class SkipReason(Enum)` with members `BINARY_DETECTED`, `PERMISSION_DENIED`, `DECODE_ERROR`.
- `src/wordcount/scanner.py` defines `def scan_dir(root: Path, emitter: SignalEmitter) -> None`.
- `tests/test_scanner.py` includes at least one test that asserts on emitted signals via `SignalCapture` (per technique #38 — test fixtures from confirmed-good captures).

### Command exit codes

- `python -m pytest tests/test_counter.py -v` returns 0
- `python -m pytest tests/test_scanner.py -v` returns 0
- `python -m pytest tests/ -v` returns 0 (all sprint-002 tests pass; sprint-001 tests still pass)

---

## observation contract

`pass_kind: functional` — observation contract required per AGENTS.md hard rule 9.

### Input fixtures

- `tests/fixtures/sample_tree/` — a directory containing:
  - `hello.txt` (small text file, ~5 lines, ~15 words)
  - `nested/world.md` (small markdown file, ~3 lines, ~10 words)
  - `image.png` (small binary file, contains null bytes in first 1024)

### Expected runtime signals (in order)

- `SCAN_STARTED(root_path=<abs path to sample_tree>)` — exactly 1
- `DIR_ENTERED(dir_path=<abs path to sample_tree>, entry_count=3)` — exactly 1
- `DIR_ENTERED(dir_path=<abs path to sample_tree/nested>, entry_count=1)` — exactly 1
- `FILE_COUNTED` for `hello.txt` and `nested/world.md` — exactly 2
- `FILE_SKIPPED(reason="binary_detected")` for `image.png` — exactly 1
- `SCAN_COMPLETE(files_counted=2, files_skipped=1, total_words≈25, ...)` — exactly 1

### Expected log substrings

Not applicable (no human-facing logging in this sprint; CLI lands sprint 003).

### Expected screenshot / visual state

Not applicable (no UI).

---

## done criteria

`count_file` and `scan_dir` exist per canonical home registry; tests pass; the expected runtime signals fire in the right order with the right payloads when `scan_dir` is run against `tests/fixtures/sample_tree/`.

---

## notes

Binary detection heuristic: read the first 1024 bytes; if any null byte present, classify as binary. This is the standard `file(1)`-style heuristic. Not perfect (UTF-16 starts with a null byte for ASCII-range chars) but adequate for this example's scope.

Word counting: split on any whitespace via `str.split()` (no argument). This matches `wc -w` semantics for text files. Don't reinvent regex tokenization.

The scanner is tested via `SignalCapture` (technique #38): set up a fresh `SignalVocabulary` + `SignalEmitter`, run `scan_dir`, snapshot the buffer, assert on tag sequence + payloads. The artifact (the Python module) and the signal trace (the buffer snapshot) are both verifiable — dual contract holds.
