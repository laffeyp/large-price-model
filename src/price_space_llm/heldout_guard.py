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

# Sprint 081: every naming convention the pipeline uses today for dated
# artifacts. A new pipeline stage that mints a fresh filename shape must
# register its pattern here; the fail-loud raise below forces the addition
# to be visible at review time instead of silently bypassing the guard.
KNOWN_DATED_PATTERNS: tuple[re.Pattern[str], ...] = (
    ALIGNED_FILENAME_PATTERN,
    # tokens.<run_id>.pt where run_id embeds `tokenize-features-align-YYYY-MM-...`
    # per Sprint 078 versioned-write convention.
    re.compile(r"^tokens\.tokenize-features-align-(\d{4})-(\d{2})"),
    # Sprint 119: the bare bucketize output (`tokenize-features-align-YYYY-MM-...pt`
    # and its `.parquet` sibling), which the Sprint 117 held-out run read.
    re.compile(r"^tokenize-features-align-(\d{4})-(\d{2})"),
)

# Sprint 119: any artifact whose name says it is held-out is held-out, whatever
# its date layout. Sprint 117 wrote `tokens.sprint117-heldout-...-2024-01-2025-06-
# tokenize.pt`, a shape no dated pattern matched.
HELDOUT_NAME_MARK = "heldout"


class HeldoutReadRefused(RuntimeError):
    """Raised when guard_heldout_parquet refuses a read without an acknowledgment."""


class UnrecognizedArtifactShape(RuntimeError):
    """Sprint 081: raised when the filename matches no known dated-artifact
    pattern. Prevents silent bypass when a new pipeline stage introduces a
    shape the guard has never seen. Callers that legitimately open non-artifact
    files pass `allow_unrecognized=True` to opt out.
    """


def parquet_range_starts_in_heldout(
    path: Path,
    *,
    allow_unrecognized: bool = False,
) -> bool:
    """True iff `path`'s filename matches a known dated-artifact pattern and
    the leading year is >= `HELDOUT_START_YEAR`.

    Sprint 081: raises `UnrecognizedArtifactShape` when `path.name` matches
    no pattern in `KNOWN_DATED_PATTERNS` and `allow_unrecognized=False`.
    Pass `allow_unrecognized=True` to fall back to the pre-Sprint-081
    "unknown shape = not heldout" behavior — legitimate for callers that
    invoke the guard on scratch or non-artifact files.

    Sprint 119: checks the symlink target's name as well as the link's own
    name. `data/tokenized/tokens.latest.pt` is a symlink; after Sprint 117 it
    pointed at the held-out tokens while its own name matched no pattern.
    """
    names = [path.name]
    if path.is_symlink():
        names.append(path.resolve().name)
    if any(HELDOUT_NAME_MARK in name for name in names):
        return True
    for name in names:
        for pattern in KNOWN_DATED_PATTERNS:
            match = pattern.match(name)
            if match is None:
                continue
            year = int(match.group(1))
            return year >= HELDOUT_START_YEAR
    if allow_unrecognized:
        return False
    raise UnrecognizedArtifactShape(
        f"heldout_guard: filename {path.name!r} matches no known dated-artifact "
        f"pattern (known patterns: {[p.pattern for p in KNOWN_DATED_PATTERNS]}). "
        "Register a new pattern in KNOWN_DATED_PATTERNS if this is a new "
        "pipeline artifact class, or pass allow_unrecognized=True if this is a "
        "scratch / non-artifact file."
    )


def guard_heldout_parquet(
    path: Path,
    *,
    allow_test_look: bool = False,
    allow_unrecognized: bool = False,
) -> None:
    """Raise HeldoutReadRefused if `path` is held-out and `allow_test_look` is False.

    Callers that legitimately need held-out access (Sprint 088 first held-out
    evaluation, drift diagnostic against test window, etc.) pass
    `allow_test_look=True` after registering the look via
    `price_space_llm.testlook.register_test_look`. The guard does not check
    the log itself — that is the caller's contract.

    Sprint 081: `allow_unrecognized=True` passes through to
    `parquet_range_starts_in_heldout` for callers that legitimately open
    non-artifact files.
    """
    if not parquet_range_starts_in_heldout(path, allow_unrecognized=allow_unrecognized):
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
    "HELDOUT_NAME_MARK",
    "HELDOUT_START_YEAR",
    "KNOWN_DATED_PATTERNS",
    "HeldoutReadRefused",
    "UnrecognizedArtifactShape",
    "guard_heldout_parquet",
    "parquet_range_starts_in_heldout",
]
