# SDD-discipline check — sprints 001-006

**Reviewer:** Claude Code (Opus 4.7), acting in Agent role.
**Date:** 2026-08-10.
**Scope:** the six sprint cards under `sprints/`, the current state of `src/price_space_llm/signals.py` (319 lines), `tests/test_signals.py`, and `pyproject.toml`. Focused pass: is SDD's discipline holding, and are the techniques being used the way TECHNIQUES.md / PRINCIPLES.md name them.
**Verdict:** two hard-rule stretches worth naming; every technique used is used correctly.

---

## 1. Where the discipline holds cleanly

**Sprint card shape is uniform.** All six carry YAML front-matter with `id`, `status`, `phase`, `pass_kind`. Every card names scope in one paragraph, lists prerequisites, enumerates context_files, populates signal + artifact + observation contracts, states done criteria, closes with a plan-mode-review checklist. That is the template from `sdd-kit-2/templates/SPRINT_CARD.md` applied verbatim.

**Pass-kind drives the observation contract correctly.** Sprint 002 declares `functional` and authors an observation contract with `tmp_path` fixtures, expected runtime signals, expected exit codes. Sprints 001, 003, 004, 005, 006 declare `architecture` and correctly write "Not applicable" with the pass_kind cited as the reason. Hard rule 9 honored across the board.

**Vocabulary-as-contract commitment held.** Every sprint's signal-contract invariants include "no out-of-vocabulary tags emitted anywhere" and "strict-extras posture preserved," even sprints that add no new emit surfaces. That is how the contract expresses itself in the pre-behavior sprints — the vocabulary is invariant, and the sprint asserts non-drift.

**Content assertions are mechanically checkable.** Every artifact-contract section lists `grep`-able strings, `does not contain the substring`, `sha256 of contents match`, `exit 0`. No "the code should be clean" language — every check is a shell command. Dual-contract discipline (PRINCIPLES.md #4) at the artifact side.

**Sprint 003's wheel-install exit-code is the outside grader.** `pip install dist/*.whl` in a fresh venv then `python -c "from price_space_llm.signals import get_emitter; print(len(get_emitter()._vocab.tags()))"` is exactly the pattern Addendum D1 names: the engine that produced the bytes cannot judge them, so a fresh-venv install runs the artifact against a different engine. That is the correct answer to the ship-blocker my code review named.

**Review-driven cadence.** Sprints 003, 005, 006 execute the findings from `reviews/code-best-practices-round-1.md` explicitly, section by section. §1 → Sprint 003. §2 → Sprint 004. §3/§4/§5 → Sprint 005. §6 → Sprint 006. Not one review finding got silently absorbed; each is named in a sprint card's scope with the review section as citation. That is exactly the review→sprint→signal loop the kit describes.

**Technique applications are correct where they appear.** `importlib.resources` (Sprint 003) is the Python-3.9+ right answer for packaged resources. PEP 562 `__getattr__` at module scope (Sprint 005) is the right shim for lazy module-level attributes without breaking `from … import …` call sites. `@lru_cache(maxsize=1)` is the idiomatic per-process cached factory. `[[tool.mypy.overrides]]` for the `sdd` module (Sprint 006) is the right way to ignore-missing-imports for one dependency without loosening strict mode globally. Each technique matches its documented use.

## 2. Two hard-rule stretches worth naming

**Sprint 003 modifies three files and creates two.** AGENTS.md hard rule 6 caps scope at ≤2 files / one concept. The sprint card acknowledges the count and proceeds anyway ("three modified files, two new files (one is a symlink; the __init__ is empty ceremony)"). Two of the five are ceremony (empty `__init__.py`, a symlink), which is defensible — the *code* touched sits at three files. But the rule counts files, not code, and the plan-mode checklist marker at line 125 ticks "one concept" without ticking "≤2 files." That is a discipline slip — the halt-and-articulate move is to split (Sprint 003a: `importlib.resources` refactor; Sprint 003b: encoding + docstring + double-validate one-liners), not to note the stretch in a comment and proceed.

**Sprint 005 bundles three concepts.** The scope explicitly says "the remaining small findings from `reviews/code-best-practices-round-1.md`: §3 (leftovers)… §4 (factory)… §5 (tests)." Three concepts sharing one sprint card. The card names the stretch ("multiple small concepts bundled under 'review cleanups'. Above the ≤2 files rule 6 in absolute file count; within it in code count"). But the hard rule reads *"one concept"* — it is not about line count. §3, §4, §5 are three distinct changes with three distinct failure modes. If §4's PEP 562 shim regresses, the sprint diff also carries the §3 mkdir change and the §5 test relaxation — a Reviewer bisecting the failure faces three suspect concept changes at once instead of one.

Both stretches happened without a `halt` entry in BLACKBOARD. The kit's halt-and-articulate rule reads: when the sprint's scope is unclear or hard rule breaks, halt. Naming the stretch in the sprint card notes is not the halt — it is a bypass. Not fatal; the code shipped and the tests pass. But the pattern to watch for.

## 3. One technique application that could tighten

**`_parse_type` in `signals.py` returns `_check_str` as its "unknown type" fallback (line 205).** The rationale in the code comment says a future vocabulary type should also add its entry to `_TYPE_CHECKERS`, and until then the loader stays working. That is a permissive default. TECHNIQUES.md §1 (kit-strictness patterns) and PRINCIPLES.md commitment 2 (schema at speaker's mouth) both push the other way: an unknown type in the schema is a Layer-2 authoring error and should raise at load, not silently accept. The current fallback means a vocabulary bump that mistypes `int` as `nit` in the JSON succeeds at load and only surfaces if a test happens to pass a non-string value to `nit`. Tighten to raise on unknown type strings; add a NEW_TYPE test that fails until the type is registered.

Same shape at `StrictSignalVocabulary.__init__` line 220 (`entry.get("field_types", {})`): if the vocabulary lacks `field_types` (e.g., an old-format entry from a prior version), validation silently degrades to keys-only. Defensive; also strictness-defeating. Fail loudly on absence, so an unmigrated entry cannot ship.

## 4. Observations, not defects

**KIT_DIARY grew 3KB → 34KB across the six sprints.** That is diary discipline at the load-bearing volume the kit asks for. Not sampled for this review; assume it holds unless a specific finding says otherwise.

**No `bridge_mapping_required` halts yet.** Correct — no external SDK imports in the first six sprints (pytest, ruff, mypy are dev-only). The bridge-mapping halt fires when a sprint imports PyTorch, Polars, Hydra, W&B, or the MCP client. That sprint is Sprint 007 or later per the working-agreement phase plan.

**No `probe_missing` halts yet.** Same reason — no feature or ingestion code has landed. Correct absence.

**Determinism-budget declaration missing across all six sprint cards.** WORKING_AGREEMENT §"Determinism budget" says every training sprint declares its level. Sprints 001–006 are pre-training; the requirement does not bite yet. Once Sprint N imports PyTorch and runs a training step, that card needs a `determinism_budget: bit-deterministic` or `statistically-deterministic` field. Add to the template ahead of time so no sprint dispatches without one.

## 5. Bottom line

The discipline holds, with two stretches that should have been halts (Sprint 003's file-count, Sprint 005's three-concepts-in-one). Every technique used matches its documented use. The one code-side loose thread is the permissive fallback in `_parse_type` — a tighten that costs a two-line change and one test.

The trajectory: six sprints, three of them (003, 005, 006) explicitly executing prior review findings, and each one closing the loop the review opened. That is the loop the kit describes. Next-sprint watch: the determinism-budget declaration ahead of the first PyTorch sprint, and a halt-not-bypass on the next hard-rule stretch.
