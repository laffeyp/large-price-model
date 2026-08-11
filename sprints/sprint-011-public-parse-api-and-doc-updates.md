# Sprint 011 — public parser API + review-driven doc updates

---

```yaml
---
id: 011
status: closed
phase: 1
pass_kind: architecture
determinism_budget: n/a
---
```

---

## scope

Address the "before Sprint 011" items from `reviews/full-review-round-1.md` that concern the public API surface and project-level documentation:

- **§2.5 rename privates to public.** `_parse_type` and `_check_struct` are used from `tests/test_signals.py` as if public. Rename to `parse_type` and `check_struct`, expose via `__all__`, drop the underscore-prefix imports in tests.
- **§1.1 layout decision, documented.** Keep `signals.py` at package root. Add an entry to `WORKING_AGREEMENT.md § Canonical home registry` naming the placement as a deliberate deviation from the tech-arch's `src/utils/` inference — observability is not a pipeline concern the spec dictates.
- **§4.1 dep-pin rule.** Add a `WORKING_AGREEMENT.md § External SDK bridge mappings` sub-rule: first sprint that imports each SDK pins the dep in `pyproject.toml` in the same commit as the bridge mapping.
- **§4.7 BBO source deferral.** Product-spec names BBO as an input for `scripts/calibrate_spread.py` but no source is specified. File to `BLACKBOARD.md § Deferred` with revisit trigger "sprint that authors calibrate_spread.py."

ProcessRunner context manager (§3.2), dict<K,V> refactor (§1.4), StrictSignalEmitter parent-type tighten (§2.4), monkeypatched clock-reset test (§2.6), version-field bump (§2.7), and ruff RUF/ANN packs (§2.1) all defer to later sprints. Sprint 012 is ProcessRunner.

---

## prerequisites

- Sprint 010 closed.
- `reviews/full-review-round-1.md` on file.

---

## context_files

- `reviews/full-review-round-1.md` (§1.1, §2.5, §4.1, §4.7)
- `src/price_space_llm/signals.py` (`_parse_type` at line 215, `_check_struct` at line 173, `__all__` at line 373)
- `tests/test_signals.py` (eight underscore-import sites the review names)
- `WORKING_AGREEMENT.md § Canonical home registry` and `§ External SDK bridge mappings`
- `BLACKBOARD.md § Deferred`
- `specs/product-spec-v4.md § Dependencies § Data § BBO calibration` (the source gap)

---

## signal contract

### Emits

Test-time only.

### Consumes

- `signals/0.2.json` at load (unchanged).

### Invariants

- All 25 existing tests pass unchanged.
- `parse_type` and `check_struct` are importable from `price_space_llm.signals` without underscores.
- The underscore-prefixed forms remain for backwards compatibility (`_parse_type = parse_type`, `_check_struct = check_struct` at module scope).
- No behavior changes in `signals.py` beyond the exposed-name rename.

---

## artifact contract

### Files modified

- `src/price_space_llm/signals.py` — rename `_parse_type` → `parse_type` and `_check_struct` → `check_struct` at the definition site. Keep underscore aliases for backwards compat. Add both to `__all__`.
- `tests/test_signals.py` — replace every `from price_space_llm.signals import _parse_type` / `_check_struct` with the public names.
- `WORKING_AGREEMENT.md` — canonical-home-registry entry for `signals.py` placement; bridge-mapping sub-rule for dep pins.
- `BLACKBOARD.md § Deferred` — one new entry for the BBO source gap.

### Files created

None.

### Content assertions

- `signals.py` `__all__` contains both `parse_type` and `check_struct`.
- `signals.py` defines `def parse_type(...)` and `def check_struct(...)`.
- `signals.py` retains `_parse_type = parse_type` and `_check_struct = check_struct` aliases (backwards compat; tests that already migrated stay green; any external caller that used the private form continues to work).
- `tests/test_signals.py` contains zero occurrences of `import _parse_type` or `import _check_struct`.
- `WORKING_AGREEMENT.md § Canonical home registry` names `price_space_llm.signals` as the observability module home with the deviation rationale.
- `WORKING_AGREEMENT.md § External SDK bridge mappings` states the dep-pin rule.
- `BLACKBOARD.md § Deferred` gains a "BBO source" entry with the revisit trigger.

### Command exit codes

- `uv run ruff check src tests` exit 0.
- `uv run ruff format --check src tests` exit 0.
- `uv run mypy src` exit 0.
- `uv run pytest tests/ -v` exit 0; 25 tests pass.
- `uv build` clean.

---

## observation contract

Not applicable. `pass_kind: architecture`.

---

## done criteria

`parse_type` and `check_struct` are public. Tests import them without underscores. Two WORKING_AGREEMENT clauses added. One BLACKBOARD deferral filed. 25 tests pass.

---

## notes

**Backwards compat via aliases.** External callers may already import `_parse_type` (unlikely at Sprint 011 — no external callers yet — but cheap insurance). `_parse_type = parse_type` at module scope preserves the private form as an alias. Sprint N deletes the aliases when kit-diary hypothesis says they're safely unused.

**Not renaming private helpers that are actually private.** `_check_str`, `_check_int`, `_check_sha256`, etc. stay underscore-prefixed. Tests do not import them directly; only `parse_type` and `check_struct` are exercised in tests. The rename is targeted at the public-in-effect symbols.

**Layout deviation rationale.** Tech-arch §3 lists pipeline module directories (`src/ingestion/`, `src/features/`, etc.). Observability is not on that list. `src/utils/` is closest by process of elimination, but overloads the "utility helpers" name. Package root is the honest placement; a `observability/` sub-package emerges if the layer grows past one module.

---

## plan-mode review checklist

- [x] Scope one paragraph. Four items bundled under "review-driven pre-11 doc + rename."
- [x] Two code files modified; two documentation files updated. Within hard rule 6's code-file count.
- [x] Signal contract vacuous.
- [x] Artifact contract gradable.
- [x] Determinism budget declared (n/a).

---

*Sprint 011. Public API + doc updates. Sprint 012 is ProcessRunner.*
