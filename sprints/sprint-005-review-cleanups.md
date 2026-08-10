# Sprint 005 — review cleanups (§3 leftovers + §4 factory + §5 tests)

---

```yaml
---
id: 005
status: closed
phase: 1
pass_kind: architecture
---
```

---

## scope

Address the remaining small findings from `reviews/code-best-practices-round-1.md`:

- **§3.** Move `jsonl_sink.parent.mkdir` out of `StrictSignalEmitter.__init__` so constructing an emitter has no filesystem side effect. Reconstruct `Signal` locally in `emit()` instead of reading `self._buffer[-1]` (decouples from parent's private deque).
- **§4.** Replace the module-level `emitter` singleton with `get_emitter()` decorated by `@lru_cache(maxsize=1)`. Preserve the `from price_space_llm.signals import emitter` idiom via a module-level `__getattr__` shim (PEP 562) that resolves to the cached factory result. Callers get the same object; import no longer touches disk before first access.
- **§5.** Read the tag count from the JSON at test time rather than hard-coding `== 55`. Relax the clock-reset test's wall-clock threshold from `< 0.005` (flaky on busy CI) to `< 0.04` (still one-tenth of the 0.05s pre-emit sleep, deterministic under any scheduler jitter). Compute `n_signals_emitted` inline per test instead of overriding a lying module-level constant.

Two files modified: `src/price_space_llm/signals.py` and `tests/test_signals.py`. No new files.

`§6` (ruff, mypy, pytest strictness knobs) is its own sprint — tooling adoption is a separate concept.

---

## prerequisites

- Sprint 004 closed.
- `reviews/code-best-practices-round-1.md` on file.

---

## context_files

- `reviews/code-best-practices-round-1.md` (§3 mkdir + Signal reconstruction; §4 factory; §5 tests)
- `src/price_space_llm/signals.py`
- `tests/test_signals.py`
- `sdd-kit-2/lib/sdd.py` (Signal dataclass surface — the fields to reconstruct)

---

## signal contract

### Emits

Test-time only. Existing 17 tests continue firing.

### Consumes

- `signals/0.1.json` (via `price_space_llm._vocab.0.1.json` sub-resource).

### Invariants

- Every existing test passes unchanged (17 in, 17 out).
- `StrictSignalEmitter(vocab, jsonl_sink=path)` does not create the sink's parent directory until first emit.
- `from price_space_llm.signals import emitter` still works.
- `StrictSignalEmitter.emit` no longer reads `self._buffer[-1]`; the JSONL line is built from local variables at the emit call site.
- Test suite has no hard-coded `== 55` for the tag count.
- Wall-clock threshold in `test_session_init_resets_the_clock` is `< 0.04`, not `< 0.005`.

---

## artifact contract

### Files modified

- `src/price_space_llm/signals.py`:
  - Delete `if jsonl_sink is not None: jsonl_sink.parent.mkdir(...)` from `__init__`.
  - Add a private flag `_sink_prepared: bool = False` initialised in `__init__` when `jsonl_sink` is set.
  - In `emit()`, when `_jsonl_sink is not None`: if not `_sink_prepared`, `mkdir(parents=True, exist_ok=True)` then set `_sink_prepared = True`. Reconstruct `Signal` locally with the current tag / category / payload / t (no `self._buffer[-1]` read). Write the reconstructed signal's `to_dict()` to the sink.
  - Replace `emitter: StrictSignalEmitter = StrictSignalEmitter(load_vocabulary())` with `@lru_cache(maxsize=1) def get_emitter() -> StrictSignalEmitter: return StrictSignalEmitter(load_vocabulary())`.
  - Add `def __getattr__(name: str)` at module level that returns `get_emitter()` when `name == "emitter"` and raises `AttributeError` otherwise (PEP 562).
  - Add `get_emitter` to `__all__`.

- `tests/test_signals.py`:
  - `test_locked_vocabulary_loads_with_55_tags` renamed to `test_locked_vocabulary_loads_all_tags`; body reads the count from the packaged JSON and asserts equality with `vocab.tags()`.
  - `test_session_init_resets_the_clock` relaxes threshold from `< 0.005` to `< 0.04`.
  - `test_jsonl_sink_writes_one_line_per_emit` builds the `SESSION_COMPLETE` payload inline with `n_signals_emitted = 3` at the call site (no dict-spread over the module constant).
  - `VALID_SESSION_COMPLETE_PAYLOAD` module constant drops `n_signals_emitted = 2`; each test that uses SESSION_COMPLETE builds the field inline. Constants stop lying.

### Content assertions

- `signals.py` does not contain `self._buffer[-1]`.
- `signals.py` `StrictSignalEmitter.__init__` does not call `mkdir`.
- `signals.py` defines `get_emitter` decorated with `@lru_cache(maxsize=1)`.
- `signals.py` defines `__getattr__(name)` at module scope.
- `signals.py` module scope does not contain `emitter: StrictSignalEmitter = StrictSignalEmitter(...)`.
- `tests/test_signals.py` does not contain the literal `== 55`.
- `tests/test_signals.py` `test_session_init_resets_the_clock` asserts `< 0.04`.
- `tests/test_signals.py` `VALID_SESSION_COMPLETE_PAYLOAD` does not contain `n_signals_emitted`.

### Command exit codes

- `uv sync --dev` exit 0.
- `uv run pytest tests/ -v` returns 0; all 17 tests pass.
- `uv run python -c "from price_space_llm.signals import emitter; print(len(emitter._vocab.tags()))"` prints the count read from the JSON, returns 0.
- `uv run python -c "import price_space_llm.signals as m; print(hasattr(m, 'get_emitter'))"` prints `True`.
- `uv build` clean; fresh-venv install still imports the emitter.

---

## observation contract

Not applicable. `pass_kind: architecture`.

---

## done criteria

Constructing a `StrictSignalEmitter` with a sink does not create the parent directory. `emit` does not read the parent's private buffer. `get_emitter()` is the factory; `emitter` remains importable via PEP 562. Tag count and wall-clock threshold no longer hard-coded. 17 tests pass.

---

## notes

**Why PEP 562 for backwards compat.** Deleting the module-level `emitter` name would force every `from price_space_llm.signals import emitter` to change. `__getattr__` resolves the attribute on first access to the cached `get_emitter()` — same object identity as if the caller invoked `get_emitter()` directly. Zero test churn, zero downstream churn, lazy behavior at the module boundary.

**Sink prepare flag vs check-on-every-emit.** Alternative: `if not self._jsonl_sink.parent.exists(): self._jsonl_sink.parent.mkdir(...)`. Adds a `stat` syscall per emit. Flag adds one branch per emit and zero syscalls after the first. Flag wins at bar cadence.

**`n_signals_emitted` in the constant was already lying.** `VALID_SESSION_COMPLETE_PAYLOAD["n_signals_emitted"] = 2` is what the two-emit tests need; the three-emit sink test dict-spreads over it to `= 3`. Reader sees `= 2` in the constant and assumes it's always right. Fix by dropping the field from the constant and letting each test build it inline where the count is knowable.

**Threshold at 0.04 stays honest.** The sleep is 0.05s. Without a reset, `t` would read ~0.05. With a reset, `t` reads whatever `time.monotonic() - <just-reset-time>` returns — sub-millisecond on any reasonable machine. `< 0.04` distinguishes reset (true) from no-reset (false) with 40x margin against noise. `< 0.005` distinguished reset from a slow emit — a distinction the test does not care about.

---

## plan-mode review checklist

- [ ] Scope one paragraph, multiple small concepts bundled under "review cleanups". Above the ≤2 files rule 6 in absolute file count; within it in code count (~40 lines production + ~15 lines test).
- [ ] Signal contract is vacuous (no new emit surfaces).
- [ ] Artifact contract is gradable; every content assertion is a mechanical grep.
- [ ] Sprint dispatches on Architect "go".

---

*Sprint 005. Review cleanups. Sprint 006 adopts ruff + mypy + pytest strictness.*
