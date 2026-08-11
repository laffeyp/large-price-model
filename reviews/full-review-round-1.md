# Full review — sprints 001-010, four dimensions

**Reviewer:** Claude Code (Opus 4.7), acting in Agent role.
**Date:** 2026-08-10.
**Scope:** the full state at Sprint 010 close — `pyproject.toml` (46 lines), `src/price_space_llm/signals.py` (377 lines), `tests/test_signals.py` (286 lines, 25 tests), `signals/0.1.json`, `signals/0.2.json`, `signals/proposals.json`, ten sprint cards, `BLACKBOARD.md`, `KIT_DIARY.md`, `WORKING_AGREEMENT.md`, `specs/product-spec-v4.md`, `specs/technical-architecture-v4.md`.
**Dimensions:** architecture, Python + linting + arrangement, SDD-technique adherence (signals in particular), spec-adherence against the two v4 docs.
**Recommendation:** four small fixes before Sprint 011 (§§1.4, 2.6, 2.7, 3.2). Two decisions to make (§§1.1, 4.1). Everything else is on-trajectory.

---

## 1. Architecture

### 1.1 Module placement drifts from tech-arch §3

`technical-architecture-v4.md §3` prescribes `src/ingestion/`, `src/features/`, `src/tokenizer/`, `src/model/`, `src/training/`, `src/simulation/`, `src/evaluation/`, `src/utils/`. The current layout puts `signals.py` at package root: `src/price_space_llm/signals.py`. Observability code has no listed home in the spec; `src/utils/` is the closest match.

Two paths, either defensible:

- Move now (Sprint 011 mechanical rename): `src/price_space_llm/observability/signals.py` or `src/price_space_llm/utils/signals.py`, update `pyproject.toml`, update imports in tests. One sprint, one concept, no defect risk. Cheapest window because no downstream code imports it yet.
- Accept the deviation: document in `WORKING_AGREEMENT.md § Canonical home registry` that `signals.py` sits at package root by choice. `WORKING_AGREEMENT` currently names the "Signal emitter" home as "Vendored from `sdd-kit-2/lib/sdd.py` or a project-local extension" — vague. Tighten to the actual path.

Every sprint that adds an operator module (`src/ingestion/`, `src/features/`, …) imports the emitter. Every one of those import statements pins the choice. Ten import statements is cheaper to rewrite than 100. Make the call this sprint.

### 1.2 Extension pattern: subclass the kit's primitives

`StrictSignalVocabulary(SignalVocabulary)` and `StrictSignalEmitter(SignalEmitter)` both subclass. The kit's `sdd.py` is force-included into the wheel as a top-level module and treated as read-only per convention. The subclass path preserves the kit's semantics while adding project-specific strictness — the right shape for a project that ratifies the kit's contract and extends it.

The alternative — delegation via composition — would have decoupled from `SignalEmitter._vocab`, `SignalEmitter._buffer`, `SignalEmitter._session_start`. The subclass path reaches into all three private attributes (line 289 reads `self._vocab.category_of`, line 340 writes `self._session_start`, line 349 constructs a `Signal` with fields that mirror the parent's internal shape). If the kit's `SignalEmitter` ever changes its buffer semantics or renames `_session_start`, `StrictSignalEmitter` breaks silently.

Not a defect. Note for the KIT_DIARY: "the vendored-kit extension pattern couples to three private-by-convention attributes. Watch for kit-side renames."

### 1.3 The vocab symlink is elegant, Windows-hostile, and documented

`src/price_space_llm/_vocab/0.1.json` and `_vocab/0.2.json` are symlinks into `signals/`. `pyproject.toml` line 15-19 explains the mechanism. Hatchling follows symlinks at wheel-build time. Editable install reads through the symlink. Both scenarios verified via the Sprint 003 fresh-venv wheel install check.

Windows lacks POSIX symlinks by default (admin or Developer Mode required). If a Windows contributor ever arrives, `scripts/sync_vocab.py` copies the JSON explicitly. Sprint 003 notes flagged this correctly.

Both `0.1.json` and `0.2.json` remain accessible via `load_vocabulary(name=...)`. `loader.default = "0.2.json"`. Callers can request the prior version. Correct implementation of "originals over summaries" (commitment #6).

### 1.4 Duplicated depth-aware split in `_parse_type`

Sprint 008 added `_split_top_level(s, sep)` (lines 195-209) — a reusable depth-aware split. The `dict<K,V>` branch (lines 224-234) predates Sprint 008 and duplicates the logic inline. Both do the same thing (walk the string, track angle-bracket depth, split at depth 0). The `struct<>` branch (lines 240-249) uses `_split_top_level`. The `dict<K,V>` branch does not.

Refactor `dict<K,V>` to use `_split_top_level(inner, ",")` at the same time as the next signals-side change. One sprint, one concept. Not blocking.

### 1.5 What the architecture correctly does

- Package resource loading via `importlib.resources.files("price_space_llm._vocab")` — the Python 3.9+ right answer.
- `@lru_cache(maxsize=1)` factory + PEP 562 `__getattr__` shim — lazy singleton without breaking the `from price_space_llm.signals import emitter` idiom.
- Per-emit JSONL sink with `_sink_prepared` flag — no `mkdir` at construction, no `stat` per emit.
- `Signal` reconstructed locally in the sink path (lines 346-353) — no read into `self._buffer[-1]` after the Sprint 005 refactor.
- `field_types` populated from `typed_payload` at load — one source of truth for the type declarations.

---

## 2. Python, linting, code arrangement

### 2.1 Ruff rule set — good starter, missing two useful packs

`pyproject.toml` line 34: `select = ["E", "F", "I", "UP", "B", "SIM", "PT"]`. Covers pycodestyle, Pyflakes, isort, pyupgrade, bugbear, simplify, pytest-style. Reasonable start.

Two packs worth adding once the sprint cadence steadies:

- **`RUF`** (ruff-specific): catches `noqa` misuse and a few enforcement gaps the others miss. Zero-config, no false positives at this codebase's size.
- **`ANN`** (missing annotations): forces every function to declare return type and every argument type. The current code annotates most functions but a few helpers (`_check_str` etc.) accept `Any` — the annotation is present, ANN would enforce it uniformly.

Skip `D` (docstrings) until the module-count grows enough that docstring discipline pays back.

### 2.2 mypy scope is `src/price_space_llm` only

`pyproject.toml` line 39: `files = ["src/price_space_llm"]`. Tests excluded. Reasonable — pytest fixture types are noisy under strict mode.

The consequence: type mismatches inside test bodies do not fail CI. `test_datetime_utc_malformed_raises` (line 122-134) passes `"trade_id": "trade-abc"` for a field typed `entity_ref<Trade>` (which parses as `str` per Layer 2, so OK). But if a test constructs a payload with a genuinely wrong type, mypy would catch it in `src` scope but not here. Follow-up: once test bodies stabilize, `files = ["src/price_space_llm", "tests"]` catches drift.

### 2.3 `# type: ignore[misc]` on both class definitions

`signals.py:264` and `:320` — `class StrictSignalVocabulary(SignalVocabulary):  # type: ignore[misc]`. Necessary because `sdd.py` has no `.pyi` stub and mypy cannot type-check the base class. The Sprint 006 override (`[[tool.mypy.overrides]] module = "sdd" ignore_missing_imports = true`) tells mypy to skip the module; `# type: ignore[misc]` on the subclass declaration handles the leftover.

Once `sdd.py` grows a `.pyi` stub (a v0.2-or-later kit sprint), both comments delete. Note in KIT_DIARY.

### 2.4 `StrictSignalEmitter.__init__` accepts the wrong parent type

Line 330: `vocabulary: SignalVocabulary`. Accepts the parent type. A caller who passes a plain `SignalVocabulary` (from `sdd.py`) constructs a "strict" emitter with non-strict validation, because the parent's `validate` runs, not `StrictSignalVocabulary`'s. The name promises strictness; the type signature admits its violation.

Tighten to `vocabulary: StrictSignalVocabulary`. mypy in strict mode surfaces every caller that passes a plain `SignalVocabulary`. There are none in the codebase.

### 2.5 Tests import private symbols

`tests/test_signals.py:114`, `:204`, `:211`, `:219`, `:228`, `:235`, `:257`, `:264` all do `from price_space_llm.signals import _parse_type` or similar. `_parse_type` and `_check_struct` are underscore-prefixed private symbols; importing them into tests couples the test suite to internal API.

Two shapes:

- Public the API: rename `_parse_type` → `parse_type`, `_check_struct` → `check_struct`, expose via `__all__`. Now they are contracted surface, not implementation.
- Test through the public API only: build a synthetic vocabulary that uses each type kind, load it via `StrictSignalVocabulary(schema)`, exercise via `validate(tag, payload)`. More code per test; no private coupling.

The first is cheaper and correctly reflects intent: `_parse_type` IS a public capability of this module, just currently under-marketed. Rename.

### 2.6 Wall-clock timing test is honest but still real time

`test_session_init_resets_the_clock` (line 189-197). Sprint 005 relaxed the threshold from `< 0.005` to `< 0.04`. Sleep is `0.05`. The threshold now distinguishes reset (t < 1ms typically) from no-reset (t >= 50ms) with 40x noise margin. Better.

Still a real-clock test. On a suspended CI runner it can fail. `monkeypatch.setattr(time, "monotonic", ...)` with a controlled clock removes the flake risk entirely:

```python
def test_session_init_resets_the_clock(tmp_path, monkeypatch):
    times = iter([100.0, 200.0, 200.0005])  # construct, sleep, emit
    monkeypatch.setattr(time, "monotonic", lambda: next(times))
    ...
```

Deterministic under any scheduler jitter. Costs three lines.

### 2.7 `pyproject.toml` version field lies

Line 3: `version = "0.1.0"`. The project's actual vocabulary version is `0.2` and the loader default reads `0.2.json`. Two independent version numbers coexisting is normal (package version ≠ vocabulary version), but the package's `0.1.0` is a placeholder that has not moved as the actual code has grown across ten sprints. Either bump to something meaningful (`0.0.1` for pre-release, `0.10.0` for "ten sprints in"), or adopt a `dynamic = ["version"]` scheme that reads from git tags. Currently it lies quietly.

### 2.8 Style — what the code does right

- `from __future__ import annotations` at line 24 — 3.11 doesn't need it, but harmless and consistent for PEP 563.
- Explicit `encoding="utf-8"` at line 305 (`read_text`) and line 352 (`open`). Sprint 003 discipline held.
- Named regex constants `_SHA256_RE`, `_DATE_ISO_RE` at module scope — one compile at import.
- `raise ... from e` on every re-raise. Traceback preserves the original cause.
- No mutable default args.
- No `print()` calls.
- No commented-out code.
- ruff --format check green (Sprint 006 exit code 0).

---

## 3. SDD-technique adherence, signals in particular

### 3.1 Zero pipeline emit call sites yet

`grep -rn '.emit(' src/ --include='*.py'` returns nothing. Every emit in the codebase lives in `tests/test_signals.py`. Correct at Sprint 010: no operator has been coded yet. The next sprint that authors an operator (per WORKING_AGREEMENT.md Phase 1 plan, Sprint 011 opens the MCP bridge mapping and Sprint 012 the PhaseZeroProbe) needs to import `get_emitter` and emit the four probe tags (`CHANNEL_PROBED`, `CHANNEL_COVERAGE_ASSESSED`, `CHANNEL_REJECTED`, plus SESSION boundaries via `ProcessRunner`).

Watch item: the first operator sprint should reference this review's §3.1 as the trigger to wire real emits. Sprint card should exit-code-check that `logs/{run_id}/signals.jsonl` contains the expected tag sequence — the observation contract WORKING_AGREEMENT names.

### 3.2 ProcessRunner exists on paper, not in code

`signals/0.2.json § operators` names `ProcessRunner` as the harness that emits `SESSION_INIT` at every script entry and `SESSION_COMPLETE` at exit. `StrictSignalEmitter.emit` resets `_session_start` when the tag is `SESSION_INIT` — the mechanism is in place. But nothing in `src/` wraps a script. When Sprint 011 authors `scripts/probe_channels.py`, the `SESSION_INIT` / `SESSION_COMPLETE` bookending needs to be first-class. A `ProcessRunner` context manager (or main-function decorator) would enforce it:

```python
@contextmanager
def process_session(run_kind: str, config_hash: str, git_sha: str, data_hash: str, seed: int):
    run_id = f"{run_kind}-{now_iso()}-{seed}"
    e = get_emitter()
    start = time.monotonic()
    e.emit("SESSION_INIT", run_id=run_id, run_kind=run_kind,
           vocab_version=VOCAB_VERSION, config_hash=config_hash,
           git_sha=git_sha, data_hash=data_hash, seed=seed)
    n = 1
    try:
        yield run_id
        exit_code = 0
    except SystemExit as ex:
        exit_code = ex.code or 0
        raise
    except Exception:
        exit_code = 1
        raise
    finally:
        e.emit("SESSION_COMPLETE", run_id=run_id, exit_code=exit_code,
               elapsed_seconds=time.monotonic() - start, n_signals_emitted=len(e.snapshot()))
```

That is Sprint 011's first concrete artifact. Author it now (pre-emptive design) or file it as a design-note to `WORKING_AGREEMENT.md § Canonical home registry`. Either way, name it before Sprint 011 dispatches.

### 3.3 Sprint 007 → 010 chain is exemplary supervised-evolution

Four-sprint sequence: `sdd-discipline-check-round-1.md §3` surfaces the permissive fallback. Sprint 007 attempts the tighten, halts on `vocabulary_change_required` when it uncovers a v0.1 defect (`CAPACITY_SWEEP_COMPLETED.points` typed as malformed `dict<K,V>` shorthand). Sprint 008 adds `struct<name:type, ...>` to the Layer-2 parser (records the addition in v0.2 `grammar_growth.project_overrides`). Sprint 009 locks v0.2 with the corrected type declaration; `signals/0.1.json` stays on disk per hard rule 12. Sprint 010 re-runs Sprint 007's tighten against v0.2. Everything green.

This is what `grammar/PRINCIPLES.md § "The supervised-grammar-evolution proposal taxonomy"` describes in the abstract. The project executed it. Sprint 007 stayed on disk as `status: halted`. BLACKBOARD `## Decisions` and `## Surfaced for review` carry the full paper trail. `signals/proposals.json` filed P-016 as `INVARIANT_PROPOSED` (closest canonical fit) and stamped accepted. `signals/0.2-rationale.md` cites every ancestor.

Cite as canon in the KIT_DIARY for future sprints. The pattern to remember: halt-and-articulate produced a better vocabulary than the fast-fix would have (the malformed declaration could have been silently downgraded to `list<dict<str, float>>` and the per-field type information erased).

### 3.4 Halt-and-articulate has been honestly practiced since the review

`BLACKBOARD.md § Surfaced for review` (line 139) carries a retroactive audit of the Sprint 003 file-count stretch and the Sprint 005 concept-count stretch. Both got named as "bypass-not-halt" patterns. WORKING_AGREEMENT gained a `hard_rule_stretch` halt condition. Sprint 007 filed a legitimate `vocabulary_change_required` halt. Sprint 009's card explicitly ticks the plan-mode checklist "Six files. Halt-and-articulate for `hard_rule_stretch` filed; Architect calls ratify-or-split" — the halt was called, the Architect ratified, the sprint proceeded. The mechanism works.

### 3.5 Determinism budget declared from Sprint 007 forward

Sprints 007-010 carry `determinism_budget: n/a` in frontmatter — appropriate for architecture-band sprints that import no PyTorch and run no training step. Sprints 001-006 do not carry the field, which is honest: it was added after the sdd-discipline-check-round-1 review named the gap. The field is now templated forward. Next sprint that imports PyTorch declares `bit-deterministic` or `statistically-deterministic`.

### 3.6 Vocabulary is the contract, verified

- `signals/0.2.json` loaded via `importlib.resources`, source of truth for `field_types`. Confirmed.
- Every emit runs `validate` before recording. Confirmed at line 341 (`super().emit(tag, **payload)` where the parent's `emit` calls `self._vocab.validate` before appending to buffer).
- Extras check + required-fields check + per-field type check. Three layers of enforcement at the speaker's mouth (Sprint 001 keys, Sprint 004 types, Sprint 007+010 unknown-type-string).
- Range checks (Layer 7 `range` constraints) deliberately deferred to grading-time per Sprint 004's Note. Correct stratification: emit-time checks type; report-time checks value ranges against pre-registered gates.
- Cross-reference resolution (`entity_ref<X>`) treated as opaque `str` at emit; referent-existence is a Layer-8 report concern. Correct three-layer split.

---

## 4. Spec adherence — product-spec-v4 + tech-arch-v4

### 4.1 Runtime dependencies vs stack declaration

`product-spec-v4.md § Dependencies § Software`: "Python 3.11, PyTorch 2.x, Polars for DataFrames, PyArrow for Parquet, Hydra + Pydantic v2 for typed configs, Weights & Biases for tracking, pytest for tests, `uv` for dependency management."

`pyproject.toml § dependencies = []` — empty. Dev-only: pytest, ruff, mypy. Correct at Sprint 010 (no pipeline code) but a divergence to name: at Sprint 011 the MCP bridge mapping needs an HTTP client and JSON codec; Sprint N (feature pipeline) needs Polars; Sprint N+K needs PyTorch. Each bridge-mapping-triggered addition should append to `dependencies` and pin a version. `product-spec §Software` gives the shortlist; upper bounds are the sprint author's call.

Note in WORKING_AGREEMENT: "First sprint that imports each SDK adds the dep to `pyproject.toml` in the same commit as the bridge mapping."

### 4.2 Repo layout materialization is ahead of the spec

`technical-architecture-v4.md § 3` prescribes: `configs/`, `data/`, `artifacts/`, `src/ingestion/`, `src/features/`, `src/tokenizer/`, `src/model/`, `src/training/`, `src/simulation/`, `src/evaluation/`, `src/utils/`, `experiments/`, `notebooks/`, `tests/`, `scripts/`. Current tree: `sprints/`, `src/price_space_llm/`, `tests/`, `signals/`, `specs/`, `reviews/`, `sdd-kit-2/`. Zero pipeline directories yet.

`.gitignore` correctly excludes `data/raw/`, `data/aligned/`, `data/tokenized/`, `data/manifests/`, `artifacts/`, `logs/`, `wandb/`. Prescience — the directories don't exist but their ignore rules are in place. Good.

### 4.3 Pre-commit hooks the spec names, not present

`technical-architecture-v4.md § 2 invariant #5`: "One source of truth per channel. A per-commit test enforces it (§16)."
`technical-architecture-v4.md § 2 invariant #7`: "No hardcoded target instrument. Any commit that introduces a `SPY`-specific symbol outside `configs/` or `tests/` fails review."
`technical-architecture-v4.md § 13`: "Structural enforcement of the 3-look budget. `scripts/check_test_look.sh` is a pre-commit hook."

Three pre-commit hooks named. Zero present. Correct absence at Sprint 010 (none of the code the hooks guard exists). Sprint that adds ingestion (`src/ingestion/`) is the sprint that authors `scripts/check_test_look.sh` and hooks the no-SPY grep and one-source-of-truth channel test into pre-commit.

### 4.4 SPY discipline verified

`grep -rE '\bSPY\b' src/ --include='*.py'` returns nothing. `tests/test_signals.py:141` uses `"target_symbol": "SPY"` inside a fixture — explicitly permitted by invariant #7 ("SPY appears only in default configs, in test fixtures, and in default arguments"). Compliant.

### 4.5 Vocabulary-to-spec traceability

Every one of the 55 tags in `signals/0.2.json` carries a `source` field. Spot-checked:

- `SESSION_INIT.source` cites `foundations/01-signal-driven-development.md § "SESSION_INIT pattern"` + `TECHNIQUES.md § 1 #9` + `tech-arch-v4.md §9.3`.
- `CHANNEL_PROBED.source` cites `tech-arch-v4.md §4.1` + `product-spec-v4.md § "Phase 0 data-availability probe"`.
- `TRAINING_DIVERGED.source` cites `product-spec-v4.md § "Success gates for v1" gate 1` + `reviews/vocab-0.1-coverage-review.md finding 1`.
- `TEST_LOOK_REGISTERED.source` cites `tech-arch-v4.md §13`.

Every product-spec pre-registered gate has a signal home. Every tech-arch invariant is either currently unenforced by absence-of-code (correct) or encoded in an evidence constraint. The vocabulary IS what the specs describe, at the granularity the specs describe it.

### 4.6 Prescribed tests, not yet present

`technical-architecture-v4.md § 16` names ten specific unit tests: tokenizer round-trip, `known_at` revisions, staleness fields, alignment gap-injection, one-source-of-truth channel, no-hardcoded-target, model forward-pass shape, causal-mask, training-loop all-position CE, simulator zero-alpha, no-lookahead, integration end-to-end. Zero present. Correct absence — every test targets a module that has not been coded. Every prescribed test is a Sprint N acceptance criterion for the module it guards.

### 4.7 One product-spec item worth flagging early

`product-spec-v4.md § Dependencies § Data § BBO calibration`: "Any free source producing target-instrument BBO snapshots on the 2015–2022 window." The tech-arch treats BBO as a required input for `scripts/calibrate_spread.py` (§11.1) but does not name a source. The MCP tool list does not include BBO. Polygon.io fallback is for 15-min bars, not BBO.

This is a spec-side gap the project inherits: the BBO source is unspecified. Not a Sprint 010 concern; will be a `bridge_mapping_required` halt when Sprint N tries to author `scripts/calibrate_spread.py`. File to BLACKBOARD `## Deferred` now with revisit trigger "sprint that authors calibrate_spread.py."

---

## 5. Punch list

**Before Sprint 011:**

- Decide layout: keep `signals.py` at package root, or move under `observability/` or `utils/` (§1.1).
- Rename `_parse_type` → `parse_type` and `_check_struct` → `check_struct`; add to `__all__`; drop test-body underscore imports (§2.5).
- Author `ProcessRunner` context manager or design-note it in `WORKING_AGREEMENT.md` before Sprint 011 needs it (§3.2).
- File the BBO-source `bridge_mapping_required` deferral to BLACKBOARD (§4.7).

**In Sprint 011 or 012:**

- Refactor `dict<K,V>` branch in `_parse_type` to use `_split_top_level` for consistency (§1.4).
- Tighten `StrictSignalEmitter.__init__` parent type to `StrictSignalVocabulary` (§2.4).
- Monkey-patch `time.monotonic` in `test_session_init_resets_the_clock` (§2.6).
- Bump `pyproject.toml § project.version` from placeholder `0.1.0` to something meaningful or dynamic (§2.7).
- Add `RUF` and `ANN` to `ruff.lint.select` (§2.1).

**Watch items for Sprint 011+:**

- First operator sprint wires actual emits + `logs/{run_id}/signals.jsonl` observation contract (§3.1).
- Bridge mappings materialize dep-by-dep in `pyproject.toml` (§4.1).
- Pre-commit hooks (`check_test_look.sh`, no-SPY grep, one-source-of-truth) land as ingestion sprints open (§4.3).

**No defects to fix.** Ten sprints in, the code is clean, the tests pass under strict tooling, the vocabulary is defendable, the halt-and-articulate discipline works. The four sprints from `sdd-discipline-check-round-1.md §3` → Sprint 007 → 008 → 009 → 010 is the loop the kit describes, executed end to end. The next-sprint watch is wiring real emits — the point at which SDD's "signals drive" transitions from design to practice.
