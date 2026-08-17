"""Sprint 064: pre-commit test-look guard per tech-arch §13."""

from __future__ import annotations

from pathlib import Path

from price_space_llm.hooks import (
    DEFAULT_CONFIG_GLOBS,
    check_commit_for_test_look,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_no_staged_files_does_not_block(tmp_path: Path):
    should_block, _ = check_commit_for_test_look("routine fix", [])
    assert not should_block


def test_non_config_staged_file_does_not_block(tmp_path: Path, monkeypatch):
    """Even a file with a 2024 date does not block if the path is not a config."""
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "src" / "foo.py"
    _write(src, "# 2024-06-15 notes")
    should_block, _ = check_commit_for_test_look(
        "routine fix", [Path("src/foo.py")], config_globs=DEFAULT_CONFIG_GLOBS
    )
    assert not should_block


def test_config_with_heldout_date_blocks_without_token(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "configs" / "experiment" / "v1.json"
    _write(cfg, '{"training_start": "2024-01-05"}')
    should_block, reason = check_commit_for_test_look(
        "sweep config",
        [Path("configs/experiment/v1.json")],
    )
    assert should_block
    assert "2024-01-05" in reason
    assert "test-look" in reason.lower()


def test_config_with_heldout_date_permitted_with_token(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "configs" / "experiment" / "v1.json"
    _write(cfg, '{"training_end": "2024-06-30"}')
    should_block, reason = check_commit_for_test_look(
        "sweep config [test-look] look 1 of 3",
        [Path("configs/experiment/v1.json")],
    )
    assert not should_block
    assert "test-look token present" in reason


def test_config_with_pre_2024_date_does_not_block(tmp_path: Path, monkeypatch):
    """Dates in the training window (2015-2022) never block."""
    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "configs" / "experiment" / "v1.json"
    _write(cfg, '{"training_start": "2015-01-05", "training_end": "2022-12-30"}')
    should_block, _ = check_commit_for_test_look(
        "routine training-window edit",
        [Path("configs/experiment/v1.json")],
    )
    assert not should_block


def test_data_manifest_with_heldout_date_blocks(tmp_path: Path, monkeypatch):
    """data/manifests/*.json is a config path too."""
    monkeypatch.chdir(tmp_path)
    manifest = tmp_path / "data" / "manifests" / "channel_coverage.json"
    _write(manifest, '{"latest_timestamp": "2025-06-30T20:00:00+00:00"}')
    should_block, reason = check_commit_for_test_look(
        "refresh manifest",
        [Path("data/manifests/channel_coverage.json")],
    )
    assert should_block
    assert "2025-06-30" in reason


def test_multiple_dates_reported(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "configs" / "sweep.json"
    _write(
        cfg,
        '{"a": "2024-01-05", "b": "2024-06-30", "c": "2025-03-01"}',
    )
    should_block, reason = check_commit_for_test_look(
        "sweep",
        [Path("configs/sweep.json")],
    )
    assert should_block
    for stamp in ("2024-01-05", "2024-06-30", "2025-03-01"):
        assert stamp in reason
