#!/usr/bin/env python3
"""Phase 0 channel-coverage probe CLI.

Reads a channel manifest (JSON), invokes the probe against the selected
fetcher, writes a JSONL trace to `logs/{run_id}/signals.jsonl`, writes
the channel manifest to `data/manifests/channel_coverage.json`, prints
a short stderr summary, exits 0 on all-accepted and 2 on any-dropped.

--fetcher mock (default): deterministic mock; USO drops.
--fetcher alphavantage: live Alpha-Vantage over HTTP; needs
    ALPHAVANTAGE_API_KEY env var. Fetcher exceptions are caught inside
    `probe_channel` and surface as v0.3's `CHANNEL_FETCH_FAILED` incident
    signals — no fabricated observations, no fill values.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import traceback
from datetime import date
from pathlib import Path

from price_space_llm.ingestion.alphavantage import make_alphavantage_fetcher
from price_space_llm.ingestion.probe import (
    DEFAULT_SAMPLE_DATES,
    ChannelSpec,
    Fetcher,
    FetchResult,
    run_phase_zero_probe,
)
from price_space_llm.signals import (
    StrictSignalEmitter,
    load_vocabulary,
    process_session,
)


def mock_fetcher(channel: str, symbol: str, source: str, sample_date: date) -> FetchResult:
    """Deterministic mock. USO drops so the CLI exercises the exit-2 path."""
    del source, sample_date
    missing = 0.20 if (channel == "market_context" and symbol == "USO") else 0.001
    return FetchResult(
        actual_frequency="15min",
        earliest_timestamp="2015-01-05T13:30:00+00:00",
        latest_timestamp="2025-06-30T20:00:00+00:00",
        missing_fraction=missing,
        timezone="UTC",
        timestamp_semantics="bar_close",
        revision_behavior="immutable",
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


def _load_config(config_path: Path) -> list[ChannelSpec]:
    doc = json.loads(config_path.read_text(encoding="utf-8"))
    return [ChannelSpec(**c) for c in doc["channels"]]


def _resolve_fetcher(kind: str) -> Fetcher:
    if kind == "mock":
        return mock_fetcher
    if kind == "alphavantage":
        key = os.environ.get("ALPHAVANTAGE_API_KEY")
        if not key:
            raise SystemExit(
                "probe: --fetcher alphavantage requires ALPHAVANTAGE_API_KEY env var "
                "(copy .env.example to .env and fill in the key)."
            )
        return make_alphavantage_fetcher(key)
    raise ValueError(f"unknown fetcher kind: {kind!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="probe_channels")
    parser.add_argument("config", type=Path, help="JSON channel manifest")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--logs-dir", type=Path, default=Path("logs"))
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/manifests/channel_coverage.json"),
    )
    parser.add_argument(
        "--fetcher",
        choices=("mock", "alphavantage"),
        default="mock",
    )
    args = parser.parse_args(argv)

    if not args.config.exists():
        print(f"probe: config not found: {args.config}", file=sys.stderr)
        return 1

    try:
        fetcher = _resolve_fetcher(args.fetcher)
    except SystemExit as ex:
        print(str(ex), file=sys.stderr)
        return 1

    channels = _load_config(args.config)
    config_hash = hashlib.sha256(args.config.read_bytes()).hexdigest()
    git_sha = _git_sha()
    data_hash = hashlib.sha256(b"probe:no-data-input").hexdigest()

    run_id = f"probe-{args.fetcher}-{args.seed:016d}"
    sink_path = args.logs_dir / run_id / "signals.jsonl"
    emitter = StrictSignalEmitter(load_vocabulary(), jsonl_sink=sink_path)

    exit_code = 0
    with process_session(
        run_kind="probe",
        config_hash=config_hash,
        git_sha=git_sha,
        data_hash=data_hash,
        seed=args.seed,
        run_id=run_id,
        emitter=emitter,
    ):
        try:
            coverages = run_phase_zero_probe(
                channels,
                DEFAULT_SAMPLE_DATES,
                fetcher,
                emitter,
                args.manifest,
            )
        except Exception:
            traceback.print_exc(file=sys.stderr)
            return 1

    n_accepted = sum(1 for c in coverages if c["verdict"] == "accepted")
    n_dropped = sum(1 for c in coverages if c["verdict"] == "dropped")
    if n_dropped > 0:
        exit_code = 2
    print(
        f"probe: {n_accepted} accepted, {n_dropped} dropped; "
        f"manifest={args.manifest}; trace={sink_path}",
        file=sys.stderr,
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
