"""Sprint 091: Corwin-Schultz proportional-spread estimator + 2024 bias correction."""

from __future__ import annotations

import math

import pytest

from price_space_llm.cost_calibration import (
    BiasCorrection,
    apply_bias_correction,
    corwin_schultz_spread,
    fit_bias_correction,
)


def test_corwin_schultz_shape_and_length():
    """Output length is N-1 for input length N."""
    highs = [100.0, 101.0, 102.0, 103.0]
    lows = [99.5, 100.5, 101.5, 102.5]
    out = corwin_schultz_spread(highs, lows)
    assert len(out) == len(highs) - 1


def test_corwin_schultz_rejects_length_mismatch():
    with pytest.raises(ValueError, match="same length"):
        corwin_schultz_spread([1.0, 2.0], [1.0])


def test_corwin_schultz_returns_empty_on_single_bar():
    """One bar cannot form a two-bar pair."""
    assert corwin_schultz_spread([100.0], [99.0]) == []


def test_corwin_schultz_nan_on_non_positive_price():
    """Zero or negative H/L propagates NaN, not a math error."""
    out = corwin_schultz_spread([100.0, 0.0, 102.0], [99.5, 0.0, 101.5])
    # Pair (bar 0, bar 1): bar 1 has H=0 → NaN.
    # Pair (bar 1, bar 2): bar 1 has H=0 → NaN.
    assert all(math.isnan(v) for v in out)


def test_corwin_schultz_returns_nan_on_negative_alpha_boundary():
    """Two identical bars with H=L produce beta=0 gamma=0 alpha=0 → S=0 (boundary).

    The paper's boundary is alpha<0, not alpha==0; alpha==0 → S = 2*(exp(0)-1)/(1+exp(0)) = 0.
    """
    out = corwin_schultz_spread([100.0, 100.0], [100.0, 100.0])
    assert len(out) == 1
    # beta=gamma=0 → alpha = 0 - 0 = 0 → S = 0.
    assert out[0] == pytest.approx(0.0, abs=1e-12)


def test_corwin_schultz_positive_estimate_on_realistic_bar_pair():
    """A synthetic pair with a plausible 15-min-bar spread produces a positive estimate."""
    # SPY-like bars around $400 with ~15-bp range each and a small overnight gap.
    highs = [400.60, 400.75]
    lows = [400.20, 400.35]
    out = corwin_schultz_spread(highs, lows)
    assert len(out) == 1
    s = out[0]
    assert not math.isnan(s)
    assert s > 0.0
    # Sanity: CS on 15-min bars sits well under 100 bps for a liquid ETF.
    assert s < 0.01


def test_fit_bias_correction_ratio_math():
    """ratio = mean(known) / mean(estimated) over finite entries."""
    known = [0.001, 0.001, 0.001]  # mean 0.001
    estimated = [0.0005, 0.0005, 0.0005]  # mean 0.0005
    correction = fit_bias_correction(known, estimated, provenance="test")
    assert correction.ratio == pytest.approx(2.0)
    assert correction.n_known == 3
    assert correction.n_estimated == 3
    assert correction.provenance == "test"


def test_fit_bias_correction_ignores_nan_entries():
    """NaN entries drop from each series' mean independently."""
    known = [0.002, float("nan"), 0.002]
    estimated = [0.001, 0.001, float("nan")]
    correction = fit_bias_correction(known, estimated, provenance="test-nan")
    assert correction.ratio == pytest.approx(2.0)
    assert correction.n_known == 2
    assert correction.n_estimated == 2


def test_fit_bias_correction_rejects_non_positive_estimated_mean():
    with pytest.raises(ValueError, match="non-positive"):
        fit_bias_correction([0.001], [0.0], provenance="bad")


def test_fit_bias_correction_rejects_all_nan_series():
    with pytest.raises(ValueError, match="no finite values"):
        fit_bias_correction([float("nan")], [0.001], provenance="bad")


def test_apply_bias_correction_scalar_multiply():
    """Elementwise multiply; NaN entries pass through."""
    correction = BiasCorrection(
        ratio=2.0, n_known=1, n_estimated=1, provenance="test"
    )
    out = apply_bias_correction([0.001, float("nan"), 0.003], correction)
    assert out[0] == pytest.approx(0.002)
    assert math.isnan(out[1])
    assert out[2] == pytest.approx(0.006)
