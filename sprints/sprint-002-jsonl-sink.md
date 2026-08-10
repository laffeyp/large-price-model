# Sprint 002 — JSONL sink + SESSION_INIT clock reset

---

```yaml
---
id: 002
status: pending
phase: 1
pass_kind: functional
---
```

---

## scope

Extend `src/price_space_llm/signals.py` so `StrictSignalEmitter` writes one JSON line per emit to a configured sink path, and so it resets the emitter's `_session_start` clock on any `SESSION_INIT` emit. Fixes Sprint 001 code note 3 (drift-watchlist entry: `t` values currently read relative to Python import, not to session init). Extend `tests/test_signals.py` with three tests that exercise the sink: SESSION_INIT bookends a capture, the JSONL file has the right line count, and `t` resets to near-zero at SESSION_INIT even when the emitter has been alive for seconds.

Two files, one concept: **a bounded capture with an on-disk trace and correct per-session clock**. This sprint is functional-band because it changes runtime behavior (a sink writes to disk when configured); the observation contract below verifies that behavior.

---

## prerequisites

- Sprint 001 closed (emitter, strict-extras, four tests passing).

---

## context_files

- `sdd-kit-2/AGENTS.md`
- `sdd-kit-2/lib/sdd.py` (`SignalEmitter.emit` signature, buffer semantics, `SignalCapture.as_json` format)
- `signals/0.1.json` (SESSION_INIT and SESSION_COMPLETE payload schemas — the tests build valid payloads for both)
- `src/price_space_llm/signals.py` (current state; the sprint modifies this file in place per hard rule 7 SEARCH/REPLACE discipline)
- `tests/test_signals.py` (current state; the sprint appends the three new tests)
- `BLACKBOARD.md` (`## Drift watchlist` entry naming the `_session_start` fix)
- `WORKING_AGREEMENT.md` (project observation-contract environment — JSONL trace + file existence + line count)
- `sdd-kit-2/TECHNIQUES.md` §1 #9 (SESSION_INIT pattern), #38 (test fixtures from confirmed-good captures)

---

## signal contract

### Emits

At test-time. Tests emit real SESSION_INIT and SESSION_COMPLETE with valid payloads plus a few in-between tags so the trace has shape. Concrete list (once per test that exercises the sink):

- `SESSION_INIT` (`run_id`, `run_kind='eval'`, `vocab_version='0.1'`, `config_hash`, `git_sha`, `data_hash`, `seed`)
- `CHECKPOINT_WRITTEN` (`run_id`, `step`, `path`, `val_nll`, `val_ece`, `val_brier`, `val_rps`, `val_dir_acc`, `val_top1`, `val_top3`) — one in-between event to prove the sink writes non-boundary tags too
- `SESSION_COMPLETE` (`run_id`, `exit_code=0`, `elapsed_seconds`, `n_signals_emitted=3`)

### Consumes

- The extended `StrictSignalEmitter(vocab, jsonl_sink=Path(...))` constructor path.

### Invariants

- `SESSION_INIT` is the first line of any JSONL trace written to a fresh sink path.
- `SESSION_COMPLETE` is the last line.
- No out-of-vocabulary tags emitted.
- Strict-extras posture preserved (Sprint 001's validation path unchanged).
- `_session_start` resets exactly once per `SESSION_INIT` emit; subsequent tags in that capture carry `t` values relative to that reset.

---

## artifact contract

### Files modified

- `src/price_space_llm/signals.py` — `StrictSignalEmitter` gains an optional `jsonl_sink: Path | None` constructor argument and overrides `emit()` to (a) reset `_session_start` when `tag == "SESSION_INIT"`, (b) append one JSON object per emit to the sink path when set. Existing exports and the module-level `emitter` singleton (no sink) unchanged.
- `tests/test_signals.py` — appends three tests.

### Files created

None.

### Content assertions

- `src/price_space_llm/signals.py` `StrictSignalEmitter.__init__` accepts `jsonl_sink: Path | None = None`.
- `src/price_space_llm/signals.py` `StrictSignalEmitter.emit` opens `jsonl_sink` in append mode and writes one line of `json.dumps({...}) + "\n"` per emit when the sink is set.
- `src/price_space_llm/signals.py` `StrictSignalEmitter.emit` resets `self._session_start = time.monotonic()` when the incoming tag is `SESSION_INIT`, before recording the signal.
- `tests/test_signals.py` contains three new named tests: `test_jsonl_sink_writes_one_line_per_emit`, `test_session_init_and_complete_bookend_the_trace`, `test_session_init_resets_the_clock`.

### Command exit codes

Architect runs each.

- `uv run pytest tests/ -v` returns 0; all 7 tests pass (4 from Sprint 001 + 3 new).
- `uv run python -c "from price_space_llm.signals import StrictSignalEmitter, load_vocabulary; from pathlib import Path; e = StrictSignalEmitter(load_vocabulary(), jsonl_sink=Path('/tmp/psllm_test.jsonl')); e.emit('SESSION_INIT', run_id='r1', run_kind='eval', vocab_version='0.1', config_hash='a'*64, git_sha='b'*40, data_hash='c'*64, seed=1); e.emit('SESSION_COMPLETE', run_id='r1', exit_code=0, elapsed_seconds=0.001, n_signals_emitted=2); print(sum(1 for _ in open('/tmp/psllm_test.jsonl')))"` prints `2` and returns 0.

---

## observation contract

Required per `pass_kind: functional` and hard rule 9.

### Input fixtures

- A temporary directory per test (pytest `tmp_path` fixture). No global state.

### Expected runtime signals

For `test_jsonl_sink_writes_one_line_per_emit`: three lines in the sink file — SESSION_INIT, CHECKPOINT_WRITTEN, SESSION_COMPLETE, in that order.

For `test_session_init_and_complete_bookend_the_trace`: the first line's `tag` field equals `"SESSION_INIT"`; the last line's `tag` field equals `"SESSION_COMPLETE"`.

For `test_session_init_resets_the_clock`: create an emitter, sleep 0.05 seconds, emit SESSION_INIT. Read the JSONL line back; `t` field is < 0.005 (well under the pre-emit sleep). Confirms the reset happened at emit time, not at emitter construction.

### Expected log substrings

Not applicable — pytest captures stdout/stderr; no external log stream.

### Expected screenshot

Not applicable — no UI.

### Expected exit codes

`uv run pytest tests/ -v` exit 0. The pytest run itself is the observation harness for this sprint.

---

## done criteria

`StrictSignalEmitter(vocab, jsonl_sink=path)` writes one JSON line per emit; `t` in the trace reads relative to the most recent `SESSION_INIT` (or emitter construction if none fired). Seven tests pass.

---

## notes

**Why override `emit()` instead of subclassing `SignalCapture`.** The reference `SignalCapture.as_json` produces a bulk snapshot at capture close; this sprint wants per-emit streaming so the trace file grows live and a killed process still leaves a partial trace on disk. Streaming is what the observation contract in WORKING_AGREEMENT names.

**Why append mode.** A test that opens the sink and emits three tags then re-opens and emits three more should see six lines, not the last three. Append semantics match the log-append discipline for JSONL traces.

**Line format.** `json.dumps({"tag": ..., "category": ..., "t": ..., **payload}) + "\n"`. Mirrors `sdd.Signal.to_dict()` which returns the same shape. The sink appends one such dict per emit.

**Path handling.** `jsonl_sink.parent.mkdir(parents=True, exist_ok=True)` runs in `__init__` so `logs/{run_id}/signals.jsonl` works without a pre-existing directory.

**Backwards compatibility.** Module-level `emitter` continues to construct with no sink; existing Sprint 001 tests keep passing unchanged.

---

## plan-mode review checklist

- [ ] Scope one paragraph, one concept.
- [ ] Two modified files, no new files. Within hard rule 6.
- [ ] Observation contract present per hard rule 9 (functional-band sprint).
- [ ] Signal contract references only tags in `signals/0.1.json`.
- [ ] Artifact contract is gradable.
- [ ] Sprint dispatches on Architect "go".

---

*Sprint 002. JSONL sink + session-clock reset. Fixes Sprint 001 code note 3. Three new tests.*
