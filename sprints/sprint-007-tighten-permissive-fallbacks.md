# Sprint 007 — tighten permissive fallbacks in the type checker

---

```yaml
---
id: 007
status: halted
phase: 1
pass_kind: architecture
determinism_budget: n/a
---
```

---

## scope

Close `reviews/sdd-discipline-check-round-1.md` §3. Two permissive fallbacks in `src/price_space_llm/signals.py` defeat the strict-at-speaker's-mouth commitment: `_parse_type` returns `_check_str` on any unrecognised type string; `StrictSignalVocabulary.__init__` treats a missing `field_types` entry as an empty dict. Both silently degrade validation. A vocabulary bump mistyping `int` as `nit` in the JSON succeeds at load and only surfaces if a test passes a non-string to `nit`.

Fix: `_parse_type` raises `ValueError` on unknown type strings; `StrictSignalVocabulary.__init__` raises `ValueError` if any tag's schema entry is missing `field_types`. Two new tests exercise both raise paths.

---

## prerequisites

- Sprint 006 closed.
- `reviews/sdd-discipline-check-round-1.md` on file.

---

## context_files

- `reviews/sdd-discipline-check-round-1.md` (§3)
- `src/price_space_llm/signals.py` (`_parse_type` at line 174; `StrictSignalVocabulary.__init__` at line 214)
- `tests/test_signals.py`
- `sdd-kit-2/grammar/PRINCIPLES.md` commitment 2 (schema at the speaker's mouth)

---

## signal contract

### Emits

Test-time only.

### Consumes

- `signals/0.1.json` (unchanged).

### Invariants

- All 18 existing tests pass unchanged.
- `_parse_type("nonexistent_type")` raises `ValueError`.
- `StrictSignalVocabulary(schema)` raises `ValueError` if any tag's entry lacks `field_types`.
- The locked v0.1 vocabulary continues to load — every tag in `signals/0.1.json` carries `field_types` because `load_vocabulary` populates it from `typed_payload`.

---

## artifact contract

### Files modified

- `src/price_space_llm/signals.py` — `_parse_type` raises on unknown type strings (drop the `_check_str` fallback; keep the comment explaining why). `StrictSignalVocabulary.__init__` raises if any schema entry lacks `field_types`.
- `tests/test_signals.py` — two new tests: `test_parse_type_raises_on_unknown_type_string`, `test_vocabulary_raises_on_missing_field_types`.

### Files created

None.

### Content assertions

- `signals.py` `_parse_type` last statement raises `ValueError`, not `return _check_str`.
- `signals.py` `StrictSignalVocabulary.__init__` raises when `entry.get("field_types")` is `None`.
- `tests/test_signals.py` contains `test_parse_type_raises_on_unknown_type_string`.
- `tests/test_signals.py` contains `test_vocabulary_raises_on_missing_field_types`.

### Command exit codes

- `uv sync --dev` exit 0.
- `uv run ruff check src tests` exit 0.
- `uv run ruff format --check src tests` exit 0.
- `uv run mypy src` exit 0.
- `uv run pytest tests/ -v` exit 0; 20 tests pass.

---

## observation contract

Not applicable. `pass_kind: architecture`.

---

## done criteria

Unknown type strings raise at load. Missing `field_types` raises at load. 20 tests pass, all tools green.

---

## notes

**Why raise, not fall back.** The vocabulary is the contract (hard rule 2). An unknown type string in `typed_payload` is a Layer-2 authoring error — either a typo in the JSON or an unimplemented type. Both cases want the same treatment: fail loudly at load, force the author to either correct the typo or register the new type in `_TYPE_CHECKERS`. A permissive fallback defers the failure to whichever downstream test happens to pass a non-string value, which may be never.

**`field_types` missing is a shape violation.** `load_vocabulary` always populates `field_types` from `typed_payload`; a schema entry without it is either a hand-built schema (rare, test-only) or a stale format. Test-only construction can pass `field_types = {}` explicitly if it wants an empty-typing shape. The default should be strict.

**Sprint 003a/003b + Sprint 005 stretches acknowledged.** BLACKBOARD § Surfaced for review carries the retroactive halt-acknowledgment entry per `reviews/sdd-discipline-check-round-1.md` §2. WORKING_AGREEMENT § Project-specific halt conditions gains `hard_rule_stretch` and `determinism_budget_missing`. Neither belongs in this sprint's file contract — they landed as documentation moves outside the sprint frame.

**Determinism budget declared `n/a`.** This sprint imports no PyTorch, runs no training step, writes no model artifact. The frontmatter carries the field for the pattern; the value is `n/a` for architecture-band sprints.

---

## plan-mode review checklist

- [x] Scope one paragraph, one concept.
- [x] Two files modified. Within hard rule 6.
- [x] `context_files` covers the read set.
- [x] Signal contract is vacuous (no new emit surfaces).
- [x] Artifact contract is gradable.
- [x] Determinism budget declared (n/a).
- [x] Sprint dispatches on Architect "go".

---

*Sprint 007. Tighten the permissive fallbacks. First sprint to carry `determinism_budget` in frontmatter.*
