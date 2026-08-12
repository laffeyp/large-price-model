# Sprint 022 — vocabulary v0.3 lock: add CHANNEL_FETCH_FAILED

---

```yaml
---
id: 022
status: closed
phase: 1
pass_kind: architecture
determinism_budget: bit-deterministic
---
```

---

## scope

Add one incident tag `CHANNEL_FETCH_FAILED` (category `probe`) to the vocabulary so the probe can record fetcher exceptions honestly instead of fabricating `CHANNEL_PROBED` payloads. Lock as v0.3. Six required payload fields: `channel`, `symbol`, `source`, `sample_date`, `exception_class`, `error_message`. Add one `diagnostic_required` evidence constraint on `error_message` (non-empty).

Triggered by the 2026-08-11 Architect correction: Sprint 020's `_error_shim` in `scripts/probe_channels.py` shipped fabricated fill values (`actual_frequency="15min"`, epoch-zero timestamps, `revision_behavior="immutable"`) whenever a fetcher raised. That was a code failure, not a "vocabulary gap" to file for later. The correct sequence — halt at first emit-time refusal, evolve the vocabulary if genuinely insufficient, then wire the code — was missed. Sprint 022 executes the evolve step. Sprint 023 executes the wire step and rips the lies out.

---

## prerequisites

- v0.2 locked (`signals/0.2.json` on disk).
- Architect ratification of path (b): new `CHANNEL_FETCH_FAILED` tag (2026-08-11 "yeah, then we update the vocab if need be, then continue").

---

## artifact contract

### Files created

- `signals/0.3.json` — the lock (copy of 0.2 + one new tag + one new evidence constraint + version metadata bump).
- `signals/0.3-rationale.md` — delta doc (~450 words).
- `src/price_space_llm/_vocab/0.3.json` — symlink to `../../../signals/0.3.json`.

### Files modified

- `src/price_space_llm/signals.py` — `load_vocabulary` default `"0.2.json" -> "0.3.json"`.
- `tests/test_signals.py` — `test_locked_vocabulary_loads_all_tags` reads `0.3.json`.
- `tests/test_ingestion_client.py` — SESSION_INIT `vocab_version="0.3"`.

### Content assertions

- `signals/0.3.json` parses as JSON.
- `signals/0.3.json § tags` contains `CHANNEL_FETCH_FAILED` with the six required payload fields, category `probe`, stratum `incident`.
- `signals/0.3.json § evidence_constraints.constraints` gains one `diagnostic_required` entry on `CHANNEL_FETCH_FAILED.error_message`.
- v0.3 tag count = 56 (55 → 56).
- v0.2 remains on disk unchanged (hard rule 12).

### Command exit codes

- `uv run pytest tests/ -q` exit 0; test count unchanged from Sprint 021 (77) — no code changes yet.
- `uv run ruff check src tests scripts` exit 0.
- `uv run mypy src` exit 0.

---

## observation contract

Not applicable. `pass_kind: architecture` — vocabulary lock, no runtime behavior. Sprint 023 supplies the observation contract for the wiring.

---

## done criteria

v0.3 locks. Loader defaults to v0.3. Existing tests pass against v0.3 (backward-compatible extension — every prior tag unchanged; adding a new tag does not break any existing emit path).

---

## notes

**Why path (b) and not (a) or (c).** Path (a) would mark `earliest_timestamp` optional on `CHANNEL_REJECTED` and `CHANNEL_COVERAGE_ASSESSED`. Semantic ambiguity: `null` earliest_timestamp could mean "empty month" or "vendor error" or "we haven't populated it yet." Path (b) — a distinct tag for the fetcher-exception case — separates "we got data but not enough" from "the vendor call itself broke." A Reviewer reading the trace does not need context to tell them apart.

**Path (c) — both — deferred.** Path (a) would only pay off for a "legitimate empty month" case that hasn't occurred yet. If the alignment sprint or a live smoke surfaces it, v0.4 revisits.

**Zero-observation channels.** With v0.3, when a channel has zero successful probes, `CHANNEL_FETCH_FAILED` fires per date but neither `CHANNEL_REJECTED` nor `CHANNEL_COVERAGE_ASSESSED` can (both require `earliest_timestamp`). The channel's `ChannelCoverage` object returns `verdict="dropped"`, `reason="all_fetches_failed"`, `earliest_timestamp=None`. The trace record: N `CHANNEL_FETCH_FAILED` and no closer. A downstream reader inspects: a channel with `CHANNEL_FETCH_FAILED` and no `CHANNEL_COVERAGE_ASSESSED` is unassessable. The signal grammar tells the truth by what it says and what it refuses to say.

**Layer-4 pairing constraint not added.** A future sprint that formalises the "either CHANNEL_COVERAGE_ASSESSED or all-failed" rule as a temporal invariant could add it. Not blocking.

---

## plan-mode review checklist

- [x] Scope one paragraph, one concept (one new tag + one new constraint).
- [x] One artifact-side lock (v0.3.json); two files modified (loader default + one test fixture).
- [x] Signal contract: vacuous — the tag is added but no emit call site changes in Sprint 022.
- [x] Determinism budget declared (bit-deterministic — pure JSON edit).
- [x] Architect ratification recorded in `## Decisions` on the same day.

---

## close (2026-08-11)

v0.3 locked at 56 tags. Every existing tag unchanged in shape. `CHANNEL_FETCH_FAILED` added with six required fields; one diagnostic_required constraint on `error_message`. Loader default retargeted. 77 tests pass unchanged. Sprint 023 wires the tag.
