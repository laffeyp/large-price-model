#!/usr/bin/env python3
"""Sprint 086: backfill provenance sidecars + index rows for pre-Sprint-036 cache entries.

Sprint 036 introduced the `.meta.json` sidecar + append-only `cache_index.jsonl`.
Cache entries written before Sprint 036 landed have neither surface. This script
walks `data/raw/mcp_av/**/*.json`, generates a synthetic `.meta.json` where absent,
and appends a matching row to `data/raw/cache_index.jsonl`. Synthetic fields:

- `pulled_at_utc`: the file's mtime in UTC (best available timestamp).
- `pulled_by_run_id`: `"pre-sprint-036-backfill"`.
- `git_sha`: `"unknown"` (pre-Sprint-036 writes did not record it).
- `size_bytes`: current file size.
- `response_schema_hash`: computed live from the payload (matches Sprint 036 semantics).
- `tool`: derived from the parent directory (`data/raw/mcp_av/{tool}/`).
- `channel` + `symbol` + `params`: extracted from the payload where possible; else
  `channel="unknown"`, `symbol="unknown"`, `params={}`.
- `cache_key`: the filename stem (sha256 hex of the original cache key).

Idempotent: files that already have a `.meta.json` sidecar are skipped, and every
appended index row is checked against the index by cache_key before writing.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from price_space_llm.ingestion.cache import (
    CACHE_INDEX_FILENAME,
    META_SUFFIX,
    CacheMeta,
    _response_schema_hash,
    meta_path,
)

CACHE_ROOT_DEFAULT = Path("data/raw")
BACKFILL_RUN_ID = "pre-sprint-036-backfill"


def _extract_symbol(payload: dict, tool: str) -> str:
    """Best-effort symbol extraction from AV response envelopes."""
    meta = payload.get("Meta Data") or payload.get("meta_data") or {}
    for key in ("2. Symbol", "3. Symbol", "1. Symbol", "symbol"):
        if key in meta:
            return str(meta[key])
    for key in ("symbol", "Symbol"):
        if key in payload:
            return str(payload[key])
    return "unknown"


def _existing_cache_keys_in_index(index_path: Path) -> set[str]:
    if not index_path.exists():
        return set()
    keys: set[str] = set()
    with index_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = row.get("cache_key")
            if isinstance(key, str):
                keys.add(key)
    return keys


def _walk_cache_files(cache_root: Path) -> list[Path]:
    """Every .json under cache_root that isn't a .meta.json sidecar."""
    files: list[Path] = []
    for p in sorted(cache_root.rglob("*.json")):
        if p.name.endswith(META_SUFFIX):
            continue
        if p.name == CACHE_INDEX_FILENAME:
            continue
        files.append(p)
    return files


def _synthesize_meta(data_path: Path) -> CacheMeta:
    """Read the payload, derive the fields Sprint 036 would have stamped."""
    tool = data_path.parent.name
    cache_key = data_path.stem
    body = data_path.read_bytes()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = {}
    symbol = _extract_symbol(payload, tool) if isinstance(payload, dict) else "unknown"
    schema_hash = (
        _response_schema_hash(payload) if isinstance(payload, dict) else "unknown"
    )
    mtime = datetime.fromtimestamp(data_path.stat().st_mtime, tz=UTC)
    return CacheMeta(
        tool=tool,
        channel="unknown",
        symbol=symbol,
        params={},
        cache_key=cache_key,
        pulled_at_utc=mtime.isoformat(),
        pulled_by_run_id=BACKFILL_RUN_ID,
        git_sha="unknown",
        size_bytes=len(body),
        response_schema_hash=schema_hash,
    )


def _write_meta(data_path: Path, meta: CacheMeta) -> None:
    body = json.dumps(asdict(meta), sort_keys=True, indent=2)
    meta_path(data_path).write_text(body, encoding="utf-8")


def _append_index_row(index_path: Path, meta: CacheMeta, data_path: Path) -> None:
    row = {
        "tool": meta.tool,
        "channel": meta.channel,
        "symbol": meta.symbol,
        "params": meta.params,
        "cache_key": meta.cache_key,
        "pulled_at_utc": meta.pulled_at_utc,
        "pulled_by_run_id": meta.pulled_by_run_id,
        "git_sha": meta.git_sha,
        "size_bytes": meta.size_bytes,
        "response_schema_hash": meta.response_schema_hash,
        "data_path": str(data_path),
    }
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def backfill(
    cache_root: Path = CACHE_ROOT_DEFAULT, dry_run: bool = False
) -> tuple[int, int]:
    """Return (sidecars_written, index_rows_appended)."""
    index_path = cache_root / CACHE_INDEX_FILENAME
    existing = _existing_cache_keys_in_index(index_path)
    sidecars_written = 0
    rows_appended = 0
    for data_path in _walk_cache_files(cache_root):
        needs_sidecar = not meta_path(data_path).exists()
        needs_index = data_path.stem not in existing
        if not (needs_sidecar or needs_index):
            continue
        meta = _synthesize_meta(data_path)
        if dry_run:
            print(f"would backfill {data_path}", file=sys.stderr)
            sidecars_written += int(needs_sidecar)
            rows_appended += int(needs_index)
            continue
        if needs_sidecar:
            _write_meta(data_path, meta)
            sidecars_written += 1
        if needs_index:
            _append_index_row(index_path, meta, data_path)
            existing.add(meta.cache_key)
            rows_appended += 1
    return sidecars_written, rows_appended


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="backfill_cache_sidecars")
    parser.add_argument("--cache-root", type=Path, default=CACHE_ROOT_DEFAULT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    sidecars, rows = backfill(args.cache_root, dry_run=args.dry_run)
    print(f"backfill: sidecars={sidecars} index_rows={rows}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
