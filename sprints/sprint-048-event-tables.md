# Sprint 048 -- event tables (EARNINGS_CALENDAR + curated FOMC + CPI-release + deterministic options expiry)

---

```yaml
---
id: 048
status: closed
phase: 2
pass_kind: functional
determinism_budget: bit-deterministic
---
```

---

## scope

Ships the fourth spec §Channels category: events. Product-spec-v4 line 63 names four items — earnings-calendar density for the target's constituents, FOMC dates, CPI release dates, options expiry. All four land here as event channels in the aligned parquet.

Tech-arch §Data (line 219) names `EARNINGS_CALENDAR` as the MCP tool for the Event category. AV's `EARNINGS_CALENDAR` is forward-only (returns the next-three-months schedule keyed on the request timestamp). Historical constituent earnings density requires per-symbol `EARNINGS` calls; each call returns every quarterly report back to that symbol's first listing with a `reportedDate` field. Iterate the S&P 500 constituent list (~500 calls at 150/min ≈ 3.5 minutes, cached forever). Aggregate `reportedDate` across constituents to produce one row per date with `close = count of SPX constituents reporting that day`.

FOMC and CPI release dates are hand-curated static tables. Federal Reserve historical calendars (federalreserve.gov/monetarypolicy/fomccalendars.htm) publish every scheduled FOMC meeting since 1994; BLS (bls.gov/schedule/news_release/cpi.htm) publishes the CPI release schedule. Both sources are authoritative and static.

Options expiry is deterministic: third Friday of every month, adjusted forward if that Friday is an NYSE holiday. Pure date arithmetic; no vendor call.

## halt-and-articulate

**EARNINGS_CALENDAR is not the historical endpoint.** The MCP tool's `horizon` parameter accepts `3month`, `6month`, `12month` and returns the *forthcoming* schedule from the request timestamp. It cannot backfill 2015-2022 earnings dates because the schedule is regenerated each day forward. This mismatches the spec's tool assignment on line 219 (`Event | EARNINGS_CALENDAR`). Two paths:

- Use `EARNINGS` per symbol. Returns full history of `reportedDate` for every quarterly filing since the symbol's IPO. ~500 calls to cover SPX; each response ~5KB; cached forever. This is the historical path.
- Live with `EARNINGS_CALENDAR` and start capture forward from today. This leaves the 2015-2022 training window with zero earnings-density signal, gutting the channel. Not acceptable.

Sprint 048 takes the `EARNINGS` per-symbol path. Manifest tool is `EARNINGS`; spec tech-arch will be amended in the same commit to reflect the corrected tool assignment. Product-spec channel intent (`earnings-calendar density for the target's constituents`) is unchanged.

**Survivorship bias in the constituent list.** SPX membership churns; ~20-30 names enter and exit per year. A 2026-08 snapshot misses the earnings dates of 2015-era constituents that have since been removed (Yahoo, Kraft, Sprint, Time Warner, etc.), and includes 2026-era additions that were not in SPX in 2015. The `EARNINGS` per-symbol path only covers currently-listed names — delisted tickers return empty responses. Under-counting on the 2015-2022 window is estimated at 4-8% of aggregate earnings-day mass (30 removed names × ~4 reports/year / ~2000 total reports/year). Documented as a v1 limitation; historical constituent-list vendors (S&P, CRSP) sit behind paid licenses.

## signal contract

### Emits

No new emit sites in `src/`. `CHANNEL_FETCH_FAILED` (Sprint 046 wiring) fires per constituent-symbol `EARNINGS` request failure with `exception_class=AlphaVantageResponseError` for delisted or unknown tickers.

Static tables (`event__FOMC`, `event__CPI_RELEASE`) and the deterministic table (`event__OPTIONS_EXPIRY`) issue zero AV calls and therefore zero `CHANNEL_FETCH_FAILED` emits.

### Invariants

- `load_earnings_density_bars(constituents, cache_dir)` walks per-symbol `EARNINGS` cache, extracts every `quarterlyEarnings[].reportedDate`, aggregates across constituents to a per-date scalar, returns one row per date with `close = count`.
- `load_static_event_bars(dates, symbol)` takes a list of date strings and a channel identifier, returns one row per date with `close = 1` and `known_at = midnight ET on the event date` (event dates are known before the trading day opens).
- `load_options_expiry_bars(start, end)` generates the third-Friday-of-each-month between `start` and `end` inclusive. If the third Friday is an NYSE holiday, roll forward to the next trading day. Returns one row per expiry.
- Event channel `close` carries a scalar; `open=high=low=close` per uniform-fill; `volume=0`.
- `known_at` for FOMC = release-day midnight ET (schedule is public months ahead; a bar on the FOMC date at 09:30 ET knows the meeting happens today).
- `known_at` for CPI release = release-day midnight ET (same reasoning: the release schedule is public months in advance, but the *value* of CPI is not known until 08:30 ET on the release day — that value is handled by the `macro__CPI` channel, not the event flag).
- `known_at` for options expiry = expiry-day midnight ET.
- `known_at` for earnings density = report-date midnight ET (schedule is public within days of release).

## artifact contract

### Files

- `src/price_space_llm/ingestion/alphavantage.py` — new `alphavantage_earnings_extract_metadata` extractor. Parses `EARNINGS` response; iterates `quarterlyEarnings[].reportedDate`; returns a DataFrame with `timestamp = reportedDate + midnight ET`, `symbol`, `close = 1` (per-report), `volume = 0`.
- `src/price_space_llm/alignment/join.py` — four new loaders (`load_earnings_density_bars`, `load_fomc_bars`, `load_cpi_release_bars`, `load_options_expiry_bars`) and dispatch branches in `run_alignment` for the four new tool identifiers (`EARNINGS`, `STATIC_FOMC`, `STATIC_CPI_RELEASE`, `DETERMINISTIC_OPTIONS_EXPIRY`).
- `src/price_space_llm/alignment/__init__.py` — export the four new loaders.
- `scripts/ingest.py` — new dispatch category for `EARNINGS`. Loads the constituent list from `data/manifests/spx_constituents.json`, iterates one call per symbol.
- `data/manifests/spx_constituents.json` — new file, top-500 SPX constituent tickers as of 2026-08-14, sourced from Wikipedia's "List of S&P 500 companies" article.
- `data/manifests/channel_coverage.json` — four new entries: `event__EARNINGS_DENSITY_SPX`, `event__FOMC`, `event__CPI_RELEASE`, `event__OPTIONS_EXPIRY`.
- `data/static/fomc_dates.json` — new file, hand-curated FOMC meeting dates 2015-01 through 2025-06 from federalreserve.gov historical calendars.
- `data/static/cpi_release_dates.json` — new file, hand-curated CPI release dates 2015-01 through 2025-06 from BLS release schedules.
- `tests/test_alignment.py` — new tests: earnings density aggregation counts correctly; FOMC known-date check (2023-03-22 = the 75bp hike day); CPI known-date check (2023-05-10 = April CPI release); options expiry deterministic (2023-01-20 = January 2023 third Friday); options expiry rolls forward when third Friday is a holiday.
- `specs/technical-architecture-v4.md` — amend line 219 tool assignment to note `EARNINGS_CALENDAR` is forward-only and the historical path is per-symbol `EARNINGS`.

### Command exit codes

- Per-symbol `EARNINGS` pull for 500 SPX constituents: expected ~500 ok, small number failed (delisted/renamed tickers).
- Re-align × 2 windows: expected training 54,262 × 160 columns (19 channels × 8 fields + grid_ts + 3 staleness × 15 channels), test 10,166 × 160.
- Features × 2 + tokenize: exit 0.
- ruff, ruff format, mypy, pytest: green.
- Test count 304 → 308+ (new alignment tests).

### Live smoke

Training-window read-back:
- `event__EARNINGS_DENSITY_SPX__close`: expect ~2,004 rows with non-zero counts (one per trading day where any constituent reported). Peak weeks (late Jan, late Apr, late Jul, late Oct — earnings season) show counts of 30-80; off-weeks show 0-5.
- `event__FOMC__close`: expect ~80 non-zero rows across 8 years (8 scheduled meetings per year × 10 years, filtered to training window).
- `event__CPI_RELEASE__close`: expect ~96 non-zero rows (12/year × 8 years).
- `event__OPTIONS_EXPIRY__close`: expect ~96 non-zero rows.

Spot checks:
- 2023-03-22 = FOMC (Powell's 25bp hike after SVB): event__FOMC__close = 1.
- 2023-05-10 = April CPI release: event__CPI_RELEASE__close = 1.
- 2023-01-20 = January 2023 options expiry: event__OPTIONS_EXPIRY__close = 1.
- 2023-01-25 (a typical peak earnings-season Wednesday): event__EARNINGS_DENSITY_SPX__close in 40-80 range.

---

## observation contract

Required (`pass_kind: functional`). Live-trace read-back at aggregate (fresh-event counts match calendar-derived expectations) and per-date (four known-date spot checks). Unit tests lock the invariants at synthetic-data resolution: per-date aggregation, static-table date presence, options-expiry deterministic generation, holiday-rollforward for options expiry.

---

## honest audit

**What lands.** All four spec §Channels event items with real historical values across both windows. Event channel schema (uniform OHLCV with count-or-boolean in `close`) mirrors the daily channel schema Sprint 042 established. Static tables checked into the repo; no vendor dependency for FOMC/CPI/expiry after ingest closes.

**What does not land.** No countdown-to-next or minutes-to-release features — those are Phase B feature-layer work (Sprint 052 in the roadmap). Sprint 048 delivers the raw event flags in the aligned parquet; the feature layer will read them.

**What surfaces.** Spec tech-arch line 219 assigned `EARNINGS_CALENDAR` for events, which turns out to be forward-only. Historical path is per-symbol `EARNINGS`. Spec amended to note this. Survivorship bias in the SPX constituent list is real and named — no free fix without a paid historical-constituents feed.

---

## notes

**Why 500 constituents instead of top-100.** The user's no-scope-reduction rule. The API cost is 500 one-time cached calls (~3.5 minutes at 150/min). Top-100 would cover ~65% of SPX market-cap weight but only ~20-30% of earnings-report *count* (constituents 100-500 are the mid-cap names that pack the peak-week schedules). Density is a count aggregate, not a market-cap-weighted average — under-counting the mid-caps would flatten the peak-week signal.

**Uniform OHLCV for event channels.** Same reasoning as VOL_SPY in Sprint 047. Trainer already handles daily/sparse channels via the staleness triple; no new schema.

**FOMC vs CPI known_at.** Both are "release schedule public months ahead, value not known until release-day 14:00 ET / 08:30 ET". The `event__` channel encodes "does an event happen today", which the pipeline may consume from midnight ET the day of. The `macro__` channel (CPI's actual value, released 08:30 ET with vendor lag) is a separate concern that Sprint 045 already handles with per-tool `known_at_lag_days` / `known_at_hour_utc`.

**Options-expiry holiday rollforward.** Third-Friday of the month is the standard monthly-expiry rule. When that Friday is a market holiday (rare — the third Friday almost never lands on Christmas, Good Friday, or Independence Day), the expiry rolls to Thursday per CBOE convention. Implementation uses a small hard-coded holiday set covering the 2015-2025 window; the same holiday list already lives in the ingest layer for weekday iteration.

---

## plan-mode review checklist

- [x] Files under hard rule 6 (three code + one test + several config/static/manifest).
- [x] No new emit sites; existing CHANNEL_FETCH_FAILED wires through cleanly.
- [x] Observation contract (functional-band): four fresh-event spot-checks against calendar-known dates.
- [x] Determinism budget bit-deterministic (same cache + manifest = byte-identical parquet).
- [x] Ships spec §Channels event category — all four items — no scope reduction.
- [x] Spec tech-arch amended to note `EARNINGS_CALENDAR` forward-only limitation.

---

## close (2026-08-14)

Landed. All four event items in the aligned parquet across both windows. Training 54,262 × 172 columns (19 channels × 9 fields + grid_ts); test 10,166 × 172. Live pull 550 ok, 7 failed (497 EARNINGS + 3 dotted/renamed ticker failures + 4 pre-existing holiday nulls on options). Read-back: 71 FOMC events (2015-2022, 8 scheduled + 7 emergency 2020), 97 CPI-release events, 97 options-expiry events, 1,515 earnings-density event dates with peak 71 constituents 2016-07-28. Good-Friday rollback verified — 2022-04-14 carries fresh options expiry across 26 RTH bars, 2022-04-15 carries zero. 2020-03-16 first bar picks Sunday 2020-03-15 emergency-cut FOMC (backward-fill honest). Test count 304 → 315 (+11 alignment tests). Four tools green. Spec tech-arch amended for EARNINGS_CALENDAR forward-only limitation. Phase A complete; Sprint 049 opens Phase B feature layer.
