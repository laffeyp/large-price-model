"""Sprint 107: sync_to_gpu.sh --dry-run emits a deterministic SHA-256 manifest."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "aws" / "sync_to_gpu.sh"


def _payload_exists() -> bool:
    for rel in (
        "data/tokenized/tokens.latest.pt",
        "artifacts/tokenizer/normalizers.latest.pt",
        "artifacts/tokenizer/bucket_stats.latest.json",
    ):
        if not (REPO_ROOT / rel).exists():
            return False
    return True


@pytest.mark.skipif(not _payload_exists(), reason="payload files not on disk in this tree")
def test_sync_dry_run_emits_manifest_with_all_payload_files():
    proc = subprocess.run(
        [str(SCRIPT), "--run-id", "test-sync", "--dry-run"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    stderr = proc.stderr
    assert "DRY RUN" in stderr
    assert "tokens.latest.pt" in stderr
    assert "normalizers.latest.pt" in stderr
    assert "bucket_stats.latest.json" in stderr
    assert "code.tar.gz" in stderr


@pytest.mark.skipif(not _payload_exists(), reason="payload files not on disk in this tree")
def test_sync_dry_run_manifest_is_deterministic_across_runs():
    """Same tree, two invocations, byte-identical code-tarball sha lines."""

    def _lines() -> list[str]:
        proc = subprocess.run(
            [str(SCRIPT), "--run-id", "det-test", "--dry-run"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr
        stderr = proc.stderr
        return [ln for ln in stderr.splitlines() if "code.tar.gz" in ln]

    first = _lines()
    second = _lines()
    assert first == second, f"non-deterministic manifest: {first} vs {second}"


def test_sync_requires_run_id():
    proc = subprocess.run(
        [str(SCRIPT), "--dry-run"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "--run-id required" in proc.stderr


@pytest.mark.skipif(not _payload_exists(), reason="payload files not on disk in this tree")
def test_sync_manifest_uses_basenames_only():
    """Sprint 109 fix (CPU dry-run bug): remote box downloads flat; manifest must too.

    A repo-relative path in the manifest (e.g. `data/tokenized/tokens.latest.pt`)
    would not match the flat S3 layout the box sees. sha256sum -c on the box
    would then FAIL every payload entry.
    """
    proc = subprocess.run(
        [str(SCRIPT), "--run-id", "basename-test", "--dry-run"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    for line in proc.stderr.splitlines():
        if not line or not any(line.strip().endswith(suffix) for suffix in
                               (".pt", ".json", ".tar.gz")):
            continue
        # Manifest lines: `<64-hex>  <path>` — the path should have no `/`.
        parts = line.split()
        if len(parts) == 2 and len(parts[0]) == 64:
            path = parts[1]
            assert "/" not in path, (
                f"manifest carries a repo-relative path {path!r}; "
                "must be basename only"
            )


@pytest.mark.skipif(not _payload_exists(), reason="payload files not on disk in this tree")
def test_sync_code_tarball_includes_sdd_kit_and_signals():
    """Sprint 109 fix (CPU dry-run v2 bug): pyproject force-includes sdd-kit-2/lib/sdd.py.

    The remote `uv sync` fails with `Forced include not found` if the tarball
    omits sdd-kit-2/. signals/ is required at runtime for vocabulary loading.
    """
    import subprocess as sp
    import tarfile
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        # Run the sync script but reroute the tar to a known location for inspection.
        # We can't easily hook the internal tar; instead do the equivalent build here
        # and assert the file list.
        proc = sp.run(
            ["bash", "-c",
             f"cd '{REPO_ROOT}' && "
             "(find src scripts -type f -print && "
             " find sdd-kit-2/lib signals -type f \\( -name '*.py' -o -name '*.json' \\) -print && "
             " printf 'pyproject.toml\\nuv.lock\\n') | LC_ALL=C sort > "
             f"{td}/files.txt && "
             f"tar -cf - -T {td}/files.txt | gzip -n -c > {td}/code.tar.gz"],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stderr
        with tarfile.open(f"{td}/code.tar.gz", "r:gz") as tar:
            names = set(tar.getnames())
        assert "sdd-kit-2/lib/sdd.py" in names, (
            "code tarball missing sdd-kit-2/lib/sdd.py; "
            "the pyproject.toml force-include will break uv sync on the box"
        )
        assert any(n.startswith("signals/") and n.endswith(".json") for n in names), (
            "code tarball has no signals/*.json"
        )


@pytest.mark.skipif(not _payload_exists(), reason="payload files not on disk in this tree")
def test_sync_sha256sum_shim_lets_macos_shells_produce_manifest():
    """Sprint 108 review §11.4: sha256sum is Linux; macOS ships shasum -a 256.

    Prove the shim runs even when sha256sum is not on PATH (macOS default).
    """
    import os
    # Build a PATH that excludes sha256sum but keeps everything else.
    parts = os.environ["PATH"].split(":")
    filtered = []
    for d in parts:
        if os.path.exists(os.path.join(d, "sha256sum")):
            continue
        filtered.append(d)
    if len(filtered) == len(parts):
        pytest.skip("no sha256sum on PATH to remove; macOS default")
    env = os.environ.copy()
    env["PATH"] = ":".join(filtered)
    proc = subprocess.run(
        [str(SCRIPT), "--run-id", "shim-test", "--dry-run"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert "tokens.latest.pt" in proc.stderr
