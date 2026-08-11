# Sprint 019 — Alpha-Vantage HTTP fetcher module

---

```yaml
---
id: 019
status: closed
phase: 1
pass_kind: architecture
determinism_budget: bit-deterministic
---
```

---

## scope

Author `src/price_space_llm/ingestion/alphavantage.py` — an `httpx`-based fetcher that implements the `Fetcher` signature from `probe.py` (`Callable[[channel, symbol, source, sample_date], FetchResult]`). Factory: `make_alphavantage_fetcher(api_key, client=None) -> Fetcher`. The optional `client` param lets tests inject `httpx.MockTransport`; production wires a default `httpx.Client(base_url="https://www.alphavantage.co", timeout=30)`.

Sprint 019 covers TIME_SERIES_INTRADAY for `channel ∈ {target, market_context}` — the three channels in `configs/channels/v1.json` (target SPY, market_context VIX, market_context USO). Other channel families raise `NotImplementedError` — later sprints add per-family tool dispatch (macro → CPI/UNRATE/etc, options → HISTORICAL_PUT_CALL_RATIO, event → EARNINGS_CALENDAR).

Adds `httpx>=0.27` to `pyproject.toml [project] dependencies` in the same commit per the dep-pin rule.

Sprint 020 wires the fetcher into `scripts/probe_channels.py` with a `--fetcher {mock,alphavantage}` flag and runs a live smoke against the real API.

---

## prerequisites

- Sprint 018 halted; Architect Decision on file naming path (a) HTTP + API key.

---

## context_files

- `WORKING_AGREEMENT.md § External SDK bridge mappings § Alpha-Vantage` (observed signatures + response shape from Sprint 018)
- `src/price_space_llm/ingestion/probe.py` (Fetcher signature + FetchResult shape)
- `signals/0.2.json` (source enum values)
- `.env.example` (env-var name)

---

## signal contract

### Emits

None. This sprint authors a fetcher primitive. No emit call sites; no import of `price_space_llm.signals`. The probe (Sprint 016 module) is where emits fire; the fetcher just returns a FetchResult.

### Consumes

Nothing at import. At call time: the injected `httpx.Client`.

### Invariants

- All 37 existing tests pass.
- The fetcher never emits a signal directly; the probe module is the emit boundary.
- `make_alphavantage_fetcher("no-key")` succeeds at construction; the key only matters at call time.
- Tests use `httpx.MockTransport` — zero live network calls in the CI suite.
- `pyproject.toml [project] dependencies` includes `"httpx>=0.27"`.

---

## artifact contract

### Files created

- `src/price_space_llm/ingestion/alphavantage.py` — the fetcher module.
- `tests/test_alphavantage.py` — MockTransport-driven tests.

### Files modified

- `pyproject.toml` — `dependencies` list gains `"httpx>=0.27"`.

### Content assertions

- `alphavantage.py` defines `make_alphavantage_fetcher(api_key: str, client: httpx.Client | None = None) -> Fetcher`.
- `alphavantage.py` defines `class AlphaVantageError(RuntimeError)`, `class AlphaVantageRateLimitError(AlphaVantageError)`, `class AlphaVantageResponseError(AlphaVantageError)`.
- `alphavantage.py` `Fetcher` returned by the factory: given `channel ∈ {target, market_context}`, calls `client.get("/query", params={function: "TIME_SERIES_INTRADAY", symbol, interval: "15min", outputsize: "full", month: sample_date.strftime("%Y-%m"), apikey: api_key, datatype: "json"})`.
- `alphavantage.py` normalises the response: strips ordinal prefixes (`"1. open"` → `"open"`), coerces string values to `float`/`int`, converts US/Eastern timestamps to UTC, computes `missing_fraction` and `earliest_timestamp` from the response's `Time Series (15min)` map.
- `alphavantage.py` raises `AlphaVantageResponseError` if the response JSON contains `"Error Message"`.
- `alphavantage.py` raises `AlphaVantageRateLimitError` if the response JSON contains `"Note"` or `"Information"` (Alpha-Vantage's rate-limit indicators).
- `alphavantage.py` raises `NotImplementedError` for `channel ∉ {target, market_context}`.
- `tests/test_alphavantage.py` contains at least eight tests exercising the paths above.

### Command exit codes

- `uv sync --dev` exit 0 (installs httpx).
- `uv run ruff check src tests scripts` exit 0.
- `uv run ruff format --check src tests scripts` exit 0.
- `uv run mypy src` exit 0.
- `uv run pytest tests/ -v` exit 0; test count ≥ 45 (37 + 8 new).
- `uv build` clean.

---

## observation contract

Not applicable. `pass_kind: architecture` — the fetcher is a primitive with no product behavior on its own. Sprint 020 wires and adds an observation contract for the live smoke run.

---

## done criteria

Fetcher module compiles, tests pass, tools green, wheel builds. Sprint 020 wires + smokes.

---

## notes

**Why `httpx` over `requests`.** Async support (future streaming), `MockTransport` for clean test injection, first-class type hints. `requests` would work; `httpx` is modern default. One dep; no additional test deps beyond the existing `pytest`.

**Free tier note.** Alpha-Vantage free tier is 25 req/day (updated from the older 5/min figure). Five sample dates × three channels = 15 calls per probe run. Fits inside daily budget. Ingestion sprints (Sprint N+K) need a paid tier or the Polygon fallback.

**`missing_fraction` computation for a probe of one month.** Expected bar count: `26 bars/day × trading_days_in_month`. Actual: `len(response["Time Series (15min)"])`. `missing_fraction = max(0, (expected - actual) / expected)`. Trading-day count from a US-market calendar — for Sprint 019 use a rough heuristic (21 trading days per month) and refine when Sprint N adds `pandas_market_calendars`.

**`earliest_timestamp` for a probe of one month.** `min(response["Time Series (15min)"].keys())` after UTC normalisation. Represents the earliest bar seen in the sampled month. The probe's aggregate `earliest_timestamp` (across all five sample dates) is the overall min.

**No `NotImplementedError` swallowing.** Probe/CLI catches at call time and maps to CHANNEL_REJECTED with reason `unsupported_channel` — Sprint 020's wire.

**Fetcher does not read env.** `api_key` is a param. Caller (CLI) reads `os.environ["ALPHAVANTAGE_API_KEY"]`. Cleaner separation; tests never touch env.

---

## plan-mode review checklist

- [x] Scope one paragraph, one concept.
- [x] Two code files created (fetcher + tests); one config modified (pyproject.toml).
- [x] Signal contract vacuous (no emits from the fetcher).
- [x] Artifact contract gradable.
- [x] Determinism budget declared (bit-deterministic — mocked HTTP, deterministic input → deterministic output).

---

*Sprint 019. Alpha-Vantage HTTP fetcher primitive. Sprint 020 wires + smoke.*
