"""Sprint 099: kappa sensitivity plot -- Sharpe vs kappa-multiplier grid.

Per product-spec § 'Success gates for v1': sweep a kappa multiplier over
`[0.5, 2.0]`; report Sharpe at each; the Layer-7 gate
`sharpe_crosses_zero_in_range` must be False for a robust reported number.

Sprint 096 named the linearization: `slippage_frac * |size|` approximates
`kappa * size^2`. Scaling `slippage_frac` by `m` scales the linearized cost
by `m` at a fixed size; that is the mechanic this sweep exercises.

Emits `SENSITIVITY_PLOT_GENERATED` once at close with the full
`(kappa_multipliers, sharpe_by_multiplier)` pair plus `min_sharpe`,
`max_sharpe`, and the strict `sharpe_crosses_zero_in_range` flag.

Sprint 099 closes Phase F.
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
class SensitivityPoint:
    """One sweep point -- one simulator run at one kappa multiplier."""

    kappa_multiplier: float
    sharpe: float
    sharpe_se: float


@dataclass(slots=True, frozen=True, kw_only=True)
class SensitivityPlotResult:
    """Full sensitivity sweep return value.

    `sharpe_crosses_zero_in_range` is strict: min < 0 AND max > 0. A flat
    Sharpe pinned at zero does not cross.
    """

    points: tuple[SensitivityPoint, ...]
    min_sharpe: float
    max_sharpe: float
    sharpe_crosses_zero_in_range: bool
    per_multiplier_results: tuple[SimResult, ...]


def run_kappa_sensitivity(
    artifact: TokenizedArtifact,
    model: MarketStateTransformer,
    bucket_stats: BucketStats,
    policy_template: PolicyConfig,
    kappa_multipliers: tuple[float, ...],
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
) -> SensitivityPlotResult:
    """Run one simulator per multiplier; emit SENSITIVITY_PLOT_GENERATED.

    Each iteration scales `policy_template.slippage_frac` by `m`; nested
    per-multiplier runs fire their own SIM_RUN_STARTED/COMPLETED pair.
    """
    if not kappa_multipliers:
        raise ValueError(
            "run_kappa_sensitivity requires at least one multiplier in kappa_multipliers"
        )

    swept = run_axis_sweep(
        artifact, model, bucket_stats, policy_template, kappa_multipliers,
        policy_field="slippage_frac",
        value_to_policy=lambda m, tpl: tpl.slippage_frac * m,
        sub_run_id=lambda parent, m: f"{parent}-kappa-{m:0.4f}",
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
    points: list[SensitivityPoint] = []
    per_multiplier_results: list[SimResult] = []
    for mult, sim_result in swept:
        metrics = sim_result.metrics
        sharpe = metrics.sharpe_point if metrics is not None else 0.0
        sharpe_se = metrics.sharpe_se if metrics is not None else 0.0
        points.append(
            SensitivityPoint(kappa_multiplier=mult, sharpe=sharpe, sharpe_se=sharpe_se)
        )
        per_multiplier_results.append(sim_result)

    sharpes = [p.sharpe for p in points]
    min_sharpe = min(sharpes)
    max_sharpe = max(sharpes)
    crosses = (min_sharpe < 0.0) and (max_sharpe > 0.0)

    emitter.emit(
        "SENSITIVITY_PLOT_GENERATED",
        run_id=run_id,
        kappa_multipliers=list(kappa_multipliers),
        sharpe_by_multiplier=sharpes,
        min_sharpe=min_sharpe,
        max_sharpe=max_sharpe,
        sharpe_crosses_zero_in_range=crosses,
    )

    return SensitivityPlotResult(
        points=tuple(points),
        min_sharpe=min_sharpe,
        max_sharpe=max_sharpe,
        sharpe_crosses_zero_in_range=crosses,
        per_multiplier_results=tuple(per_multiplier_results),
    )


__all__ = [
    "SensitivityPlotResult",
    "SensitivityPoint",
    "run_kappa_sensitivity",
]
