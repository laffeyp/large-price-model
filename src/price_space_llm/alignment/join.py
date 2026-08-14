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
