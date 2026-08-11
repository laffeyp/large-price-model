# Sprint 013 — signals.py internal cleanups

---

```yaml
---
id: 013
status: closed
phase: 1
pass_kind: architecture
determinism_budget: n/a
---
```

---

## scope

Close two review items in the same file, same concept ("internal-shape tightens after Sprint 008 landed the helpers"):

- **§1.4** `_parse_type`'s `dict<K,V>` branch predates the `_split_top_level` helper Sprint 008 added and duplicates the depth-aware split inline. Refactor to use the helper. Same behavior; less duplicated logic.
- **§2.4** `StrictSignalEmitter.__init__` accepts `vocabulary: SignalVocabulary` (the parent type). A caller passing a plain `SignalVocabulary` constructs a "strict" emitter with non-strict validation. Tighten the parameter type to `StrictSignalVocabulary`; mypy strict enforces it.

One file (`src/price_space_llm/signals.py`); no test changes needed — the existing 29-test suite exercises both paths.

---

## prerequisites

- Sprint 012 closed.

---

## context_files

- `reviews/full-review-round-1.md` §1.4 and §2.4
- `src/price_space_llm/signals.py` (`_parse_type` dict<K,V> branch at line 223; `StrictSignalEmitter.__init__` at line 330)

---

## signal contract

### Emits

Test-time only.

### Consumes

- `signals/0.2.json` (unchanged).

### Invariants

- All 29 existing tests pass unchanged.
- `_parse_type("dict<K,V>")` semantics unchanged: split on the first top-level comma, `_check_dict_of(K_check, V_check)`.
- `StrictSignalEmitter(SignalVocabulary(...))` is a mypy strict-mode error (parent-type argument passed to child-typed parameter).
- The narrower type does not break any existing caller — `StrictSignalVocabulary` is what `load_vocabulary` returns and what `get_emitter` uses.

---

## artifact contract

### Files modified

- `src/price_space_llm/signals.py`:
  - `_parse_type` dict branch: replace inline depth-tracker with `_split_top_level(inner, ",")`. If the split returns exactly two parts, take K and V; else raise a clear error.
  - `StrictSignalEmitter.__init__`: change parameter type from `vocabulary: SignalVocabulary` to `vocabulary: StrictSignalVocabulary`.

### Files created

None.

### Content assertions

- `signals.py` `_parse_type` dict branch does not contain the inline `depth = 0; split = None; for i, c in enumerate(inner):` pattern.
- `signals.py` `StrictSignalEmitter.__init__` signature contains `vocabulary: StrictSignalVocabulary`.

### Command exit codes

- `uv run ruff check src tests` exit 0.
- `uv run ruff format --check src tests` exit 0.
- `uv run mypy src` exit 0.
- `uv run pytest tests/ -v` exit 0; 29 tests pass.
- `uv build` clean.

---

## observation contract

Not applicable. `pass_kind: architecture`.

---

## done criteria

`dict<K,V>` branch uses `_split_top_level`. Constructor demands `StrictSignalVocabulary`. 29 tests pass. All tools green.

---

## notes

**`dict<K,V>` split semantics.** The current inline code breaks on the first top-level comma. `_split_top_level` returns every top-level split. For `dict<K,V>` there should be exactly one comma at depth 0 — take the two parts. `dict<K,V,extra>` (invalid) has two commas → three parts → raise. This is a strictness upgrade the vocabulary can handle: v0.2 verified to have no malformed `dict<K,V>` declarations (grep confirmed at Sprint 007 halt time; all five composite types in v0.2 are clean).

**StrictSignalVocabulary parameter type.** Type narrowing catches the class of bug where a caller passes `SignalVocabulary(schema)` directly. mypy strict fires; no runtime check needed. Runtime construction with a plain `SignalVocabulary` would fail at first emit anyway (no strict-extras or type checking) — the type parameter surfaces the mistake earlier.

---

## plan-mode review checklist

- [x] Scope one paragraph, one concept ("internal-shape tightens").
- [x] One file modified. Within hard rule 6.
- [x] Signal contract vacuous.
- [x] Artifact contract gradable.
- [x] Determinism budget declared (n/a).

---

*Sprint 013. Signal.py cleanups. Sprint 014 handles the test brittleness fix.*
