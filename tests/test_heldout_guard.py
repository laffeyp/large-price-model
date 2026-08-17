"""Sprint 065: filesystem guard on held-out aligned parquet reads."""

from __future__ import annotations

from pathlib import Path

import pytest

from price_space_llm.heldout_guard import (
    HeldoutReadRefused,
    guard_heldout_parquet,
    parquet_range_starts_in_heldout,
)


def test_heldout_detection_on_align_prefix():
    assert parquet_range_starts_in_heldout(Path("align-2024-01-2025-06-0000.parquet"))
    assert parquet_range_starts_in_heldout(Path("align-2025-01-2025-06-0000.parquet"))


def test_heldout_detection_on_features_prefix():
    """features-align-YYYY-MM-... derives from a held-out aligned parquet."""
    assert parquet_range_starts_in_heldout(Path("features-align-2024-01-2025-06-0000-0000.parquet"))


def test_pre_2024_align_is_not_heldout():
    assert not parquet_range_starts_in_heldout(Path("align-2015-01-2022-12-0000.parquet"))
    assert not parquet_range_starts_in_heldout(
        Path("features-align-2015-01-2022-12-0000-0000.parquet")
    )


def test_unrelated_filename_is_not_heldout():
    """Guard only fires on files it can positively identify as aligned."""
    assert not parquet_range_starts_in_heldout(Path("some_other.parquet"))
    assert not parquet_range_starts_in_heldout(Path("checkpoint.pt"))


def test_guard_raises_on_heldout_without_flag():
    with pytest.raises(HeldoutReadRefused, match="held-out"):
        guard_heldout_parquet(Path("align-2024-01-2025-06-0000.parquet"))


def test_guard_permits_with_flag():
    # Does not raise.
    guard_heldout_parquet(Path("align-2024-01-2025-06-0000.parquet"), allow_test_look=True)


def test_guard_permits_pre_2024_without_flag():
    guard_heldout_parquet(Path("align-2015-01-2022-12-0000.parquet"))
