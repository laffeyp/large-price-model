"""Unit tests for the probability-forecast metrics."""

import math

import pytest
import torch
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from price_space_llm.evaluation.metrics import (
    compute_brier,
    compute_bucket_frequency_drift,
    compute_dir_acc,
    compute_ece,
    compute_metric_set,
    compute_nll,
    compute_rps,
    compute_top_k,
)


def _uniform(n: int, v: int) -> torch.Tensor:
    return torch.full((n, v), 1.0 / v)


def _one_hot_pred(preds: list[int], v: int) -> torch.Tensor:
    n = len(preds)
    out = torch.zeros((n, v))
    for i, p in enumerate(preds):
        out[i, p] = 1.0
    return out


# nll ---------------------------------------------------------------------


def test_nll_of_uniform_predictions_equals_log_v():
    v = 32
    probs = _uniform(100, v)
    targets = torch.zeros(100, dtype=torch.long)
    nll = compute_nll(probs, targets)
    assert nll == pytest.approx(math.log(v), abs=1e-6)


def test_nll_of_perfect_predictions_is_near_zero():
    v = 8
    preds = [0, 1, 2, 3, 0, 1, 2, 3]
    probs = _one_hot_pred(preds, v)
    targets = torch.tensor(preds, dtype=torch.long)
    nll = compute_nll(probs, targets)
    # Perfect one-hot yields ~0 after eps clamp.
    assert nll < 1e-8


def test_nll_handles_empty_input():
    assert compute_nll(torch.zeros((0, 8)), torch.zeros((0,), dtype=torch.long)) == 0.0


# top-k -------------------------------------------------------------------


def test_top1_of_perfect_predictions_is_one():
    v = 8
    preds = [0, 1, 2]
    probs = _one_hot_pred(preds, v)
    targets = torch.tensor(preds, dtype=torch.long)
    assert compute_top_k(probs, targets, 1) == 1.0


def test_top3_includes_true_class_when_in_top3():
    probs = torch.tensor(
        [
            # target=0. Top-3 are indices 5, 4, 0. → hit.
            [0.15, 0.05, 0.05, 0.05, 0.20, 0.30, 0.10, 0.10],
        ]
    )
    targets = torch.tensor([0])
    assert compute_top_k(probs, targets, 3) == 1.0


def test_top3_misses_when_target_is_not_top3():
    probs = torch.tensor(
        [
            # target=0 has 5th-highest probability → miss.
            [0.05, 0.20, 0.20, 0.20, 0.20, 0.10, 0.05, 0.00],
        ]
    )
    targets = torch.tensor([0])
    assert compute_top_k(probs, targets, 3) == 0.0


# dir_acc -----------------------------------------------------------------


def test_dir_acc_matches_when_argmax_and_target_share_half():
    v = 4  # threshold = 2. buckets {0, 1} = down; {2, 3} = up.
    probs = _one_hot_pred([3, 0, 2, 1], v)
    targets = torch.tensor([3, 0, 3, 0])  # both up-up, down-down, up-up, down-down
    assert compute_dir_acc(probs, targets, v) == 1.0


def test_dir_acc_mismatches_when_sides_differ():
    v = 4
    probs = _one_hot_pred([3, 0], v)  # pred up, pred down
    targets = torch.tensor([0, 3])  # target down, target up → both mismatch
    assert compute_dir_acc(probs, targets, v) == 0.0


# brier -------------------------------------------------------------------


def test_brier_of_perfect_predictions_is_zero():
    v = 4
    probs = _one_hot_pred([0, 1, 2], v)
    targets = torch.tensor([0, 1, 2])
    assert compute_brier(probs, targets) == pytest.approx(0.0, abs=1e-8)


def test_brier_of_uniform_predictions_matches_formula():
    v = 4
    probs = _uniform(1, v)
    targets = torch.tensor([0])
    # (1 - 1/4)^2 + 3 * (0 - 1/4)^2 = 9/16 + 3/16 = 12/16 = 0.75
    assert compute_brier(probs, targets) == pytest.approx(0.75, abs=1e-6)


# rps ---------------------------------------------------------------------


def test_rps_of_perfect_predictions_is_zero():
    v = 4
    probs = _one_hot_pred([0, 1, 2], v)
    targets = torch.tensor([0, 1, 2])
    assert compute_rps(probs, targets) == pytest.approx(0.0, abs=1e-8)


def test_rps_penalizes_predictions_far_from_target():
    v = 4
    # Predict bucket 0 with certainty when target is bucket 3 -- CDF diverges maximally.
    probs = _one_hot_pred([0], v)
    targets = torch.tensor([3])
    high = compute_rps(probs, targets)
    # Predict bucket 2 (adjacent to 3) -- CDF closer.
    probs2 = _one_hot_pred([2], v)
    low = compute_rps(probs2, targets)
    assert high > low


# ece ---------------------------------------------------------------------


def test_ece_of_perfectly_calibrated_high_confidence_is_zero():
    """Perfect confidence + accuracy both 1.0 in the top bin: ECE = 0."""
    v = 4
    preds = [0, 1, 2, 3, 0, 1, 2, 3]
    probs = _one_hot_pred(preds, v)
    targets = torch.tensor(preds)
    assert compute_ece(probs, targets, n_bins=10) == pytest.approx(0.0, abs=1e-8)


def test_ece_reports_gap_when_confident_but_wrong():
    v = 4
    # High-confidence but always wrong: confidence 1, accuracy 0, ECE approx 1.
    probs = _one_hot_pred([0, 0, 0, 0], v)
    targets = torch.tensor([1, 1, 1, 1])
    ece = compute_ece(probs, targets, n_bins=10)
    assert ece > 0.9


# metric_set --------------------------------------------------------------


def test_metric_set_returns_all_seven_metrics():
    v = 8
    probs = _uniform(50, v)
    targets = torch.randint(0, v, (50,))
    ms = compute_metric_set(probs, targets, v)
    for f in ("nll", "ece", "brier", "rps", "dir_acc", "top1", "top3"):
        assert getattr(ms, f) is not None
    assert ms.n_examples == 50


# bucket-frequency drift --------------------------------------------------


def test_drift_of_identical_distributions_has_zero_deviation():
    train = [0, 1, 2, 3] * 10
    val = [0, 1, 2, 3] * 5
    _, _, dev, ratio = compute_bucket_frequency_drift(train, val, vocab_size=4)
    assert dev == pytest.approx(0.0, abs=1e-9)
    assert ratio == pytest.approx(1.0, abs=1e-9)


def test_drift_deviation_flags_tail_shift():
    v = 4
    train = [1, 2] * 10  # zero tail mass
    val = [0, 3] * 5  # all tail mass
    _, _, dev, ratio = compute_bucket_frequency_drift(train, val, vocab_size=v)
    assert dev == pytest.approx(0.5, abs=1e-9)
    assert ratio == 0.0  # train tails are zero → ratio explicitly 0.0


# Property-based ----------------------------------------------------------


@given(
    v=st.integers(min_value=2, max_value=32),
    n=st.integers(min_value=1, max_value=100),
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_top1_bounded_between_zero_and_one(v: int, n: int) -> None:
    probs = torch.rand(n, v)
    probs = probs / probs.sum(dim=-1, keepdim=True)  # normalise
    targets = torch.randint(0, v, (n,))
    assert 0.0 <= compute_top_k(probs, targets, 1) <= 1.0


@given(
    v=st.integers(min_value=2, max_value=32),
    n=st.integers(min_value=1, max_value=100),
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_brier_non_negative(v: int, n: int) -> None:
    probs = torch.rand(n, v)
    probs = probs / probs.sum(dim=-1, keepdim=True)
    targets = torch.randint(0, v, (n,))
    assert compute_brier(probs, targets) >= 0.0
