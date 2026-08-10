# Sprint 001 — signal emitter with strict validation

---

```yaml
---
id: 001
status: closed
phase: 1
pass_kind: architecture
---
```

---

## scope

Make the locked vocabulary loadable and validating from within a Python package. Three files: `pyproject.toml` (uv-managed, Python ≥ 3.11, pytest as the only dev dep, package discovery includes `sdd-kit-2/lib` so `import sdd` works), `src/price_space_llm/signals.py` (reads `signals/0.1.json`, wraps `sdd.SignalEmitter` with a strict-extras check that raises on any payload field not in the schema), and `tests/test_signals.py` (four tests: vocabulary loads, unknown tag raises, missing required field raises, extra payload field raises).

No JSONL sink this sprint. No MCP. No PyTorch. That work lands in Sprint 2 and later.

---

## prerequisites

- Sprint 0. `signals/0.1.json` locked at v0.1.

---

## context_files

- `sdd-kit-2/AGENTS.md`
- `sdd-kit-2/lib/sdd.py`
- `signals/0.1.json`
- `BLACKBOARD.md`
- `WORKING_AGREEMENT.md`
- `sdd-kit-2/example/src/wordcount/__main__.py`
- `sdd-kit-2/example/tests/test_scanner.py`

---

## signal contract

### Emits

Test-time only. The tests exercise the emitter and fire tags from the locked vocabulary. Expected during `pytest`:

- `SESSION_INIT` and `SESSION_COMPLETE` may fire in tests that need a bounded capture; not required.

The emitter itself fires no signals at import.

### Consumes

- `signals/0.1.json` at import time.

### Invariants

- No out-of-vocabulary tags emitted anywhere.
- Extra payload fields raise `ValueError` at the emit call (strict-extras per WORKING_AGREEMENT).
- Missing required payload fields raise `ValueError` (inherited from `sdd.SignalVocabulary.validate`).
- `signals/0.1.json` is read-only for this sprint.
- No runtime dependencies added. `pytest` is the one dev dep.
- No `SPY` string anywhere in `src/` (word-boundary, outside comments and docstrings).

---

## artifact contract

### Files created

- `pyproject.toml`
- `src/price_space_llm/signals.py`
- `tests/test_signals.py`

### Files modified

None.

### Content assertions

- `pyproject.toml` declares `name = "price-space-llm"`, `requires-python = ">=3.11"`, lists `pytest` in a dev group, and sets package discovery so both `src/price_space_llm/` and `sdd-kit-2/lib/` are importable.
- `src/price_space_llm/signals.py` defines `load_vocabulary(path=...) -> SignalVocabulary` that reads `signals/0.1.json` and returns an instance whose `tags()` length equals 55.
- `src/price_space_llm/signals.py` defines a class (name: `StrictSignalEmitter`) that either subclasses or delegates to `sdd.SignalEmitter` and overrides validation to raise on payload keys not in the tag's schema.
- `src/price_space_llm/signals.py` exports a module-level `emitter: StrictSignalEmitter` bound to the locked vocabulary.
- `src/price_space_llm/__init__.py` exists (empty).
- `tests/__init__.py` exists (empty).
- `tests/test_signals.py` contains four named tests: `test_locked_vocabulary_loads_with_55_tags`, `test_unknown_tag_raises`, `test_missing_required_payload_raises`, `test_extra_payload_field_raises`.

Empty `__init__.py` files count as ceremony, not code — three code files + two empty init files.

### Command exit codes

Architect runs each and reports the exit code.

- `python -m pytest tests/ -v` returns 0.
- `python -c "from price_space_llm.signals import emitter; print(len(emitter._vocab.tags()))"` prints `55` and returns 0.
- `python -c "from price_space_llm.signals import emitter; emitter.emit('NOT_A_REAL_TAG')"` returns non-zero; stderr contains `Unknown signal tag`.
- `python -c "from price_space_llm.signals import emitter; emitter.emit('SESSION_INIT', bogus_field=1)"` returns non-zero; stderr message names the unknown field.
- `grep -rE '\bSPY\b' src/ --include='*.py'` prints nothing.

---

## observation contract

Not applicable. `pass_kind: architecture`, no product behavior.

---

## done criteria

`price_space_llm.signals.emitter` imports. It loads the 55-tag locked vocabulary. It refuses unknown tags. It refuses unknown payload fields. Four tests pass.

---

## notes

**Import path for `sdd.py`.** `sdd-kit-2/lib/sdd.py` is in the repo. `pyproject.toml` adds `sdd-kit-2/lib` to package discovery; `from sdd import SignalVocabulary, SignalEmitter` works from any module. No `sys.path` hacks in the module.

**Why extend, not fork.** `sdd-kit-2/lib/sdd.py` is read-only per convention (AGENTS.md hard rule 1 applies to `foundations/`; `lib/` follows the same convention because the file ships upstream). The strict-extras posture is stricter than `SignalVocabulary.validate`. Extend it in `price_space_llm.signals`. `sdd.py` stays untouched.

**No JSONL sink this sprint.** The sink is Sprint 2. This sprint proves the emitter validates; the sink proves capture works.

---

## plan-mode review checklist

- [ ] Scope one paragraph, one concept.
- [ ] Three code files, two ceremony init files. Within hard rule 6.
- [ ] `context_files` covers the read set.
- [ ] Signal contract references only tags in `signals/0.1.json`.
- [ ] Artifact contract is gradable.
- [ ] No observation contract needed.
- [ ] Sprint dispatches on Architect "go".

---

*Sprint 001. Three code files. One concept: strict-validating emitter over the locked vocabulary.*
