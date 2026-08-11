# Sprint 020 — wire Alpha-Vantage fetcher into probe CLI + live smoke

---

```yaml
---
id: 020
status: closed
phase: 1
pass_kind: functional
determinism_budget: statistically-deterministic
---
```

---

## scope

Extend `scripts/probe_channels.py` with a `--fetcher {mock,alphavantage}` flag. The default stays `mock` (deterministic, offline, matches the Sprint 017 tests). `--fetcher alphavantage` reads `ALPHAVANTAGE_API_KEY` from env, constructs the real fetcher, and runs the probe against live Alpha-Vantage over HTTP. Manual smoke: run against `configs/channels/v1.json` with the live fetcher; verify the JSONL trace, the manifest, and the exit code against real data.

`determinism_budget: statistically-deterministic` — same config → the same signal sequence and manifest structure; the exact numeric values (missing_fraction, timestamps) depend on live vendor data and change over time.

---

## prerequisites

- Sprint 019 closed (fetcher module + tests + httpx dep).
- `.env` at project root with a valid `ALPHAVANTAGE_API_KEY` (already on file).

---

## context_files

- `scripts/probe_channels.py` (current CLI shape from Sprint 017)
- `src/price_space_llm/ingestion/alphavantage.py` (fetcher factory)
- `src/price_space_llm/ingestion/probe.py` (Fetcher signature)
- `configs/channels/v1.json` (three-channel manifest)
- `.env.example` (env-var name)

---

## signal contract

### Emits

At CLI invocation with `--fetcher alphavantage`:
- SESSION_INIT (via `process_session`).
- CHANNEL_PROBED × 5 dates × 3 channels = 15.
- CHANNEL_REJECTED × 0..3 (depends on live data).
- CHANNEL_COVERAGE_ASSESSED × 3.
- SESSION_COMPLETE.

Same emit surface as Sprint 017; only the fetcher underneath changes.

### Consumes

- `configs/channels/v1.json`.
- `ALPHAVANTAGE_API_KEY` env var (only under `--fetcher alphavantage`).
- Alpha-Vantage HTTP API at `https://www.alphavantage.co/query`.

### Invariants

- All 48 existing tests continue to pass (no regressions in the mock-path CLI test).
- Under `--fetcher mock`, behavior is exactly as Sprint 017 (test suite proves it).
- Under `--fetcher alphavantage`, missing `ALPHAVANTAGE_API_KEY` env var exits with a clear error (return code 1).
- Under `--fetcher alphavantage`, Alpha-Vantage errors surface via emitted CHANNEL_REJECTED with a descriptive reason rather than an uncaught Python exception.

---

## artifact contract

### Files modified

- `scripts/probe_channels.py`:
  - Add `--fetcher {mock,alphavantage}` argument (default `mock`).
  - When `alphavantage`: read env var, build fetcher via `make_alphavantage_fetcher`, wrap in an error-mapping shim that catches `AlphaVantageError`, `NotImplementedError`, and `httpx.HTTPError` and returns a `missing_fraction=1.0` `FetchResult` with a special error marker in the timestamp fields — so the probe emits CHANNEL_REJECTED naturally instead of crashing.
  - Alternative shape: extend `probe_channel` in the module to accept an on-error callback. Sprint 020 uses the shim approach to avoid probe-module changes.

### Files created

None.

### Content assertions

- `scripts/probe_channels.py` accepts `--fetcher {mock,alphavantage}`.
- `scripts/probe_channels.py` reads `ALPHAVANTAGE_API_KEY` from `os.environ` only when `--fetcher alphavantage`.
- `scripts/probe_channels.py` returns exit 1 with `"ALPHAVANTAGE_API_KEY"` in stderr when the flag is `alphavantage` and the env var is unset.
- The subprocess test `tests/test_probe_cli.py` gains one test for the missing-env-var path.

### Command exit codes

- `uv run ruff check src tests scripts` exit 0.
- `uv run ruff format --check src tests scripts` exit 0.
- `uv run mypy src` exit 0.
- `uv run pytest tests/ -v` exit 0; test count ≥ 49.

### Live smoke run (Architect-verified)

```
export ALPHAVANTAGE_API_KEY=$(grep ALPHAVANTAGE_API_KEY .env | cut -d= -f2)
uv run python scripts/probe_channels.py configs/channels/v1.json --fetcher alphavantage
```

Expected: exit 0 or 2 (0 all-accepted, 2 any-dropped — depends on what Alpha-Vantage returns for SPY/VIX/USO at the five sample dates). Trace and manifest written to their usual paths.

---

## observation contract

Required (`pass_kind: functional`).

### Input fixtures

- `configs/channels/v1.json` (three channels).
- `.env` at project root with a valid key.

### CLI driving steps

```
export ALPHAVANTAGE_API_KEY=$(grep ALPHAVANTAGE_API_KEY .env | cut -d= -f2)
uv run python scripts/probe_channels.py configs/channels/v1.json --fetcher alphavantage
```

### Expected runtime signals

- Line 1: SESSION_INIT with `run_kind: probe`.
- Lines 2..N-1: 15 CHANNEL_PROBED with real Alpha-Vantage-sourced payloads (real `earliest_timestamp` values, real `missing_fraction` numbers, real `actual_frequency` = "15min").
- Between CHANNEL_PROBED bursts: 0..3 CHANNEL_REJECTED (Alpha-Vantage free-tier limits or genuine data gaps).
- Every channel closes with CHANNEL_COVERAGE_ASSESSED carrying the verdict.
- Last line: SESSION_COMPLETE with correct `n_signals_emitted`.

### Expected log substrings

- Stderr `probe: N accepted, M dropped; manifest=...; trace=...`.

### Expected exit codes

- 0 (all-accepted) or 2 (any-dropped). Live-data-dependent.

---

## done criteria

CLI supports the fetcher flag. Mock path unchanged. Alpha-Vantage path exits cleanly on missing-key. Live smoke run produces a real trace + manifest. 49+ tests pass.

---

## notes

**Free-tier ceiling.** Alpha-Vantage free tier is 25 req/day. Probe uses 3 channels × 5 sample dates = 15 calls. Fits inside the daily budget with margin.

**Error-mapping shim vs probe module change.** The probe module (Sprint 016) doesn't catch fetcher exceptions. Two ways to route errors into CHANNEL_REJECTED:
- **(a)** Extend probe with an on-error callback. Changes the module signature.
- **(b)** Wrap the fetcher in a shim that catches and returns a `missing_fraction=1.0` FetchResult with a marker (e.g., `revision_behavior="error:<msg>"`). Sprint 020 uses (b) to keep the probe module untouched. A later sprint (021+) can promote (a) if error semantics matter more.

**Statistically-deterministic budget.** Same config + same day → same signal count and same verdict per channel. Numeric fields (missing_fraction to two decimals, timestamps to the second) vary across days as Alpha-Vantage's data window rolls. The trace shape is deterministic; the exact values are not.

**Not implementing `--month` control this sprint.** The default sample dates are hardcoded in `DEFAULT_SAMPLE_DATES`. If a live run needs a different date set for testing, edit the module. Sprint N adds a `--sample-dates` flag.

---

## plan-mode review checklist

- [x] Scope one paragraph, one concept (wire fetcher + smoke).
- [x] One code file modified (probe_channels.py); tests extended.
- [x] Signal contract cites v0.2 tags.
- [x] Observation contract present (functional-band); includes live smoke command.
- [x] Determinism budget declared (statistically-deterministic; rationale in notes).

---

*Sprint 020. Real Alpha-Vantage data flows into the JSONL trace and the manifest.*
