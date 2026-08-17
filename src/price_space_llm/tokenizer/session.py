"""Session flags — cyclic time-of-day + day-of-week + first-bar-of-session.

Product-spec § Channels session flags:
- `is_overnight_gap` — True on the first RTH bar of each trading day.
- `minute_of_day` — encoded as (sin, cos) so the model sees a continuous cyclic
  representation of intraday phase.
- `day_of_week` — encoded as (sin, cos) same way for weekly cycle.

Sprint 062 computes all three at tokenizer time from `timestamps: Tensor[T]`
of UTC Unix seconds (Sprint 052 field). No new alignment run or feature parquet
regen required — session state is purely a function of grid_ts, not of any
channel's data.

`is_overnight_gap` uses inter-bar deltas: if the gap between successive
timestamps exceeds one 15-min bar, this row is the first bar of a new session.
Timezone-agnostic; no need to convert to US/Eastern.
"""

from __future__ import annotations

import math

import numpy as np
import torch
from torch import Tensor

# 15-min RTH grid: 26 bars per day, 5 weekdays.
BAR_SECONDS = 15 * 60
MINUTES_PER_RTH_DAY = 26 * 15  # 09:45 through 16:00 = 390 minutes = 26 bars of 15 min.


def compute_session_features(
    timestamps: Tensor,
) -> tuple[Tensor, Tensor]:
    """Return (session_features, is_overnight_gap) from `timestamps: Tensor[T]` int64.

    session_features shape: `[T, 4]` — columns
    `[minute_of_day_sin, minute_of_day_cos, day_of_week_sin, day_of_week_cos]`.
    is_overnight_gap shape: `[T]` int8 — 1 on the first bar of a session, 0 elsewhere.

    Sprint 062. Every value is a pure function of the timestamp so this can be
    called any time after the tokenizer has a `timestamps` tensor.
    """
    ts_np: np.ndarray = timestamps.detach().cpu().numpy().astype(np.int64)
    t = ts_np.size

    # is_overnight_gap: True when the delta from the prior bar exceeds BAR_SECONDS.
    # Row 0 is treated as the first bar of its session (True).
    if t == 0:
        gaps_empty: np.ndarray = np.zeros(0, dtype=np.int8)
        feats_empty: np.ndarray = np.zeros((0, 4), dtype=np.float32)
        return torch.from_numpy(feats_empty), torch.from_numpy(gaps_empty)
    deltas = np.diff(ts_np)
    is_gap: np.ndarray = np.empty(t, dtype=np.int8)
    is_gap[0] = 1
    is_gap[1:] = (deltas > BAR_SECONDS).astype(np.int8)

    # minute_of_day in [0, 1440) → sin, cos over 2π*minute/1440.
    # day_of_week in {0..6} where Monday=0 → sin, cos over 2π*dow/7.
    seconds_of_day: np.ndarray = ts_np % 86_400
    minute_of_day: np.ndarray = seconds_of_day // 60
    dow: np.ndarray = (ts_np // 86_400 + 4) % 7
    # Unix epoch 1970-01-01 was Thursday; +4 shifts so Monday=0.

    two_pi = 2.0 * math.pi
    m_frac = minute_of_day.astype(np.float32) / 1440.0
    d_frac = dow.astype(np.float32) / 7.0
    feats = np.stack(
        [
            np.sin(two_pi * m_frac),
            np.cos(two_pi * m_frac),
            np.sin(two_pi * d_frac),
            np.cos(two_pi * d_frac),
        ],
        axis=1,
    ).astype(np.float32)

    return torch.from_numpy(feats), torch.from_numpy(is_gap)


__all__ = [
    "BAR_SECONDS",
    "MINUTES_PER_RTH_DAY",
    "compute_session_features",
]
