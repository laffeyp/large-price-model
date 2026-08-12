"""Shared `git_sha()` for the SESSION_INIT payload across scripts.

Every CLI script emits `SESSION_INIT.git_sha` as part of `process_session`.
Pulling the value from a shared helper prevents shotgun surgery when the
command shape changes (e.g. worktree-aware invocation, or a switch to
`git describe`).
"""

import subprocess


def git_sha() -> str:
    """Return the current commit's 40-char hex SHA, or 40 zeros if git is unavailable."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "0" * 40
