"""Polars join_asof alignment over a 15-min UTC RTH grid.

Tech-arch §4.3: for each grid moment, take the latest observation per
channel whose `known_at <= grid_ts`. `strategy="backward"` is the
alignment invariant — it enforces that features at time T can only see
data known at or before T. Look-ahead leakage is impossible by construction.

Simplifications:
- Sprint 043: real US/Eastern zone via `zoneinfo("America/New_York")` shared
  with `alphavantage.US_EASTERN_ZONE`. DST correct; a March bar reports UTC-4
  and a November bar reports UTC-5. Cache bars and grid bars flow through the
  same zone, so the join stays internally consistent AND the UTC labels match
  reality.
- Weekday-only calendar (Mon-Fri, no holidays). US market holidays
  (Juneteenth, July 4, etc.) still get grid bars; if the vendor returned
  no data on those days, `AS_OF_JOIN_MISS` fires for each grid bar.
  Refined when `pandas_market_calendars` lands.
"""

import json
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any

import polars as pl

from price_space_llm.ingestion import cache as _cache
from price_space_llm.ingestion.alphavantage import US_EASTERN_ZONE
from price_space_llm.signals import StrictSignalEmitter

# RTH in US/Eastern per tech-arch §5: 09:30 open → 16:00 close.
# 15-min bars close at 09:45, 10:00, ..., 16:00 = 26 bars per day.
RTH_OPEN_US_EASTERN_MINUTES = 9 * 60 + 30  # 09:30 EST
RTH_CLOSE_US_EASTERN_MINUTES = 16 * 60  # 16:00 EST
BAR_MINUTES = 15


@dataclass(slots=True, frozen=True, kw_only=True)
class AlignmentResult:
    run_id: str
    total_rows: int
    missing_fractions_per_channel: dict[str, float]
    elapsed_seconds: float
    output_path: str


def load_channel_bars(
    cache_dir: Path,
    source: str,
    tool: str,
    channel: str,
    symbol: str,
    params: dict[str, Any],
) -> pl.DataFrame:
    """Read a cached raw response and return a normalised bar DataFrame.

    Columns: `known_at: datetime[UTC]`, `open`, `high`, `low`, `close`,
    `volume` (float64/int64), `channel: str`, `symbol: str`. Sprint 042
    kept the full OHLCV row so downstream feature computation (bar_shape,
    range_pct, volume_z_100, dollar_volume, spread_proxy per spec §6)
    reads real quantities rather than close-only.

    Uses the SAME fixed EST offset as `alphavantage.py` so the alignment
    grid and the bar timestamps live on the same (biased) clock.
    """
    key = _cache.cache_key(tool, channel, symbol, params)
    path = _cache.cache_path(cache_dir, source, tool, key)
    payload = _cache.read(path)
    if payload is None:
        raise FileNotFoundError(f"cache miss for {channel}/{symbol}: {path}")

    series_key = next((k for k in payload if k.startswith("Time Series")), None)
    if series_key is None:
        raise ValueError(f"no 'Time Series ...' key in cached response for {channel}/{symbol}")
    series = payload[series_key]

    rows: list[dict[str, Any]] = []
    for ts_str, bar in series.items():
        naive = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        bar_time_utc = naive.replace(tzinfo=_us_eastern_zone()).astimezone(UTC)
        # known_at is bar_close + 1 minute per Sprint 024's convention.
        known_at = bar_time_utc + timedelta(minutes=1)
        rows.append(
            {
                "known_at": known_at,
                "open": float(bar.get("1. open", bar.get("open", "0"))),
                "high": float(bar.get("2. high", bar.get("high", "0"))),
                "low": float(bar.get("3. low", bar.get("low", "0"))),
                "close": float(bar.get("4. close", bar.get("close", "0"))),
                "volume": int(float(bar.get("5. volume", bar.get("volume", "0")))),
                "channel": channel,
                "symbol": symbol,
            }
        )

    return pl.DataFrame(rows).sort("known_at")


def load_index_daily_bars(
    cache_dir: Path,
    source: str,
    tool: str,
    channel: str,
    symbol: str,
    params: dict[str, Any],
) -> pl.DataFrame:
    """Read a cached INDEX_DATA daily response and return bars stamped `known_at`.

    Alpha-Vantage's `INDEX_DATA` returns `{"symbol", "name", "interval",
    "data": [{"date", "open", "high", "low", "close"}, ...]}` — one row per
    trading day. Sprint 038 uses this endpoint for VIX (no intraday VIX exists
    on the platform; the underlying is an index, not an equity).

    `known_at` per row = market close in US/Eastern at 16:00 + 1 minute, cast
    to UTC via the same fixed offset the RTH grid uses. Downstream
    `polars.join_asof(strategy="backward")` on `known_at` then forward-fills
    the daily close onto every 15-min grid bar that comes after it, which is
    the correct causality: at 09:45 on day D the model sees the prior day's
    close; at 21:00 UTC on day D it still sees the prior day's close because
    day D's close doesn't print until 21:01 UTC.
    """
    key = _cache.cache_key(tool, channel, symbol, params)
    path = _cache.cache_path(cache_dir, source, tool, key)
    payload = _cache.read(path)
    if payload is None:
        raise FileNotFoundError(f"cache miss for {channel}/{symbol}: {path}")

    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise ValueError(f"INDEX_DATA response for {channel}/{symbol} has no non-empty 'data' list")

    rows: list[dict[str, Any]] = []
    for row in data:
        date_str = row.get("date")
        if not date_str:
            continue
        naive_close = datetime.strptime(f"{date_str} 16:00:00", "%Y-%m-%d %H:%M:%S")
        close_utc = naive_close.replace(tzinfo=_us_eastern_zone()).astimezone(UTC)
        known_at = close_utc + timedelta(minutes=1)
        # INDEX_DATA carries OHLC per day; no volume field on the endpoint.
        rows.append(
            {
                "known_at": known_at,
                "open": float(row.get("open", "0")),
                "high": float(row.get("high", "0")),
                "low": float(row.get("low", "0")),
                "close": float(row.get("close", "0")),
                "volume": 0,
                "channel": channel,
                "symbol": symbol,
            }
        )

    return pl.DataFrame(rows).sort("known_at")


def load_macro_bars(
    cache_dir: Path,
    source: str,
    tool: str,
    channel: str,
    symbol: str,
    params: dict[str, Any],
    known_at_lag_days: int,
    known_at_hour_utc: int,
) -> pl.DataFrame:
    """Read a cached macro response (CPI, FEDFUNDS, DGS10, UNRATE, NFP) and
    return bars in the same `{known_at, open, high, low, close, volume, channel,
    symbol}` shape the intraday and index loaders use.

    Macro endpoints return `{"data": [{"date", "value"}, ...]}` where `date` is
    the reference-period start (`value_time`), NOT the release date. Spec §Data
    time semantics: `known_at = released_at`. This loader approximates
    `known_at = value_time + known_at_lag_days at known_at_hour_utc` per the
    per-channel manifest values. Approximation loses a few days on any given
    row but preserves ordinal ordering; the trainer sees "roughly-right when
    it became public" per spec's release-calendar intent.

    Macro rows carry a single `value`; the loader writes it into all four
    OHLC fields and sets `volume=0`, keeping the aligned parquet schema
    uniform across channels. Downstream feature computation reads `close`.
    """
    key = _cache.cache_key(tool, channel, symbol, params)
    path = _cache.cache_path(cache_dir, source, tool, key)
    payload = _cache.read(path)
    if payload is None:
        raise FileNotFoundError(f"cache miss for {channel}/{symbol}: {path}")

    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise ValueError(f"macro response for {channel}/{symbol} has no non-empty 'data' list")

    rows: list[dict[str, Any]] = []
    for row in data:
        date_str = row.get("date")
        value_str = row.get("value")
        if not date_str or value_str in (None, "", "."):
            continue
        try:
            value = float(value_str)
        except ValueError:
            continue
        naive_midnight = datetime.strptime(f"{date_str} 00:00:00", "%Y-%m-%d %H:%M:%S")
        value_time_utc = naive_midnight.replace(tzinfo=_us_eastern_zone()).astimezone(UTC)
        known_at = value_time_utc + timedelta(days=known_at_lag_days, hours=known_at_hour_utc)
        rows.append(
            {
                "known_at": known_at,
                "open": value,
                "high": value,
                "low": value,
                "close": value,
                "volume": 0,
                "channel": channel,
                "symbol": symbol,
            }
        )

    return pl.DataFrame(rows).sort("known_at")


def load_options_volume_bars(
    cache_dir: Path,
    source: str,
    symbol: str,
    channel: str,
    known_at_lag_days: int,
    known_at_hour_utc: int,
    av_symbol: str | None = None,
) -> pl.DataFrame:
    """Read all cached HISTORICAL_OPTIONS responses for `av_symbol` and return bars
    with `close = sum(volume across all contracts)` for each date.

    Sprint 047: ships the second options channel spec §Channels names. Each
    HISTORICAL_OPTIONS response covers one date and carries per-contract rows
    with `contractID, expiration, strike, type, volume, open_interest, ...`.
    The loader iterates the cache directory, filters by `av_symbol` (the AV
    underlying identifier), and sums the `volume` field across every contract
    on each date to produce one aggregate scalar per date. The returned
    DataFrame's `symbol` field carries the manifest-visible identifier so the
    aligned column becomes `{channel}__{symbol}__*` even when two channels
    share the same AV underlying (PCR_SPY + VOL_SPY both target SPY).

    `known_at = value_time + known_at_lag_days at known_at_hour_utc`. OHLC
    filled with the same aggregate; volume field set to 0 to match the schema
    used for macro and put/call-ratio channels.
    """
    if av_symbol is None:
        av_symbol = symbol
    tool_dir = cache_dir / source / "HISTORICAL_OPTIONS"
    if not tool_dir.exists():
        raise FileNotFoundError(f"no HISTORICAL_OPTIONS cache directory at {tool_dir}")

    rows: list[dict[str, Any]] = []
    for cache_file in tool_dir.glob("*.json"):
        if cache_file.name.endswith(".meta.json"):
            continue
        payload = _cache.read(cache_file)
        if payload is None:
            continue
        data = payload.get("data") or []
        if not data:
            continue
        # HISTORICAL_OPTIONS response does not carry a top-level `symbol` field;
        # per-contract `symbol` field on each row identifies the underlying.
        if data[0].get("symbol") != av_symbol:
            continue
        date_str = data[0].get("date")
        if not date_str:
            continue
        total_volume = 0
        for row in data:
            v = row.get("volume")
            if v is None:
                continue
            try:
                total_volume += int(v)
            except (TypeError, ValueError):
                continue
        naive_midnight = datetime.strptime(f"{date_str} 00:00:00", "%Y-%m-%d %H:%M:%S")
        value_time_utc = naive_midnight.replace(tzinfo=_us_eastern_zone()).astimezone(UTC)
        known_at = value_time_utc + timedelta(days=known_at_lag_days, hours=known_at_hour_utc)
        v_float = float(total_volume)
        rows.append(
            {
                "known_at": known_at,
                "open": v_float,
                "high": v_float,
                "low": v_float,
                "close": v_float,
                "volume": 0,
                "channel": channel,
                "symbol": symbol,
            }
        )
    if not rows:
        raise ValueError(
            f"no HISTORICAL_OPTIONS cache rows matched av_symbol={av_symbol!r} in {tool_dir}"
        )
    return pl.DataFrame(rows).sort("known_at").unique(subset="known_at")


def load_put_call_ratio_bars(
    cache_dir: Path,
    source: str,
    symbol: str,
    channel: str,
    known_at_lag_days: int,
    known_at_hour_utc: int,
    av_symbol: str | None = None,
) -> pl.DataFrame:
    """Read all cached HISTORICAL_PUT_CALL_RATIO responses for `av_symbol` and
    return bars in the standard `{known_at, open, high, low, close, volume,
    channel, symbol}` shape.

    Sprint 046: unlike macros and index-data, this endpoint returns ONE date per
    call and each date lands in a distinct cache file. The loader walks the
    HISTORICAL_PUT_CALL_RATIO cache directory, filters to responses matching
    `av_symbol`, and constructs a per-date time series.

    Sprint 047: added `av_symbol` split so the manifest can distinguish
    aligned-column identity (`symbol`, e.g. PCR_SPY) from the AV underlying
    (`av_symbol`, e.g. SPY). Defaults to symbol when unset.

    `known_at = value_time + known_at_lag_days at known_at_hour_utc`.
    Value used = `put_call_ratio_full_chain`; the per-expiration breakdown is
    ignored for v1. OHLC filled with the same value; volume = 0.
    """
    if av_symbol is None:
        av_symbol = symbol
    tool_dir = cache_dir / source / "HISTORICAL_PUT_CALL_RATIO"
    if not tool_dir.exists():
        raise FileNotFoundError(f"no HISTORICAL_PUT_CALL_RATIO cache directory at {tool_dir}")

    rows: list[dict[str, Any]] = []
    for cache_file in tool_dir.glob("*.json"):
        if cache_file.name.endswith(".meta.json"):
            continue
        payload = _cache.read(cache_file)
        if payload is None:
            continue
        if payload.get("symbol") != av_symbol:
            continue
        date_str = payload.get("date")
        value = payload.get("put_call_ratio_full_chain")
        if not date_str or date_str == "latest" or value is None:
            continue
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        naive_midnight = datetime.strptime(f"{date_str} 00:00:00", "%Y-%m-%d %H:%M:%S")
        value_time_utc = naive_midnight.replace(tzinfo=_us_eastern_zone()).astimezone(UTC)
        known_at = value_time_utc + timedelta(days=known_at_lag_days, hours=known_at_hour_utc)
        rows.append(
            {
                "known_at": known_at,
                "open": v,
                "high": v,
                "low": v,
                "close": v,
                "volume": 0,
                "channel": channel,
                "symbol": symbol,
            }
        )
    if not rows:
        raise ValueError(
            f"no HISTORICAL_PUT_CALL_RATIO cache rows matched av_symbol={av_symbol!r} in {tool_dir}"
        )
    return pl.DataFrame(rows).sort("known_at").unique(subset="known_at")


_MACRO_TOOLS = {
    "CPI",
    "FEDERAL_FUNDS_RATE",
    "TREASURY_YIELD",
    "UNEMPLOYMENT",
    "NONFARM_PAYROLL",
}


# Sprint 048: monthly options expiration rolls back to Thursday when the third
# Friday of the month is a US market holiday. Only one such collision in the
# 2015-2025 window: 2022-04-15 was Good Friday (market closed), so April 2022
# monthly SPY options expired 2022-04-14. Well-documented CBOE convention. If
# the window extends, add entries here (next likely: 2026-06-19 Juneteenth on
# the third Friday of June 2026).
_OPTIONS_EXPIRY_HOLIDAY_ROLLBACK = {
    "2022-04-15": "2022-04-14",
}


def _third_friday_of_month(year: int, month: int) -> date:
    """Return the third Friday of the given month. Deterministic date arithmetic."""
    first = date(year, month, 1)
    # weekday() Monday=0..Friday=4. Offset to the first Friday.
    offset = (4 - first.weekday()) % 7
    first_friday = first + timedelta(days=offset)
    return first_friday + timedelta(days=14)


def load_earnings_density_bars(
    cache_dir: Path,
    source: str,
    channel: str,
    symbol: str,
) -> pl.DataFrame:
    """Read every cached per-symbol EARNINGS response and return a per-date
    scalar `close = count of constituents reporting on that date`.

    Sprint 048: `EARNINGS_CALENDAR` is forward-only, so historical earnings
    density comes from per-symbol `EARNINGS` calls. The loader walks the
    EARNINGS cache directory, extracts every `quarterlyEarnings[].reportedDate`
    from every cached response, and counts occurrences per date. Returns one
    row per date with `close = count`; OHLC uniform-filled; volume = 0.

    `known_at = reportedDate + midnight ET` — release-schedule is public
    within days of the report, so a bar closing 09:45 ET on the reportedDate
    may legally consume the flag.

    The DataFrame's `channel` and `symbol` fields carry the manifest-visible
    identifiers passed in (e.g. `event`/`EARNINGS_DENSITY_SPX`), not any AV
    per-symbol ticker.
    """
    tool_dir = cache_dir / source / "EARNINGS"
    if not tool_dir.exists():
        raise FileNotFoundError(f"no EARNINGS cache directory at {tool_dir}")

    counts: dict[str, int] = {}
    for cache_file in tool_dir.glob("*.json"):
        if cache_file.name.endswith(".meta.json"):
            continue
        payload = _cache.read(cache_file)
        if payload is None:
            continue
        quarterly = payload.get("quarterlyEarnings") or []
        for row in quarterly:
            reported = row.get("reportedDate")
            if not reported:
                continue
            counts[reported] = counts.get(reported, 0) + 1

    if not counts:
        raise ValueError(f"no EARNINGS cache rows carried a reportedDate in {tool_dir}")

    rows: list[dict[str, Any]] = []
    for date_str, count in counts.items():
        naive_midnight = datetime.strptime(f"{date_str} 00:00:00", "%Y-%m-%d %H:%M:%S")
        value_time_utc = naive_midnight.replace(tzinfo=_us_eastern_zone()).astimezone(UTC)
        c_float = float(count)
        rows.append(
            {
                "known_at": value_time_utc,
                "open": c_float,
                "high": c_float,
                "low": c_float,
                "close": c_float,
                "volume": 0,
                "channel": channel,
                "symbol": symbol,
            }
        )
    return pl.DataFrame(rows).sort("known_at").unique(subset="known_at")


def _load_static_date_list(path: Path) -> list[str]:
    """Load a JSON file with a top-level `dates` list of YYYY-MM-DD strings."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    dates = doc.get("dates")
    if not isinstance(dates, list) or not dates:
        raise ValueError(f"{path} has no non-empty 'dates' list")
    return sorted({str(d) for d in dates})


def load_fomc_bars(
    static_path: Path,
    channel: str,
    symbol: str,
) -> pl.DataFrame:
    """Read the curated FOMC-dates static table and return one row per meeting
    date with `close = 1`.

    Sprint 048: FOMC schedule is public months ahead, so `known_at` = the
    meeting-date midnight ET. A bar closing 09:45 ET on an FOMC day sees the
    flag; the 14:00 ET decision itself is a separate signal carried by the
    macro__FEDFUNDS channel's `observed_at_this_grid_step` staleness column.
    """
    dates = _load_static_date_list(static_path)
    rows: list[dict[str, Any]] = []
    for date_str in dates:
        naive_midnight = datetime.strptime(f"{date_str} 00:00:00", "%Y-%m-%d %H:%M:%S")
        known_at = naive_midnight.replace(tzinfo=_us_eastern_zone()).astimezone(UTC)
        rows.append(
            {
                "known_at": known_at,
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 0,
                "channel": channel,
                "symbol": symbol,
            }
        )
    return pl.DataFrame(rows).sort("known_at")


def load_cpi_release_bars(
    cache_dir: Path,
    source: str,
    channel: str,
    symbol: str,
    known_at_lag_days: int,
    known_at_hour_utc: int,
) -> pl.DataFrame:
    """Derive CPI-release event dates from the cached `macro__CPI` response.

    Sprint 048: BLS's release calendar is not carried on any Alpha-Vantage
    endpoint, and no free public source proved fetchable during Sprint 048.
    v1 approximation: use the same known_at rule Sprint 045 installed for
    `macro__CPI` (reference_month_first + known_at_lag_days at
    known_at_hour_utc). This is a within-week approximation of BLS's actual
    release timing — the actual release lands 10-15 calendar days into the
    month following the reference month, whereas this rule stamps ~45 days
    after reference-month-first. The event *ordering* is preserved (one
    event per released CPI observation) and the density (12/year) is
    correct.

    Real BLS release dates require a paid feed (or manual curation from
    bls.gov archives, which return 403 to unauthenticated fetchers). v1
    accepts the approximation and names it.

    `close = 1` on each release. OHLC uniform-filled; volume = 0.
    """
    params = _default_macro_params("CPI")
    key = _cache.cache_key("CPI", "macro", "CPI", params)
    path = _cache.cache_path(cache_dir, source, "CPI", key)
    payload = _cache.read(path)
    if payload is None:
        raise FileNotFoundError(
            f"cache miss for macro__CPI (required by event__CPI_RELEASE): {path}"
        )

    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise ValueError(f"CPI response has no non-empty 'data' list: {path}")

    rows: list[dict[str, Any]] = []
    for row in data:
        date_str = row.get("date")
        value_str = row.get("value")
        if not date_str or value_str in (None, "", "."):
            continue
        naive_midnight = datetime.strptime(f"{date_str} 00:00:00", "%Y-%m-%d %H:%M:%S")
        value_time_utc = naive_midnight.replace(tzinfo=_us_eastern_zone()).astimezone(UTC)
        known_at = value_time_utc + timedelta(days=known_at_lag_days, hours=known_at_hour_utc)
        rows.append(
            {
                "known_at": known_at,
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 0,
                "channel": channel,
                "symbol": symbol,
            }
        )
    if not rows:
        raise ValueError(f"no CPI rows carried a usable date in {path}")
    return pl.DataFrame(rows).sort("known_at").unique(subset="known_at")


def load_options_expiry_bars(
    start: date,
    end: date,
    channel: str,
    symbol: str,
) -> pl.DataFrame:
    """Generate deterministic monthly SPY options expiry dates over [start, end].

    Sprint 048: monthly SPY options expire on the third Friday of every month,
    with one CBOE-convention holiday rollback (2022-04-15 Good Friday →
    2022-04-14 Thursday) covered by `_OPTIONS_EXPIRY_HOLIDAY_ROLLBACK`.

    `known_at` = expiry-date midnight ET. `close = 1` per expiry; OHLC
    uniform-filled; volume = 0.

    No AV call. No cache. Pure date arithmetic + one lookup.
    """
    rows: list[dict[str, Any]] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        exp = _third_friday_of_month(year, month)
        rollback = _OPTIONS_EXPIRY_HOLIDAY_ROLLBACK.get(exp.isoformat())
        if rollback is not None:
            exp = date.fromisoformat(rollback)
        if start <= exp <= end:
            naive_midnight = datetime.strptime(f"{exp.isoformat()} 00:00:00", "%Y-%m-%d %H:%M:%S")
            known_at = naive_midnight.replace(tzinfo=_us_eastern_zone()).astimezone(UTC)
            rows.append(
                {
                    "known_at": known_at,
                    "open": 1.0,
                    "high": 1.0,
                    "low": 1.0,
                    "close": 1.0,
                    "volume": 0,
                    "channel": channel,
                    "symbol": symbol,
                }
            )
        month += 1
        if month == 13:
            month = 1
            year += 1
    if not rows:
        raise ValueError(f"no options expiries in [{start.isoformat()}, {end.isoformat()}]")
    return pl.DataFrame(rows).sort("known_at")


def _default_macro_params(tool: str) -> dict[str, Any]:
    """Default per-tool params matching the AV endpoint defaults + spec §Channels
    choices (daily for FEDFUNDS/TREASURY_YIELD; 10year maturity for TREASURY_YIELD).
    """
    if tool == "CPI":
        return {"interval": "monthly", "datatype": "json"}
    if tool == "FEDERAL_FUNDS_RATE":
        return {"interval": "daily", "datatype": "json"}
    if tool == "TREASURY_YIELD":
        return {"interval": "daily", "maturity": "10year", "datatype": "json"}
    if tool in ("UNEMPLOYMENT", "NONFARM_PAYROLL"):
        return {"datatype": "json"}
    raise ValueError(f"no default params for tool {tool!r}")


def _us_eastern_zone() -> tzinfo:
    """Return a real US/Eastern zone with DST via stdlib zoneinfo. Sprint 043."""
    return US_EASTERN_ZONE


def build_rth_grid(start: date, end: date) -> pl.DataFrame:
    """Build a 15-min UTC RTH grid over [start, end] weekdays.

    Returns a single-column DataFrame `grid_ts: datetime[UTC]`. The RTH
    window in US/Eastern is 09:30 → 16:00, so bars close at 09:45, 10:00,
    ..., 16:00 (26 bars per weekday).
    """
    all_days = []
    day = start
    while day <= end:
        if day.weekday() < 5:  # Mon-Fri
            for minutes in range(
                RTH_OPEN_US_EASTERN_MINUTES + BAR_MINUTES,
                RTH_CLOSE_US_EASTERN_MINUTES + 1,
                BAR_MINUTES,
            ):
                hh, mm = divmod(minutes, 60)
                naive = datetime(day.year, day.month, day.day, hh, mm, 0)
                utc = naive.replace(tzinfo=_us_eastern_zone()).astimezone(UTC)
                all_days.append(utc)
        day += timedelta(days=1)
    return pl.DataFrame({"grid_ts": all_days})


_OHLCV_FIELDS = ("open", "high", "low", "close", "volume")


def align_channels(
    grid: pl.DataFrame,
    channel_bars: dict[str, pl.DataFrame],
    emitter: StrictSignalEmitter,
) -> pl.DataFrame:
    """Join each channel into the grid via `join_asof(strategy=backward)`.

    Returns a wide DataFrame with, per channel `{key}`:
    - `{key}__open`, `{key}__high`, `{key}__low`, `{key}__close`, `{key}__volume`
    - `{key}__known_at`
    - `missing_mask__{key}` (bool: true iff the as-of join found no eligible row)
    - `age_since_known_at__{key}` (int32: number of 15-min bars since the last
      observation was known; 0 on a fresh observation; 0 while the mask is true)
    - `observed_at_this_grid_step__{key}` (bool: true iff the picked bar's
      known_at differs from the previous grid step's picked known_at)

    Emits one `ALIGNMENT_ROW_EMITTED` per grid row with `missing_channels_count`
    (the count of channels whose `close` is null for that row). Emits one
    `AS_OF_JOIN_MISS` per (channel, grid_ts) with a null `close`, reason
    `no_history_yet`.
    """
    aligned = grid
    channel_col_map: dict[str, tuple[str, str, str]] = {}

    for key, bars in channel_bars.items():
        # `key` is "channel__symbol" per the manifest convention.
        channel_name, symbol_name = key.split("__", 1)
        known_col = f"{key}__known_at"
        rename_map: dict[str, str] = {"known_at": known_col}
        for f in _OHLCV_FIELDS:
            if f in bars.columns:
                rename_map[f] = f"{key}__{f}"
        renamed = bars.rename(rename_map).select(list(rename_map.values()))
        aligned = aligned.join_asof(
            renamed,
            left_on="grid_ts",
            right_on=known_col,
            strategy="backward",
        )
        channel_col_map[key] = (f"{key}__close", channel_name, symbol_name)

    # Sprint 042: staleness columns per channel — missing_mask,
    # observed_at_this_grid_step, age_since_known_at (spec §5).
    for key in channel_bars:
        close_col = f"{key}__close"
        known_col = f"{key}__known_at"

        close_null = aligned[close_col].is_null().to_list()
        known_at = aligned[known_col].to_list()

        missing_mask: list[bool] = [bool(v) for v in close_null]
        observed: list[bool] = []
        age: list[int] = []

        prev_known: Any = None
        age_counter = 0
        for ka, is_missing in zip(known_at, close_null, strict=True):
            if is_missing:
                observed.append(False)
                age.append(0)
                prev_known = None
                age_counter = 0
                continue
            is_fresh = ka != prev_known
            observed.append(bool(is_fresh))
            if is_fresh:
                age_counter = 0
            age.append(age_counter)
            age_counter += 1
            prev_known = ka

        aligned = aligned.with_columns(
            pl.Series(f"missing_mask__{key}", missing_mask, dtype=pl.Boolean),
            pl.Series(f"observed_at_this_grid_step__{key}", observed, dtype=pl.Boolean),
            pl.Series(f"age_since_known_at__{key}", age, dtype=pl.Int32),
        )

    # Emit per-row and per-miss signals.
    close_cols = [close_col for (close_col, _, _) in channel_col_map.values()]
    missing_counts = (
        aligned.select(
            pl.sum_horizontal([pl.col(c).is_null().cast(pl.Int64) for c in close_cols]).alias(
                "missing"
            )
        )
        .to_series()
        .to_list()
    )
    grid_ts_values = aligned["grid_ts"].to_list()

    for ts, missing in zip(grid_ts_values, missing_counts, strict=True):
        emitter.emit(
            "ALIGNMENT_ROW_EMITTED",
            timestamp=ts.isoformat(),
            missing_channels_count=int(missing),
        )

    for _key, (close_col, channel_name, symbol_name) in channel_col_map.items():
        miss_mask = aligned[close_col].is_null().to_list()
        for ts, is_miss in zip(grid_ts_values, miss_mask, strict=True):
            if is_miss:
                emitter.emit(
                    "AS_OF_JOIN_MISS",
                    timestamp=ts.isoformat(),
                    channel=channel_name,
                    symbol=symbol_name,
                    reason="no_history_yet",
                )

    return aligned


def enumerate_months(start_month: str, end_month: str) -> list[str]:
    """Return `["YYYY-MM", ...]` inclusive from start_month to end_month.

    Sprint 037: multi-month alignment enumerates months in the range and
    concatenates cached bars per channel before the single as-of join.
    Raises ValueError on malformed input or start > end.
    """
    try:
        sy, sm = (int(x) for x in start_month.split("-"))
        ey, em = (int(x) for x in end_month.split("-"))
    except ValueError as ex:
        raise ValueError(f"month must be YYYY-MM; got {start_month!r} / {end_month!r}") from ex
    if not (1 <= sm <= 12 and 1 <= em <= 12):
        raise ValueError(f"month index out of range: {start_month!r} / {end_month!r}")
    if (sy, sm) > (ey, em):
        raise ValueError(f"start_month {start_month} > end_month {end_month}")

    out: list[str] = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            m = 1
            y += 1
    return out


def _month_first_day(month: str) -> date:
    year, mo = month.split("-")
    return date(int(year), int(mo), 1)


def _month_last_day(month: str) -> date:
    year, mo = (int(x) for x in month.split("-"))
    if mo == 12:
        return date(year + 1, 1, 1) - timedelta(days=1)
    return date(year, mo + 1, 1) - timedelta(days=1)


def run_alignment(
    manifest_path: Path,
    cache_dir: Path,
    months: list[str],
    output_path: Path,
    emitter: StrictSignalEmitter,
    run_id: str,
) -> AlignmentResult:
    """End-to-end alignment over `months` (inclusive list). Reads manifest → loads bars
    across all months per channel → concatenates → aligns to one grid → writes parquet.

    Single-month callers pass `months=["YYYY-MM"]`. Multi-month callers pass the enumerated
    list from `enumerate_months(start_month, end_month)`. The RTH grid spans first day of
    the earliest month to last day of the latest.
    """
    if not months:
        raise ValueError("months must not be empty")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    accepted = [c for c in manifest["channels"].values() if c.get("verdict") == "accepted"]
    if not accepted:
        raise ValueError(f"no accepted channels in {manifest_path}")

    start = _month_first_day(months[0])
    end = _month_last_day(months[-1])

    channels_names = sorted({c["channel"] for c in accepted})
    target = next((c["symbol"] for c in accepted if c["channel"] == "target"), None)
    if target is None:
        raise ValueError(f"manifest has no accepted target channel: {manifest_path}")

    emitter.emit(
        "ALIGNMENT_RUN_STARTED",
        run_id=run_id,
        date_range_start=start.isoformat(),
        date_range_end=end.isoformat(),
        channels=channels_names,
        target_symbol=target,
    )

    t0 = time.monotonic()

    channel_bars: dict[str, pl.DataFrame] = {}
    for c in accepted:
        tool = c.get("tool", "TIME_SERIES_INTRADAY")
        if tool == "INDEX_DATA":
            params = {"symbol": c["symbol"], "interval": "daily", "datatype": "json"}
            combined = load_index_daily_bars(
                cache_dir=cache_dir,
                source=c["source"],
                tool=tool,
                channel=c["channel"],
                symbol=c["symbol"],
                params=params,
            )
        elif tool == "TIME_SERIES_INTRADAY":
            per_month: list[pl.DataFrame] = []
            for month in months:
                params = {
                    "symbol": c["symbol"],
                    "interval": "15min",
                    "month": month,
                    "outputsize": "full",
                    "datatype": "json",
                }
                bars = load_channel_bars(
                    cache_dir=cache_dir,
                    source=c["source"],
                    tool=tool,
                    channel=c["channel"],
                    symbol=c["symbol"],
                    params=params,
                )
                per_month.append(bars)
            combined = pl.concat(per_month).unique(subset="known_at").sort("known_at")
        elif tool in _MACRO_TOOLS:
            # Sprint 045: five macro endpoints share one loader; per-channel manifest
            # supplies known_at_lag_days + known_at_hour_utc + tool-specific params.
            params = c.get("params") or _default_macro_params(tool)
            combined = load_macro_bars(
                cache_dir=cache_dir,
                source=c["source"],
                tool=tool,
                channel=c["channel"],
                symbol=c["symbol"],
                params=params,
                known_at_lag_days=int(c.get("known_at_lag_days", 0)),
                known_at_hour_utc=int(c.get("known_at_hour_utc", 12)),
            )
        elif tool == "HISTORICAL_PUT_CALL_RATIO":
            # Sprint 046: one endpoint call per date; loader walks the cache dir
            # to build the full time series from many single-date cache files.
            # Sprint 047: av_symbol split -- filter cache by AV underlying;
            # tag DataFrame with manifest-visible symbol.
            combined = load_put_call_ratio_bars(
                cache_dir=cache_dir,
                source=c["source"],
                symbol=c["symbol"],
                channel=c["channel"],
                known_at_lag_days=int(c.get("known_at_lag_days", 1)),
                known_at_hour_utc=int(c.get("known_at_hour_utc", 13)),
                av_symbol=c.get("av_symbol", c["symbol"]),
            )
        elif tool == "HISTORICAL_OPTIONS":
            # Sprint 047: per-contract volume aggregation. One endpoint call per
            # date; each response carries thousands of contract rows; loader sums
            # the volume field across all contracts per date.
            combined = load_options_volume_bars(
                cache_dir=cache_dir,
                source=c["source"],
                symbol=c["symbol"],
                channel=c["channel"],
                known_at_lag_days=int(c.get("known_at_lag_days", 1)),
                known_at_hour_utc=int(c.get("known_at_hour_utc", 13)),
                av_symbol=c.get("av_symbol", c["symbol"]),
            )
        elif tool == "EARNINGS":
            # Sprint 048: per-symbol EARNINGS aggregated across SPX constituents
            # into a per-date density scalar. Historical path since
            # EARNINGS_CALENDAR is forward-only.
            combined = load_earnings_density_bars(
                cache_dir=cache_dir,
                source=c["source"],
                channel=c["channel"],
                symbol=c["symbol"],
            )
        elif tool == "STATIC_FOMC":
            # Sprint 048: curated FOMC-dates static table (2015-2025).
            static_path = Path(c["static_path"])
            combined = load_fomc_bars(
                static_path=static_path,
                channel=c["channel"],
                symbol=c["symbol"],
            )
        elif tool == "STATIC_CPI_RELEASE":
            # Sprint 048: derived from macro__CPI cache with Sprint 045 known-at
            # rule. Within-week approximation of BLS release timing; documented
            # in the loader docstring.
            combined = load_cpi_release_bars(
                cache_dir=cache_dir,
                source=c["source"],
                channel=c["channel"],
                symbol=c["symbol"],
                known_at_lag_days=int(c.get("known_at_lag_days", 45)),
                known_at_hour_utc=int(c.get("known_at_hour_utc", 12)),
            )
        elif tool == "DETERMINISTIC_OPTIONS_EXPIRY":
            # Sprint 048: deterministic third-Friday-monthly with a CBOE
            # holiday-rollback lookup. No AV call, no cache.
            combined = load_options_expiry_bars(
                start=start,
                end=end,
                channel=c["channel"],
                symbol=c["symbol"],
            )
        else:
            raise ValueError(f"unsupported tool {tool!r} on channel {c['channel']}/{c['symbol']}")
        channel_bars[f"{c['channel']}__{c['symbol']}"] = combined

    grid = build_rth_grid(start, end)
    aligned = align_channels(grid, channel_bars, emitter)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    aligned.write_parquet(output_path)

    total_rows = aligned.height
    missing_fractions: dict[str, float] = {}
    for key in channel_bars:
        close_col = f"{key}__close"
        n_missing = int(aligned[close_col].is_null().sum())
        missing_fractions[key.split("__", 1)[0]] = n_missing / total_rows if total_rows else 0.0

    elapsed = time.monotonic() - t0

    emitter.emit(
        "ALIGNMENT_RUN_COMPLETED",
        run_id=run_id,
        total_rows=total_rows,
        missing_fractions_per_channel=missing_fractions,
        elapsed_seconds=elapsed,
        output_path=str(output_path),
    )

    return AlignmentResult(
        run_id=run_id,
        total_rows=total_rows,
        missing_fractions_per_channel=missing_fractions,
        elapsed_seconds=elapsed,
        output_path=str(output_path),
    )
