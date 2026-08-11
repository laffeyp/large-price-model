# Sprint 016 — Phase 0 probe module (mock-source; MCP wiring deferred)

---

```yaml
---
id: 016
status: closed
phase: 1
pass_kind: functional
determinism_budget: bit-deterministic
---
```

---

## scope

Author `src/price_space_llm/ingestion/probe.py` — the Phase 0 channel-coverage probe primitive per `technical-architecture-v4.md §4.1`. Two public functions:

- `probe_channel(channel_spec, sample_dates, fetcher, emitter) -> ChannelCoverage` — probes one (channel, symbol) at five sample dates using an injected `fetcher` callable; emits `CHANNEL_PROBED` per date, `CHANNEL_REJECTED` when the verdict is `dropped`, and `CHANNEL_COVERAGE_ASSESSED` at the end with the summary. Returns the coverage record.
- `run_phase_zero_probe(channels, sample_dates, fetcher, emitter, output_path) -> list[ChannelCoverage]` — loops `probe_channel` over every entry in a channel manifest, writes the aggregated result to `output_path` (typically `data/manifests/channel_coverage.json`), returns the coverage list.

Fetcher signature: `Callable[[str, str, date], FetchResult]` — takes `(channel, symbol, sample_date)`, returns a dict with `actual_frequency`, `earliest_timestamp`, `latest_timestamp`, `missing_fraction`, `timezone`, `timestamp_semantics`, `revision_behavior`. Sprint 016 uses a mock fetcher only; Sprint 018 substitutes the Alpha-Vantage MCP client.

Verdict logic per tech-arch: `dropped` if `missing_fraction > 0.05` or `earliest_timestamp > 2015-06-15`; `accepted` otherwise. `renegotiate` reserved for future policy.

Also flesh out `WORKING_AGREEMENT.md § External SDK bridge mappings § Alpha-Vantage MCP` from stub to a real surface listing the v1 tools (`TIME_SERIES_INTRADAY`, `CPI`, `FEDERAL_FUNDS_RATE`, `TREASURY_YIELD`, `UNEMPLOYMENT`, `NONFARM_PAYROLL`, `HISTORICAL_PUT_CALL_RATIO`, `HISTORICAL_VOLUME_OPEN_INTEREST_RATIO`, `EARNINGS_CALENDAR`) with their argument shapes as best-effort documentation. Sprint 018 halts with `bridge_mapping_required` if the actual MCP surface diverges.

---

## prerequisites

- Sprint 015 closed.
- `signals/0.2.json` locked with `CHANNEL_PROBED`, `CHANNEL_COVERAGE_ASSESSED`, `CHANNEL_REJECTED`, `SESSION_INIT`, `SESSION_COMPLETE`.
- `process_session` context manager from Sprint 012.

---

## context_files

- `reviews/full-review-round-1.md` §3.1 (first operator sprint wires real emits)
- `specs/technical-architecture-v4.md §4.1` (Phase 0 probe requirements)
- `specs/product-spec-v4.md §Phase 0 data-availability probe`
- `signals/0.2.json` (CHANNEL_PROBED, CHANNEL_COVERAGE_ASSESSED, CHANNEL_REJECTED payload schemas — the emits must match)
- `src/price_space_llm/signals.py` (`get_emitter`, `process_session`, StrictSignalEmitter API)
- `WORKING_AGREEMENT.md § External SDK bridge mappings` (Alpha-Vantage MCP stub)

---

## signal contract

### Emits

At test-time. Sprint 016's tests exercise the probe with a mock fetcher.

- `SESSION_INIT` (via `process_session` in the tests)
- `SESSION_COMPLETE` (via `process_session`)
- `CHANNEL_PROBED` — one per (channel, symbol, sample_date) tuple; payload matches v0.2 schema (channel, symbol, source, sample_date, actual_frequency, earliest_timestamp, latest_timestamp, missing_fraction, timezone, timestamp_semantics, revision_behavior)
- `CHANNEL_COVERAGE_ASSESSED` — one per channel, always; payload carries the verdict enum value
- `CHANNEL_REJECTED` — one per channel when verdict == `dropped`; payload names the reason

### Consumes

- `signals/0.2.json` (via `get_emitter`).
- Nothing else; the fetcher is injected.

### Invariants

- All 29 existing tests pass unchanged.
- New tests fire only vocabulary-declared tags with strict-valid payloads.
- The probe writes `data/manifests/channel_coverage.json` (in a tmp_path during tests) as a JSON object mapping `channel__symbol` to its coverage record.
- No import of any external SDK (`mcp`, `httpx`, `requests`, etc.). Sprint 018 adds those.

---

## artifact contract

### Files created

- `src/price_space_llm/ingestion/__init__.py` (empty; makes `ingestion` a sub-package).
- `src/price_space_llm/ingestion/probe.py` — the module.
- `tests/test_probe.py` — tests.

### Files modified

- `WORKING_AGREEMENT.md § External SDK bridge mappings § Alpha-Vantage MCP` — flesh out from stub to real surface.

### Content assertions

- `src/price_space_llm/ingestion/probe.py` defines `probe_channel(channel_spec, sample_dates, fetcher, emitter) -> dict` (or a typed `ChannelCoverage` NamedTuple/dataclass).
- `src/price_space_llm/ingestion/probe.py` defines `run_phase_zero_probe(channels, sample_dates, fetcher, emitter, output_path) -> list`.
- `probe.py` emits at most three tag names: `CHANNEL_PROBED`, `CHANNEL_COVERAGE_ASSESSED`, `CHANNEL_REJECTED`. (SESSION_INIT/COMPLETE emit from `process_session` in the caller.)
- `tests/test_probe.py` contains at least: `test_probe_channel_emits_probed_per_date`, `test_probe_channel_accepts_clean_channel`, `test_probe_channel_rejects_high_missing_fraction`, `test_probe_channel_rejects_history_too_short`, `test_run_phase_zero_probe_writes_manifest_json`.
- `WORKING_AGREEMENT.md § External SDK bridge mappings § Alpha-Vantage MCP` lists at least nine v1 tools with their argument shapes.

### Command exit codes

- `uv run ruff check src tests` exit 0.
- `uv run ruff format --check src tests` exit 0.
- `uv run mypy src` exit 0.
- `uv run pytest tests/ -v` exit 0; test count ≥ 34 (29 + 5 new).
- `uv build` clean.

---

## observation contract

Required (`pass_kind: functional`).

### Input fixtures

- Two mock fetchers: one returns clean coverage for every date; one returns `missing_fraction = 0.2` for one date (triggers rejection).

### Expected runtime signals

For `test_probe_channel_accepts_clean_channel` (single channel, five sample dates, mock success): emitter buffer contains exactly 5 CHANNEL_PROBED + 1 CHANNEL_COVERAGE_ASSESSED. No CHANNEL_REJECTED.

For `test_probe_channel_rejects_high_missing_fraction` (mock reports missing_fraction 0.2): buffer contains 5 CHANNEL_PROBED + 1 CHANNEL_REJECTED (reason=`missing_fraction_high`) + 1 CHANNEL_COVERAGE_ASSESSED (verdict=`dropped`).

For `test_run_phase_zero_probe_writes_manifest_json` (three channels, mock mixed): manifest file exists, JSON parses, contains three entries keyed by `channel__symbol`.

### Expected exit codes

`pytest` exit 0. No CLI script this sprint (Sprint 017).

---

## done criteria

Probe module works. Five new tests pass. Manifest JSON writes correctly. Alpha-Vantage MCP bridge mapping doc is real. All tools green.

---

## notes

**Why deterministic budget `bit-deterministic`.** No PyTorch, no seeded RNG, no floats beyond payload values. The probe is a pure function of (channels, sample_dates, fetcher). Same inputs → same outputs → same emit trace → same manifest JSON byte-for-byte.

**Why inject the fetcher.** Testability is the load-bearing reason. A probe module that reaches into an MCP client is untestable without mocking the network. Injecting a `Callable[..., dict]` makes the tests fast, deterministic, and offline. Sprint 018's MCP client provides the real fetcher.

**No CLI this sprint.** Sprint 017 authors `scripts/probe_channels.py` that reads a channel manifest, wraps the probe in `process_session`, writes the JSONL trace to `logs/{run_id}/signals.jsonl`. Splitting keeps this sprint at one concept.

**No `mcp` dep.** Sprint 018 adds the pin. The dep-pin rule (WORKING_AGREEMENT § External SDK bridge mappings) says pin lands in the same commit as the first import.

**Bridge mapping — best-effort at this sprint.** Sprint 018 verifies the actual MCP tool signatures via `ToolSearch` and halts with `bridge_mapping_required` if any tool argument shape diverges from what this sprint documents. That's the halt the discipline exists to trigger.

**Sub-package placement.** `src/price_space_llm/ingestion/` matches tech-arch §3's module directories. Package-root `signals.py` is the observability exception (per Sprint 011 WORKING_AGREEMENT decision); pipeline modules go under sub-packages as the spec prescribes.

---

## plan-mode review checklist

- [x] Scope one paragraph, one concept.
- [x] Three files created + one modified. Two of the three new files are code (probe.py + test_probe.py); the third is an empty ceremony init. Within hard rule 6's code-file count.
- [x] Signal contract cites only v0.2 tags.
- [x] Artifact contract gradable.
- [x] Determinism budget declared (bit-deterministic).
- [x] Observation contract present (required per pass_kind: functional).

---

*Sprint 016. Probe primitive with mock source. Sprint 017 wires the CLI script + JSONL. Sprint 018 wires the MCP.*
