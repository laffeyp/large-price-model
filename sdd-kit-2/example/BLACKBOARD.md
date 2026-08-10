# BLACKBOARD.md — wordcount

*Single writer per section. Discipline, not code-enforced. See `sdd-kit-2/AGENTS.md` § The BLACKBOARD protocol.*

---

## Surfaced for review

*You (Agent) and the Architect. Halts, partials, comprehension affirmations, Rubber Duck observations marked `surfaced`.*

- **2026-05-20 Claude Code (Opus 4.7)** — COMPREHENSION_AFFIRMATION: I have read sdd-kit-2/foundations 01 and 04, AGENTS.md, grammar/PRINCIPLES.md, and the BLACKBOARD's first Decision. This project is `wordcount`, a tiny directory-walking CLI that counts words/lines/chars per file and produces a JSON report — the explicit purpose is to demonstrate sdd-kit-2's discipline on a small enough project that the kit's overhead is visible. SDD at root replaces the lossy human-description step with designed, typed signals: vocabulary as a first-class API contract; signals as structured events not log lines; the program's runtime trace becomes machine-readable by the next session's agent. The kit's canonical loop here is: I read the next sprint card from sprints/, execute via Read/Write/Edit, return a Signal Report per templates/SIGNAL_REPORT.md, run the Rubber Duck Pass at sprint close per the procedure in AGENTS.md, write to BLACKBOARD sections per single-writer discipline (never to ## Decisions which is Architect-only). For this project specifically: vocabulary is locked at signals/0.1.json with 8 tags across 3 categories (session, scan, report); canonical home registry is in WORKING_AGREEMENT.md and lists Counts, count_file, scan_dir, format_json_report, main; build command is `python -m pytest tests/ -v`; class is CLI so I consult TECHNIQUES.md Section 2 → CLI subsection for class-specific techniques (exit codes as contract, stdout for data / stderr for narration, flag-driven instrumentation). The hard rule binding me: halt and ask when uncertain. If a sprint's scope is unclear or I can't predict what a passing Signal Report should contain, I write to ## Surfaced for review and stop rather than paper over.

- **2026-05-21 Architect** — Acknowledged. Affirmation is real. Proceed to sprint 001.

- **2026-05-22 Claude Code** — Sprint 002 Rubber Duck Pass observation #2 (surfaced, not halted): the spec said "`FILE_SKIPPED` payload includes `reason`" but didn't specify what enum values `reason` could take. I emitted `binary_detected`, `permission_denied`, `decode_error` based on the implementation. Surfacing in case the Architect wants to formalize these in the vocabulary (currently `signals/0.1.json` says `reason` is a string with no enum). Disposition: surfaced; not blocking. The Architect can add an enum constraint in a future vocabulary bump or leave it as documentation.

- **2026-05-22 Architect** — Leave as documentation for now. If a future sprint needs to dispatch on reason, we'll formalize then. Updated rationale field in `signals/0.1.json` to mention the three values as the current enum.

---

## Decisions

*Architect-only, append-only.*

- **2026-05-20** — Project scope: wordcount is a tiny Python CLI that walks a directory tree, counts words/lines/chars per text file (skipping binaries), and produces a JSON report on stdout. Signals emitted at every meaningful boundary (session, dir entry, per-file, summary). Optional JSONL sink via `--signals-out=PATH`. Purpose: a worked example for sdd-kit-2's `example/` folder. Three sprints. Plan-mode per sprint.

- **2026-05-20** — Stack: Python 3.11+, stdlib only for core, `lib/sdd.py` for signal emission, `pytest` for tests. No additions without surfacing.

- **2026-05-20** — Vocabulary version locked at 0.1 after the Vocabulary Session: 8 tags across 3 categories (session, scan, report). Stratified per grammar/PRINCIPLES.md commitment 5. Validator-extras posture: strict.

- **2026-05-22** — `reason` field on `FILE_SKIPPED` stays as documentation-typed string (enum-like values `binary_detected | permission_denied | decode_error` enumerated in rationale, not enforced in payload schema). Re-visit if a future sprint dispatches on reason.

---

## Built

*Agent appends one entry per sprint close. Append-only.*

- **Sprint 001 (2026-05-21)** — Vocabulary lock + scaffold. `signals/0.1.json` (8 tags), `WORKING_AGREEMENT.md` (canonical home registry, tone canon, build commands), `src/wordcount/__init__.py`, `src/wordcount/types.py` (the `Counts` dataclass), this BLACKBOARD with first Decision. Dual contract: signal (vacuous — content sprint) + artifact (all assertions pass; `python -c "import json; json.load(open('signals/0.1.json'))"` exit 0). Rubber Duck Pass: vacuous (no runtime signals). No Surfaced entries.

- **Sprint 002 (2026-05-22)** — Counter + scanner. `src/wordcount/counter.py` (the pure `count_file` function + `SkipReason` enum), `src/wordcount/scanner.py` (the `scan_dir` function emitting scan-category signals), `tests/test_counter.py`, `tests/test_scanner.py`, `tests/fixtures/sample_tree/` (hello.txt, nested/world.md, image.png). Dual contract: signal (all 5 expected scan signals fire in correct order with correct payloads, verified via `SignalCapture` in `tests/test_scanner.py::test_scan_emits_expected_sequence`) + artifact (`pytest tests/` exit 0). Observation contract: all 6 expected runtime signals verified. Rubber Duck Pass: 3 observations, 1 resolved-here, 1 surfaced (FILE_SKIPPED.reason enum — see ## Surfaced for review), 1 deferred (drift watchlist — see below).

- **Sprint 003 (2026-05-23)** — CLI + JSONL sink. `src/wordcount/__main__.py` (the `main()` entrypoint wiring SignalVocabulary + SignalEmitter + scanner + report + sink), `src/wordcount/report.py` (the `format_json_report` formatter), `tests/test_cli.py`, `tests/test_report.py`. Dual contract: signal (SESSION_INIT first, SESSION_COMPLETE last, REPORT_EMITTED after report write, all verified via tests/test_cli.py end-to-end run) + artifact (`pytest tests/ -v` exit 0; `python -m wordcount tests/fixtures/sample_tree/` exit 2). Observation contract: all 10 expected JSONL lines present in correct sorted-entry order. Rubber Duck Pass: 1 observation, resolved-here (initial implementation had `byte_count` measured before write rather than after; corrected to write-then-size).

---

## Deferred

*Anyone may append. Re-visit conditions noted.*

- **2026-05-22 (Agent, drift watchlist disposition from sprint 002 Pass)** — The `entry_count` payload on `DIR_ENTERED` counts only direct children, not recursive descendants. The vocabulary's note field is silent on this. Re-visit when the first user asks "why doesn't `DIR_ENTERED(entry_count=3)` plus the child `DIR_ENTERED(entry_count=1)` add up to the total `FILE_COUNTED` count?" If asked, clarify in the rationale field that `entry_count` is non-recursive.

- **2026-05-23 (Agent)** — A `--format=json|yaml|csv` flag would generalize the report writer, but it's out of scope for the example. The current code hardcodes JSON. If a future sprint adds the flag, the `REPORT_EMITTED.output_format` field is already in place to receive the variant.

---

## Open questions

*Anyone may append.*

- None outstanding.

---

## Drift watchlist

*Agent maintains. Patterns to monitor across sprints.*

- **DIR_ENTERED.entry_count semantics** — tracked under ## Deferred. Re-visit when user surfaces confusion.

- **Path handling: `pathlib.Path` vs `str`** — counter.py + scanner.py use `Path` exclusively in signatures. If a future sprint accidentally takes a `str`, that's an integration drift; the canonical home registry implicitly assumes `Path`. Add to registry explicitly if violated.

---

## Sprint tail

*Agent maintains. Last 10 sprint summaries; older entries roll into `## Built` as compressed paragraphs.*

### Sprint 003 (2026-05-23, closed)
- **Scope:** CLI entrypoint + JSONL signal sink. Two files (`__main__.py`, `report.py`) + their tests. Wires SignalVocabulary + SignalEmitter from `lib/sdd.py` against sprint-002's scanner.
- **Dual contract:** signal pass (full end-to-end trace verified in test_cli.py — SESSION_INIT first, SESSION_COMPLETE last, REPORT_EMITTED after report write, 10 lines total in JSONL); artifact pass (`pytest tests/ -v` exit 0; manual `python -m wordcount tests/fixtures/sample_tree/` exit 2).
- **Observation contract:** pass (all 10 expected JSONL lines in correct sorted-entry order; stderr summary line matches tone canon).
- **Rubber Duck Pass:**
  - *Sequence narration:* t=0.000 SESSION_INIT (root_path=/abs/.../sample_tree, vocab_version=0.1, config_signals_out=/tmp/wc_trace.jsonl). t=0.0001 SCAN_STARTED. t=0.0002 DIR_ENTERED (root, entry_count=3). t=0.0004 FILE_COUNTED (hello.txt, words=23). t=0.0006 FILE_SKIPPED (image.png, reason=binary_detected). t=0.0008 DIR_ENTERED (nested, entry_count=1). t=0.0010 FILE_COUNTED (nested/world.md, words=11). t=0.0012 SCAN_COMPLETE (files_counted=2, files_skipped=1, total_words=34). t=0.0014 REPORT_EMITTED (output_format=json, byte_count=N, destination=stdout). t=0.0016 SESSION_COMPLETE (exit_code=2, elapsed_seconds≈0.002).
  - *Observation 1 (payload anomaly):* initial implementation emitted REPORT_EMITTED with byte_count measured before the report was written, giving stale length. Disposition: resolved-here — moved the emit to after `sys.stdout.write()` so the byte count reflects what was actually written. Invariant in the vocab ("REPORT_EMITTED.byte_count must equal the size of the bytes written to destination") now holds.
- **Files:** src/wordcount/__main__.py, src/wordcount/report.py, tests/test_cli.py, tests/test_report.py
- **Closed:** clean, no surfacing required.

### Sprint 002 (2026-05-22, closed)
- **Scope:** Counter + scanner. `count_file(path) -> Counts | SkipReason` + `scan_dir(root, emitter)`. Two files + tests + fixtures.
- **Dual contract:** signal pass (5 expected scan signals fire in correct order, verified via SignalCapture in test_scanner.py); artifact pass (pytest tests/ exit 0).
- **Observation contract:** pass (6 expected runtime signals all present with correct payloads).
- **Rubber Duck Pass:**
  - *Sequence narration:* t=0.000 SCAN_STARTED. t=0.0001 DIR_ENTERED (sample_tree, entry_count=3). t=0.0002 FILE_COUNTED (hello.txt). t=0.0003 FILE_SKIPPED (image.png, reason=binary_detected). t=0.0004 DIR_ENTERED (nested, entry_count=1). t=0.0005 FILE_COUNTED (nested/world.md). t=0.0006 SCAN_COMPLETE (files_counted=2, files_skipped=1). (Order is alphabetical-sort within each directory: hello.txt < image.png < nested/.)
  - *Observation 1 (resolved-here, missing pair):* initial implementation skipped `DIR_ENTERED` for the nested subdirectory because `os.walk` only yielded its files inline. Fixed by switching to manual recursion that explicitly emits per-directory.
  - *Observation 2 (surfaced):* `FILE_SKIPPED.reason` enum not formalized in vocabulary; emitting `binary_detected | permission_denied | decode_error`. See ## Surfaced for review. Architect resolved 2026-05-22 to leave as documentation.
  - *Observation 3 (deferred, vocabulary gap):* `DIR_ENTERED.entry_count` semantics ambiguous — non-recursive but vocabulary's note is silent. Added to ## Drift watchlist + ## Deferred. Re-visit when first user confusion appears.

### Sprint 001 (2026-05-21, closed)
- **Scope:** Vocabulary lock + scaffold. signals/0.1.json + WORKING_AGREEMENT.md + types.py + first BLACKBOARD Decision.
- **Dual contract:** signal vacuous (no runtime emission this sprint); artifact pass.
- **Observation contract:** N/A (content sprint).
- **Rubber Duck Pass:** N/A (no runtime signals to narrate).
- **Closed:** clean.

---

*BLACKBOARD.md for wordcount. Three sprints closed (001-003). One COMPREHENSION_AFFIRMATION on file. One surfaced item (resolved). Two deferred items. Drift watchlist active on entry_count semantics + Path-vs-str discipline. Project complete as an example; not under active development.*
