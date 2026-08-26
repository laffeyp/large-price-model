"""Sprint 094: decision policy — variance, edge, hysteresis, DECISION_MADE + SIGNAL_DROPPED."""

from __future__ import annotations

import pytest
import torch

from price_space_llm.signals import StrictSignalEmitter, load_vocabulary
from price_space_llm.simulation import (
    PolicyConfig,
    compute_edge,
    decide,
    variance_vn,
)


def _fresh_emitter(max_buffer: int = 16384) -> StrictSignalEmitter:
    return StrictSignalEmitter(load_vocabulary(), max_buffer=max_buffer)


# --- variance_vn -----------------------------------------------------------


def test_variance_vn_uniform_symmetric_returns_second_moment():
    """Uniform on symmetric means -> variance = mean(means²) (first moment is 0)."""
    probs = torch.full((4,), 0.25)
    means = torch.tensor([-1.0, -0.5, 0.5, 1.0])
    v = variance_vn(probs, means)
    # E[X] = 0; E[X²] = (1 + 0.25 + 0.25 + 1) / 4 = 0.625.
    assert v == pytest.approx(0.625, abs=1e-6)


def test_variance_vn_confident_zero_variance():
    """Point mass -> 0 variance."""
    probs = torch.tensor([0.0, 0.0, 1.0, 0.0])
    means = torch.tensor([-1.0, -0.5, 0.5, 1.0])
    assert variance_vn(probs, means) == pytest.approx(0.0, abs=1e-12)


def test_variance_vn_ignores_nan_train_means():
    """NaN train_means contribute zero to both moments."""
    probs = torch.tensor([0.25, 0.25, 0.25, 0.25])
    means = torch.tensor([-1.0, float("nan"), 0.5, 1.0])
    # E[X] with NaN->0: (-1 + 0 + 0.5 + 1)/4 = 0.125.
    # E[X²]: (1 + 0 + 0.25 + 1)/4 = 0.5625.
    # var = 0.5625 - 0.125² = 0.546875.
    assert variance_vn(probs, means) == pytest.approx(0.546875, abs=1e-6)


def test_variance_vn_rejects_shape_mismatch():
    with pytest.raises(ValueError, match="len"):
        variance_vn(torch.tensor([0.5, 0.5]), torch.tensor([-1.0, 0.0, 1.0]))


# --- compute_edge ----------------------------------------------------------


def test_compute_edge_reduces_to_expected_vn_when_costs_zero():
    edge = compute_edge(
        expected_vn_return=0.42,
        variance_vn_value=0.5,
        realized_vol=0.01,
        spread_cost_frac=0.0,
        slippage_frac=0.0,
        lambda_risk=0.0,
    )
    assert edge == pytest.approx(0.42)


def test_compute_edge_subtracts_cost_over_vol():
    """cost 5 bps * vol 0.01 -> 0.05 vn-units subtracted."""
    edge = compute_edge(
        expected_vn_return=1.0,
        variance_vn_value=0.0,
        realized_vol=0.01,
        spread_cost_frac=0.0005,
        slippage_frac=0.0,
        lambda_risk=0.0,
    )
    assert edge == pytest.approx(1.0 - 0.05)


def test_compute_edge_subtracts_risk_penalty():
    edge = compute_edge(
        expected_vn_return=1.0,
        variance_vn_value=0.5,
        realized_vol=0.01,
        spread_cost_frac=0.0,
        slippage_frac=0.0,
        lambda_risk=2.0,
    )
    # penalty = 2.0 * 0.5 = 1.0; edge = 1 - 1 = 0.
    assert edge == pytest.approx(0.0)


def test_compute_edge_rejects_zero_vol():
    with pytest.raises(ValueError, match="realized_vol"):
        compute_edge(0.1, 0.0, 0.0, 0.0001, 0.0, 0.0)


# --- decide ----------------------------------------------------------------


def _base_policy(threshold: float = 0.1, hysteresis: float = 0.5) -> PolicyConfig:
    return PolicyConfig(
        threshold=threshold,
        hysteresis=hysteresis,
        lambda_risk=0.0,
        spread_cost_frac=0.0,
        slippage_frac=0.0,
        position_size_usd=1_000_000.0,
    )


def test_decide_flat_below_threshold():
    d, dropped = decide("flat", 0.05, _base_policy())
    assert d.direction == "flat"
    assert d.size == 0.0
    assert d.reason == "hysteresis_hold"  # flat->flat carries the below-threshold reason
    assert dropped is False


def test_decide_long_above_threshold():
    d, dropped = decide("flat", 0.5, _base_policy())
    assert d.direction == "long"
    assert d.size == 1_000_000.0
    assert d.reason == "edge_above_threshold"
    assert dropped is False


def test_decide_short_below_threshold():
    d, dropped = decide("flat", -0.5, _base_policy())
    assert d.direction == "short"
    assert d.size == -1_000_000.0
    assert d.reason == "edge_below_threshold"
    assert dropped is False


def test_decide_position_held_on_same_direction():
    d, dropped = decide("long", 0.5, _base_policy())
    assert d.direction == "long"
    assert d.reason == "position_held"
    assert dropped is False


def test_decide_hysteresis_hold_between_threshold_and_flip_boundary():
    """prev long, edge = -0.11, threshold 0.1, hysteresis 0.5 -> flip threshold 0.15.

    |edge| = 0.11 < 0.15 -> hold long; drop signal.
    """
    d, dropped = decide("long", -0.11, _base_policy(threshold=0.1, hysteresis=0.5))
    assert d.direction == "long"
    assert d.reason == "hysteresis_hold"
    assert d.effective_threshold == pytest.approx(0.15)
    assert dropped is True


def test_decide_flip_when_edge_above_effective_threshold():
    """prev long, edge = -0.2, threshold 0.1, hysteresis 0.5 -> flip threshold 0.15; 0.2 > 0.15."""
    d, dropped = decide("long", -0.2, _base_policy(threshold=0.1, hysteresis=0.5))
    assert d.direction == "short"
    assert d.reason == "edge_below_threshold"
    assert dropped is False


def test_decide_rejects_unknown_prev_direction():
    with pytest.raises(ValueError, match="prev_direction"):
        decide("sideways", 0.5, _base_policy())
