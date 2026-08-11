# SDD-discipline check round 2 — sprints 011-020, with spec adherence

**Reviewer:** Claude Code (Opus 4.7), acting in Agent role.
**Date:** 2026-08-11.
**Scope:** the ten sprints since the last SDD check — 011 (public parse API), 012 (`process_session`), 013 (signals cleanups), 014 (monkeypatch clock reset), 015 (tooling + version), 016 (Phase 0 probe module), 017 (probe CLI), 018 (MCP bridge — halted), 019 (Alpha-Vantage fetcher), 020 (live wire-in). Focus: SDD adherence — signals in particular — checked against `specs/product-spec-v4.md` and `specs/technical-architecture-v4.md`.
**Verdict:** halt-and-articulate discipline held twice under load (Sprint 018 halt, Sprints 020 Surfaced x2). Three real signal-side gaps against tech-arch §4.2/§4.3. One vocabulary gap the live smoke surfaced.

---

## 1. What went right

**Halt-and-articulate stuck.** Sprint 018 discovered the real MCP tool shape differed from what WORKING_AGREEMENT had documented (US/Eastern timestamps not UTC, ordinal-prefixed OHLCV keys, string-typed numbers, no vendor `known_at`). Sprint 018 filed a `bridge_mapping_required` halt, wrote nothing to production, updated WORKING_AGREEMENT with observed reality, and waited for the Architect to pick a transport. That is the exact loop `sdd-discipline-check-round-1.md §2` prescribed after the Sprint 003 and Sprint 005 bypasses. Two rounds of feedback, one changed behavior.

**`process_session` landed as recommended.** `signals.py:365` implements the context manager. Sprint 012 wired it before Sprint 016 needed it. Sprint 017's CLI script wraps `run_phase_zero_probe` inside it, produces a real 21-line JSONL trace at `logs/{run_id}/signals.jsonl`, with correct `n_signals_emitted` count and vocab_version sourced from `get_emitter()._vocab.version` — no hardcoded constant.

**Spec-derived constants match tech-arch §4.1.** `probe.py:29-38` names the five sample dates verbatim: 2015-06-15, 2018-06-15, 2020-06-15, 2022-06-15, 2025-01-15. `MISSING_FRACTION_THRESHOLD = 0.05` matches tech-arch. `EARLIEST_HISTORY_REQUIRED = date(2015, 6, 15)` matches. Verdict enum `{accepted, dropped, renegotiate}` matches the vocabulary's `CHANNEL_COVERAGE_ASSESSED.verdict` enum, which itself matches tech-arch §4.1.

**Determinism budget declared per sprint.** Every card 011 forward carries `determinism_budget: {bit-deterministic | statistically-deterministic | n/a}` in frontmatter. Sprint 020 (live network calls) correctly declares `statistically-deterministic`.

**Fetcher injection is a real code-side provider abstraction.** `probe.py:59` types `Fetcher = Callable[[str, str, str, date], FetchResult]`. `alphavantage.py:125` implements it; the probe module never imports httpx. That matches tech-arch §4.2's `ChannelFetcher Protocol` intent — the probe consumes an interface, providers plug in behind it.

**Live smoke caught a real ingestion gap.** Sprint 020's Alpha-Vantage run returned exit 2 because `TIME_SERIES_INTRADAY` does not support `^VIX` (VIX is an index, not an equity). The probe surfaced the config's blindspot; the vocabulary correctly recorded `dropped` with `reason: missing_fraction_high`. The dual contract worked — a live artifact-side check caught what unit tests could not.

## 2. Three signal-emission gaps against tech-arch §4.2 / §4.3

The v0.2 vocabulary declares five ingest-category tags: `INGESTION_CALL_ISSUED` (ambient), `INGESTION_CALL_CACHED` (ambient), `SOURCE_FALLBACK_TRIGGERED` (incident), `RAW_OBSERVATION_WRITTEN` (event), `REVISION_LANDED` (event). None fire in the running program.

**Gap A: `INGESTION_CALL_ISSUED` never emitted.** Tech-arch §4.2 defines `IngestionClient.call(tool, **params) -> DataFrame` as "the atomic unit of fetching from the Alpha-Vantage MCP." Every HTTP call in `alphavantage.py:149` is one such call; none emits. The vocabulary's Layer-4 cadence rule (`≤ 75 per minute per Source`, matching the tech-arch's token-bucket limit) is unenforced because no signal fires.

**Gap B: `INGESTION_CALL_CACHED` never emitted, no cache exists.** Tech-arch §4.2 prescribes "Parquet caching keyed by sha256(tool, params)." Current `alphavantage.py` has no cache. A Phase 0 probe is a read-only path; caching is not strictly necessary here. But the vocabulary declares the tag and the tech-arch prescribes the mechanism.

**Gap C: Rate limiter, retry-with-backoff, `SOURCE_FALLBACK_TRIGGERED` — all absent.** Tech-arch §4.2 names them; `alphavantage.py:149` is a raw `http.get`. If Alpha-Vantage returns 429, the fetcher `.raise_for_status()` throws, the `_error_shim` in `scripts/probe_channels.py` (per BLACKBOARD line 11) fabricates vocabulary-legal fill values, and the failure disappears into stderr. No `SOURCE_FALLBACK_TRIGGERED` fires because no fallback exists (Polygon is prescribed as fallback per tech-arch §4.2, unimplemented).

None of the three is a defect at Sprint 020 (Phase 0 probe read-only; single-source; no cache needed for one-shot). All three are watch items for the sprint that authors `src/price_space_llm/ingestion/client.py` (the tech-arch's `IngestionClient` facade). File a Deferred entry with revisit trigger "sprint that authors the IngestionClient facade" so future readers know these signals await wiring, not invention.

## 3. Vocabulary gap the live smoke exposed

The 2026-08-11 Surfaced entry (BLACKBOARD line 11) names it correctly: `CHANNEL_PROBED`'s payload has no field for "the fetcher raised an exception." Every payload slot is either a strict enum (`actual_frequency`, `revision_behavior`, `timestamp_semantics`), a fixed value (`timezone: UTC`), or an ISO datetime that must parse. When the fetcher throws, `_error_shim` fabricates `actual_frequency="15min"`, `revision_behavior="immutable"`, epoch-zero timestamps — vocabulary-legal but semantically dishonest. A Reviewer reading only the JSONL trace cannot distinguish rate-limit from data gap from schema error; all three collapse to `missing_fraction=1.0`.

The two paths the Surfaced entry names — (a) new `CHANNEL_FETCH_FAILED` tag at v0.3, (b) `revision_behavior` enum gains `"error"` — are the right two. Path (a) is cleaner (separate incident from ambient); path (b) is smaller (no v0.3 lock). The right time to decide is the sprint that first needs to distinguish AV rate-limit from data gap programmatically, per the entry's revisit trigger. Not this sprint's decision.

But name a third path too: the shim itself is the problem. `_error_shim` shouldn't fabricate — it should emit the exception context to a separate incident tag and mark the channel `dropped` without pretending the probe returned anything. That is path (a) refined: `CHANNEL_FETCH_FAILED` with `exception_class` and `error_message` fields, and `CHANNEL_PROBED` fires only when a fetch succeeded. Cleaner semantics.

## 4. Two hygiene items surfaced Sprint 020, honest handling

**JSONL append semantics (BLACKBOARD line 13).** Two invocations with the same `run_id` produce a doubled trace. Fix candidate: truncate on `SESSION_INIT`. Filed for a later signals-hygiene sprint. Not blocking. Real; honest; will land.

**Fixed-offset EST in `alphavantage.py:32`.** `US_EASTERN_OFFSET = timedelta(hours=-5)` is DST-wrong in warmer months. Deferred to a sprint that adopts `zoneinfo("America/New_York")`. Named in the module docstring and BLACKBOARD's Sprint 019 Rubber Duck Pass. Correct disposition: probe cares about `missing_fraction` and coverage window, not exact bar timestamps; the wrong-by-one-hour timestamp does not change the verdict.

## 5. Discipline scoreboard

| Item | Status |
|---|---|
| Sprint cards uniform template | Every card |
| `pass_kind` drives observation contract | Every card |
| `determinism_budget` declared | Sprints 011+ |
| Rubber Duck Pass logged | Every closed sprint |
| BLACKBOARD `## Surfaced` entries on live findings | Two today |
| Halt on bridge divergence | Sprint 018 |
| Halt-not-bypass on hard-rule stretch | Sprint 009 last used it; no stretches since |
| Vocabulary-as-contract | 55 tags, 64 evidence constraints, every source cited |
| Real emit call sites in `src/` | Three, in `probe.py` |
| Real JSONL trace on disk | Yes — Sprint 017 produced a 21-line trace |
| Dual contract on live artifact | Sprint 020 exit-2 caught VIX gap |
| Signals-drive on all pipeline stages | Phase 0 only — no ingest-category emits (§2 above) |

## 6. Recommendations

**Add to BLACKBOARD Deferred now** (do not open a sprint):

- "Wire ingest-category signals (`INGESTION_CALL_ISSUED`, `INGESTION_CALL_CACHED`, `SOURCE_FALLBACK_TRIGGERED`, `RAW_OBSERVATION_WRITTEN`, `REVISION_LANDED`) when the `IngestionClient` facade lands. Cite `reviews/sdd-check-round-2-with-spec.md §2` as the trigger. Absent this, the vocabulary declares five signals the running program never emits — a signals-drive gap."

**Decide before the sprint that authors the second fetcher** (Polygon fallback, or the BBO source):

- Fetcher-error vocabulary path (a vs b vs c per §3 above). The second fetcher forces the choice because a fallback needs `SOURCE_FALLBACK_TRIGGERED` and a distinguishable reason.

**One rationale-doc addition to v0.2 or v0.3:**

- Name the fetcher-injection pattern explicitly. Tech-arch §4.2 declares `ChannelFetcher Protocol` at the module level; the project has landed it as a plain `Callable` type alias in `probe.py:59`. That is the right pragmatic shape (Protocol adds runtime cost, Callable doesn't). Note in the rationale so a future Reviewer does not read the divergence as a spec violation.

**No sprint blocked.** Sprint 021 opens on the Architect's call. If the next slice is "wire more fetchers per channel family," the vocabulary gap in §3 should be resolved first so the added fetchers don't compound the shim burden. If the next slice is "author `IngestionClient` facade," the signal-emission gap in §2 closes as a side effect.

The trajectory: fifteen sprints, one legitimate halt (018), two hygiene Surfaced entries (2026-08-11), zero silent bypasses, one design pattern (fetcher injection) that matches spec intent without matching spec syntax. The dual contract caught a real data gap on the live smoke. Signals now emit from running code, not only from tests. The system is doing what SDD says it should do.
