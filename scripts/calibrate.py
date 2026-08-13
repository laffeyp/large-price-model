#!/usr/bin/env python3
"""Cost calibration CLI: pull data via IngestionClient, then fit + emit.

Pulls (i) HISTORICAL_OPTIONS chains for SPY at N monthly dates across
the training range, (ii) M REALTIME_BULK_BID_ASK_PRICES snapshots, and
reads already-cached TIME_SERIES_INTRADAY bars for kappa. Fits both
models and emits SPREAD_SCALER_WRITTEN + KAPPA_WRITTEN + COST_CALIBRATION_FITTED.
"""

import argparse
import hashlib
import os
import sys
import time as _time
import traceback
from datetime import date
from pathlib import Path

from price_space_llm.config import ConfigValidationFailed, load_config
from price_space_llm.cost_calibration import run_cost_calibration
from price_space_llm.git import git_sha
from price_space_llm.ingestion import cache as _cache
from price_space_llm.ingestion.alphavantage import (
    alphavantage_bbo_extract_metadata,
    alphavantage_options_extract_metadata,
    make_alphavantage_raw_fetcher,
)
from price_space_llm.ingestion.client import IngestionClient
from price_space_llm.script_harness import script_session

CACHE_SOURCE = "mcp_av"


def _pull_options_month(client: IngestionClient, cache_dir: Path, symbol: str, month: date) -> Path:
    """Pull HISTORICAL_OPTIONS for `symbol` at a given month-anchor date; return cache path."""
    params = {"symbol": symbol, "date": month.isoformat(), "datatype": "json"}
    client.call(
        channel="target",
        symbol=symbol,
        tool="HISTORICAL_OPTIONS",
        params=params,
        extract_metadata=alphavantage_options_extract_metadata,
    )
    key = _cache.cache_key("HISTORICAL_OPTIONS", "target", symbol, params)
    return _cache.cache_path(cache_dir, CACHE_SOURCE, "HISTORICAL_OPTIONS", key)


def _pull_bbo_snapshot(client: IngestionClient, cache_dir: Path, symbol: str, tag: str) -> Path:
    """Poll REALTIME_BULK_BID_ASK_PRICES; store under a tag-suffixed cache key."""
    params = {
        "symbol": symbol,
        "entitlement": "realtime",
        "datatype": "json",
        "poll_tag": tag,
    }
    client.call(
        channel="target",
        symbol=symbol,
        tool="REALTIME_BULK_BID_ASK_PRICES",
        params=params,
        extract_metadata=alphavantage_bbo_extract_metadata,
    )
    key = _cache.cache_key("REALTIME_BULK_BID_ASK_PRICES", "target", symbol, params)
    return _cache.cache_path(cache_dir, CACHE_SOURCE, "REALTIME_BULK_BID_ASK_PRICES", key)


def _list_intraday_cache(cache_dir: Path, symbol: str) -> list[Path]:
    """Return every TIME_SERIES_INTRADAY response cached under `cache_dir`."""
    root = cache_dir / CACHE_SOURCE / "TIME_SERIES_INTRADAY"
    if not root.exists():
        return []
    matches: list[Path] = []
    for p in sorted(root.glob("*.json")):
        # Cheap heuristic: peek at the file for the requested symbol.
        head = p.read_bytes()[:2048].decode("utf-8", errors="ignore")
        if f'"2. Symbol": "{symbol}"' in head:
            matches.append(p)
    return matches


def _monthly_dates(start: date, end: date) -> list[date]:
    """Return one anchor date per month in [start, end]. If the 15th falls on a weekend,
    walk backward to the nearest weekday. Skips true market holidays imperfectly --
    AV will refuse those and the CLI can be re-run with a different anchor."""
    from datetime import timedelta as _td

    out: list[date] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        anchor = date(y, m, 15)
        while anchor.weekday() >= 5:  # Sat=5, Sun=6
            anchor -= _td(days=1)
        if start <= anchor <= end:
            out.append(anchor)
        m += 1
        if m == 13:
            m = 1
            y += 1
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="calibrate")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/cost_calibration"))
    parser.add_argument("--cache-dir", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--options-start",
        type=date.fromisoformat,
        default=date(2024, 1, 15),
    )
    parser.add_argument(
        "--options-end",
        type=date.fromisoformat,
        default=date(2024, 6, 15),
    )
    parser.add_argument(
        "--bbo-snapshots", type=int, default=3, help="Number of BBO polls to take now."
    )
    parser.add_argument("--bbo-interval-seconds", type=float, default=5.0)
    parser.add_argument("--config", type=Path, default=Path("configs/experiment/v1.json"))
    parser.add_argument("--logs-dir", type=Path, default=Path("logs"))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--kappa-bootstrap", type=int, default=500)
    args = parser.parse_args(argv)

    key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not key:
        print("calibrate: ALPHAVANTAGE_API_KEY not set", file=sys.stderr)
        return 1

    span = f"{args.options_start.isoformat()}-{args.options_end.isoformat()}"
    run_id = f"calibrate-{span}-{args.seed:016d}"
    config_hash = hashlib.sha256(f"{args.options_start}:{args.options_end}".encode()).hexdigest()
    data_hash = hashlib.sha256(b"calibrate:no-single-input").hexdigest()

    result = None
    with script_session(
        run_kind="calibrate",
        run_id=run_id,
        config_hash=config_hash,
        data_hash=data_hash,
        seed=args.seed,
        logs_dir=args.logs_dir,
    ) as (emitter, sink_path):
        try:
            load_config(args.config, emitter=emitter, run_id=run_id, git_sha=git_sha())
        except ConfigValidationFailed as ex:
            print(f"calibrate: config invalid: {ex}", file=sys.stderr)
            return 1

        raw_fetcher = make_alphavantage_raw_fetcher(key)
        client = IngestionClient(
            primary=raw_fetcher,
            primary_source="mcp_av",
            cache_dir=args.cache_dir,
            emitter=emitter,
            clock=_time.monotonic,
        )

        symbol = "SPY"
        option_paths: list[Path] = []
        for month_date in _monthly_dates(args.options_start, args.options_end):
            option_paths.append(_pull_options_month(client, args.cache_dir, symbol, month_date))

        bbo_paths: list[Path] = []
        for i in range(args.bbo_snapshots):
            if i > 0:
                _time.sleep(args.bbo_interval_seconds)
            bbo_paths.append(_pull_bbo_snapshot(client, args.cache_dir, symbol, tag=f"snap{i:03d}"))

        intraday_paths = _list_intraday_cache(args.cache_dir, symbol)
        if not intraday_paths:
            print(f"calibrate: no TIME_SERIES_INTRADAY cache for {symbol}", file=sys.stderr)
            return 1

        try:
            result = run_cost_calibration(
                option_response_paths=option_paths,
                bbo_response_paths=bbo_paths,
                intraday_response_paths=intraday_paths,
                target_symbol=symbol,
                output_dir=args.output_dir,
                emitter=emitter,
                run_id=run_id,
                kappa_bootstrap=args.kappa_bootstrap,
                seed=args.seed,
            )
        except (ValueError, FileNotFoundError):
            traceback.print_exc(file=sys.stderr)
            return 1

    if result is not None:
        s = result.spread_scaler
        k = result.kappa
        print(
            f"calibrate: spread_scaler slope={s.slope:.4f} intercept={s.intercept:.6f} "
            f"r2={s.r_squared:.3f} n_pairs={s.n_pairs} | "
            f"kappa point={k.kappa_point:.5f} se={k.kappa_se:.5f} "
            f"CI=[{k.kappa_ci_low:.5f}, {k.kappa_ci_high:.5f}] r2={k.kappa_r2:.3f} n={k.n} | "
            f"artifacts={result.spread_scaler_path},{result.kappa_path} trace={sink_path}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
