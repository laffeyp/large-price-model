"""Pre-commit hook logic per tech-arch §13.

Fails any commit whose staged config files carry dates >= 2024-01-01 unless
the commit message contains the `[test-look]` token. That token acknowledges
the operator is deliberately touching held-out-window configuration; every
such commit should also register a real look via `scripts/register_test_look.py`.

Sprint 064 ships the pure-Python check function. `scripts/check_test_look.sh`
is a thin bash wrapper that resolves staged files via `git diff --cached
--name-only` and hands the list to this module.
"""

from __future__ import annotations

import re
from pathlib import Path

# Held-out window starts 2024-01-01 per spec § v1. Any config file that
# carries a date at or beyond this threshold is a candidate test-look.
HELDOUT_START_YEAR = 2024
TEST_LOOK_TOKEN = "[test-look]"
# Anchored on non-digit context so `2025-06-30T20:00:00` matches (the `T`
# breaks `\b`-boundary word semantics because both sides are word chars).
DATE_PATTERN = re.compile(r"(?<!\d)(20[2-9][0-9])-([01][0-9])-([0-3][0-9])(?!\d)")

# Only these paths trigger the check. Tech-arch §13 names configs; the hook
# stays narrow so unrelated commits are not blocked by coincidental date
# strings in code comments or docs.
DEFAULT_CONFIG_GLOBS = (
    "configs/**/*.json",
    "configs/**/*.yaml",
    "configs/**/*.yml",
    "data/manifests/**/*.json",
)


def _matches_config_path(path: Path, globs: tuple[str, ...]) -> bool:
    """True iff `path` matches any of the config globs.

    Uses `PurePath.full_match` (Python 3.13+) so `**` matches arbitrary depths
    including zero directories. That's the semantic the tech-arch §13 globs
    require: `data/manifests/**/*.json` should match a file directly under
    `data/manifests/`.
    """
    for glob in globs:
        if path.full_match(glob):
            return True
    return False


def _find_heldout_dates(text: str) -> list[str]:
    """Return every distinct YYYY-MM-DD in `text` with year >= HELDOUT_START_YEAR."""
    matches = DATE_PATTERN.findall(text)
    found: list[str] = []
    for year_str, month_str, day_str in matches:
        year = int(year_str)
        if year >= HELDOUT_START_YEAR:
            found.append(f"{year_str}-{month_str}-{day_str}")
    return found


def check_commit_for_test_look(
    commit_message: str,
    staged_files: list[Path],
    config_globs: tuple[str, ...] = DEFAULT_CONFIG_GLOBS,
) -> tuple[bool, str]:
    """Return `(should_block, reason)` for one commit.

    Blocks iff any staged file that matches `config_globs` contains a
    `YYYY-MM-DD` date with `YYYY >= 2024` AND the commit message does NOT
    contain `[test-look]`.
    """
    has_token = TEST_LOOK_TOKEN in commit_message
    triggering: list[str] = []
    for path in staged_files:
        if not _matches_config_path(path, config_globs):
            continue
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        dates = _find_heldout_dates(content)
        if dates:
            triggering.append(f"{path}: {sorted(set(dates))[:3]}")
    if not triggering:
        return False, "no held-out dates in staged config files"
    if has_token:
        return False, f"test-look token present; permitted. Triggering: {triggering}"
    reason = (
        f"staged config files reference dates >= {HELDOUT_START_YEAR}-01-01 without "
        f"[test-look] in the commit message. Files: {triggering}. Add [test-look] "
        f"to the commit message and record via scripts/register_test_look.py."
    )
    return True, reason


__all__ = [
    "DEFAULT_CONFIG_GLOBS",
    "HELDOUT_START_YEAR",
    "TEST_LOOK_TOKEN",
    "check_commit_for_test_look",
]
