# Sprint 008 — struct type kind for the Layer-2 parser

---

```yaml
---
id: 008
status: closed
phase: 1
pass_kind: architecture
determinism_budget: n/a
---
```

---

## scope

Extend the Layer-2 type vocabulary with a `struct<name:type, name:type, ...>` composite. `_check_struct` accepts a dict of field checkers, verifies the value is a dict, checks every declared field is present, rejects extras, and runs each field's checker on its value. `_parse_type` gains one branch that splits the inner on top-level commas, splits each part on the top-level colon, recurses on each field's type. Nested types work: `struct<a:list<int>, b:dict<str, float>>` parses correctly.

No vocabulary changes this sprint. Sprint 009 lands v0.2 with the corrected `CAPACITY_SWEEP_COMPLETED.points` declaration using the new syntax. Sprint 010 re-runs Sprint 007's tightening against v0.2.

---

## prerequisites

- Sprint 007 halted (`vocabulary_change_required` filed 2026-08-10).

---

## context_files

- `src/price_space_llm/signals.py` (`_parse_type` line 174; the inline top-level-split logic in the `dict<K,V>` branch is the pattern to follow)
- `tests/test_signals.py`
- `signals/0.1-rationale.md` § Layer 2 (type vocabulary listing; the sprint's addition extends this)
- BLACKBOARD § Surfaced for review (the Sprint 007 halt entry)

---

## signal contract

### Emits

Test-time only.

### Consumes

- `signals/0.1.json` (unchanged; no vocabulary declaration uses `struct` yet — that's Sprint 009).

### Invariants

- All 18 existing tests pass unchanged.
- `_parse_type("struct<a:int, b:float>")` returns a callable that raises on non-dict, missing fields, extra fields, or wrong per-field types.
- Nested composites parse: `_parse_type("list<struct<a:int, b:float>>")` returns a valid checker.
- v0.1 vocabulary continues to load unchanged (struct kind is unused there).

---

## artifact contract

### Files modified

- `src/price_space_llm/signals.py` — add `_check_struct(fields: dict[str, Checker]) -> Checker`; add a `struct<...>` branch to `_parse_type` mirroring the `dict<K,V>` branch's depth-aware split. No changes to the existing checkers or vocabulary loader.
- `tests/test_signals.py` — five new tests exercising the struct parser: valid record accepted; missing field raises; extra field raises; wrong per-field type raises; nested composite parses.

### Files created

None.

### Content assertions

- `signals.py` defines `def _check_struct(fields: dict[str, Checker]) -> Checker`.
- `signals.py` `_parse_type` contains `if type_str.startswith("struct<")`.
- `tests/test_signals.py` contains `test_struct_parser_accepts_valid_record`, `test_struct_parser_rejects_missing_field`, `test_struct_parser_rejects_extra_field`, `test_struct_parser_rejects_wrong_type_on_field`, `test_struct_parser_handles_nested_types`.

### Command exit codes

- `uv sync --dev` exit 0.
- `uv run ruff check src tests` exit 0.
- `uv run ruff format --check src tests` exit 0.
- `uv run mypy src` exit 0.
- `uv run pytest tests/ -v` exit 0; 23 tests pass (18 + 5 new).
- `uv build` clean.

---

## observation contract

Not applicable. `pass_kind: architecture`.

---

## done criteria

`_parse_type("struct<name:type, ...>")` returns a working checker. Five new tests pass. All tools green.

---

## notes

**Why `struct`, not `record` or `tuple`.** `struct` reads as a fixed-shape dict. `record` conflicts with the Layer-6 "record of a run" sense. `tuple` implies positional access; the JSON payload is dict-keyed. `struct` matches C/Rust convention and reads unambiguously in the vocabulary's type strings.

**Field-order semantics.** The parser preserves declaration order in the resulting checker's field dict (Python 3.7+ dict ordering). Not load-bearing for validation — the check verifies presence and per-field type; order does not matter to the caller's dict payload.

**Nested struct.** `struct<a:struct<x:int, y:int>, b:float>` parses recursively. Top-level split on `,` at depth 0 gives `["a:struct<x:int, y:int>", "b:float"]`; each part splits on `:` at depth 0 giving `("a", "struct<x:int, y:int>")` and `("b", "float")`; each type recurses through `_parse_type`.

**Not adding grammar_growth entry yet.** The `project_overrides` list in `signals/0.1.json § grammar_growth` records vocabulary-discipline overrides. Adding `struct` as a supported Layer-2 type kind is a project-side extension worth naming in that log — but the record lands in `signals/0.2.json` when Sprint 009 bumps the version. Sprint 008 authors code only.

---

## plan-mode review checklist

- [x] Scope one paragraph, one concept.
- [x] Two files modified. Within hard rule 6.
- [x] Signal contract vacuous.
- [x] Artifact contract gradable.
- [x] Determinism budget declared (n/a).

---

*Sprint 008. `struct` type kind. Sprint 009 uses it in the vocabulary.*
