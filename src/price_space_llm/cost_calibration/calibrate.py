"""End-to-end cost calibration orchestrator.

Reads intraday bars (already-cached TIME_SERIES_INTRADAY responses),
options chains (must be pre-fetched via IngestionClient into
data/raw/), and BBO snapshots (also pre-fetched). Fits spread scaler +
kappa. Writes two frozen artifacts and emits three vocabulary tags.
"""

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from price_space_llm.cost_calibration.kappa import KappaFit, fit_kappa
from price_space_llm.cost_calibration.spread import (
    AtmSpread,
    BboSnapshot,
    SpreadScalerFit,
    extract_atm_spread,
    extract_bbo_snapshot,
    fit_spread_scaler,
)
from price_space_llm.signals import StrictSignalEmitter


@dataclass(slots=True, frozen=True, kw_only=True)
class CostCalibrationResult:
    run_id: str
    spread_scaler: SpreadScalerFit
    kappa: KappaFit
    n_option_dates: int
    n_bbo_snapshots: int
    n_intraday_bars: int
    spread_scaler_path: str
    kappa_path: str
    elapsed_seconds: float


def _load_option_atm_spreads(
    option_response_paths: list[Path],
    symbol: str,
) -> list[AtmSpread]:
    """Read cached HISTORICAL_OPTIONS responses; extract ATM per date."""
    out: list[AtmSpread] = []
    for p in option_response_paths:
        response = json.loads(p.read_text(encoding="utf-8"))
        out.append(extract_atm_spread(response, symbol))
    return out


def _load_bbo_snapshots(
    bbo_response_paths: list[Path],
    symbol: str,
) -> list[BboSnapshot]:
    """Read cached BBO responses; extract the row for `symbol` in each."""
    return [
        extract_bbo_snapshot(json.loads(p.read_text(encoding="utf-8")), symbol)
        for p in bbo_response_paths
    ]


def _load_intraday_series(
    intraday_response_paths: list[Path],
) -> tuple[list[float], list[float]]:
    """Concatenate close + volume across cached TIME_SERIES_INTRADAY responses (chronological)."""
    all_bars: list[tuple[str, float, float]] = []  # (ts, close, volume)
    for p in intraday_response_paths:
        response = json.loads(p.read_text(encoding="utf-8"))
        series_key = next((k for k in response if k.startswith("Time Series")), None)
        if series_key is None:
            continue
        series = response[series_key]
        for ts, bar in series.items():
            close = float(bar.get("4. close", bar.get("close", 0)))
            volume = float(bar.get("5. volume", bar.get("volume", 0)))
            all_bars.append((ts, close, volume))
    all_bars.sort(key=lambda t: t[0])
    closes = [b[1] for b in all_bars]
    volumes = [b[2] for b in all_bars]
    return closes, volumes


def _pair_option_and_bbo(
    option_spreads: list[AtmSpread],
    bbo_snapshots: list[BboSnapshot],
) -> list[tuple[float, float]]:
    """Pair each historical option date with the mean of same-session BBO snapshots.

    Options run historically; BBO snapshots run today (all within a few seconds of
    each other). We use each option date's `normalized_spread` as x and the
    mean of today's BBO snapshots as y. This gives one pair per option date --
    real x-variance from the historical time series, one y-anchor from the
    current session. Multi-day BBO polling (later sprint) replaces the single
    y-anchor with a time-matched y per option date.
    """
    if not option_spreads or not bbo_snapshots:
        return []
    y_bar = sum(s.normalized_spread for s in bbo_snapshots) / len(bbo_snapshots)
    return [(atm.normalized_spread, y_bar) for atm in option_spreads]


def _write_json_artifact(path: Path, body: dict[str, object], run_id: str) -> tuple[str, Path]:
    """Versioned write via `artifacts.write_versioned`. Returns (sha256, versioned_path)."""
    from price_space_llm.artifacts import write_versioned

    text = json.dumps(body, sort_keys=True, indent=2).encode("utf-8")
    result = write_versioned(path, run_id, text)
    return result.sha256, result.versioned_path


def run_cost_calibration(
    *,
    option_response_paths: list[Path],
    bbo_response_paths: list[Path],
    intraday_response_paths: list[Path],
    target_symbol: str,
    output_dir: Path,
    emitter: StrictSignalEmitter,
    run_id: str,
    kappa_bootstrap: int = 500,
    kappa_adv_window: int = 20,
    seed: int = 0,
) -> CostCalibrationResult:
    """End-to-end fit + emit + persist. All three tags fire from real values."""
    t0 = time.monotonic()

    option_spreads = _load_option_atm_spreads(option_response_paths, target_symbol)
    bbo_snapshots = _load_bbo_snapshots(bbo_response_paths, target_symbol)
    pairs = _pair_option_and_bbo(option_spreads, bbo_snapshots)
    if len(pairs) < 2:
        raise ValueError(f"need >= 2 (option_spread, bbo_spread) pairs; got {len(pairs)}")
    spread_fit = fit_spread_scaler(pairs)

    closes, volumes = _load_intraday_series(intraday_response_paths)
    if len(closes) < kappa_adv_window + 10:
        raise ValueError(
            f"need >= {kappa_adv_window + 10} intraday bars for the kappa fit; got {len(closes)}"
        )
    kappa_fit = fit_kappa(
        closes,
        volumes,
        adv_window=kappa_adv_window,
        n_bootstrap=kappa_bootstrap,
        seed=seed,
    )

    spread_body: dict[str, object] = {
        "kind": "spread_scaler",
        "model": "bbo_spread = slope * option_atm_spread + intercept",
        "target_symbol": target_symbol,
        "slope": spread_fit.slope,
        "intercept": spread_fit.intercept,
        "r_squared": spread_fit.r_squared,
        "n_pairs": spread_fit.n_pairs,
        "option_history_dates": [a.date for a in option_spreads],
        "bbo_snapshot_timestamps": [s.timestamp_utc for s in bbo_snapshots],
    }
    kappa_body: dict[str, object] = {
        "kind": "kappa",
        "model": "|log_return| = kappa * sqrt(volume / ADV)",
        "target_symbol": target_symbol,
        "kappa_point": kappa_fit.kappa_point,
        "kappa_se": kappa_fit.kappa_se,
        "kappa_ci_low": kappa_fit.kappa_ci_low,
        "kappa_ci_high": kappa_fit.kappa_ci_high,
        "kappa_r2": kappa_fit.kappa_r2,
        "n": kappa_fit.n,
        "adv_window": kappa_adv_window,
        "n_bootstrap": kappa_bootstrap,
        "seed": seed,
    }
    spread_base = output_dir / "spread_scaler.json"
    kappa_base = output_dir / "kappa.json"
    spread_sha, spread_versioned = _write_json_artifact(spread_base, spread_body, run_id)
    kappa_sha, kappa_versioned = _write_json_artifact(kappa_base, kappa_body, run_id)

    emitter.emit(
        "SPREAD_SCALER_WRITTEN",
        run_id=run_id,
        path=str(spread_versioned),
        sha256=spread_sha,
    )
    emitter.emit(
        "KAPPA_WRITTEN",
        run_id=run_id,
        path=str(kappa_versioned),
        sha256=kappa_sha,
    )
    emitter.emit(
        "COST_CALIBRATION_FITTED",
        run_id=run_id,
        spread_scaler_slope=spread_fit.slope,
        spread_scaler_intercept=spread_fit.intercept,
        kappa_point=kappa_fit.kappa_point,
        kappa_se=kappa_fit.kappa_se,
        kappa_ci_low=kappa_fit.kappa_ci_low,
        kappa_ci_high=kappa_fit.kappa_ci_high,
        kappa_r2=kappa_fit.kappa_r2,
        n=kappa_fit.n,
    )

    return CostCalibrationResult(
        run_id=run_id,
        spread_scaler=spread_fit,
        kappa=kappa_fit,
        n_option_dates=len(option_spreads),
        n_bbo_snapshots=len(bbo_snapshots),
        n_intraday_bars=len(closes),
        spread_scaler_path=str(spread_versioned),
        kappa_path=str(kappa_versioned),
        elapsed_seconds=time.monotonic() - t0,
    )


__all__ = ["CostCalibrationResult", "_write_json_artifact", "asdict", "run_cost_calibration"]
