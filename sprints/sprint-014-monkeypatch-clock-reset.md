# Sprint 014 — deterministic clock-reset test

---

```yaml
---
id: 014
status: closed
phase: 1
pass_kind: architecture
determinism_budget: n/a
---
```

---

## scope

Replace the real-clock `time.sleep(0.05)` and `assert line["t"] < 0.04` in `test_session_init_resets_the_clock` with a monkeypatched `time.monotonic` per `reviews/full-review-round-1.md` §2.6. The current test remains a wall-clock timing assertion, which can drift on a suspended CI runner or under `pytest-xdist` parallelism. Injecting a controlled clock removes the flake risk entirely and asserts the same invariant deterministically.

One file (`tests/test_signals.py`); no production code changes.

---

## prerequisites

- Sprint 013 closed.

---

## context_files

- `reviews/full-review-round-1.md` §2.6
- `tests/test_signals.py` (`test_session_init_resets_the_clock` at line ~189)
- `src/price_space_llm/signals.py` (`StrictSignalEmitter.emit` uses `time.monotonic`; the test monkeypatches that module's binding via `monkeypatch.setattr`)

---

## signal contract

### Emits

Test-time only.

### Consumes

- `signals/0.2.json` (unchanged).

### Invariants

- All 29 existing tests pass.
- `test_session_init_resets_the_clock` uses `monkeypatch.setattr(time_module, "monotonic", controlled_clock)` — no `time.sleep`.
- The test asserts `line["t"] == 0.0` (or equivalent tight bound) after a controlled-clock-injected reset.

---

## artifact contract

### Files modified

- `tests/test_signals.py` — rewrite `test_session_init_resets_the_clock` to inject a controlled monotonic clock. The clock returns three values in sequence: `100.0` at emitter construction (`__init__` reads via parent), `200.0` at the pre-SESSION_INIT `_session_start` reset, `200.0005` at the SESSION_INIT emit's `t = monotonic - session_start`. Assert the sink line's `t` equals `0.0005` (deterministic).

### Files created

None.

### Content assertions

- `tests/test_signals.py` `test_session_init_resets_the_clock` does not contain `time.sleep`.
- The test uses `monkeypatch` (pytest fixture).
- The test asserts `t < 0.001` (well under any real-clock threshold).

### Command exit codes

- `uv run ruff check src tests` exit 0.
- `uv run ruff format --check src tests` exit 0.
- `uv run mypy src` exit 0.
- `uv run pytest tests/ -v` exit 0; 29 tests pass.

---

## observation contract

Not applicable. `pass_kind: architecture`.

---

## done criteria

Test is deterministic. 29 tests pass. All tools green.

---

## notes

**Monkeypatch target.** `StrictSignalEmitter.emit` and `_session_start = time.monotonic()` both call the `time.monotonic` symbol resolved from the `time` import in `price_space_llm.signals`. Patching `time.monotonic` at the module scope (`monkeypatch.setattr("price_space_llm.signals.time.monotonic", fake)`) redirects both call sites.

**Clock schedule.** The reference emitter's `__init__` sets `_session_start = time.monotonic()`. The test constructs an emitter, calls emit SESSION_INIT which resets `_session_start` and then records t. Two monotonic reads happen after construction: the reset itself, and the Signal's t computation. Pre-seed an iterator with three values: construction, reset, emit-record.

**Threshold after patch.** With a controlled clock, `t = 200.0005 - 200.0 = 0.0005`. Assert `< 0.001` — deterministic, distinct from no-reset (which would give `200.0005 - 100.0 = 100.0005`).

---

## plan-mode review checklist

- [x] Scope one paragraph, one concept.
- [x] One file modified.
- [x] Signal contract vacuous.
- [x] Artifact contract gradable.
- [x] Determinism budget declared (n/a).

---

*Sprint 014. Deterministic clock-reset test. Sprint 015 handles the tooling + version bumps.*
