"""Versioned-artifact writes.

Every frozen artifact (bucket_stats, spread_scaler, kappa, checkpoints)
gets a `{stem}.{run_id}{ext}` filename, plus a `{stem}.latest{ext}`
symlink that points at the newest write. Downstream consumers name the
specific `run_id` they read (through the SESSION_INIT `config_hash`
which incorporates the artifact path); resolution to `latest` is a
convenience for CLI ergonomics, never for reproducibility.

The sha256 of the content is written to a matching `{stem}.{run_id}.sha256`
sidecar. Emit sites (`BUCKET_STATS_WRITTEN`, `SPREAD_SCALER_WRITTEN`,
`KAPPA_WRITTEN`, `CHECKPOINT_WRITTEN`) already carry the sha256 in
their payload — the sidecar is redundant-but-useful for offline audit.
"""

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True, kw_only=True)
class VersionedWrite:
    versioned_path: Path
    latest_symlink: Path
    sha256: str
    size_bytes: int


def versioned_path(base_path: Path, run_id: str) -> Path:
    """Return `{stem}.{run_id}{ext}` next to `base_path`.

    `base_path=/a/b/bucket_stats.json` + `run_id=r1` → `/a/b/bucket_stats.r1.json`.
    """
    stem = base_path.stem
    suffix = base_path.suffix
    return base_path.with_name(f"{stem}.{run_id}{suffix}")


def latest_symlink_path(base_path: Path) -> Path:
    """Return `{stem}.latest{ext}` next to `base_path`."""
    stem = base_path.stem
    suffix = base_path.suffix
    return base_path.with_name(f"{stem}.latest{suffix}")


def write_versioned(base_path: Path, run_id: str, content: bytes) -> VersionedWrite:
    """Write `content` to `versioned_path(base_path, run_id)`; update the `latest` symlink.

    Also writes a `.sha256` sidecar with the hex digest. Overwrites any prior
    write at the SAME `run_id` (idempotent for re-runs); the symlink flips to
    whichever `run_id` was written most recently.
    """
    vpath = versioned_path(base_path, run_id)
    vpath.parent.mkdir(parents=True, exist_ok=True)
    vpath.write_bytes(content)
    sha256_hex = hashlib.sha256(content).hexdigest()
    vpath.with_suffix(vpath.suffix + ".sha256").write_text(sha256_hex + "\n", encoding="utf-8")

    latest = latest_symlink_path(base_path)
    if latest.exists() or latest.is_symlink():
        latest.unlink()
    # Symlink target is relative so the pair is portable across roots.
    os.symlink(vpath.name, latest)

    return VersionedWrite(
        versioned_path=vpath,
        latest_symlink=latest,
        sha256=sha256_hex,
        size_bytes=len(content),
    )


def resolve_latest(base_path: Path) -> Path:
    """Return the path the `latest` symlink points at, or raise if no `latest` exists."""
    latest = latest_symlink_path(base_path)
    if not (latest.exists() or latest.is_symlink()):
        raise FileNotFoundError(f"no latest symlink at {latest}")
    target = os.readlink(latest)
    return (latest.parent / target).resolve() if not Path(target).is_absolute() else Path(target)


def list_versions(base_path: Path) -> list[Path]:
    """Return every versioned file under `base_path.parent` that shares its stem."""
    stem = base_path.stem
    suffix = base_path.suffix
    parent = base_path.parent
    if not parent.exists():
        return []
    matches: list[Path] = []
    for p in sorted(parent.iterdir()):
        if p.suffix != suffix:
            continue
        if not p.name.startswith(f"{stem}."):
            continue
        if p.name == f"{stem}.latest{suffix}":
            continue
        matches.append(p)
    return matches


__all__ = [
    "VersionedWrite",
    "latest_symlink_path",
    "list_versions",
    "resolve_latest",
    "versioned_path",
    "write_versioned",
]
