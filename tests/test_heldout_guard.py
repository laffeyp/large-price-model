"""Sprint 065: filesystem guard on held-out aligned parquet reads."""

from __future__ import annotations

from pathlib import Path

import pytest

from price_space_llm.heldout_guard import (
    HeldoutReadRefused,
    UnrecognizedArtifactShape,
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


def test_unrelated_filename_raises_by_default():
    """Sprint 081: unknown filenames raise; caller must opt into the fallback."""
    with pytest.raises(UnrecognizedArtifactShape, match="known dated-artifact"):
        parquet_range_starts_in_heldout(Path("some_other.parquet"))
    with pytest.raises(UnrecognizedArtifactShape):
        parquet_range_starts_in_heldout(Path("checkpoint.pt"))


def test_unrelated_filename_permits_with_allow_unrecognized():
    """`allow_unrecognized=True` falls back to the pre-Sprint-081 permit behavior."""
    assert not parquet_range_starts_in_heldout(
        Path("some_other.parquet"), allow_unrecognized=True
    )
    assert not parquet_range_starts_in_heldout(
        Path("checkpoint.pt"), allow_unrecognized=True
    )


def test_tokens_pt_versioned_filename_detected_as_heldout():
    """Sprint 081: tokens.<run_id>.pt on the Sprint 078 shape is a known pattern."""
    heldout = Path(
        "tokens.tokenize-features-align-2024-01-2025-06-0000000000000000-"
        "0000000000000000-0000000000000000.pt"
    )
    training = Path(
        "tokens.tokenize-features-align-2015-01-2022-12-0000000000000000-"
        "0000000000000000-0000000000000000.pt"
    )
    assert parquet_range_starts_in_heldout(heldout)
    assert not parquet_range_starts_in_heldout(training)


def test_guard_raises_on_heldout_without_flag():
    with pytest.raises(HeldoutReadRefused, match="held-out"):
        guard_heldout_parquet(Path("align-2024-01-2025-06-0000.parquet"))


def test_guard_permits_with_flag():
    # Does not raise.
    guard_heldout_parquet(Path("align-2024-01-2025-06-0000.parquet"), allow_test_look=True)


def test_guard_permits_pre_2024_without_flag():
    guard_heldout_parquet(Path("align-2015-01-2022-12-0000.parquet"))


# Sprint 119: the Sprint 117 held-out tokens escaped every pattern above, and
# data/tokenized/tokens.latest.pt (a symlink) pointed at them while the README
# told readers to train on that path. Each test below plants that defect.

SPRINT117_HELDOUT = "tokens.sprint117-heldout-sprint115-mixer-2024-01-2025-06-tokenize.pt"
TRAINING_PT = (
    "tokens.tokenize-features-align-2015-01-2022-12-0000000000000000-"
    "0000000000000000-0000000000000000.pt"
)


def test_heldout_name_mark_detected_whatever_the_date_layout():
    assert parquet_range_starts_in_heldout(Path(SPRINT117_HELDOUT))


def test_bare_bucketize_output_detected_as_heldout():
    bare = Path(
        "tokenize-features-align-2024-01-2025-06-0000000000000000-"
        "0000000000000000-0000000000000000.pt"
    )
    assert parquet_range_starts_in_heldout(bare)


def test_innocent_symlink_to_heldout_is_heldout(tmp_path: Path):
    target = tmp_path / SPRINT117_HELDOUT
    target.write_bytes(b"")
    link = tmp_path / "tokens.latest.pt"
    link.symlink_to(target.name)
    assert parquet_range_starts_in_heldout(link, allow_unrecognized=True)
    with pytest.raises(HeldoutReadRefused):
        guard_heldout_parquet(link, allow_unrecognized=True)


def test_innocent_symlink_to_training_passes(tmp_path: Path):
    target = tmp_path / TRAINING_PT
    target.write_bytes(b"")
    link = tmp_path / "tokens.latest.pt"
    link.symlink_to(target.name)
    assert not parquet_range_starts_in_heldout(link, allow_unrecognized=True)


def test_train_refuses_symlink_to_heldout(tmp_path: Path):
    import os
    import subprocess

    repo_root = Path(__file__).resolve().parents[1]
    target = tmp_path / SPRINT117_HELDOUT
    target.write_bytes(b"")
    link = tmp_path / "tokens.latest.pt"
    link.symlink_to(target.name)
    proc = subprocess.run(
        ["uv", "run", "python", str(repo_root / "scripts" / "train.py"), "--tokens-pt", str(link)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env={"PATH": os.environ["PATH"], "PSLM_SKIP_EC2_CHECK": "1"},
    )
    assert proc.returncode == 2, proc.stderr
    assert "held-out data cannot be a training input" in proc.stderr
