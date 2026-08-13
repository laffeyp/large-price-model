"""JSON-on-disk cache with provenance sidecars, freshness policy, append-only index.

Cache layout (Sprint 036):
- Data:      `{cache_dir}/{source}/{tool}/{cache_key}.json`
- Provenance:`{cache_dir}/{source}/{tool}/{cache_key}.meta.json`
- Index:     `{cache_dir}/cache_index.jsonl` (append-only; one row per write)

Every `write_with_meta` call writes both files atomically enough for the
sequential workload we have and appends one summary line to the index.
`read_with_freshness` returns None when the entry is older than the
tool's `max_age_seconds` policy (`FRESHNESS_POLICY`); otherwise returns
the payload as `read` did before.

Sprint 021 shipped plain `read`/`write` (still exported for callers that
don't yet route through the policy layer). Sprint 036 layers provenance
+ freshness on top without removing the older API — the IngestionClient
migrates in the same commit.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CACHE_INDEX_FILENAME = "cache_index.jsonl"
META_SUFFIX = ".meta.json"


# Freshness policy per tool. `math.inf` means "immutable, never stale."
FRESHNESS_POLICY: dict[str, float] = {
    # Historical months are immutable once the month closes.
    "TIME_SERIES_INTRADAY": math.inf,
    # Historical options are immutable once the trading day closes.
    "HISTORICAL_OPTIONS": math.inf,
    # Realtime BBO changes every millisecond; cache only useful for near-simultaneous re-reads.
    "REALTIME_BULK_BID_ASK_PRICES": 5.0,
    # Realtime options: same class.
    "REALTIME_OPTIONS": 5.0,
    # Global quotes: single latest price; short lifetime.
    "GLOBAL_QUOTE": 30.0,
}
DEFAULT_MAX_AGE_SECONDS = math.inf


@dataclass(slots=True, frozen=True, kw_only=True)
class CacheMeta:
    """Sidecar provenance for one cached response."""

    tool: str
    channel: str
    symbol: str
    params: dict[str, Any]
    cache_key: str
    pulled_at_utc: str  # ISO-8601
    pulled_by_run_id: str
    git_sha: str
    size_bytes: int
    response_schema_hash: str  # sha256 of the sorted response top-level key set


def cache_key(
    tool: str,
    channel: str,
    symbol: str,
    params: dict[str, Any],
) -> str:
    """Deterministic sha256 over sorted-keys JSON of (tool, channel, symbol, params)."""
    canonical = json.dumps(
        {"tool": tool, "channel": channel, "symbol": symbol, "params": params},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def cache_path(cache_dir: Path, source: str, tool: str, key: str) -> Path:
    return cache_dir / source / tool / f"{key}.json"


def meta_path(data_path: Path) -> Path:
    return data_path.with_suffix(data_path.suffix + META_SUFFIX)


def read(path: Path) -> dict[str, Any] | None:
    """Legacy plain read. Ignores freshness; returns whatever is on disk."""
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, dict):
        raise ValueError(f"cache file {path} is not a JSON object")
    return obj


def write(path: Path, payload: dict[str, Any]) -> int:
    """Legacy plain write. Writes only the data file — no meta, no index."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, sort_keys=True, default=str)
    return path.write_text(body, encoding="utf-8")


def payload_hash(payload: dict[str, Any]) -> str:
    """sha256 of the JSON-serialised payload; used for revision detection."""
    body = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _response_schema_hash(payload: dict[str, Any]) -> str:
    """sha256 of the sorted top-level key set. Fingerprints the vendor response shape."""
    keys = sorted(payload.keys())
    canonical = json.dumps(keys, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def read_meta(data_path: Path) -> CacheMeta | None:
    """Read the sidecar for `data_path` if it exists; else None."""
    mp = meta_path(data_path)
    if not mp.exists():
        return None
    doc = json.loads(mp.read_text(encoding="utf-8"))
    return CacheMeta(**doc)


def _write_meta(data_path: Path, meta: CacheMeta) -> None:
    mp = meta_path(data_path)
    body = json.dumps(asdict(meta), sort_keys=True, indent=2)
    mp.write_text(body, encoding="utf-8")


def _append_index(cache_dir: Path, meta: CacheMeta, data_path: Path) -> None:
    """Append one JSONL row summarising the cache write."""
    index_path = cache_dir / CACHE_INDEX_FILENAME
    index_path.parent.mkdir(parents=True, exist_ok=True)
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
    with index_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def write_with_meta(
    data_path: Path,
    payload: dict[str, Any],
    *,
    cache_dir: Path,
    tool: str,
    channel: str,
    symbol: str,
    params: dict[str, Any],
    key: str,
    pulled_by_run_id: str,
    git_sha: str,
    now: datetime | None = None,
) -> CacheMeta:
    """Write data + sidecar + append index. Returns the meta record just written."""
    size = write(data_path, payload)
    meta = CacheMeta(
        tool=tool,
        channel=channel,
        symbol=symbol,
        params=params,
        cache_key=key,
        pulled_at_utc=(now or datetime.now(UTC)).isoformat(),
        pulled_by_run_id=pulled_by_run_id,
        git_sha=git_sha,
        size_bytes=size,
        response_schema_hash=_response_schema_hash(payload),
    )
    _write_meta(data_path, meta)
    _append_index(cache_dir, meta, data_path)
    return meta


def read_with_freshness(
    data_path: Path,
    tool: str,
    *,
    now: datetime | None = None,
    policy: dict[str, float] = FRESHNESS_POLICY,
) -> dict[str, Any] | None:
    """Return payload if fresh per policy; else None. Missing sidecar => treat as stale."""
    if not data_path.exists():
        return None
    meta = read_meta(data_path)
    max_age = policy.get(tool, DEFAULT_MAX_AGE_SECONDS)
    if math.isinf(max_age):
        # Immutable — return whatever is there regardless of meta.
        return read(data_path)
    if meta is None:
        # No sidecar under a non-infinite policy: cannot verify freshness → refuse.
        return None
    pulled_at = datetime.fromisoformat(meta.pulled_at_utc)
    reference = now or datetime.now(UTC)
    age_seconds = (reference - pulled_at).total_seconds()
    if age_seconds > max_age:
        return None
    return read(data_path)
