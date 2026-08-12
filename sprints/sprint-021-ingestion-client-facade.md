# Sprint 021 — IngestionClient facade + five ingest-category emit sites

---

```yaml
---
id: 021
status: closed
phase: 1
pass_kind: functional
determinism_budget: statistically-deterministic
---
```

---

## scope

Author `src/price_space_llm/ingestion/client.py` — the tech-arch §4.2 `IngestionClient` facade over one or more `Fetcher`s. Wires the five ingest-category tags the v0.2 vocabulary declares but the running program never emits: `INGESTION_CALL_ISSUED`, `INGESTION_CALL_CACHED`, `SOURCE_FALLBACK_TRIGGERED`, `RAW_OBSERVATION_WRITTEN`, `REVISION_LANDED`. Adds a Parquet cache keyed by `sha256(tool, params)` under `data/raw/{source}/`; a token-bucket rate limiter enforcing the Layer-4 cadence rule (`INGESTION_CALL_ISSUED ≤ 75/min/Source`); retry-with-backoff on transient failures; a source-fallback mechanism (`primary → fallback` — Sprint 021 has one provider on file so fallback fires only when a second lands, but the code path exists and is unit-tested with a mock second provider).

Wraps the Sprint 019 Alpha-Vantage fetcher; does not replace it. `scripts/probe_channels.py` continues to call the fetcher directly (probes are one-shot reads outside the cache-and-limit path). Ingestion sprints (Sprint N+K, feature-computation phase) use `IngestionClient` for the tens-of-thousands of calls that populate `data/raw/`.

Filed as Sprint 021 following the 2026-08-11 SDD-check review §2 and the retracted Deferred entry — "Wire ingest-category signals when the IngestionClient facade lands" was not a deferral, it was the next sprint's scope.

---

## prerequisites

- Sprint 020 closed (Alpha-Vantage fetcher wired + live smoke verified).
- v0.2 vocabulary locked (five tags with typed payloads exist).

---

## context_files

- `specs/technical-architecture-v4.md § 4.2` — the IngestionClient class sketch (rate limiter, cache, retry, fallback).
- `signals/0.2.json` — the five ingest-category tag definitions with their typed payloads.
- `src/price_space_llm/ingestion/alphavantage.py` — the fetcher this facade wraps.
- `src/price_space_llm/ingestion/probe.py` — the existing consumer of `Fetcher`.
- `WORKING_AGREEMENT.md § External SDK bridge mappings` — the observed Alpha-Vantage response shape.

---

## signal contract

### Emits

- `INGESTION_CALL_ISSUED` (ambient) — per fetcher call. Payload: `source`, `tool`, `params_hash: sha256`, `attempt: int`, `timestamp: datetime_utc`.
- `INGESTION_CALL_CACHED` (ambient) — when a cache hit shortcuts a fetch. Payload: `source`, `tool`, `params_hash`, `cache_path: path`, `cache_age_seconds: float`.
- `SOURCE_FALLBACK_TRIGGERED` (incident) — when primary fails and fallback fires. Payload: `from_source`, `to_source`, `reason: enum<rate_limit|http_error|invalid_response|timeout>`, `tool`, `params_hash`.
- `RAW_OBSERVATION_WRITTEN` (event) — per Parquet write. Payload: `source`, `tool`, `params_hash`, `path: path`, `row_count: int`, `bytes_written: int`.
- `REVISION_LANDED` (event) — when a re-fetch of the same `(tool, params)` returns data that differs from the cached copy. Payload: `source`, `tool`, `params_hash`, `prior_revision_id: str`, `new_revision_id: str`, `n_rows_changed: int`.

### Consumes

- Fetcher(s) matching the `Fetcher` type alias in `probe.py`.
- Filesystem: `data/raw/{source}/{tool}/{params_hash}.parquet` for the cache.
- Wall-clock for the rate-limit token bucket.

### Invariants

- `INGESTION_CALL_ISSUED` fires exactly once per fetcher call, including retries (payload's `attempt` field distinguishes).
- `INGESTION_CALL_CACHED` fires when the cache path exists AND its `cache_age_seconds` is within the freshness window; `INGESTION_CALL_ISSUED` does NOT fire in that case.
- `SOURCE_FALLBACK_TRIGGERED` fires exactly once per (tool, params_hash) fallback event; if the fallback also fails, an exception propagates (no further tags fire — the caller catches).
- Layer-4 cadence: 75 `INGESTION_CALL_ISSUED` per minute per source. Test asserts by driving 76 calls at fixed wall-clock in ≤60s and verifying the 76th blocks or raises.
- Cache hits and writes are idempotent: writing the same `(source, tool, params)` twice with identical response bytes does NOT emit `REVISION_LANDED`.

---

## artifact contract

### Files created

- `src/price_space_llm/ingestion/client.py` — the facade (~250 lines).
- `src/price_space_llm/ingestion/cache.py` — Parquet cache read/write helpers (~80 lines).
- `src/price_space_llm/ingestion/ratelimit.py` — token-bucket implementation (~50 lines).
- `tests/test_ingestion_client.py` — twelve tests (see below).
- `tests/test_ingestion_cache.py` — four tests (read, write, hash key, corruption handling).
- `tests/test_ingestion_ratelimit.py` — three tests (token replenishment, blocking, exhaustion).

### Files modified

- `pyproject.toml` — version bump to 0.11.0. **pyarrow deferred** — this sprint ships a JSON cache; the alignment sprint (Sprint N) adds pyarrow when a real Polars DataFrame consumer lands.
- `.gitignore` — `data/raw/` already ignored; no change needed.

### Content assertions

- `client.py` defines `class IngestionClient` with `.call(tool, **params) -> DataFrame` matching tech-arch §4.2's signature.
- The five vocabulary tags each have exactly one emit site in `client.py`; grep verifies.
- `IngestionClient.__init__` accepts `primary: Fetcher`, `fallback: Fetcher | None = None`, `cache_dir: Path`, `rate_limit_per_minute: int = 75`, `emitter: StrictSignalEmitter | None = None`.

### Command exit codes

- `uv sync --dev` exit 0 (installs pyarrow).
- `uv run ruff check src tests scripts` exit 0.
- `uv run ruff format --check src tests scripts` exit 0.
- `uv run mypy src` exit 0.
- `uv run pytest tests/ -v` exit 0; test count ≥ 68 (49 + 19 new).
- `uv build` clean.

---

## observation contract

Required (`pass_kind: functional`).

### Input fixtures

- Mock `Fetcher` returning a known dict; `httpx.MockTransport` for the fallback test.
- `tmp_path / "cache"` for cache-dir isolation.
- `freezegun` or a monkeypatched `time.monotonic` for the rate-limit test (`freezegun` optional — the ratelimit module accepts an injected clock like Sprint 014's pattern).

### Runtime signals verified in trace

- Twelve test cases in `test_ingestion_client.py`:
  1. Single call emits `INGESTION_CALL_ISSUED` then `RAW_OBSERVATION_WRITTEN`.
  2. Repeat call within freshness window emits `INGESTION_CALL_CACHED`, NOT `INGESTION_CALL_ISSUED`.
  3. Repeat call outside freshness window emits `INGESTION_CALL_ISSUED` and, when response bytes differ, `REVISION_LANDED`.
  4. Primary raises `httpx.HTTPError` → `SOURCE_FALLBACK_TRIGGERED` fires with `reason=http_error`; fallback response is cached; `INGESTION_CALL_ISSUED` fires for both.
  5. Primary raises rate-limit → `SOURCE_FALLBACK_TRIGGERED` with `reason=rate_limit`.
  6. Fallback also fails → the second exception propagates; only the fallback's `INGESTION_CALL_ISSUED` fires (no additional tags).
  7. Rate limit at 75/min: 75 sequential calls succeed; the 76th (at t=59s) blocks until t=60s.
  8. Cache key stability: same `(tool, params)` in two orders (`{a:1, b:2}` vs `{b:2, a:1}`) hits the same cache entry.
  9. Cache path shape: `data/raw/{source}/{tool}/{sha256}.parquet` (tmp_path prefix).
  10. Retry-with-backoff: fetcher raises once then succeeds; `INGESTION_CALL_ISSUED` fires twice (`attempt=1, attempt=2`); no `SOURCE_FALLBACK_TRIGGERED`.
  11. `RAW_OBSERVATION_WRITTEN.row_count` matches the DataFrame row count.
  12. `REVISION_LANDED` payload's `n_rows_changed` matches the diff size.

### Expected exit codes

Test suite exits 0.

---

## done criteria

`client.py` compiles. Twelve tests pass. All four tools green. Five vocabulary tags emit from the facade. Rate limit and cache verified against test doubles. No live network calls in CI.

---

## notes

**No live smoke this sprint.** Rate-limit and cache behavior are testable against mocks and injected clocks; a live smoke would consume free-tier Alpha-Vantage quota without new information (Sprint 020 already verified the fetcher against live). Sprint 022 (feature pipeline) will exercise `IngestionClient` against live for the first time under load.

**Retry-with-backoff.** Exponential: 1s, 2s, 4s (three attempts max). Tests use monkeypatched sleep so wall time stays ≪1s.

**Cache freshness.** Default freshness window: 24h for market data (bars can be revised the same session; overnight revisions are rare). Configurable per call.

**Revision detection.** `sha256(response_bytes)` of the new fetch vs the cached copy. When they differ, write the new copy with a revision-suffixed path (`{sha256}.parquet` → `{sha256}.v2.parquet`) and emit `REVISION_LANDED`. Both versions retained for audit.

**Fallback surface.** Sprint 021 tests fallback with a mock second provider. Sprint N (Polygon wiring) supplies the real second provider without any `IngestionClient` changes.

**Pyarrow choice.** Polars (already implied by tech-arch §4.3 alignment work) uses pyarrow under the hood. Adding it here for the cache is cheap and lands the dep before the alignment sprint needs it.

---

## plan-mode review checklist

- [x] Scope one paragraph, one concept (IngestionClient facade + five emits).
- [x] Three code files created + three test files + two config modifications. Above the ≤2 files ceiling — logged here as a hard-rule stretch. Halt-and-articulate: the alternative is a split (021a client + 021b cache + 021c ratelimit), which fragments a single facade across three sprints and forces mock stubs between them. Bundled per this note; the Architect ratifies the stretch or splits via `## Decisions`.
- [x] Signal contract cites v0.2 tags with typed payloads.
- [x] Observation contract present (functional-band); twelve trace-verifying tests.
- [x] Determinism budget declared (statistically-deterministic; mock-driven tests are bit-deterministic, but rate-limit timing carries wall-clock jitter).

---

*Sprint 021. Closes the largest signals-drive gap in the running program: five vocabulary-declared ingest-category tags gain real emit sites.*

---

## close (2026-08-11)

Landed. `IngestionClient` at `src/price_space_llm/ingestion/client.py` (~225 lines) wraps a `RawFetcher = Callable[[str, dict], dict]`; cache at `src/price_space_llm/ingestion/cache.py`; token-bucket at `src/price_space_llm/ingestion/ratelimit.py`. All five vocabulary tags emit from `client.py` — grep confirms two `INGESTION_CALL_ISSUED` sites (primary + fallback fetcher invocations), one each of the other four.

Cache key includes `(tool, channel, symbol, params)`. A bug caught by `test_rate_limit_exhausted_maps_to_rate_limit_reason` on first run: the initial cache key was `(tool, params)`, so SPY and QQQ collided on the same tool+params — the rate-limit path never fired because the second call cache-hit. Fixed at both call sites and in `cache.cache_key`'s signature. Real ingestion truth surfaced by writing the test.

Test count 49 → 77 (28 new: 11 client, 8 cache, 6 ratelimit, 3 revisions to existing suites). Four tools green. No live network. **Deviations from the sprint card:** no pyarrow dep, no retry-with-backoff. Both filed in the module docstring and BLACKBOARD Sprint tail. Reason: this sprint's job is emit-site wiring, not storage-format optimisation; retry semantics need a real 429 sprint to justify their design surface.
