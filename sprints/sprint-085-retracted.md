# Sprint 085 -- RETRACTED (2026-08-17)

---

```yaml
---
id: 085
status: retracted
phase: E
pass_kind: architecture
determinism_budget: n/a
---
```

## retraction

Sprint 085 was reserved for a `StrictSignalEmitter.close_session()` helper that would compute `n_signals_emitted` from the buffer instead of accepting the value from the caller. The 2026-08-10 drift-watchlist entry (from Sprint 002 Rubber Duck Pass) named this as a follow-up.

On 2026-08-17, before opening the sprint, a grep across `src/` and `scripts/` for `emit("SESSION_COMPLETE", ...)` returned exactly one hit: inside `signals.py::process_session`, which already computes `n_signals_emitted` from the buffer as `len(e.snapshot()) - buffer_before + 1`. Zero direct callers exist outside the context manager. The caller-set-lie failure mode has no reachable code path today.

Retracted. The drift-watchlist entry marked RESOLVED in the same audit pass ("2026-08-10 ... RESOLVED 2026-08-17 by architecture — no live caller-set path exists"). Sprint 086 (cache sidecar backfill) opened next.

## audit-trail preservation

Per hard rule 12 (no deletions). Sprint 085 exists as this retracted-card marker so a future reader tracing the sprint numbering encounters an explanation at the number rather than a silent gap. The `close_session` helper is not scheduled; if a direct `emit("SESSION_COMPLETE", ...)` call site ever lands outside `process_session`, a future sprint reopens the concept.

## reference

- 2026-08-10 (Agent, from Sprint 002 Rubber Duck Pass; RESOLVED 2026-08-17 by architecture) — `BLACKBOARD.md ## Drift watchlist`.
- KIT_DIARY entry 2026-08-17 "Sprints 084 + 086: drift-watchlist convention retired" names the same architectural resolution.
