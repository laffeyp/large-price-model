"""Sprint 098: capacity sweep — largest position size where Sharpe stays positive.

Per tech-arch § 11.5: sweep size_usd across a log-spaced grid, run the
simulator at each size, report the largest size where the point Sharpe
stayed above zero as `capacity_usd`.

The sweep runs one nested `run_simulation_with_trades` call per size. Each
call fires its own `SIM_RUN_STARTED` and `SIM_RUN_COMPLETED` with a
size-tagged sub-run_id `{parent_run_id}-cap-{size_usd:012d}`. The sweep
itself fires `CAPACITY_SWEEP_COMPLETED` once at close carrying the full
`points` list plus the summary numbers.

Named on card: `capacity_usd = 0.0` when no point crosses zero — honest
zero, not a fabricated ceiling.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from price_space_llm.model.dataset import TokenizedArtifact
from price_space_llm.model.transformer import MarketStateTransformer
from price_space_llm.signals import StrictSignalEmitter
from price_space_llm.simulation.policy import PolicyConfig
from price_space_llm.simulation.skeleton import SimResult
from price_space_llm.simulation.sweeps import run_axis_sweep
from price_space_llm.tokenizer.bucketize import BucketStats


@dataclass(slots=True, frozen=True, kw_only=True)
class CapacityPoint:
    """One sweep point — one simulator run at one size."""

    size_usd: float
    sharpe: float
    sharpe_se: float


@dataclass(slots=True, frozen=True, kw_only=True)
class CapacitySweepResult:
    """Full sweep return value.

    `points` in the order sweep was called (typically ascending size_usd).
    `capacity_usd` = 0.0 when no point crossed zero.
    """

    points: tuple[CapacityPoint, ...]
    capacity_usd: float
    sharpe_at_capacity: float
    per_size_results: tuple[SimResult, ...]


def run_capacity_sweep(
    artifact: TokenizedArtifact,
    model: MarketStateTransformer,
    bucket_stats: BucketStats,
    policy_template: PolicyConfig,
    sizes_usd: tuple[float, ...],
    *,
    target_symbol: str,
    emitter: StrictSignalEmitter,
    run_id: str,
    checkpoint_step: int,
    checkpoint_run_id: str,
    cost_calibration_run_id: str,
    split: str = "train",
    date_range_start: date = date(2015, 1, 1),
    date_range_end: date = date(2022, 12, 31),
) -> CapacitySweepResult:
    """Run one simulator per size; return the sweep + emit CAPACITY_SWEEP_COMPLETED.

    `policy_template` provides every knob except `position_size_usd`; the
    sweep overrides that field per iteration. Nested per-size runs fire
    their own SIM_RUN_STARTED/COMPLETED pair against the same emitter.
    """
    if not sizes_usd:
        raise ValueError("run_capacity_sweep requires at least one size in sizes_usd")

    swept = run_axis_sweep(
        artifact, model, bucket_stats, policy_template, sizes_usd,
        policy_field="position_size_usd",
        value_to_policy=lambda v, _t: v,
        sub_run_id=lambda parent, v: f"{parent}-cap-{int(v):012d}",
        target_symbol=target_symbol,
        emitter=emitter,
        run_id=run_id,
        checkpoint_step=checkpoint_step,
        checkpoint_run_id=checkpoint_run_id,
        cost_calibration_run_id=cost_calibration_run_id,
        split=split,
        date_range_start=date_range_start,
        date_range_end=date_range_end,
    )
    points: list[CapacityPoint] = []
    per_size_results: list[SimResult] = []
    for size, sim_result in swept:
        m = sim_result.metrics
        sharpe = m.sharpe_point if m is not None else 0.0
        sharpe_se = m.sharpe_se if m is not None else 0.0
        points.append(CapacityPoint(size_usd=size, sharpe=sharpe, sharpe_se=sharpe_se))
        per_size_results.append(sim_result)

    # Capacity = largest size where Sharpe stayed positive.
    positives = [p for p in points if p.sharpe > 0.0]
    if positives:
        winner = max(positives, key=lambda p: p.size_usd)
        capacity_usd = winner.size_usd
        sharpe_at_capacity = winner.sharpe
    else:
        capacity_usd = 0.0
        sharpe_at_capacity = 0.0

    # Emit the summary tag with the full points list.
    payload_points = [
        {
            "size_usd": p.size_usd,
            "sharpe": p.sharpe,
            "sharpe_se": p.sharpe_se,
        }
        for p in points
    ]
    emitter.emit(
        "CAPACITY_SWEEP_COMPLETED",
        run_id=run_id,
        points=payload_points,
        capacity_usd=capacity_usd,
        sharpe_at_capacity=sharpe_at_capacity,
    )

    return CapacitySweepResult(
        points=tuple(points),
        capacity_usd=capacity_usd,
        sharpe_at_capacity=sharpe_at_capacity,
        per_size_results=tuple(per_size_results),
    )


__all__ = [
    "CapacityPoint",
    "CapacitySweepResult",
    "run_capacity_sweep",
]
