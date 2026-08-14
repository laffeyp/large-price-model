#!/usr/bin/env python3
"""Ingest a range of months of 15-min bars for each accepted channel.

Reads the Phase 0 manifest (`data/manifests/channel_coverage.json`),
picks every channel with `verdict == "accepted"`, iterates months in
`[--start-month, --end-month]`, and calls Alpha-Vantage
`TIME_SERIES_INTRADAY` for each (channel, month). Each call goes through
`IngestionClient`, which handles rate limiting, JSON caching, and the
five ingest-category emit sites.

Second-and-later invocations for the same (month, channel) short-circuit
via cache-hit; the CLI stays cheap during iterative debugging.

Free-tier budget: 25 requests/day. `N_channels * N_months` fetches per
invocation; every cache-hit costs zero.
"""

import argparse
import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

from price_space_llm.alignment.join import _default_macro_params
from price_space_llm.ingestion.alphavantage import (
    alphavantage_extract_metadata,
    alphavantage_index_extract_metadata,
    alphavantage_macro_extract_metadata,
    make_alphavantage_raw_fetcher,
)
from price_space_llm.ingestion.client import IngestionCallFailed, IngestionClient, RawFetcher
from price_space_llm.script_harness import script_session

_MACRO_TOOLS = frozenset(
    {"CPI", "FEDERAL_FUNDS_RATE", "TREASURY_YIELD", "UNEMPLOYMENT", "NONFARM_PAYROLL"}
)


def _month_range(start: str, end: str) -> list[str]:
    """Return every YYYY-MM string between `start` and `end` inclusive."""
    start_y, start_m = (int(x) for x in start.split("-"))
    end_y, end_m = (int(x) for x in end.split("-"))
    if (end_y, end_m) < (start_y, start_m):
        raise ValueError(f"end_month {end!r} precedes start_month {start!r}")
    months: list[str] = []
    y, m = start_y, start_m
    while (y, m) <= (end_y, end_m):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            m = 1
            y += 1
    return months


def _load_accepted_channels(manifest_path: Path) -> list[dict]:
    """Return the list of accepted channel entries as manifest-shaped dicts.

    `tool` defaults to `TIME_SERIES_INTRADAY` when unset. Sprint 045: macro
    channels carry `params`, `known_at_lag_days`, and `known_at_hour_utc`
    fields that pass through untouched.
    """
    doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    out = []
    for c in doc["channels"].values():
        if c.get("verdict") != "accepted":
            continue
        out.append(
            {
                "channel": c["channel"],
                "symbol": c["symbol"],
                "source": c["source"],
                "tool": c.get("tool", "TIME_SERIES_INTRADAY"),
                "params": c.get("params"),
                "known_at_lag_days": c.get("known_at_lag_days", 0),
                "known_at_hour_utc": c.get("known_at_hour_utc", 12),
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ingest")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/manifests/channel_coverage.json"),
        help="Phase 0 manifest with per-channel verdicts.",
    )
    parser.add_argument(
        "--start-month",
        required=True,
        help="YYYY-MM (inclusive). Alpha-Vantage TIME_SERIES_INTRADAY 'month' parameter.",
    )
    parser.add_argument(
        "--end-month",
        default=None,
        help="YYYY-MM (inclusive). Defaults to `--start-month` (single-month run).",
    )
    parser.add_argument("--cache-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--logs-dir", type=Path, default=Path("logs"))
    parser.add_argument(
        "--fetcher",
        choices=("mock", "alphavantage"),
        default="alphavantage",
        help="'mock' returns a small canned response for testing; 'alphavantage' hits live.",
    )
    args = parser.parse_args(argv)

    if not args.manifest.exists():
        print(f"ingest: manifest not found: {args.manifest}", file=sys.stderr)
        return 1

    end_month = args.end_month or args.start_month
    try:
        months = _month_range(args.start_month, end_month)
    except ValueError as ex:
        print(f"ingest: {ex}", file=sys.stderr)
        return 1

    channels = _load_accepted_channels(args.manifest)
    if not channels:
        print(f"ingest: no accepted channels in {args.manifest}; nothing to do", file=sys.stderr)
        return 1

    if args.fetcher == "alphavantage":
        key = os.environ.get("ALPHAVANTAGE_API_KEY")
        if not key:
            print(
                "ingest: --fetcher alphavantage requires ALPHAVANTAGE_API_KEY env var",
                file=sys.stderr,
            )
            return 1
        raw_fetcher: RawFetcher = make_alphavantage_raw_fetcher(key)
    else:
        raw_fetcher = _mock_raw_fetcher()

    span_tag = (
        args.start_month if end_month == args.start_month else f"{args.start_month}_{end_month}"
    )
    run_id = f"ingest-{args.fetcher}-{span_tag}-{args.seed:016d}"
    manifest_bytes = args.manifest.read_bytes()
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    config_hash = hashlib.sha256(f"{span_tag}:{manifest_hash}".encode()).hexdigest()
    data_hash = manifest_hash

    exit_code = 0
    n_ok = 0
    n_failed = 0
    with script_session(
        run_kind="probe",  # v0.3 has no `ingest` run_kind yet; probe covers Phase 0 + Phase 1
        run_id=run_id,
        config_hash=config_hash,
        data_hash=data_hash,
        seed=args.seed,
        logs_dir=args.logs_dir,
    ) as (emitter, sink_path):
        primary_source = channels[0]["source"]
        client = IngestionClient(
            primary=raw_fetcher,
            primary_source=primary_source,
            cache_dir=args.cache_dir,
            emitter=emitter,
            clock=time.monotonic,
        )
        index_channels = [c for c in channels if c["tool"] == "INDEX_DATA"]
        intraday_channels = [c for c in channels if c["tool"] == "TIME_SERIES_INTRADAY"]
        macro_channels = [c for c in channels if c["tool"] in _MACRO_TOOLS]
        known_tools = {"INDEX_DATA", "TIME_SERIES_INTRADAY"} | set(_MACRO_TOOLS)
        other_channels = [c for c in channels if c["tool"] not in known_tools]
        if other_channels:
            print(
                f"ingest: unsupported tool on {len(other_channels)} channels; "
                f"tools={sorted({c['tool'] for c in other_channels})}",
                file=sys.stderr,
            )
            return 1

        for ch in index_channels:
            try:
                client.call(
                    channel=ch["channel"],
                    symbol=ch["symbol"],
                    tool="INDEX_DATA",
                    params={
                        "symbol": ch["symbol"],
                        "interval": "daily",
                        "datatype": "json",
                    },
                    extract_metadata=alphavantage_index_extract_metadata,
                )
                n_ok += 1
            except IngestionCallFailed:
                traceback.print_exc(file=sys.stderr)
                n_failed += 1
                exit_code = 2

        for ch in macro_channels:
            try:
                client.call(
                    channel=ch["channel"],
                    symbol=ch["symbol"],
                    tool=ch["tool"],
                    params=ch.get("params") or _default_macro_params(ch["tool"]),
                    extract_metadata=alphavantage_macro_extract_metadata,
                )
                n_ok += 1
            except IngestionCallFailed:
                traceback.print_exc(file=sys.stderr)
                n_failed += 1
                exit_code = 2

        for month in months:
            for ch in intraday_channels:
                try:
                    client.call(
                        channel=ch["channel"],
                        symbol=ch["symbol"],
                        tool="TIME_SERIES_INTRADAY",
                        params={
                            "symbol": ch["symbol"],
                            "interval": "15min",
                            "month": month,
                            "outputsize": "full",
                            "datatype": "json",
                        },
                        extract_metadata=alphavantage_extract_metadata,
                    )
                    n_ok += 1
                except IngestionCallFailed:
                    traceback.print_exc(file=sys.stderr)
                    n_failed += 1
                    exit_code = 2

    print(
        f"ingest: {n_ok} ok, {n_failed} failed; months={args.start_month}..{end_month}; "
        f"cache={args.cache_dir}; trace={sink_path}",
        file=sys.stderr,
    )
    return exit_code


def _mock_raw_fetcher() -> RawFetcher:
    """Deterministic mock for the --fetcher mock path. Returns a two-bar response."""

    def fetch(tool: str, params: dict) -> dict:
        del tool
        return {
            "Meta Data": {"4. Interval": "15min", "6. Time Zone": "US/Eastern"},
            "Time Series (15min)": {
                "2024-06-28 15:45:00": {
                    "1. open": "540.0",
                    "2. high": "541.0",
                    "3. low": "539.0",
                    "4. close": "540.5",
                    "5. volume": "1000000",
                },
                "2024-06-28 16:00:00": {
                    "1. open": "540.5",
                    "2. high": "541.5",
                    "3. low": "539.5",
                    "4. close": "541.0",
                    "5. volume": "1200000",
                },
            },
        }

    return fetch


if __name__ == "__main__":
    sys.exit(main())
