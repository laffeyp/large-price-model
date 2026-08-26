"""Cost calibration -- spread scaler + kappa (Kyle's-lambda) fit.

Emits `SPREAD_SCALER_WRITTEN`, `KAPPA_WRITTEN`, `COST_CALIBRATION_FITTED`
per v0.3 vocabulary. Data sources:

- HISTORICAL_OPTIONS for the historical spread signal (SPY ATM straddle
  bid-ask, one observation per trading day over the training range).
- REALTIME_BULK_BID_ASK_PRICES for the equity BBO anchor (paired snapshots
  taken at calibration time so the linear model is fit against real
  equity-vs-option spreads, not a scale assumption).
- TIME_SERIES_INTRADAY for kappa (Kyle's-lambda regression of
  |log_return| on sqrt(volume / ADV) over intraday bars).

Every emitted field is a real fit against real observations. No
fabricated `kappa_se = 0` or scale-of-one intercepts. When paired
observations are thin, uncertainty stays honest through the reported
CI and SE.
"""

from price_space_llm.cost_calibration.calibrate import (
    CostCalibrationResult,
    run_cost_calibration,
)
from price_space_llm.cost_calibration.corwin_schultz import (
    BiasCorrection,
    apply_bias_correction,
    corwin_schultz_spread,
    fit_bias_correction,
)
from price_space_llm.cost_calibration.kappa import (
    KappaFit,
    fit_kappa,
)
from price_space_llm.cost_calibration.spread import (
    AtmSpread,
    BboSnapshot,
    SpreadScalerFit,
    extract_atm_spread,
    extract_bbo_snapshot,
    fit_spread_scaler,
)

__all__ = [
    "AtmSpread",
    "BboSnapshot",
    "BiasCorrection",
    "CostCalibrationResult",
    "KappaFit",
    "SpreadScalerFit",
    "apply_bias_correction",
    "corwin_schultz_spread",
    "extract_atm_spread",
    "extract_bbo_snapshot",
    "fit_bias_correction",
    "fit_kappa",
    "fit_spread_scaler",
    "run_cost_calibration",
]
