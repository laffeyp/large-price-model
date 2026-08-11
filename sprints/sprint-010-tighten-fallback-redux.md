# Sprint 010 — tighten `_parse_type` fallback (Sprint 007 redux against v0.2)

---

```yaml
---
id: 010
status: closed
phase: 1
pass_kind: architecture
determinism_budget: n/a
---
```

---

## scope

Re-execute Sprint 007's scope now that v0.2 has landed with the type correction. `_parse_type` raises `ValueError` on unknown type strings; `StrictSignalVocabulary.__init__` raises if any tag's schema entry lacks `field_types`. Two new tests exercise both raise paths.

v0.2 loads cleanly under the tightened parser because `struct` is now recognised (Sprint 008) and `CAPACITY_SWEEP_COMPLETED.points` uses the canonical form (Sprint 009). Sprint 007's halt condition (`vocabulary_change_required`) is satisfied.

---

## prerequisites

- Sprint 007 halted (redux is this sprint).
- Sprint 008 closed (struct parser landed).
- Sprint 009 closed (v0.2 locked with the type correction).

---

## context_files

- `sprints/sprint-007-tighten-permissive-fallbacks.md` (the halted original — this sprint is the redux)
- `src/price_space_llm/signals.py` (`_parse_type` fallback at line ~215; `StrictSignalVocabulary.__init__` at ~229)
- `tests/test_signals.py`
- `signals/0.2.json` (the locked vocabulary this sprint validates loading against)

---

## signal contract

### Emits

Test-time only.

### Consumes

- `signals/0.2.json` at load.

### Invariants

- All 23 existing tests pass unchanged.
- `_parse_type("nonexistent_type")` raises `ValueError`.
- `StrictSignalVocabulary(schema)` raises if any tag's entry lacks `field_types`.
- v0.2 vocabulary loads cleanly under the tighter parser.

---

## artifact contract

### Files modified

- `src/price_space_llm/signals.py` — `_parse_type` raises `ValueError` on unknown type strings (drop the `_check_str` fallback and its Sprint-007-halted comment). `StrictSignalVocabulary.__init__` raises `ValueError` if any schema entry lacks `field_types`.
- `tests/test_signals.py` — two new tests: `test_parse_type_raises_on_unknown_type_string`, `test_vocabulary_raises_on_missing_field_types`.

### Files created

None.

### Content assertions

- `signals.py` `_parse_type` does not contain `return _check_str` in the fallback branch.
- `signals.py` `_parse_type` last statement raises `ValueError`.
- `signals.py` `StrictSignalVocabulary.__init__` raises when `field_types` is absent from a schema entry.
- `tests/test_signals.py` contains `test_parse_type_raises_on_unknown_type_string`.
- `tests/test_signals.py` contains `test_vocabulary_raises_on_missing_field_types`.

### Command exit codes

- `uv run ruff check src tests` exit 0.
- `uv run ruff format --check src tests` exit 0.
- `uv run mypy src` exit 0.
- `uv run pytest tests/ -v` exit 0; 25 tests pass (23 + 2 new).
- `uv build` clean.

---

## observation contract

Not applicable. `pass_kind: architecture`.

---

## done criteria

Unknown type strings raise at load. Missing `field_types` raises at load. v0.2 loads clean. 25 tests pass.

---

## notes

**Sprint 007's exact code, unmodified except the comment.** The tighten is the same. The vocabulary is what changed (Sprint 009). This sprint proves the loop closed: `reviews/sdd-discipline-check-round-1.md` §3 → halted Sprint 007 → Sprint 008 parser → Sprint 009 v0.2 → Sprint 010 re-tighten. Four sprints for one review finding.

**Sprint 007 stays on disk with `status: halted`.** Hard rule 12: no deletions. Anyone reading the sprint sequence sees Sprint 007 halted, understands why via BLACKBOARD, sees Sprints 008–010 close the loop.

---

## plan-mode review checklist

- [x] Scope one paragraph, one concept.
- [x] Two files modified.
- [x] Signal contract vacuous.
- [x] Artifact contract gradable.
- [x] Determinism budget declared (n/a).

---

*Sprint 010. Sprint 007 redux against v0.2.*
