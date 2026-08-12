"""Property-based tests for the alignment invariant (tech-arch §17).

The `join_asof(strategy="backward")` invariant is the load-bearing gate
for the whole system: at grid time T, no joined observation may have
`known_at > T`. Look-ahead leakage is impossible by construction --
unit tests hand-picked three timestamps; Hypothesis walks the input
space and finds any counter-example.
"""

from datetime import UTC, datetime, timedelta

import polars as pl
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from price_space_llm.alignment.join import align_channels
from price_space_llm.signals import StrictSignalEmitter, load_vocabulary

# Bound the search space to keep property tests fast and Polars-safe.
# 2020-2025 window; second-precision timestamps.
MIN_TS = datetime(2020, 1, 1, tzinfo=UTC)
MAX_TS = datetime(2025, 12, 31, tzinfo=UTC)


def _timestamps() -> st.SearchStrategy[datetime]:
    return st.datetimes(
        min_value=MIN_TS.replace(tzinfo=None), max_value=MAX_TS.replace(tzinfo=None)
    ).map(lambda dt: dt.replace(tzinfo=UTC))


def _sorted_unique_timestamps(n: int) -> st.SearchStrategy[list[datetime]]:
    """Return `n` distinct sorted UTC datetimes within the search window."""
    return (
        st.sets(_timestamps(), min_size=n, max_size=n).map(sorted).filter(lambda xs: len(xs) == n)
    )


def _emitter() -> StrictSignalEmitter:
    return StrictSignalEmitter(load_vocabulary(), max_buffer=8192)


@given(
    grid_times=_sorted_unique_timestamps(20),
    bar_times=_sorted_unique_timestamps(15),
    bar_closes=st.lists(
        st.floats(min_value=1.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
        min_size=15,
        max_size=15,
    ),
)
@settings(
    max_examples=200,
    deadline=timedelta(seconds=5),
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.filter_too_much],
)
def test_backward_join_never_leaks_future_data(
    grid_times: list[datetime],
    bar_times: list[datetime],
    bar_closes: list[float],
) -> None:
    """No joined row has `known_at > grid_ts`. 200 random shapes; alignment invariant."""
    grid = pl.DataFrame({"grid_ts": grid_times})
    bars = pl.DataFrame(
        {
            "known_at": bar_times,
            "close": bar_closes,
            "channel": ["target"] * len(bar_times),
            "symbol": ["SPY"] * len(bar_times),
        }
    )
    aligned = align_channels(grid, {"target__SPY": bars}, _emitter())

    grid_ts_col = aligned["grid_ts"].to_list()
    known_at_col = aligned["target__SPY__known_at"].to_list()
    close_col = aligned["target__SPY__close"].to_list()

    for grid_ts, known_at, close in zip(grid_ts_col, known_at_col, close_col, strict=True):
        if close is None:
            # No prior observation exists for this grid time; known_at must also be null.
            assert known_at is None, f"grid={grid_ts}: close is null but known_at={known_at} is not"
            continue
        assert known_at is not None
        assert known_at <= grid_ts, (
            f"LEAKAGE: grid_ts={grid_ts} received data known at {known_at} "
            f"(future by {(known_at - grid_ts).total_seconds():.3f}s)"
        )


@given(
    grid_times=_sorted_unique_timestamps(10),
    bar_times=_sorted_unique_timestamps(10),
    bar_closes=st.lists(
        st.floats(min_value=1.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
        min_size=10,
        max_size=10,
    ),
)
@settings(
    max_examples=100,
    deadline=timedelta(seconds=5),
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.filter_too_much],
)
def test_backward_join_picks_latest_prior(
    grid_times: list[datetime],
    bar_times: list[datetime],
    bar_closes: list[float],
) -> None:
    """When `close` is non-null, its `known_at` equals the max bar-time <= grid_ts."""
    grid = pl.DataFrame({"grid_ts": grid_times})
    bars = pl.DataFrame(
        {
            "known_at": bar_times,
            "close": bar_closes,
            "channel": ["target"] * len(bar_times),
            "symbol": ["SPY"] * len(bar_times),
        }
    )
    aligned = align_channels(grid, {"target__SPY": bars}, _emitter())

    for grid_ts, known_at in zip(
        aligned["grid_ts"].to_list(),
        aligned["target__SPY__known_at"].to_list(),
        strict=True,
    ):
        if known_at is None:
            # No bar had known_at <= grid_ts; the earliest bar must be after grid_ts.
            assert bar_times[0] > grid_ts
            continue
        expected = max(t for t in bar_times if t <= grid_ts)
        assert known_at == expected, (
            f"grid_ts={grid_ts}: expected latest-prior={expected}, got {known_at}"
        )
