# Sprint 001 — vocabulary lock + project scaffold

---

```yaml
---
id: 001
status: closed
phase: 0
pass_kind: architecture
---
```

---

## scope

Lock the project's signal vocabulary at version 0.1 (8 tags across 3 categories per the Vocabulary Session output) and establish the project's file scaffold: `signals/0.1.json`, `WORKING_AGREEMENT.md`, `src/wordcount/types.py` (the `Counts` dataclass), `BLACKBOARD.md` with the first Decision. No counting logic yet; this sprint is the founding act per AGENTS.md hard rule 12.

---

## prerequisites

- none (this is sprint 0 of the project)

---

## context_files

- `sdd-kit-2/AGENTS.md`
- `sdd-kit-2/grammar/PRINCIPLES.md`
- `sdd-kit-2/grammar/BOOTSTRAP.md`
- `sdd-kit-2/templates/VOCABULARY.json`
- `sdd-kit-2/templates/BLACKBOARD.md`
- `sdd-kit-2/templates/WORKING_AGREEMENT.md`

---

## signal contract

### Emits

None during sprint execution. This is a content sprint; no runtime emission. The Signal Report's `signal_trace` is empty.

### Consumes

- The Vocabulary Session's output (a 30-minute Architect+Agent conversation captured separately).

### Invariants

- `signals/0.1.json` validates as JSON.
- Every tag has the required keys: `name`, `category`, `stratum`, `payload`, `note`.
- Every category referenced by a tag exists in the `categories` array.

---

## artifact contract

### Files created

- `signals/0.1.json`
- `WORKING_AGREEMENT.md`
- `src/wordcount/__init__.py` (empty)
- `src/wordcount/types.py` (the `Counts` dataclass)
- `BLACKBOARD.md` (with the first Decision)

### Files modified

- None (greenfield).

### Content assertions

- `signals/0.1.json` validates as JSON; contains 8 tags across 3 categories named `session`, `scan`, `report`.
- `signals/0.1.json` contains tag `SESSION_INIT` with payload field `vocab_version`.
- `signals/0.1.json` contains tag `SCAN_COMPLETE` with payload fields including `files_counted` and `total_words`.
- `WORKING_AGREEMENT.md` contains a `## Canonical home registry` section listing `Counts`, `count_file`, `scan_dir`, `format_json_report`, `main`.
- `src/wordcount/types.py` defines `@dataclass class Counts` with fields `bytes: int`, `lines: int`, `words: int`, `chars: int`.
- `BLACKBOARD.md` contains a `## Decisions` entry: "wordcount is a directory-walking word/line/char counter that emits typed signals and produces a JSON report."

### Command exit codes

- `python -c "import json; json.load(open('signals/0.1.json'))"` returns 0
- `python -c "from src.wordcount.types import Counts; c = Counts(1,1,1,1); assert c.bytes == 1"` returns 0

---

## observation contract

Not applicable. This sprint produces no runtime behavior — content-only architecture sprint.

---

## done criteria

`signals/0.1.json` is locked at version 0.1 and the project's canonical-home registry is established. No counting logic exists yet; sprint 002 will land it against this contract.

---

## notes

The Vocabulary Session settled on 8 tags. Notable decisions during the session:

- `SESSION_INIT` and `SCAN_STARTED` are intentionally separate so a future sprint can add pre-scan validation between them without breaking the SESSION_INIT-must-be-first invariant.
- `FILE_SKIPPED` is incident-stratum (rare-and-actionable) not event-stratum (one-per-file); rationale is that a binary file skip is something the user wants surfaced, not just logged.
- `SCAN_COMPLETE` is summary-stratum so it fires exactly once and carries the aggregates. Per technique #51 (always-emit summary + paired incident), `FILE_SKIPPED` is the paired incident.
- Validator-extras posture chosen: **strict**. Documented in `WORKING_AGREEMENT.md`.

The full Vocabulary Session rationale is in `signals/0.1.json`'s `rationale` field.
