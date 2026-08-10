# Code review — sprints 001 + 002, best-practice pass

**Reviewer:** Claude Code (Opus 4.7), acting in Agent role.
**Date:** 2026-08-10.
**Scope:** `src/price_space_llm/signals.py` (94 lines), `tests/test_signals.py` (99 lines), `pyproject.toml` (23 lines). The vocabulary session closed at v0.1 (55 tags, 24 operators, 64 evidence constraints, no orphans); this review does not re-examine that. Focus: Python correctness, packaging, design, test hygiene, tooling.
**Recommendation:** Fix §1 before Sprint 003 authors any code that runs from an installed wheel. Address §§2–4 in the next 1–2 sprints. §5 is tooling that pays back on every subsequent sprint.

---

## 1. One ship-blocker

**`_VOCAB_PATH = Path(__file__).resolve().parents[2] / "signals" / "0.1.json"`** — `signals.py:21`.

The path assumes the package lives three levels below the project root (`src/price_space_llm/signals.py` → `parents[2]` = `/…/Train Your Own LLM`). During editable install (`uv sync`) that path resolves; the JSON loads; tests pass. In a wheel install, `parents[2]` points somewhere inside `site-packages/` and no `signals/` directory sits there. `pyproject.toml` line 15 `force-include`s `sdd.py` into the wheel but does not ship `signals/0.1.json`. Any downstream consumer who installs the wheel and does `from price_space_llm.signals import emitter` gets `FileNotFoundError` at import.

Fix: package the JSON as a resource under the module (`src/price_space_llm/_vocab/0.1.json`), load with `importlib.resources`, drop the walk-up path:

```python
from importlib.resources import files

def load_vocabulary(name: str = "0.1.json") -> StrictSignalVocabulary:
    text = files("price_space_llm._vocab").joinpath(name).read_text(encoding="utf-8")
    doc = json.loads(text)
    ...
```

Add `[tool.hatch.build.targets.wheel.force-include]` for the JSON (or move the JSON into the package layout so it ships automatically). Keep `signals/0.1.json` at project root as the authoring surface; the packaging step copies it into `_vocab/` at build time. Two locations, one source of truth, no wheel-vs-editable divergence.

## 2. `Strict` is strict only about keys

`StrictSignalVocabulary.validate` (`signals.py:27–36`) rejects extra fields and missing required fields. It ignores every other constraint the vocabulary declares. The typed_payload entries in `signals/0.1.json` name `enum<probe|align|calibrate|train|eval|simulate>` for `run_kind`, `sha256` for hashes, `datetime_utc` for timestamps, `float` for numbers with declared ranges. None of those fire at emit time. Layer 7 evidence constraints (`kind: range`, `kind: required_field`, cardinality bounds) live in the JSON and stay there.

Consequence: `emitter.emit("SESSION_INIT", run_kind="banana", ...)` succeeds. The trace records `banana`. Downstream consumers of the trace break. The commitment PRINCIPLES.md #2 — "schema enforced at the speaker's mouth" — passes for tag names and required-key presence, fails for the typed-payload substance the vocabulary took eight review rounds to nail down.

Two fixes, either works:

- Extract enum/range/type rules from the JSON at load time and check them inside `validate`. Cheap, no new dependency, one pass over `typed_payload` per emit.
- Generate a Pydantic v2 model per tag (dict → BaseModel via `create_model`) and validate on construction. Buys type coercion for free, but adds a runtime dep to a module currently at zero deps.

The first is closer to the SDD kit's "text and convention, no orchestration" spirit and fits the current no-deps posture.

## 3. Design nits inside the emitter

`signals.py:73–81` — `StrictSignalEmitter.emit`. Four small slips.

**Double validation per emit.** Line 74 calls `self._vocab.validate(tag, payload)` explicitly. Line 77 calls `super().emit(tag, **payload)` which calls `self._vocab.validate(tag, payload)` again inside the parent's implementation (`sdd.py:95`). Two dispatches per call. The comment on line 74 says "pre-validate; raises before any side effect" — but the parent also raises before any side effect, so the explicit pre-call is duplicative. Delete line 74.

**Reaching into `self._buffer[-1]`.** Line 79 fetches the just-appended signal from the parent's private deque. Coupling to a `_leading_underscore` attribute. If the parent ever changes its buffer semantics (bounded queue eviction on overflow, thread-local buffers, LIFO stack), this line silently reads the wrong record. Reconstruct the signal locally instead — the fields are all available at the emit site:

```python
from sdd import Signal
signal = Signal(tag=tag, category=self._vocab.category_of(tag),
                payload=payload, t=time.monotonic() - self._session_start)
super().emit(tag, **payload)  # parent still buffers
if self._jsonl_sink is not None:
    self._jsonl_sink.open("a", encoding="utf-8").write(...)
```

**`mkdir` in `__init__` (line 71).** Constructing an emitter creates a directory as a side effect. A caller who builds an emitter to introspect its vocabulary but never emits still leaves a directory on disk. Move to first-emit or to an explicit `open_sink()` method.

**No `encoding="utf-8"`.** Line 41 (`path.read_text()`) and line 80 (`self._jsonl_sink.open("a")`) accept locale encoding. Trace files written on Linux (utf-8) then read on Windows (cp1252) mangle non-ASCII payloads. Trace files contain payload text that may include vendor names, symbol descriptors, and error strings — anywhere a `str` field lives — non-ASCII will bite. Two `encoding="utf-8"` additions.

## 4. Module-level singleton at import

`signals.py:84` — `emitter: StrictSignalEmitter = StrictSignalEmitter(load_vocabulary())`.

Reading a file at import means `from price_space_llm.signals import <anything>` fails if the JSON is missing or malformed. Any tool that walks the package (doc generation, static analysis, `python -c 'import price_space_llm'` in a sanity check) then depends on the vocabulary file being present and parseable. That is a runtime concern leaking into module load.

Two better shapes:

```python
from functools import lru_cache

@lru_cache(maxsize=1)
def get_emitter() -> StrictSignalEmitter:
    return StrictSignalEmitter(load_vocabulary())
```

or an explicit factory that callers invoke with their own configuration (paths, sink, buffer size). The `lru_cache` variant preserves the "one process, one emitter" convenience without the import-time file read.

Related: `tests/test_signals.py` uses the module-level `emitter` in three tests (lines 55, 60, 65) without isolation. The singleton's buffer accumulates across the suite. In this small suite, order does not matter; once tests emit at bar cadence, order will. A `pytest.fixture` returning a fresh `StrictSignalEmitter` per test costs one file-read per test but decouples state. The three sink-tests already do this via `tmp_path` and their own local `e`; the first three tests should follow.

## 5. Test brittleness

**`test_locked_vocabulary_loads_with_55_tags`** — asserts exact tag count against 55. Any deliberate v0.2 addition (the rationale doc names five candidates) breaks the test. Better: read the count from the JSON as the source of truth (`assert len(vocab.tags()) == len(json.loads(_VOCAB_PATH.read_text())["tags"])`), or assert a lower bound and let the JSON be the count-of-record. If the test intent is "any tag-set change is intentional," name that in the assertion message so a failing developer knows they need to update, not debug.

**`test_session_init_resets_the_clock`** — sleeps 50ms, then asserts `t < 0.005`. That is timing against real wall-clock. On a busy CI runner (GitHub Actions Linux, `pytest-xdist` in parallel), scheduler jitter easily consumes 5ms between the sleep return and the emit. Test is flaky-prone. Mock `time.monotonic` with `monkeypatch`, or relax the threshold to something the reset dramatically achieves (`< 0.04`, since the sleep was `0.05`). The current threshold makes the test read "reset works or emit is very fast"; the second interpretation dominates.

**Payload fixtures use fake hex.** `"a" * 64` for a sha256, `"b" * 40` for a git_sha. Length is right; content is trivially non-hex. When §2's type/format enforcement lands, these strings fail hash-validation and every test breaks together. Better: `hashlib.sha256(b"test").hexdigest()` and a real 40-char hex string. Costs nothing; survives the strictness upgrade.

**`n_signals_emitted` overridden in one test.** `VALID_SESSION_COMPLETE_PAYLOAD["n_signals_emitted"] = 2` is a module-level constant; `test_jsonl_sink_writes_one_line_per_emit` overrides to 3 via dict-spread (line 77). The constant now lies for anyone reading it without noticing the override. Compute the count instead: `"n_signals_emitted": len(sink.read_text().splitlines()) + 1` — or drop the constant and build the payload inline in each test.

## 6. Tooling the project should adopt now

`pyproject.toml` declares one dev dep (`pytest>=8.0`) and no linter, formatter, or type checker. For a project whose entire premise is typed-schema-at-the-speaker's-mouth, static type checking pays back per-sprint:

**Add `ruff` (lint + format).** One tool covers both roles, fast, no config needed to start. `ruff check src tests` in CI catches unused imports, mutable-default-args, missing return types.

**Add `mypy --strict` or `pyright` in strict mode.** The vocabulary types `run_kind` as an enum of six strings. Once §2 lands, the Python-side call site `emitter.emit("SESSION_INIT", run_kind=some_var)` should be typechecked against a `Literal["probe","align","calibrate","train","eval","simulate"]`. A generated `signals.pyi` from the JSON (or `TypedDict` per tag) turns emit calls into type-checked contracts. That is the SDD commitment "workers cannot invent vocabulary" expressed in Python's type system.

**Pytest strictness knobs.** Add to `[tool.pytest.ini_options]`:

```toml
addopts = ["--strict-markers", "--strict-config", "-ra"]
filterwarnings = ["error"]
xfail_strict = true
```

`--strict-markers` catches typos in `@pytest.mark.slow` becoming a silent no-op. `filterwarnings = ["error"]` turns Pydantic/PyTorch deprecation warnings into failures — a training run buries them otherwise. `-ra` prints skips/xfails at end of run for review.

**PEP 735 `[dependency-groups]`.** Works with `uv sync`; `pip install -e ".[dev]"` will not pick it up. Fine given uv is the declared tool of record, but note it in a `CONTRIBUTING.md` or a README section so a contributor arriving with pip understands the failure.

## 7. Style: sprint-narration in docstrings

`signals.py:7–9` — the module docstring narrates sprint history: *"Sprint 002: StrictSignalEmitter gains an optional JSONL sink…"*. `test_signals.py:1` does the same: *"Sprint 001 + 002 tests"*.

The user's global `CLAUDE.md` names this explicitly under "Every output is writing":

> Don't reference the current task, fix, or callers ("used by X", "added for the Y flow", "handles the case from issue #123"), since those belong in the PR description and rot as the codebase evolves.

Sprint numbers belong in `BLACKBOARD.md`, `KIT_DIARY.md`, sprint cards, and commit messages — not in shipped code. Docstrings should say what the module *is*, not when it was written. Delete the sprint references; the git log carries the timeline. Similarly `signals.py:8` — the "history in the docstring" pattern will accrete Sprint 003, 004, N with every extension until the docstring is unreadable.

## 8. What's honest about the code so far

Two files at 94 + 99 lines, clean separation between vocabulary and emitter, streaming JSONL sink with per-emit flush (a killed process leaves a valid partial trace), test isolation via `tmp_path` in the sink tests, and a package layout that keeps the vocabulary at project root as the source of truth. The strict-extras posture is real. The `SESSION_INIT` clock reset is right for how a trace file wants to read. The single ship-blocker (§1) is a common wheel-vs-editable stumble that catches every first-time Python packager; the rest are small.

The pattern to name across the sprint cadence: each sprint has added machinery a Reviewer can point to file:line and say "that is where the failure will live" — a testable surface. The next best-practice move is closing the loop between the vocabulary-declared types and the Python-side type system, so the guarantees the vocabulary session earned show up in `mypy` output rather than only at runtime.

## 9. Punch list

**Before Sprint 003:**
- Fix §1 (wheel install).
- Add `encoding="utf-8"` in two places (§3).
- Delete the double-validation call (§3).
- Delete the sprint narration in the two docstrings (§7).

**In Sprint 003 or 004:**
- Extract enum/type constraints from `typed_payload` and enforce in `StrictSignalVocabulary.validate` (§2).
- Replace `emitter` singleton with `get_emitter()` + `lru_cache` (§4).
- Reconstruct the signal locally instead of reaching into `_buffer[-1]` (§3).
- Move `mkdir` out of `__init__` (§3).
- Add ruff, mypy/pyright, pytest strictness knobs (§6).

**Whenever tests bite:**
- Replace the exact-count assertion with a data-driven read (§5).
- Mock `time.monotonic` in the clock-reset test (§5).
- Move the three singleton-based tests to a per-test emitter fixture (§4/§5).

None of this is defect. All of it is compound-cost: fix once, avoid a class of failures across every future sprint.
