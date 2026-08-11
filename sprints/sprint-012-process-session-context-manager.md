# Sprint 012 — `process_session` context manager

---

```yaml
---
id: 012
status: closed
phase: 1
pass_kind: architecture
determinism_budget: n/a
---
```

---

## scope

Author `process_session` as a context manager in `src/price_space_llm/signals.py`. Every script that runs against the pipeline wraps its work in this manager. Enter emits `SESSION_INIT` with `run_id`, `run_kind`, `vocab_version`, `config_hash`, `git_sha`, `data_hash`, `seed`. Exit emits `SESSION_COMPLETE` with `run_id`, `exit_code`, `elapsed_seconds`, `n_signals_emitted`. Exceptions produce `exit_code = 1`; `SystemExit(N)` produces `exit_code = N`. Fulfils the ProcessRunner operator named in `signals/0.2.json § operators` (currently on paper only) so Sprint 013+ probe / align / calibrate / train / eval / simulate scripts have a first-class bookending mechanism.

Also: `StrictSignalVocabulary` gains a `version: str` attribute; `load_vocabulary` reads the `version` field from the JSON and passes it through. `process_session` uses `get_emitter()._vocab.version` to fill `vocab_version` in the SESSION_INIT payload — no hardcoded constant.

Per `reviews/full-review-round-1.md` §3.2.

---

## prerequisites

- Sprint 011 closed.

---

## context_files

- `reviews/full-review-round-1.md` §3.2 (the sketch)
- `src/price_space_llm/signals.py` (the emitter and vocabulary — `process_session` lives alongside)
- `signals/0.2.json` (SESSION_INIT and SESSION_COMPLETE payload schemas — the manager's emit calls match)
- `signals/0.2.json § operators` (ProcessRunner named as the harness that emits these)
- `tests/test_signals.py` (existing SESSION_INIT / SESSION_COMPLETE test pattern)

---

## signal contract

### Emits

`process_session` emits `SESSION_INIT` on enter and `SESSION_COMPLETE` on exit. Test-time only for this sprint (no script yet imports it).

### Consumes

- `signals/0.2.json` (via `load_vocabulary` → `get_emitter()`; the manager reads the emitter singleton).

### Invariants

- Every `process_session` context emits exactly one `SESSION_INIT` on enter.
- Every `process_session` context emits exactly one `SESSION_COMPLETE` on exit, including on exception paths.
- `n_signals_emitted` in the SESSION_COMPLETE payload counts every signal emitted between the two boundary emits, inclusive.
- Exceptions raised inside the manager propagate — `finally` fires SESSION_COMPLETE, then the exception continues to the caller.
- `exit_code` on SESSION_COMPLETE: 0 on clean exit; the SystemExit code on `sys.exit(N)`; 1 on any other exception.
- All 25 existing tests continue to pass.

---

## artifact contract

### Files modified

- `src/price_space_llm/signals.py`:
  - `StrictSignalVocabulary.__init__` accepts a `version: str = "unknown"` parameter and stores it as `self.version`.
  - `load_vocabulary` reads `doc["version"]` and passes it to `StrictSignalVocabulary(schema, version=...)`.
  - Add `process_session(run_kind, config_hash, git_sha, data_hash, seed, run_id=None)` as a `@contextmanager`. On enter: mint run_id if None (format `{run_kind}-{utc-timestamp}-{seed}`), emit SESSION_INIT, start timer. On exit (finally): compute n_signals_emitted, emit SESSION_COMPLETE. Exception path: `exit_code = 1`; SystemExit path: `exit_code = int(ex.code or 0)`.
  - Add `process_session` to `__all__`.
- `tests/test_signals.py`:
  - Four new tests: `test_process_session_emits_init_and_complete`, `test_process_session_counts_signals_correctly`, `test_process_session_captures_exception_exit_code`, `test_process_session_captures_systemexit_code`.

### Files created

None.

### Content assertions

- `signals.py` `StrictSignalVocabulary.__init__` accepts a `version` parameter.
- `signals.py` `load_vocabulary` passes `version=doc["version"]` to the vocabulary constructor.
- `signals.py` defines `def process_session(...)` decorated with `@contextmanager`.
- `signals.py` `__all__` contains `process_session`.
- `tests/test_signals.py` contains the four named tests.

### Command exit codes

- `uv run ruff check src tests` exit 0.
- `uv run ruff format --check src tests` exit 0.
- `uv run mypy src` exit 0.
- `uv run pytest tests/ -v` exit 0; 29 tests pass (25 + 4 new).
- `uv build` clean.

---

## observation contract

Not applicable. `pass_kind: architecture` — no product behavior changes; the manager is a primitive that later sprints wire into scripts.

---

## done criteria

`process_session` works as a context manager. Four new tests pass. `StrictSignalVocabulary` exposes `.version`. All tools green.

---

## notes

**Why colocate with signals.py.** The manager reads `get_emitter()` and reaches into `_vocab.version` — every reference is in the signals module. Putting `process_session` in a separate `process.py` module would force a circular-import shape (process imports signals, signals module already defines emitter). Colocation is the cheapest correct layout.

**`vocab_version` from `.version`, not a constant.** A hardcoded `VOCAB_VERSION = "0.2"` in signals.py drifts on the next lock. Reading `get_emitter()._vocab.version` reads whichever version the loader loaded — one source of truth.

**Buffer-based `n_signals_emitted`.** Snapshot the buffer length before SESSION_INIT, take another snapshot before SESSION_COMPLETE emit, add one for SESSION_COMPLETE itself. Correct convention: count includes both boundary tags. Payload schema does not distinguish.

**SystemExit handling.** `sys.exit(0)` and `raise SystemExit(0)` both produce `exit_code = 0`. `sys.exit(2)` produces `2`. `sys.exit("failed")` produces `1` (Python's convention — non-integer code becomes 1). Handled via `int(ex.code or 0)` — `None` becomes `0`, ints stay, strings coerce to `1` via the fallback in the `except Exception` branch (not the SystemExit branch).

Wait — `int("failed")` raises. Cleaner: `exit_code = ex.code if isinstance(ex.code, int) else (0 if ex.code is None else 1)`. Handles the three cases explicitly.

**BaseException vs Exception.** KeyboardInterrupt inherits from BaseException, not Exception. Catching only Exception lets KeyboardInterrupt propagate without setting exit_code — SESSION_COMPLETE still fires from finally, with `exit_code = 0` unchanged. That reads as clean exit, which is wrong. Fix by initialising `exit_code = 1` at the top of finally IF an exception propagated (using `sys.exc_info` or a flag). Or: catch BaseException. The reference `contextmanager` idiom uses a flag.

---

## plan-mode review checklist

- [x] Scope one paragraph, one concept.
- [x] Two files modified.
- [x] Signal contract cites SESSION_INIT and SESSION_COMPLETE from the locked vocabulary.
- [x] Artifact contract gradable.
- [x] Determinism budget declared (n/a).

---

*Sprint 012. ProcessRunner as a context manager. Sprint 013 continues the punch list.*
