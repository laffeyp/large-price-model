"""Sprint 104: shared axis-sweep helper for capacity + kappa-sensitivity (review §6.2).

Both `run_capacity_sweep` (Sprint 098) and `run_kappa_sensitivity` (Sprint 099)
iterate a knob via `dataclasses.replace(policy_template, ...)`, call
`run_simulation_with_trades` per point, and extract `metrics.sharpe_point` +
`metrics.sharpe_se`. The summary-tag emit is per-sweep; the walker call is
shared. This helper owns the shared shape; the two callers keep their tag
composition + result-dataclass shape.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import date

from price_space_llm.model.dataset import TokenizedArtifact
from price_space_llm.model.transformer import MarketStateTransformer
from price_space_llm.signals import StrictSignalEmitter
from price_space_llm.simulation.policy import PolicyConfig
from price_space_llm.simulation.skeleton import (
    SimResult,
    run_simulation_with_trades,
)
from price_space_llm.tokenizer.bucketize import BucketStats


def run_axis_sweep(
    artifact: TokenizedArtifact,
    model: MarketStateTransformer,
    bucket_stats: BucketStats,
    policy_template: PolicyConfig,
    values: tuple[float, ...],
    *,
    policy_field: str,
    value_to_policy: Callable[[float, PolicyConfig], float],
    sub_run_id: Callable[[str, float], str],
    target_symbol: str,
    emitter: StrictSignalEmitter,
    run_id: str,
    checkpoint_step: int,
    checkpoint_run_id: str,
    cost_calibration_run_id: str,
    split: str,
    date_range_start: date,
    date_range_end: date,
) -> list[tuple[float, SimResult]]:
    """Sweep `values` on `policy_template[policy_field]` and return `[(value, sim_result), ...]`.

    `value_to_policy(v, template)` returns the actual policy-field value written
    for sweep point `v` (capacity: `v` as-is; sensitivity: `template.slippage_frac * v`).
    `sub_run_id(parent, v)` produces the per-point `run_id`. The caller composes
    the summary tag.
    """
    out: list[tuple[float, SimResult]] = []
    for v in values:
        field_value = value_to_policy(v, policy_template)
        policy = replace(policy_template, **{policy_field: field_value})
        result = run_simulation_with_trades(
            artifact,
            model,
            bucket_stats,
            policy,
            target_symbol=target_symbol,
            emitter=emitter,
            run_id=sub_run_id(run_id, v),
            checkpoint_step=checkpoint_step,
            checkpoint_run_id=checkpoint_run_id,
            cost_calibration_run_id=cost_calibration_run_id,
            split=split,
            date_range_start=date_range_start,
            date_range_end=date_range_end,
        )
        out.append((v, result))
    return out


__all__ = ["run_axis_sweep"]
