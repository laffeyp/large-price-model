"""Offline evaluator: reads a checkpoint, computes real metrics per regime, emits."""

from price_space_llm.evaluation.evaluate import (
    EvaluatorResult,
    run_evaluation,
)
from price_space_llm.evaluation.metrics import (
    MetricSet,
    compute_brier,
    compute_bucket_frequency_drift,
    compute_ece,
    compute_metric_set,
    compute_rps,
)
from price_space_llm.evaluation.regimes import (
    RegimeThresholds,
    assign_regime,
    fit_regime_thresholds,
)

__all__ = [
    "EvaluatorResult",
    "MetricSet",
    "RegimeThresholds",
    "assign_regime",
    "compute_brier",
    "compute_bucket_frequency_drift",
    "compute_ece",
    "compute_metric_set",
    "compute_rps",
    "fit_regime_thresholds",
    "run_evaluation",
]
