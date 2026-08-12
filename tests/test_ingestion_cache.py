"""Tests for the JSON-on-disk cache."""

from __future__ import annotations

from pathlib import Path

import pytest

from price_space_llm.ingestion import cache


def test_cache_key_stable_across_param_order():
    a = cache.cache_key("TOOL_X", "target", "SPY", {"a": 1, "b": 2, "c": 3})
    b = cache.cache_key("TOOL_X", "target", "SPY", {"c": 3, "a": 1, "b": 2})
    assert a == b


def test_cache_key_differs_on_different_tool():
    a = cache.cache_key("TOOL_X", "target", "SPY", {"a": 1})
    b = cache.cache_key("TOOL_Y", "target", "SPY", {"a": 1})
    assert a != b


def test_cache_key_differs_on_different_params():
    a = cache.cache_key("TOOL_X", "target", "SPY", {"a": 1})
    b = cache.cache_key("TOOL_X", "target", "SPY", {"a": 2})
    assert a != b


def test_cache_key_differs_on_different_symbol():
    a = cache.cache_key("TOOL_X", "target", "SPY", {"a": 1})
    b = cache.cache_key("TOOL_X", "target", "QQQ", {"a": 1})
    assert a != b


def test_cache_key_differs_on_different_channel():
    a = cache.cache_key("TOOL_X", "target", "SPY", {"a": 1})
    b = cache.cache_key("TOOL_X", "market_context", "SPY", {"a": 1})
    assert a != b


def test_read_returns_none_when_absent(tmp_path: Path):
    assert cache.read(tmp_path / "does-not-exist.json") is None


def test_write_creates_parent_dirs_and_reads_back(tmp_path: Path):
    path = tmp_path / "nested" / "dirs" / "payload.json"
    payload = {"key": "value", "list": [1, 2, 3]}
    cache.write(path, payload)
    assert path.exists()
    assert cache.read(path) == payload


def test_payload_hash_stable_across_key_order():
    a = cache.payload_hash({"x": 1, "y": 2})
    b = cache.payload_hash({"y": 2, "x": 1})
    assert a == b


def test_cache_path_layout(tmp_path: Path):
    p = cache.cache_path(tmp_path, "mcp_av", "TIME_SERIES_INTRADAY", "abc123")
    assert p == tmp_path / "mcp_av" / "TIME_SERIES_INTRADAY" / "abc123.json"


def test_read_rejects_non_object_json(tmp_path: Path):
    path = tmp_path / "list.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError, match="not a JSON object"):
        cache.read(path)
