"""Strictly-causal feature computation over an aligned bar frame.

Tech-arch §6: features at time T see only rows with `grid_ts <= T`.
Rolling windows are backward-only. NaN handling propagates as
`FEATURE_COMPUTATION_FAILED` with an explicit reason; no fill-value
lies (per the Sprint 023 correction).
"""

from price_space_llm.features.compute import (
    FEATURE_SPECS,
    FeatureResult,
    compute_features,
    run_feature_pipeline,
)

__all__ = [
    "FEATURE_SPECS",
    "FeatureResult",
    "compute_features",
    "run_feature_pipeline",
]
