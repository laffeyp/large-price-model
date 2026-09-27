"""Sprint 093: derive_prediction_scalars math. Walker tests deleted in Sprint 105 (dead code)."""

from __future__ import annotations

import math

import pytest
import torch

from price_space_llm.simulation import derive_prediction_scalars

# --- derive_prediction_scalars ------------------------------------------------


def test_derive_prediction_scalars_uniform_distribution():
    """Uniform probs over V=4 symmetric means.

    Expect EV=0, EV_vn=0, p_up=0.5, entropy=log(4), sharpness=0.
    """
    probs = torch.full((4,), 0.25)
    means = torch.tensor([-1.0, -0.5, 0.5, 1.0])
    s = derive_prediction_scalars(probs, means, realized_vol=0.01)
    assert s.expected_return == pytest.approx(0.0, abs=1e-6)
    assert s.expected_vn_return == pytest.approx(0.0, abs=1e-6)
    assert s.p_up == pytest.approx(0.5, abs=1e-6)
    assert s.entropy == pytest.approx(math.log(4), rel=1e-5)
    assert s.sharpness == pytest.approx(0.0, abs=1e-6)


def test_derive_prediction_scalars_confident_up():
    """Point-mass on the top bucket → EV = top_mean, EV_vn = top_mean / vol."""
    probs = torch.tensor([0.0, 0.0, 0.0, 1.0])
    means = torch.tensor([-1.0, -0.5, 0.5, 1.0])
    s = derive_prediction_scalars(probs, means, realized_vol=0.02)
    assert s.expected_return == pytest.approx(1.0, abs=1e-6)
    assert s.expected_vn_return == pytest.approx(50.0, abs=1e-4)
    assert s.p_up == pytest.approx(1.0, abs=1e-6)
    assert s.entropy == pytest.approx(0.0, abs=1e-6)
    assert s.sharpness == pytest.approx(1.0, abs=1e-6)


def test_derive_prediction_scalars_vn_is_raw_over_vol():
    """expected_vn_return = expected_return / realized_vol; expected_return invariant to vol."""
    probs = torch.tensor([0.0, 0.0, 1.0, 0.0])
    means = torch.tensor([-1.0, -0.5, 0.5, 1.0])
    s_low = derive_prediction_scalars(probs, means, realized_vol=0.01)
    s_high = derive_prediction_scalars(probs, means, realized_vol=0.05)
    assert s_low.expected_return == pytest.approx(0.5)
    assert s_high.expected_return == pytest.approx(0.5)
    assert s_low.expected_vn_return == pytest.approx(50.0)
    assert s_high.expected_vn_return == pytest.approx(10.0)


def test_derive_prediction_scalars_p_up_matches_upper_half_mass():
    """Asymmetric distribution; p_up sums buckets V//2..V-1."""
    probs = torch.tensor([0.1, 0.2, 0.3, 0.4])
    means = torch.tensor([-1.0, -0.5, 0.5, 1.0])
    s = derive_prediction_scalars(probs, means, realized_vol=0.01)
    assert s.p_up == pytest.approx(0.7)  # 0.3 + 0.4


def test_derive_prediction_scalars_nan_train_mean_contributes_zero():
    """A NaN bucket_train_mean (empty bucket) contributes zero to the expected value."""
    probs = torch.tensor([0.25, 0.25, 0.25, 0.25])
    means = torch.tensor([-1.0, float("nan"), 0.5, 1.0])
    s = derive_prediction_scalars(probs, means, realized_vol=0.01)
    # sum: 0.25*(-1) + 0.25*0 + 0.25*0.5 + 0.25*1 = 0.125
    assert s.expected_return == pytest.approx(0.125)
    assert s.expected_vn_return == pytest.approx(12.5)


def test_derive_prediction_scalars_rejects_nonpositive_vol():
    probs = torch.tensor([0.25, 0.25, 0.25, 0.25])
    means = torch.tensor([-1.0, -0.5, 0.5, 1.0])
    with pytest.raises(ValueError, match="realized_vol"):
        derive_prediction_scalars(probs, means, realized_vol=0.0)


def test_derive_prediction_scalars_rejects_shape_mismatch():
    probs = torch.tensor([0.5, 0.5])
    means = torch.tensor([-1.0, 0.5, 1.0])
    with pytest.raises(ValueError, match="len"):
        derive_prediction_scalars(probs, means, realized_vol=0.01)
