"""Regime labels: tercile split on realized volatility, frozen at fit time.

The v0.3 vocabulary describes RegimeLabel as "a VIX tercile tag (low /
mid / high) attached to a held-out bar, computed on the training window
and frozen." Sprint 032 substitutes VIX with `target__SPY__rolling_std_20`
because Sprint 023's probe dropped VIX (Alpha-Vantage refused
TIME_SERIES_INTRADAY on ^VIX). The vocabulary carries no field for
"which proxy" -- the substitution lives in this module docstring, the
Sprint 032 card, and the drift-watchlist. A real-VIX rerun replaces
the proxy when Databento (or similar) lands intraday VIX.
"""

from dataclasses import dataclass


@dataclass(slots=True, frozen=True, kw_only=True)
class RegimeThresholds:
    """Frozen tercile boundaries; low if x < low; mid if low <= x < mid; high otherwise."""

    low_threshold: float
    mid_threshold: float


def _quantile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        raise ValueError("cannot compute quantile of empty list")
    if q <= 0:
        return sorted_values[0]
    if q >= 1:
        return sorted_values[-1]
    idx = q * (len(sorted_values) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = idx - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def fit_regime_thresholds(train_volatility: list[float | None]) -> RegimeThresholds:
    """Compute 33rd/66th percentile on the non-null training volatility."""
    clean = sorted(v for v in train_volatility if v is not None)
    if len(clean) < 3:
        raise ValueError(f"need at least 3 non-null volatility values; got {len(clean)}")
    return RegimeThresholds(
        low_threshold=_quantile(clean, 1.0 / 3.0),
        mid_threshold=_quantile(clean, 2.0 / 3.0),
    )


def assign_regime(volatility: float | None, thresholds: RegimeThresholds) -> str:
    """Map one volatility value to 'low', 'mid', or 'high'. Nulls go to 'mid' by convention."""
    if volatility is None:
        return "mid"
    if volatility < thresholds.low_threshold:
        return "low"
    if volatility < thresholds.mid_threshold:
        return "mid"
    return "high"
