# Sprint 001 — package scaffold + signal emitter

---

```yaml
---
id: 001
status: pending
phase: 1
pass_kind: architecture
---
```

---

## scope

Author the Python package `price_space_llm` under `src/` and make the locked vocabulary emittable from it. Concretely: (1) `pyproject.toml` that names the package, pins Python ≥ 3.11, and declares `pytest` as the sole dev dependency; (2) `src/price_space_llm/signals.py` that loads `signals/0.1.json` at import, wraps `sdd-kit-2/lib/sdd.py`'s `SignalEmitter` with the strict validator-extras posture WORKING_AGREEMENT commits to (extra payload fields raise, not just missing required fields), and adds an opt-in JSONL sink that writes one line per emit to `logs/{run_id}/signals.jsonl` on flush; (3) tests that verify the locked vocabulary loads, an unknown tag raises, missing required fields raise, extra payload fields raise, and the JSONL sink writes one line per emitted signal.

The concept is one: **make the vocabulary loadable, emittable, and testable from within a Python package that honors the working agreement's discipline**. Every downstream sprint's emit call goes through what this sprint lands.

---

## prerequisites

- Sprint 0 (Vocabulary Session) closed. `signals/0.1.json` locked at v0.1.

---

## context_files

- `sdd-kit-2/AGENTS.md` (working agreement — session-start read)
- `sdd-kit-2/lib/sdd.py` (the reference `SignalVocabulary` + `SignalEmitter` + `SignalCapture` surface — the exact API the project wraps)
- `signals/0.1.json` (the locked vocabulary — 55 tags, strict extras posture)
- `BLACKBOARD.md` (`## Decisions` for project scope)
- `WORKING_AGREEMENT.md` (canonical home registry places the emitter at `src/price_space_llm/signals.py`; vocabulary discipline is strict validator-extras)
- `sdd-kit-2/example/src/wordcount/__main__.py` (concrete `SignalVocabulary(json.loads(...))` + `SignalEmitter(vocab)` usage pattern to pattern-match against)
- `sdd-kit-2/example/tests/test_scanner.py` (concrete `SignalCapture` testing pattern)
- `sdd-kit-2/TECHNIQUES.md` §1 #2 (schema enforced at the speaker's mouth — the discipline this sprint operationalises)

---

## signal contract

### Emits

At sprint execution time, only during the test run. The tests exercise the emitter and therefore fire tags from the locked vocabulary. Expected during `pytest tests/test_signals.py -v`:

- `SESSION_INIT` (`run_id`, `run_kind='eval'`, `vocab_version='0.1'`, `config_hash`, `git_sha`, `data_hash`, `seed`) — fires once in the test that exercises the JSONL sink
- `SESSION_COMPLETE` (`run_id`, `exit_code=0`, `elapsed_seconds`, `n_signals_emitted`) — fires once in the same test

No pipeline emission this sprint. This is a content sprint whose runtime footprint is the test suite.

### Consumes

- `signals/0.1.json` at import time (loaded once by `price_space_llm.signals` module)

### Invariants

- No out-of-vocabulary tags emitted anywhere. The wrapper raises before any tag leaves the emitter.
- `signals/0.1.json` is read-only for this sprint; no write.
- No third-party runtime dependencies added (dev dependency `pytest` only).
- Strict validator-extras posture: any payload field not declared in the schema raises `ValueError` at the emit call, not just missing required fields.
- No `SPY` string anywhere in `src/` (per WORKING_AGREEMENT invariant — the greppability test).
- The package's Python 3.11 minimum matches WORKING_AGREEMENT.

---

## artifact contract

### Files created

- `pyproject.toml`
- `src/price_space_llm/__init__.py`
- `src/price_space_llm/signals.py`
- `tests/__init__.py`
- `tests/conftest.py`
- `tests/test_signals.py`

### Files modified

None.

### Content assertions

- `pyproject.toml` declares `name = "price-space-llm"`, `requires-python = ">=3.11"`, and lists `pytest` under a dev-dependency group.
- `src/price_space_llm/signals.py` defines `def load_vocabulary(path: Path = ...) -> SignalVocabulary` that reads `signals/0.1.json` from the project root and returns a `SignalVocabulary` instance whose `tags()` length equals 55.
- `src/price_space_llm/signals.py` defines a class (e.g. `StrictSignalEmitter`) that extends `sdd_kit_2.lib.sdd.SignalEmitter` (or delegates to it) with strict-extras validation: any payload key not in `schema[tag]["payload"]` raises `ValueError`.
- `src/price_space_llm/signals.py` exports a module-level `emitter: StrictSignalEmitter` bound to the locked vocabulary, plus `capture` (a context manager) and `Signal` (re-exported from `sdd_kit_2.lib.sdd`).
- `src/price_space_llm/signals.py` accepts an optional `jsonl_sink: Path | None` constructor argument that, when set, appends one JSON object per emit to that path on flush.
- `tests/test_signals.py` contains at least these named tests: `test_locked_vocabulary_loads`, `test_unknown_tag_raises`, `test_missing_required_payload_raises`, `test_extra_payload_field_raises`, `test_jsonl_sink_writes_one_line_per_emit`, `test_session_init_and_complete_bookend_a_capture`.
- No file under `src/` contains the string `SPY` (word-boundary, case-sensitive) outside a comment or docstring. `grep -rE '\bSPY\b' src/` returns empty (or only lines matching `#|"""`).

### Command exit codes

Architect runs each and reports the exit code. The Agent does not run these.

- `python -m pytest tests/ -v` returns 0.
- `python -c "from price_space_llm.signals import emitter; print(len(emitter._vocab.tags()))"` prints `55` and returns 0.
- `python -c "from price_space_llm.signals import emitter; emitter.emit('NOT_A_REAL_TAG')"` returns non-zero and stderr contains `Unknown signal tag`.
- `python -c "from price_space_llm.signals import emitter; emitter.emit('SESSION_INIT', bogus_field=1)"` returns non-zero and stderr contains `unknown payload field` (or equivalent strict-extras message).
- `grep -rE '\bSPY\b' src/ --include='*.py'` returns empty (exit 1 for grep-with-no-match is expected; the test asserts empty stdout).

---

## observation contract

Not applicable. `pass_kind: architecture` — this sprint produces no product behavior. The dual contract (signal + artifact) is the verification; no UI, no audio, no simulator run, no training loop invoked.

---

## done criteria

`price_space_llm.signals.emitter` is importable, loads the 55-tag locked vocabulary, refuses unknown tags and unknown payload fields, and streams to a JSONL sink when configured. The test suite (six named tests) passes clean.

---

## notes

**Why extend, not fork.** `sdd-kit-2/lib/sdd.py` is read-only per convention (AGENTS.md hard rule 1 for foundations; kit-adoption convention for `lib/`). The strict-extras posture WORKING_AGREEMENT commits to is stricter than the reference `SignalVocabulary.validate` (which checks required fields only). Extending — either by subclassing `SignalEmitter` and overriding the validate hook, or by delegating and pre-validating — keeps the vendored kit clean and the strict posture project-side.

**Why a JSONL sink now.** The reference `SignalCapture.format_for_ai` returns a formatted string for a paste-back workflow. This project's observation contract (WORKING_AGREEMENT § Observation contract environment) verifies via JSONL trace files. Landing the sink in Sprint 1 means every downstream sprint's emits are already trace-able; adding it in a later sprint would require retrofitting.

**Why no MCP or PyTorch this sprint.** Both need bridge mappings per AGENTS.md hard rule 10; the current `WORKING_AGREEMENT § External SDK bridge mappings` entries for them are stubs. First sprint to import either halts with `bridge_mapping_required`. Sprint 2 or 3 fills the MCP bridge mapping and lands `scripts/probe_channels.py`; the Pydantic bridge mapping fills alongside the ExperimentConfig work.

**pyproject.toml choices.** uv-managed (WORKING_AGREEMENT § Stack). Package name kebab-case (`price-space-llm`); import name snake_case (`price_space_llm`) — Python convention. Src-layout (`src/price_space_llm/`) — matches the canonical home registry.

**Vendoring `sdd-kit-2/lib/sdd.py`.** Import path: with src-layout and sdd-kit-2/ at project root, the cleanest import is a symlink or a `PYTHONPATH` addition. Simplest for this sprint: add a `[tool.hatch.build.targets.wheel] packages = ["src/price_space_llm"]` entry AND include sdd-kit-2/lib in `sys.path` via a small `conftest.py` shim, or vendor `sdd.py` as `src/price_space_llm/_sdd.py` and re-export. The **vendor** path is cleaner (no path shim); the **shim** path is honest about the read-only relationship. Architect calls it at plan-mode review; sprint executes accordingly.

---

## plan-mode review checklist

- [ ] Scope is concrete and bounded (one paragraph; one verifiable property of the artifact set).
- [ ] `context_files` covers everything the Agent needs to read; the wordcount example patterns are cited.
- [ ] Signal contract's `Emits` list references only tags in `signals/0.1.json` (SESSION_INIT + SESSION_COMPLETE, both in the locked v0.1).
- [ ] Artifact contract is gradable: content assertions are concrete, command exit codes are runnable.
- [ ] Observation contract is not required (`pass_kind: architecture`, no product behavior).
- [ ] Sprint sweet spot: 6 files, one concept. Above the ≤2 file ceiling (hard rule 6) but matches the wordcount Sprint 1 scaffold precedent (5 files for one scaffold concept). Confirm the concept-count discipline applies here.
- [ ] Vendor-vs-shim decision for `sdd-kit-2/lib/sdd.py` — Architect calls.
- [ ] Sprint dispatches after Architect says "go" (or names revisions).

---

*Sprint 001 — package scaffold + signal emitter. Six files, one concept. Plan-mode. Sprint 2 dispatches after this one closes clean.*
