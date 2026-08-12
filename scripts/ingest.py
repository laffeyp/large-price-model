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

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

from price_space_llm.ingestion.alphavantage import (
    alphavantage_extract_metadata,
    make_alphavantage_raw_fetcher,
)
from price_space_llm.ingestion.client import IngestionCallFailed, IngestionClient, RawFetcher
from price_space_llm.signals import (
    StrictSignalEmitter,
    load_vocabulary,
    process_session,
)


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "0" * 40


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


def _load_accepted_channels(manifest_path: Path) -> list[dict[str, str]]:
    """Return the list of {channel, symbol, source} entries with verdict=accepted."""
    doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    return [
        {"channel": c["channel"], "symbol": c["symbol"], "source": c["source"]}
        for c in doc["channels"].values()
        if c.get("verdict") == "accepted"
    ]


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
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("data/raw"),
    )
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
        raw_fetcher = make_alphavantage_raw_fetcher(key)
    else:
        raw_fetcher = _mock_raw_fetcher()

    span_tag = (
        args.start_month if end_month == args.start_month else f"{args.start_month}_{end_month}"
    )
    run_id = f"ingest-{args.fetcher}-{span_tag}-{args.seed:016d}"
    sink_path = args.logs_dir / run_id / "signals.jsonl"
    emitter = StrictSignalEmitter(load_vocabulary(), jsonl_sink=sink_path)

    manifest_hash = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    config_hash = hashlib.sha256(f"{span_tag}:{manifest_hash}".encode()).hexdigest()
    data_hash = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    git_sha = _git_sha()

    # IngestionClient's primary_source is a data-provenance label; matches the
    # channel manifest entries (which all carry source="mcp_av" post-probe).
    primary_source = channels[0]["source"]
    client = IngestionClient(
        primary=raw_fetcher,
        primary_source=primary_source,
        cache_dir=args.cache_dir,
        emitter=emitter,
        clock=time.monotonic,
    )

    exit_code = 0
    n_ok = 0
    n_failed = 0
    with process_session(
        run_kind="probe",  # v0.3 has no `ingest` run_kind yet; probe covers Phase 0 + Phase 1
        config_hash=config_hash,
        git_sha=git_sha,
        data_hash=data_hash,
        seed=args.seed,
        run_id=run_id,
        emitter=emitter,
    ):
        for month in months:
            for ch in channels:
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
            "Meta Data": {
                "4. Interval": "15min",
                "6. Time Zone": "US/Eastern",
            },
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
