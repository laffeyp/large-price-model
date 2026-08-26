"""Sprint 106: shell-level test for `scripts/check_test_look.sh`.

The Sprint 064 shell wrapper had a double-heredoc bug that made the hook
always exit nonzero with a NameError; the pure-Python `check_commit_for_test_look`
tests passed because the shell wrapper itself was never exercised. Sprint 106
rewrote the wrapper and pins the wrapper's behavior here.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "scripts" / "check_test_look.sh"


def _run_hook(commit_msg: str, staged_files_output: str) -> tuple[int, str]:
    """Invoke the hook with a synthesized commit-msg file and mocked staged files.

    The hook reads staged files via `git diff --cached --name-only`; the test
    can't set that from outside without touching the index. Instead, wrap the
    hook in a subshell whose PATH shadows `git` with a stub that emits
    `staged_files_output` on stdout.
    """
    tmp = Path("/tmp") / "sprint106_hook_test"
    tmp.mkdir(exist_ok=True)
    msg_file = tmp / "COMMIT_EDITMSG"
    msg_file.write_text(commit_msg, encoding="utf-8")

    # A stub `git` that emits our staged-files list for `diff --cached`
    # and forwards everything else to the real git.
    stub_dir = tmp / "stub_bin"
    stub_dir.mkdir(exist_ok=True)
    stub_git = stub_dir / "git"
    real_git = subprocess.run(
        ["which", "git"], capture_output=True, text=True, check=True
    ).stdout.strip()
    stub_git.write_text(
        f"""#!/usr/bin/env bash
if [[ "$1" == "diff" && "$2" == "--cached" ]]; then
    printf '{staged_files_output}'
    exit 0
fi
exec {real_git} "$@"
""",
        encoding="utf-8",
    )
    stub_git.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{stub_dir}:{env['PATH']}"
    proc = subprocess.run(
        [str(HOOK), str(msg_file)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stderr


def test_hook_exits_zero_on_clean_tree_and_clean_message():
    code, _ = _run_hook("routine bugfix", staged_files_output="")
    assert code == 0


def test_hook_exits_zero_on_config_without_heldout_dates():
    # The path exists on disk (it's a real repo file) but carries no 2024+ date.
    code, _ = _run_hook(
        "add ingest v1 config", staged_files_output="configs/channels/v1.json\\n"
    )
    assert code == 0


def _write_probe_config() -> Path:
    """Write a throwaway config with a 2024 date under configs/ so the glob matches."""
    probe_dir = REPO_ROOT / "configs" / "_sprint106_probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    probe = probe_dir / "heldout_probe.json"
    probe.write_text('{"training_range_end": "2024-06-30"}', encoding="utf-8")
    return probe


def _cleanup_probe() -> None:
    probe_dir = REPO_ROOT / "configs" / "_sprint106_probe"
    probe = probe_dir / "heldout_probe.json"
    if probe.exists():
        probe.unlink()
    if probe_dir.exists():
        probe_dir.rmdir()


def test_hook_blocks_on_config_with_heldout_date_without_test_look_token():
    probe = _write_probe_config()
    try:
        rel = probe.relative_to(REPO_ROOT)
        code, stderr = _run_hook(
            "touch eval config", staged_files_output=f"{rel}\\n"
        )
        assert code == 1
        assert "BLOCKING" in stderr
    finally:
        _cleanup_probe()


def test_hook_passes_when_commit_message_carries_test_look_token():
    probe = _write_probe_config()
    try:
        rel = probe.relative_to(REPO_ROOT)
        code, _ = _run_hook(
            "[test-look] first held-out sim run", staged_files_output=f"{rel}\\n"
        )
        assert code == 0
    finally:
        _cleanup_probe()
