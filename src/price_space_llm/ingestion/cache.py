"""JSON-on-disk cache keyed by sha256(tool, params).

Tech-arch §4.2 prescribes Parquet. Sprint 021 lands JSON — the emit-site
wiring is this sprint's scope; the cache format upgrade happens when the
alignment sprint (Sprint N) actually reads cache contents into a Polars
DataFrame. JSON keeps this sprint's testing surface small and defers the
pyarrow dep until it has a real consumer.

Cache layout: `{cache_dir}/{source}/{tool}/{cache_key}.json` where
`cache_key = sha256(canonical_json({tool, **params}))`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def cache_key(
    tool: str,
    channel: str,
    symbol: str,
    params: dict[str, Any],
) -> str:
    """Deterministic sha256 over sorted-keys JSON of (tool, channel, symbol, params).

    Channel and symbol are load-bearing: two callers hitting TIME_SERIES_INTRADAY
    with identical `params` for SPY vs QQQ must NOT collide. Sort-key JSON means
    `{a:1, b:2}` and `{b:2, a:1}` hash the same.
    """
    canonical = json.dumps(
        {"tool": tool, "channel": channel, "symbol": symbol, "params": params},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def cache_path(cache_dir: Path, source: str, tool: str, key: str) -> Path:
    return cache_dir / source / tool / f"{key}.json"


def read(path: Path) -> dict[str, Any] | None:
    """Return the cached payload dict, or None if the path does not exist."""
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, dict):
        raise ValueError(f"cache file {path} is not a JSON object")
    return obj


def write(path: Path, payload: dict[str, Any]) -> int:
    """Write `payload` as JSON. Returns byte count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, sort_keys=True, default=str)
    return path.write_text(body, encoding="utf-8")


def payload_hash(payload: dict[str, Any]) -> str:
    """sha256 of the JSON-serialised payload; used for revision detection."""
    body = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
