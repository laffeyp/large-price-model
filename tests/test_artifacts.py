"""Tests for the versioned-artifact helper (Sprint 036)."""

import hashlib
from pathlib import Path

import pytest

from price_space_llm.artifacts import (
    latest_symlink_path,
    list_versions,
    resolve_latest,
    versioned_path,
    write_versioned,
)


def test_versioned_path_inserts_run_id_before_extension(tmp_path: Path):
    base = tmp_path / "artifacts" / "bucket_stats.json"
    assert versioned_path(base, "r1").name == "bucket_stats.r1.json"
    assert versioned_path(base, "r1").parent == base.parent


def test_latest_symlink_path_uses_stem_latest_ext(tmp_path: Path):
    base = tmp_path / "artifacts" / "bucket_stats.json"
    assert latest_symlink_path(base).name == "bucket_stats.latest.json"


def test_write_versioned_creates_file_and_symlink(tmp_path: Path):
    base = tmp_path / "artifacts" / "spread_scaler.json"
    result = write_versioned(base, "r7", b'{"slope": 0.5}')
    assert result.versioned_path.exists()
    assert result.latest_symlink.exists() or result.latest_symlink.is_symlink()
    assert result.versioned_path.name == "spread_scaler.r7.json"
    assert result.latest_symlink.name == "spread_scaler.latest.json"


def test_write_versioned_writes_sha256_sidecar(tmp_path: Path):
    base = tmp_path / "kappa.json"
    body = b'{"kappa": 1.23}'
    result = write_versioned(base, "r1", body)
    sidecar = result.versioned_path.with_suffix(result.versioned_path.suffix + ".sha256")
    assert sidecar.exists()
    assert sidecar.read_text(encoding="utf-8").strip() == hashlib.sha256(body).hexdigest()
    assert result.sha256 == hashlib.sha256(body).hexdigest()


def test_second_write_flips_latest_symlink(tmp_path: Path):
    base = tmp_path / "bucket_stats.json"
    write_versioned(base, "r1", b'{"a": 1}')
    write_versioned(base, "r2", b'{"a": 2}')
    latest = latest_symlink_path(base)
    target = latest.resolve()
    assert target.name == "bucket_stats.r2.json"
    assert target.read_bytes() == b'{"a": 2}'


def test_resolve_latest_returns_current_target(tmp_path: Path):
    base = tmp_path / "kappa.json"
    write_versioned(base, "r1", b'{"k": 1}')
    resolved = resolve_latest(base)
    assert resolved.name == "kappa.r1.json"
    assert resolved.read_bytes() == b'{"k": 1}'


def test_resolve_latest_raises_when_no_latest(tmp_path: Path):
    base = tmp_path / "does_not_exist.json"
    with pytest.raises(FileNotFoundError, match="no latest symlink"):
        resolve_latest(base)


def test_list_versions_omits_latest_symlink(tmp_path: Path):
    base = tmp_path / "kappa.json"
    write_versioned(base, "r1", b'{"k": 1}')
    write_versioned(base, "r2", b'{"k": 2}')
    versions = list_versions(base)
    names = sorted(p.name for p in versions)
    # Two versioned files. Symlink and .sha256 sidecars excluded.
    assert names == ["kappa.r1.json", "kappa.r2.json"]


def test_re_write_same_run_id_is_idempotent(tmp_path: Path):
    base = tmp_path / "kappa.json"
    write_versioned(base, "r1", b'{"k": 1}')
    write_versioned(base, "r1", b'{"k": 2}')  # overwrite same run_id
    versions = list_versions(base)
    assert len(versions) == 1
    assert versions[0].read_bytes() == b'{"k": 2}'


def test_bytes_are_written_verbatim(tmp_path: Path):
    base = tmp_path / "artifact.bin"
    payload = bytes(range(256))
    result = write_versioned(base, "r0", payload)
    assert result.versioned_path.read_bytes() == payload
    assert result.size_bytes == 256
