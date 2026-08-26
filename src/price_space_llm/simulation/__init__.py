"""Simulator subsystem — bar walker + cost model + decision policy + metrics.

Sprint 092 (Phase F, roadmap 074) lands the skeleton: package + bar walker +
`SimResult` + `SIM_RUN_STARTED` / `BAR_PROCESSED` / `SIM_RUN_COMPLETED` emits.
Every summary metric on `SIM_RUN_COMPLETED` is zero because the skeleton runs
zero trades.

Sprint 093 wires the model (`PREDICTION_EMITTED`) + decision policy
(`DECISION_MADE`, `POSITION_OPENED`, `POSITION_CLOSED`, `TRADE_LEDGERED`,
`SIGNAL_DROPPED`) + cost model consumption. Sprint 094 lands metrics + block
bootstrap; Sprint 095 the capacity sweep; Sprint 096 the kappa sensitivity plot.
"""

from price_space_llm.simulation.capacity import (
    CapacityPoint,
    CapacitySweepResult,
    run_capacity_sweep,
)
from price_space_llm.simulation.metrics import (
    SimMetrics,
    block_bootstrap_sharpe,
    build_equity_curve,
    compute_sharpe,
    compute_sim_metrics,
    max_drawdown_from_equity,
    time_to_recovery_bars_from_equity,
)
from price_space_llm.simulation.policy import (
    DIRECTIONS,
    Decision,
    PolicyConfig,
    compute_edge,
    decide,
    variance_vn,
)
from price_space_llm.simulation.positions import (
    Position,
    Trade,
    compute_pnl,
    derive_prices_from_log_returns,
)
from price_space_llm.simulation.prediction import (
    PredictionScalars,
    derive_prediction_scalars,
)
from price_space_llm.simulation.sensitivity import (
    SensitivityPlotResult,
    SensitivityPoint,
    run_kappa_sensitivity,
)
from price_space_llm.simulation.skeleton import (
    SimResult,
    run_simulation_skeleton,
    run_simulation_with_trades,
)

__all__ = [
    "DIRECTIONS",
    "CapacityPoint",
    "CapacitySweepResult",
    "Decision",
    "PolicyConfig",
    "Position",
    "PredictionScalars",
    "SensitivityPlotResult",
    "SensitivityPoint",
    "SimMetrics",
    "SimResult",
    "Trade",
    "block_bootstrap_sharpe",
    "build_equity_curve",
    "compute_edge",
    "compute_pnl",
    "compute_sharpe",
    "compute_sim_metrics",
    "decide",
    "derive_prediction_scalars",
    "derive_prices_from_log_returns",
    "max_drawdown_from_equity",
    "run_capacity_sweep",
    "run_kappa_sensitivity",
    "run_simulation_skeleton",
    "run_simulation_with_trades",
    "time_to_recovery_bars_from_equity",
    "variance_vn",
]
