# WORKING_AGREEMENT.md — wordcount

*Project-specific overrides on top of `sdd-kit-2/AGENTS.md`. The kit's discipline applies unchanged unless this file says otherwise. AGENTS.md is the foundation; this is the per-project extension.*

---

## Project class

CLI / command-line. (Consult `TECHNIQUES.md` Section 2 → CLI / command-line subsection during sprint composition.)

---

## Stack

- Python 3.11+
- Standard library only for `wordcount` core; no dependencies.
- `sdd-kit-2/lib/sdd.py` for signal emission (vendored as a sibling import).
- `pytest` for tests (dev-only).

No additions without surfacing per AGENTS.md hard rule about dependencies.

---

## Canonical home registry

| Type | Lives in | Notes |
|---|---|---|
| `Counts` (dataclass: bytes, lines, words, chars) | `src/wordcount/types.py` | Sole declaration. Imported elsewhere. |
| `count_file(path) -> Counts \| SkipReason` | `src/wordcount/counter.py` | Pure function; no I/O beyond reading the named file. |
| `scan_dir(root, emitter)` | `src/wordcount/scanner.py` | Walks the tree, calls counter, emits scan signals. |
| `format_json_report(scan_result) -> str` | `src/wordcount/report.py` | Pure formatter; no I/O. |
| `main(argv) -> int` | `src/wordcount/__main__.py` | The CLI entrypoint. Wires SignalEmitter, calls scanner, writes report, emits SESSION_COMPLETE. |
| Vocabulary | `signals/0.1.json` | Locked. Loaded by `__main__.py` via `SignalVocabulary(json.loads(...))`. |

Per AGENTS.md hard rule 7: workers consult this registry before authoring; do not introduce a second home for any type listed above.

---

## External SDK bridge mappings

None. The project uses only `lib/sdd.py` (an internal kit module, not an external SDK) and the Python standard library.

---

## Tone canon

The CLI's user-facing strings (stderr progress, --help text, error messages) follow these rules:

- Lowercase first word in error messages (`"could not read file: ..."`, not `"Could not read file: ..."`).
- No exclamation points anywhere.
- No emoji.
- Error messages name the file path absolutely, never relatively.
- Skip reasons are short enum-like strings (`"binary_detected"`, `"permission_denied"`, `"decode_error"`) — not free-form sentences.

---

## Build commands

The Architect runs these by hand at sprint close; the Agent does not.

- `python -m pytest tests/ -v` — full test suite. Expected exit 0.
- `python -m wordcount example_data/ --signals-out=/tmp/trace.jsonl` — manual smoke test.
- `python -c "import json; [json.loads(l) for l in open('/tmp/trace.jsonl')]"` — verify JSONL is well-formed.

---

## Validator-extras posture

**Strict.** Extra fields in signal payloads (beyond what `signals/0.1.json` declares as `payload`) raise `ValueError` at emit time. (Same as Katybird's posture; not Trading System's documentation-only posture.) Rationale: this project is small enough that drift would compound fast; strictness catches mismatches at the emit call.

---

## Hand-authorization log

(Per AGENTS.md hard rule 10: explicit hand-authorizations logged here.)

- None to date.

---

## Cadence

- Sprint 001-003: plan-mode-per-sprint (Architect reviews each card before dispatch).
- Future sprints (if any): cadence revisits at phase boundary.

---

*WORKING_AGREEMENT.md for wordcount. Project class CLI. Strict validator extras. No external SDK bridges. Canonical home registry covers all public types. Run `python -m pytest tests/ -v` to grade.*
