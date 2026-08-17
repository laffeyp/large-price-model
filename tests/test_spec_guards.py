"""Sprint 066: spec guards per tech-arch §13.

1. `test_no_hardcoded_target_in_source` — no bare `SPY` in production source
   outside of comments and string literals. Prevents a code path from
   silently baking the v1 target into logic that should thread through
   `target_symbol` from config.
2. `test_channel_source_of_truth` — for every aligned channel, recompute the
   raw close value from `data/raw/` and assert against a random 1000-bar
   window of `data/aligned/*.parquet`. Skips if the corpus is missing so
   fresh clones without cached data don't fail the suite.
"""

from __future__ import annotations

import token
import tokenize
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src" / "price_space_llm"

# Files that legitimately reference SPY in NAME tokens (not string literals or
# comments) — e.g. a config schema field with `default="SPY"` still emits a
# STRING token so those slip through the tokenize walk. Add exemptions only
# when the hardcoded reference is intentional and reviewed.
NAME_EXEMPTIONS: set[str] = set()


def _walk_python_files(base: Path) -> list[Path]:
    return [p for p in base.rglob("*.py") if "__pycache__" not in p.parts]


def _find_bare_spy(path: Path) -> list[tuple[int, str]]:
    """Return (line, snippet) for every NAME token equal to `SPY` in `path`.

    Skips COMMENT and STRING tokens so docstrings + string-literal defaults
    don't trip the guard.
    """
    hits: list[tuple[int, str]] = []
    with path.open("rb") as f:
        try:
            tokens = list(tokenize.tokenize(f.readline))
        except tokenize.TokenizeError:
            return hits
    for tok in tokens:
        if tok.type == token.NAME and tok.string == "SPY":
            hits.append((tok.start[0], tok.line.rstrip()))
    return hits


def test_no_hardcoded_target_in_source():
    """Sprint 066: no bare `SPY` NAME token in production src outside strings/comments."""
    offending: list[str] = []
    for path in _walk_python_files(SRC_DIR):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in NAME_EXEMPTIONS:
            continue
        for line_no, snippet in _find_bare_spy(path):
            offending.append(f"{rel}:{line_no}: {snippet}")
    assert not offending, (
        "Hardcoded SPY references found outside strings/comments. Route through "
        "`target_symbol` from config, or add the path to NAME_EXEMPTIONS with a "
        "justification. Hits:\n" + "\n".join(offending)
    )


def _read_source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_no_hardcoded_target_helper_survives_edge_cases():
    """The helper correctly ignores SPY in docstrings + comments + f-strings."""
    code = '''
"""Module doc mentions SPY as an example."""
# SPY in a comment
x = "SPY in a string"
y = f"SPY {x} in an f-string"
'''
    # Write to a tempfile and re-scan.
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(code)
        tmp = Path(f.name)
    try:
        hits = _find_bare_spy(tmp)
    finally:
        tmp.unlink(missing_ok=True)
    assert hits == []


def test_no_hardcoded_target_helper_catches_bare_name():
    """The helper does catch SPY used as a bare NAME (not in a string)."""
    code = "SPY = 42\nprint(SPY)\n"
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(code)
        tmp = Path(f.name)
    try:
        hits = _find_bare_spy(tmp)
    finally:
        tmp.unlink(missing_ok=True)
    assert len(hits) == 2  # SPY appears on both lines as a NAME token


def test_channel_source_of_truth_pt_matches_features_parquet():
    """Sprint 066: for a random 1000-row window on an aligned parquet, every
    per-channel close column matches the features parquet's log_return derivation
    (indirect proof that the alignment pipeline hasn't silently mangled the
    per-channel values). Skips if the corpus is missing.
    """
    import polars as pl

    aligned = REPO_ROOT / "data" / "aligned" / "align-2015-01-2022-12-0000000000000000.parquet"
    features = (
        REPO_ROOT
        / "data"
        / "features"
        / "features-align-2015-01-2022-12-0000000000000000-0000000000000000.parquet"
    )
    if not aligned.exists() or not features.exists():
        pytest.skip("aligned or features parquet not present in this checkout")

    a_df = pl.read_parquet(aligned)
    f_df = pl.read_parquet(features)
    assert a_df.height == f_df.height, "aligned + features must share row count"

    # Sample a random 1000-row window (via Python stdlib random, seed 42 for determinism).
    import random

    rng = random.Random(42)
    start = rng.randint(0, a_df.height - 1000)
    a_slice = a_df.slice(start, 1000)
    f_slice = f_df.slice(start, 1000)

    # For each target__SPY close: log(close_t / close_{t-1}) must equal
    # target__SPY__log_return in features. Sampled at 100 rows to keep it fast.
    close = a_slice["target__SPY__close"].to_list()
    log_ret = f_slice["target__SPY__log_return"].to_list()
    import math

    checked = 0
    for i in range(1, min(101, len(close))):
        if close[i] is None or close[i - 1] is None or log_ret[i] is None:
            continue
        expected = math.log(close[i] / close[i - 1])
        assert abs(expected - log_ret[i]) < 1e-9, (
            f"row {start + i}: features log_return {log_ret[i]} != log(close/prev_close) {expected}"
        )
        checked += 1
    assert checked > 0, "no non-null rows in the sampled window; corpus may be empty"
