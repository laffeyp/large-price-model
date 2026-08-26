"""Sprint 094: decision policy — edge, variance, hysteresis, direction.

Per tech-arch § 11.4:

    edge = expected_vn_return
           - (spread_cost_frac + slippage_frac) / realized_vol
           - lambda_risk * variance_vn

Decision:
  - `|edge| < threshold` -> flat.
  - `edge > +threshold` (starting from a non-long state) -> intended long.
  - `edge < -threshold` (starting from a non-short state) -> intended short.
  - Same-direction re-entry: keep current direction with `reason="position_held"`.
    No signal drop — nothing was dropped, the previous direction continues.
  - Hysteresis: to flip direction, `|edge|` must exceed
    `threshold * (1 + hysteresis)`. If below the flip threshold, decision holds
    `prev_direction` with `reason="hysteresis_hold"`. The caller emits
    `SIGNAL_DROPPED(dropped_reason="hysteresis_below_flip_threshold")` in that
    branch.

Sprint 095 lands the position state machine + `POSITION_OPENED` +
`POSITION_CLOSED` + `TRADE_LEDGERED`; Sprint 094 tracks a scalar
`current_direction` across bars — direction only, no size/entry-price/P&L.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch

DIRECTIONS = ("long", "short", "flat")


@dataclass(slots=True, frozen=True, kw_only=True)
class PolicyConfig:
    """Simulator decision-rule knobs.

    `threshold` is the base flat->signal boundary in vol-normalized edge units.
    `hysteresis` widens the flip requirement: `|edge|` must exceed
    `threshold * (1 + hysteresis)` to flip an active direction. 0.0 disables
    hysteresis. `lambda_risk * variance_vn` is subtracted from edge as the
    risk penalty. `spread_cost_frac` + `slippage_frac` are dollar-fraction
    per trade; the edge formula divides them by `realized_vol` to get vn-units.
    `position_size_usd` is the signed size the DECISION_MADE payload reports.
    """

    threshold: float
    hysteresis: float
    lambda_risk: float
    spread_cost_frac: float
    slippage_frac: float
    position_size_usd: float


@dataclass(slots=True, frozen=True, kw_only=True)
class Decision:
    """DECISION_MADE payload shape (minus timestamp, which the emitter carries)."""

    direction: str  # ∈ DIRECTIONS
    size: float  # signed; +position_size_usd long, -position_size_usd short, 0 flat
    edge: float
    threshold: float
    effective_threshold: float
    reason: str  # ∈ {edge_above_threshold, edge_below_threshold, hysteresis_hold, position_held}


def variance_vn(probs: torch.Tensor, bucket_train_means: torch.Tensor) -> float:
    """Variance of the vol-normalized return under the softmax distribution.

    `Σ p_i * mean_i² - (Σ p_i * mean_i)²`. NaN train_means contribute zero
    to both moments (matching Sprint 093's `derive_prediction_scalars`).
    """
    if probs.ndim != 1:
        raise ValueError(f"probs must be 1-D; got shape {tuple(probs.shape)}")
    if probs.shape[0] != bucket_train_means.shape[0]:
        raise ValueError(
            f"probs len {probs.shape[0]} != bucket_train_means len {bucket_train_means.shape[0]}"
        )
    # Sprint 100 fix (review §6.4): softmax on NaN logits produces NaN probs
    # that silently poison every downstream sum. Fail loud instead.
    if bool(torch.isnan(probs).any()):
        raise ValueError(
            "variance_vn: probs contain NaN; upstream model produced NaN logits. "
            "Check the walker's per-bar forward pass for NaN inputs."
        )
    means_safe = torch.where(
        torch.isnan(bucket_train_means),
        torch.zeros_like(bucket_train_means),
        bucket_train_means,
    )
    first_moment = float((probs * means_safe).sum().item())
    second_moment = float((probs * means_safe * means_safe).sum().item())
    var = second_moment - first_moment * first_moment
    # Guard against tiny negative variance from floating-point noise on near-point-masses.
    return max(var, 0.0)


def compute_edge(
    expected_vn_return: float,
    variance_vn_value: float,
    realized_vol: float,
    spread_cost_frac: float,
    slippage_frac: float,
    lambda_risk: float,
) -> float:
    """Edge in vol-normalized units per tech-arch § 11.4.

    `realized_vol` must be strictly positive; a zero-vol bar cannot be
    normalized (the simulator should filter these out via the tokenizer's
    mask, but the guard fires here too).
    """
    if realized_vol <= 0.0 or not math.isfinite(realized_vol):
        raise ValueError(
            f"compute_edge: realized_vol must be positive and finite; got {realized_vol}"
        )
    cost_vn = (spread_cost_frac + slippage_frac) / realized_vol
    risk_vn = lambda_risk * variance_vn_value
    return expected_vn_return - cost_vn - risk_vn


def decide(
    prev_direction: str,
    edge: float,
    policy: PolicyConfig,
) -> tuple[Decision, bool]:
    """Return (decision, hysteresis_flip_dropped).

    `hysteresis_flip_dropped` is True when the intended direction would have
    flipped `prev_direction` but `|edge|` sat inside the hysteresis band; the
    walker emits `SIGNAL_DROPPED(dropped_reason="hysteresis_below_flip_threshold")`
    in that branch.
    """
    if prev_direction not in DIRECTIONS:
        raise ValueError(
            f"prev_direction must be in {DIRECTIONS}; got {prev_direction!r}"
        )
    abs_edge = abs(edge)
    intended = "flat"
    if edge > policy.threshold:
        intended = "long"
    elif edge < -policy.threshold:
        intended = "short"

    # Effective threshold: default = threshold; on a flip attempt, apply hysteresis widening.
    flip_attempt = (
        intended != prev_direction
        and intended != "flat"
        and prev_direction != "flat"
    )
    effective_threshold = policy.threshold
    hysteresis_flip_dropped = False
    if flip_attempt:
        effective_threshold = policy.threshold * (1.0 + policy.hysteresis)
        if abs_edge < effective_threshold:
            # Hold prev_direction; signal dropped.
            hysteresis_flip_dropped = True
            direction = prev_direction
            reason = "hysteresis_hold"
        else:
            direction = intended
            reason = "edge_above_threshold" if intended == "long" else "edge_below_threshold"
    elif intended == prev_direction and intended != "flat":
        # Holding what we have; no drop, decision continues.
        direction = intended
        reason = "position_held"
    else:
        # prev flat -> intended {long, short, flat}. flat->flat is flat.
        direction = intended
        if intended == "long":
            reason = "edge_above_threshold"
        elif intended == "short":
            reason = "edge_below_threshold"
        else:
            # flat->flat carries the threshold-hold reason.
            reason = "hysteresis_hold"

    if direction == "long":
        size = policy.position_size_usd
    elif direction == "short":
        size = -policy.position_size_usd
    else:
        size = 0.0

    return (
        Decision(
            direction=direction,
            size=size,
            edge=edge,
            threshold=policy.threshold,
            effective_threshold=effective_threshold,
            reason=reason,
        ),
        hysteresis_flip_dropped,
    )


__all__ = [
    "DIRECTIONS",
    "Decision",
    "PolicyConfig",
    "compute_edge",
    "decide",
    "variance_vn",
]
