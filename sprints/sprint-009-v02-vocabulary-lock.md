# Sprint 009 — vocabulary v0.2 lock (CAPACITY_SWEEP_COMPLETED type correction)

---

```yaml
---
id: 009
status: closed
phase: 1
pass_kind: architecture
determinism_budget: n/a
---
```

---

## scope

Land vocabulary version 0.2. One semantic change: `CAPACITY_SWEEP_COMPLETED.points` type declaration corrected from the malformed `list<dict<size_usd:float, sharpe:float, sharpe_se:float>>` to the canonical `list<struct<size_usd:float, sharpe:float, sharpe_se:float>>` using the `struct` composite kind Sprint 008 landed. The intent is preserved; the syntax now matches the Layer-2 type vocabulary.

Author `signals/0.2.json` (copy of 0.1.json with the one-line type correction, version metadata updated, `prior_version = "0.1"`), `signals/0.2-rationale.md` (delta doc), reopen `signals/proposals.json` with the ratified proposal, retarget the loader default from `0.1.json` to `0.2.json`, retarget the `src/price_space_llm/_vocab/` symlink. Sprint 010 re-runs Sprint 007's tighten against v0.2.

---

## prerequisites

- Sprint 007 halted with `vocabulary_change_required`.
- Sprint 008 closed (`struct` parser landed).

---

## context_files

- `signals/0.1.json` (source; the whole file copies forward with one type edit)
- `signals/0.1-rationale.md` (parent rationale; the delta doc cites it)
- `signals/proposals.json` (currently closed at v0.1; reopen for the v0.2 proposal)
- `src/price_space_llm/signals.py` (loader default; `_vocab` sub-package location)
- `src/price_space_llm/_vocab/0.1.json` (current symlink target)
- `BLACKBOARD.md § Surfaced for review` (the Sprint 007 halt entry naming the correction)
- `sdd-kit-2/grammar/PRINCIPLES.md` (Layer 9 version metadata; Layer 10 grammar-growth)

---

## signal contract

### Emits

Test-time only.

### Consumes

- `signals/0.2.json` at load (after this sprint; v0.1 remains on disk for audit).

### Invariants

- `signals/0.1.json` remains unchanged (no deletion or in-place edit; audit-trail per hard rule 12).
- `signals/0.2.json` is byte-identical to `signals/0.1.json` except for: (a) `version`, `locked_at`, `locked_by`, `prior_version` metadata fields; (b) the `CAPACITY_SWEEP_COMPLETED.points` `typed_payload` type string; (c) the `grammar_growth.project_overrides` gains an entry recording the `struct` type-kind extension.
- `load_vocabulary()` defaults to `0.2.json` after this sprint.
- All 23 tests continue to pass under the loader-default retarget.
- The v0.2 vocabulary loads cleanly under the current parser (`_parse_type("list<struct<...>>")` returns a valid checker).

---

## artifact contract

### Files created

- `signals/0.2.json` — v0.2 vocabulary. Copy of 0.1.json with the type correction, version metadata bump, grammar_growth override entry.
- `signals/0.2-rationale.md` — delta doc: what changed from 0.1 and why. Cites the Sprint 007 halt, the Sprint 008 parser addition, and the resulting v0.2 shape.

### Files modified

- `signals/proposals.json` — reopened for v0.2. Add one proposal (target_vocabulary_version = "0.1 → 0.2") for the type correction. Stamp `outcome: "accepted"`, `outcome_date: "2026-08-10"`.
- `src/price_space_llm/signals.py` — `load_vocabulary(name: str = "0.2.json")` default updated.
- `src/price_space_llm/_vocab/0.1.json` symlink stays (audit trail). Add `src/price_space_llm/_vocab/0.2.json` symlink to `../../../signals/0.2.json` alongside.

### Content assertions

- `signals/0.2.json` parses as JSON.
- `signals/0.2.json` `version == "0.2"`, `locked == true`, `locked_at == "2026-08-10"`, `prior_version == "0.1"`.
- `signals/0.2.json` `tags[].typed_payload[]` for `CAPACITY_SWEEP_COMPLETED.points` `type` starts with `"list<struct<"`.
- `signals/0.2.json` `grammar_growth.project_overrides` contains an entry naming `struct` as a Layer-2 type-kind extension.
- `signals/0.2-rationale.md` cites `reviews/sdd-discipline-check-round-1.md`, the Sprint 007 halt in BLACKBOARD, and Sprint 008's parser addition.
- `src/price_space_llm/_vocab/0.2.json` is a symlink resolving to the same file as `signals/0.2.json`.
- `src/price_space_llm/signals.py` `load_vocabulary` signature default is `"0.2.json"`.
- `signals/proposals.json` contains one v0.2-target proposal with `outcome == "accepted"`.

### Command exit codes

- `uv sync --dev` exit 0.
- `uv run ruff check src tests` exit 0.
- `uv run ruff format --check src tests` exit 0.
- `uv run mypy src` exit 0.
- `uv run pytest tests/ -v` exit 0; 23 tests pass.
- `uv run python -c "from price_space_llm.signals import get_emitter; v = get_emitter()._vocab; print(v._schema['CAPACITY_SWEEP_COMPLETED']['field_types']['points'])"` prints the corrected type string.
- `uv build` clean; fresh-venv wheel install reads the v0.2 tag count.

---

## observation contract

Not applicable. `pass_kind: architecture`.

---

## done criteria

`signals/0.2.json` exists, locked, with the type correction. Loader default retargeted. 23 tests pass. v0.1 remains on disk.

---

## notes

**Halt-and-articulate on file count.** Sprint card creates 2 files, modifies 3, adds 1 symlink. Six files total — above hard rule 6's ≤2 ceiling. Filing `hard_rule_stretch` to BLACKBOARD at plan-mode review per the new WORKING_AGREEMENT halt-condition. Concept count = ONE: vocabulary v0.2 lock (the mechanical file touches all serve that single semantic change). If the Architect calls split, split by phase: Sprint 009a = author v0.2 JSON + rationale doc; Sprint 009b = retarget loader + symlink + close proposals.json. Both would ship an incomplete state independently, which is the argument against splitting.

**Why keep v0.1 on disk.** Hard rule 12: no deletions. The audit trail is the work. Anyone reading `signals/proposals.json` sees the v0.2 delta and can walk the pair to reconstruct why the correction happened.

**Grammar-growth override entry.** `struct` is a project-side extension of the Layer-2 type kinds documented in `signals/0.1-rationale.md § Layer 2`. Record in `signals/0.2.json § grammar_growth.project_overrides` so a v0.3 reader knows the type set has grown: `{"override": "layer_2_type_kind_added", "value": "struct<name:type, ...>", "source": "Sprint 008; sprints/sprint-008-struct-type-kind.md; reviews/sdd-discipline-check-round-1.md §3"}`.

**Loader default retargeting is one line.** `load_vocabulary(name: str = "0.2.json")`. Callers passing `"0.1.json"` explicitly still get v0.1. A test would enforce this if a downstream consumer ever needs both versions; not this sprint.

**Symlink strategy.** Add `_vocab/0.2.json` alongside `_vocab/0.1.json`. Both remain valid; the loader default picks one. Cleaner than replacing.

---

## plan-mode review checklist

- [x] Scope one paragraph, one concept (v0.2 lock).
- [ ] Six files. Halt-and-articulate for `hard_rule_stretch` filed; Architect calls ratify-or-split.
- [x] Signal contract vacuous.
- [x] Artifact contract gradable.
- [x] Determinism budget declared (n/a).

---

*Sprint 009. v0.2 lock. Sprint 010 re-runs Sprint 007's tighten against v0.2.*
