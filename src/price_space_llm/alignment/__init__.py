"""Alignment pipeline — tech-arch §4.3 join_asof on `known_at`.

Reads cached raw Alpha-Vantage responses, normalises bars to UTC with
`known_at` per Sprint 024's convention, builds a fixed 15-min UTC RTH
grid over the requested date range, and joins each channel's bars into
the grid with `strategy="backward"` — the alignment invariant that every
downstream feature depends on.

Emits `ALIGNMENT_RUN_STARTED` at open, one `ALIGNMENT_ROW_EMITTED` per
grid row, one `AS_OF_JOIN_MISS` per (channel, grid_ts) with no prior
observation, and `ALIGNMENT_RUN_COMPLETED` at close.
"""

from price_space_llm.alignment.join import (
    AlignmentResult,
    build_rth_grid,
    enumerate_months,
    load_channel_bars,
    load_index_daily_bars,
    load_macro_bars,
    run_alignment,
)

__all__ = [
    "AlignmentResult",
    "build_rth_grid",
    "enumerate_months",
    "load_channel_bars",
    "load_index_daily_bars",
    "load_macro_bars",
    "run_alignment",
]
