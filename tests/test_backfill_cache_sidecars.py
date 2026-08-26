"""Sprint 086: backfill_cache_sidecars script tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from backfill_cache_sidecars import backfill  # noqa: E402

from price_space_llm.ingestion.cache import (  # noqa: E402
    CACHE_INDEX_FILENAME,
    meta_path,
    read_meta,
)


def _write_cache_json(cache_root: Path, tool: str, cache_key: str, payload: dict) -> Path:
    """Write a synthetic cache .json + no sidecar (simulates pre-Sprint-036 state)."""
    p = cache_root / "mcp_av" / tool / f"{cache_key}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_backfill_writes_sidecar_and_appends_index_row(tmp_path: Path):
    """A pre-Sprint-036 cache file gains a .meta.json + one index row."""
    cache_root = tmp_path / "raw"
    data_path = _write_cache_json(
        cache_root,
        "TIME_SERIES_INTRADAY",
        "abc" + "0" * 61,
        {"Meta Data": {"2. Symbol": "SPY"}},
    )

    sidecars, rows = backfill(cache_root)
    assert sidecars == 1
    assert rows == 1

    m = read_meta(data_path)
    assert m is not None
    assert m.tool == "TIME_SERIES_INTRADAY"
    assert m.symbol == "SPY"
    assert m.pulled_by_run_id == "pre-sprint-036-backfill"
    assert m.git_sha == "unknown"

    index_path = cache_root / CACHE_INDEX_FILENAME
    lines = [json.loads(x) for x in index_path.read_text().splitlines() if x.strip()]
    assert len(lines) == 1
    assert lines[0]["cache_key"] == data_path.stem


def test_backfill_is_idempotent(tmp_path: Path):
    """Running twice yields no new writes on the second pass."""
    cache_root = tmp_path / "raw"
    _write_cache_json(
        cache_root, "HISTORICAL_OPTIONS", "def" + "0" * 61, {"data": []}
    )
    first_s, first_r = backfill(cache_root)
    assert (first_s, first_r) == (1, 1)
    second_s, second_r = backfill(cache_root)
    assert (second_s, second_r) == (0, 0)


def test_backfill_skips_files_already_indexed(tmp_path: Path):
    """A file whose cache_key already sits in the index is skipped."""
    cache_root = tmp_path / "raw"
    data_path = _write_cache_json(
        cache_root, "TIME_SERIES_INTRADAY", "ghi" + "0" * 61, {"payload": True}
    )

    # Prewrite the index row (sidecar absent).
    (cache_root / CACHE_INDEX_FILENAME).write_text(
        json.dumps({"cache_key": data_path.stem, "tool": "TIME_SERIES_INTRADAY"}) + "\n",
        encoding="utf-8",
    )
    sidecars, rows = backfill(cache_root)
    assert sidecars == 1  # sidecar still needed
    assert rows == 0  # index row already there


def test_backfill_dry_run_writes_nothing(tmp_path: Path):
    cache_root = tmp_path / "raw"
    data_path = _write_cache_json(
        cache_root, "TIME_SERIES_INTRADAY", "jkl" + "0" * 61, {"payload": True}
    )
    sidecars, rows = backfill(cache_root, dry_run=True)
    assert sidecars == 1
    assert rows == 1
    # Actually nothing was written.
    assert not meta_path(data_path).exists()
    assert not (cache_root / CACHE_INDEX_FILENAME).exists()
