"""Sprint 065: filesystem guard on held-out aligned parquet reads.

Sprint 051 wired the runtime guard in `scripts/evaluate.py --split test`
(register_test_look before touching test-window artifacts). Sprint 064 wired
the commit-time guard (`scripts/check_test_look.sh`). Sprint 065 closes the
third leg: refuse any programmatic read of `data/aligned/*.parquet` whose
filename encodes a date range starting 2024-01-01 or later unless the caller
passes `allow_test_look=True`.

Aligned parquet filenames follow the Sprint 037 convention:
`align-{YYYY}-{MM}-{YYYY}-{MM}-{seed}.parquet` (multi-month) or
`align-{YYYY}-{MM}-{seed}.parquet` (single-month). The first date is the
start of the range; if `YYYY >= 2024` the range crosses into the held-out
window.
"""

from __future__ import annotations

import re
from pathlib import Path

HELDOUT_START_YEAR = 2024
# Match both align-YYYY-MM-... and features-align-YYYY-MM-... conventions.
# The features parquet embeds the aligned range in its filename via Sprint 026's
# `features-{aligned_stem}` naming.
ALIGNED_FILENAME_PATTERN = re.compile(r"^(?:features-)?align-(\d{4})-(\d{2})")


class HeldoutReadRefused(RuntimeError):
    """Raised when guard_heldout_parquet refuses a read without an acknowledgment."""


def parquet_range_starts_in_heldout(path: Path) -> bool:
    """True iff `path`'s filename starts with `align-YYYY-MM-` and YYYY >= 2024.

    Returns False for filenames that don't match the aligned convention — the
    guard only fires on files it can positively identify as held-out.
    """
    match = ALIGNED_FILENAME_PATTERN.match(path.name)
    if match is None:
        return False
    year = int(match.group(1))
    return year >= HELDOUT_START_YEAR


def guard_heldout_parquet(path: Path, *, allow_test_look: bool = False) -> None:
    """Raise HeldoutReadRefused if `path` is held-out and `allow_test_look` is False.

    Callers that legitimately need held-out access (Sprint 088 first held-out
    evaluation, drift diagnostic against test window, etc.) pass
    `allow_test_look=True` after registering the look via
    `price_space_llm.testlook.register_test_look`. The guard does not check
    the log itself — that is the caller's contract.
    """
    if not parquet_range_starts_in_heldout(path):
        return
    if allow_test_look:
        return
    raise HeldoutReadRefused(
        f"refused to read held-out aligned parquet {path}: filename indicates the "
        f"range starts in {HELDOUT_START_YEAR} or later. Pass allow_test_look=True "
        f"after registering the look via scripts/register_test_look.py, or exit "
        f"with a clear message to the operator."
    )


__all__ = [
    "HELDOUT_START_YEAR",
    "HeldoutReadRefused",
    "guard_heldout_parquet",
    "parquet_range_starts_in_heldout",
]
