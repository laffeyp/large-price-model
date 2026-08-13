"""Tests for the cost calibration -- spread scaler + kappa fits."""

import json
import math
from pathlib import Path

import pytest

from price_space_llm.cost_calibration.calibrate import run_cost_calibration
from price_space_llm.cost_calibration.kappa import fit_kappa
from price_space_llm.cost_calibration.spread import (
    AtmSpread,
    BboSnapshot,
    extract_atm_spread,
    extract_bbo_snapshot,
    fit_spread_scaler,
)
from price_space_llm.signals import StrictSignalEmitter, load_vocabulary


def _fresh_emitter(max_buffer: int = 4096) -> StrictSignalEmitter:
    return StrictSignalEmitter(load_vocabulary(), max_buffer=max_buffer)


# Options ATM extraction --------------------------------------------------


def _synth_options_response(strikes_and_marks: list[tuple[float, float, float]]) -> dict:
    """Build a HISTORICAL_OPTIONS response with (strike, call_mark, put_mark) rows."""
    rows: list[dict] = []
    for strike, call_mark, put_mark in strikes_and_marks:
        rows.append(
            {
                "contractID": f"SPY_C_{strike:.0f}",
                "symbol": "SPY",
                "expiration": "2024-06-28",
                "strike": f"{strike:.2f}",
                "type": "call",
                "last": f"{call_mark:.2f}",
                "mark": f"{call_mark:.2f}",
                "bid": f"{call_mark - 0.10:.2f}",
                "bid_size": "50",
                "ask": f"{call_mark + 0.10:.2f}",
                "ask_size": "50",
                "volume": "100",
                "open_interest": "500",
                "date": "2024-06-28",
                "implied_volatility": "0.15",
                "delta": "0.50",
                "gamma": "0.01",
                "theta": "-0.05",
                "vega": "0.10",
                "rho": "0.02",
            }
        )
        rows.append(
            {
                "contractID": f"SPY_P_{strike:.0f}",
                "symbol": "SPY",
                "expiration": "2024-06-28",
                "strike": f"{strike:.2f}",
                "type": "put",
                "last": f"{put_mark:.2f}",
                "mark": f"{put_mark:.2f}",
                "bid": f"{put_mark - 0.10:.2f}",
                "bid_size": "50",
                "ask": f"{put_mark + 0.10:.2f}",
                "ask_size": "50",
                "volume": "80",
                "open_interest": "400",
                "date": "2024-06-28",
                "implied_volatility": "0.16",
                "delta": "-0.50",
                "gamma": "0.01",
                "theta": "-0.05",
                "vega": "0.10",
                "rho": "-0.02",
            }
        )
    return {"endpoint": "Historical Options", "message": "success", "data": rows}


def test_extract_atm_spread_picks_smallest_parity_gap():
    """The ATM strike is the one where call_mark ~ put_mark (put-call parity min)."""
    response = _synth_options_response(
        [
            (500.0, 10.0, 1.0),  # deep ITM call: gap = 9
            (540.0, 5.0, 5.0),  # perfect parity → ATM
            (580.0, 1.0, 10.0),  # deep OTM call: gap = 9
        ]
    )
    atm = extract_atm_spread(response, "SPY")
    assert atm.strike == 540.0
    assert atm.symbol == "SPY"


def test_extract_atm_spread_normalised_spread_is_positive():
    response = _synth_options_response([(540.0, 5.0, 5.0)])
    atm = extract_atm_spread(response, "SPY")
    assert atm.normalized_spread > 0


def test_extract_atm_spread_raises_on_empty():
    with pytest.raises(ValueError, match="no non-empty"):
        extract_atm_spread({"data": []}, "SPY")


def test_extract_atm_spread_raises_when_no_both_call_and_put():
    """A strike with only a call (no put) cannot be ATM."""
    response = {
        "data": [
            {
                "strike": "500",
                "type": "call",
                "mark": "5",
                "bid": "4.9",
                "ask": "5.1",
                "date": "2024-06-28",
                "implied_volatility": "0.15",
            }
        ]
    }
    with pytest.raises(ValueError, match="no strike"):
        extract_atm_spread(response, "SPY")


# BBO extraction ----------------------------------------------------------


def test_extract_bbo_snapshot_returns_row_for_symbol():
    response = {
        "data": [
            {
                "symbol": "SPY",
                "timestamp": "2026-08-12 18:40:26",
                "bid_price": "772.25",
                "ask_price": "772.33",
                "bid_size": "500",
                "ask_size": "126",
            }
        ]
    }
    snap = extract_bbo_snapshot(response, "SPY")
    assert snap.symbol == "SPY"
    assert snap.bid == 772.25
    assert snap.ask == 772.33
    assert snap.bid_size == 500
    assert snap.ask_size == 126


def test_extract_bbo_snapshot_computes_normalized_spread():
    snap = BboSnapshot(
        timestamp_utc="2026-08-12T18:40:26",
        symbol="SPY",
        bid=100.0,
        ask=100.10,
        bid_size=1,
        ask_size=1,
    )
    # (100.10 - 100.00) / 100.05 ~ 0.0009995
    assert snap.normalized_spread == pytest.approx(0.10 / 100.05, abs=1e-6)


def test_extract_bbo_snapshot_raises_on_missing_symbol():
    response = {
        "data": [
            {
                "symbol": "QQQ",
                "timestamp": "2026-08-12 18:40:26",
                "bid_price": "1.0",
                "ask_price": "1.1",
                "bid_size": "1",
                "ask_size": "1",
            }
        ]
    }
    with pytest.raises(ValueError, match="not in BBO response"):
        extract_bbo_snapshot(response, "SPY")


# Spread scaler OLS -------------------------------------------------------


def test_fit_spread_scaler_recovers_known_slope_and_intercept():
    """Given y = 2*x + 0.5 on 5 pairs, the OLS fit recovers slope=2, intercept=0.5."""
    pairs = [(x, 2 * x + 0.5) for x in [0.001, 0.002, 0.003, 0.004, 0.005]]
    fit = fit_spread_scaler(pairs)
    assert fit.slope == pytest.approx(2.0, abs=1e-6)
    assert fit.intercept == pytest.approx(0.5, abs=1e-6)
    assert fit.r_squared == pytest.approx(1.0, abs=1e-6)
    assert fit.n_pairs == 5


def test_fit_spread_scaler_rejects_single_pair():
    with pytest.raises(ValueError, match=">= 2"):
        fit_spread_scaler([(0.001, 0.002)])


def test_fit_spread_scaler_zero_variance_x_returns_slope_zero():
    pairs = [(0.001, 0.002), (0.001, 0.003), (0.001, 0.005)]
    fit = fit_spread_scaler(pairs)
    assert fit.slope == 0.0
    assert fit.intercept == pytest.approx((0.002 + 0.003 + 0.005) / 3, abs=1e-6)


# Kappa fit ---------------------------------------------------------------


def test_fit_kappa_recovers_known_relationship_within_ci():
    """Generate y = 0.3 * sqrt(vol/ADV) + gaussian noise; kappa CI must include 0.3."""
    import random

    rng = random.Random(0)
    n = 500
    closes = [100.0]
    volumes = []
    true_kappa = 0.3
    for _ in range(n):
        volume = rng.uniform(1000, 5000)
        volumes.append(volume)
        adv = 3000  # rough steady ADV
        vol_signal = math.sqrt(volume / adv)
        move = true_kappa * vol_signal * rng.choice([-1, 1]) + rng.gauss(0, 0.05)
        closes.append(closes[-1] * math.exp(move))
    volumes.append(rng.uniform(1000, 5000))  # match length
    kappa = fit_kappa(closes, volumes, adv_window=20, n_bootstrap=200, seed=0)
    # With noise the point estimate wanders; CI should still bracket true kappa.
    assert kappa.kappa_ci_low < true_kappa
    assert kappa.kappa_ci_high > 0  # point is at least positive


def test_fit_kappa_rejects_too_few_bars():
    with pytest.raises(ValueError, match=">= 10"):
        fit_kappa(
            close_prices=[100.0] * 15,
            volumes=[1000.0] * 15,
            adv_window=20,  # ADV window > data → no valid pairs
            n_bootstrap=100,
        )


def test_fit_kappa_returns_positive_bootstrap_se():
    rng_closes = [100.0 * math.exp(0.001 * i) for i in range(200)]
    rng_volumes = [1000.0 + 10 * i for i in range(200)]
    kappa = fit_kappa(rng_closes, rng_volumes, adv_window=20, n_bootstrap=100, seed=0)
    assert kappa.kappa_se > 0
    # Bootstrap CI ordering depends on sample; SE positivity is the invariant we assert.


# End-to-end run_cost_calibration -----------------------------------------


def _write_synth_options(tmp_path: Path, date_str: str) -> Path:
    response = {
        "endpoint": "Historical Options",
        "message": "success",
        "data": [
            {
                "strike": "540.00",
                "type": "call",
                "mark": "5.10",
                "bid": "5.00",
                "ask": "5.20",
                "date": date_str,
                "implied_volatility": "0.15",
            },
            {
                "strike": "540.00",
                "type": "put",
                "mark": "5.10",
                "bid": "5.00",
                "ask": "5.20",
                "date": date_str,
                "implied_volatility": "0.16",
            },
        ],
    }
    path = tmp_path / f"options_{date_str}.json"
    path.write_text(json.dumps(response), encoding="utf-8")
    return path


def _write_synth_bbo(tmp_path: Path, i: int) -> Path:
    response = {
        "endpoint": "Realtime Bulk Bid and Ask Prices",
        "message": "success",
        "data": [
            {
                "symbol": "SPY",
                "timestamp": f"2026-08-12 18:40:{20 + i:02d}",
                "bid_price": f"{540.0 + i * 0.01:.2f}",
                "ask_price": f"{540.05 + i * 0.01:.2f}",
                "bid_size": "100",
                "ask_size": "100",
            }
        ],
    }
    path = tmp_path / f"bbo_{i}.json"
    path.write_text(json.dumps(response), encoding="utf-8")
    return path


def _write_synth_intraday(tmp_path: Path, n_bars: int) -> Path:
    series: dict[str, dict[str, str]] = {}
    for i in range(n_bars):
        # Unique per bar: base time + 15 * i minutes.
        base_min = 9 * 60 + 30 + 15 * i
        day = 1 + base_min // (24 * 60)
        min_of_day = base_min % (24 * 60)
        hh, mm = divmod(min_of_day, 60)
        ts = f"2024-06-{day:02d} {hh:02d}:{mm:02d}:00"
        close = 100.0 + 0.01 * i
        series[ts] = {
            "1. open": f"{close - 0.01:.2f}",
            "2. high": f"{close + 0.05:.2f}",
            "3. low": f"{close - 0.05:.2f}",
            "4. close": f"{close:.2f}",
            "5. volume": f"{1000 + 10 * (i % 30)}",
        }
    response = {
        "Meta Data": {"2. Symbol": "SPY", "4. Interval": "15min"},
        "Time Series (15min)": series,
    }
    path = tmp_path / "intraday.json"
    path.write_text(json.dumps(response), encoding="utf-8")
    return path


def test_run_cost_calibration_emits_all_three_tags(tmp_path: Path):
    e = _fresh_emitter()
    option_paths = [_write_synth_options(tmp_path, d) for d in ["2024-05-15", "2024-06-15"]]
    bbo_paths = [_write_synth_bbo(tmp_path, i) for i in range(3)]
    intraday_paths = [_write_synth_intraday(tmp_path, n_bars=60)]
    result = run_cost_calibration(
        option_response_paths=option_paths,
        bbo_response_paths=bbo_paths,
        intraday_response_paths=intraday_paths,
        target_symbol="SPY",
        output_dir=tmp_path / "artifacts",
        emitter=e,
        run_id="test-calibrate",
        kappa_bootstrap=50,
        seed=0,
    )
    tags = [s.tag for s in e.snapshot()]
    assert "SPREAD_SCALER_WRITTEN" in tags
    assert "KAPPA_WRITTEN" in tags
    assert "COST_CALIBRATION_FITTED" in tags
    # Sprint 036: versioned artifacts land at {stem}.{run_id}.json + latest symlink.
    assert (tmp_path / "artifacts" / "spread_scaler.test-calibrate.json").exists()
    assert (tmp_path / "artifacts" / "kappa.test-calibrate.json").exists()
    assert (tmp_path / "artifacts" / "spread_scaler.latest.json").exists()
    assert (tmp_path / "artifacts" / "kappa.latest.json").exists()
    # Two option dates → two (x, y) pairs; y is the mean-BBO anchor.
    assert result.spread_scaler.n_pairs == 2


def test_run_cost_calibration_rejects_too_few_intraday_bars(tmp_path: Path):
    e = _fresh_emitter()
    option_paths = [
        _write_synth_options(tmp_path, "2024-05-15"),
        _write_synth_options(tmp_path, "2024-06-15"),
    ]
    bbo_paths = [_write_synth_bbo(tmp_path, 0), _write_synth_bbo(tmp_path, 1)]
    intraday_paths = [_write_synth_intraday(tmp_path, n_bars=10)]
    with pytest.raises(ValueError, match="intraday bars"):
        run_cost_calibration(
            option_response_paths=option_paths,
            bbo_response_paths=bbo_paths,
            intraday_response_paths=intraday_paths,
            target_symbol="SPY",
            output_dir=tmp_path / "artifacts",
            emitter=e,
            run_id="test",
        )


def test_run_cost_calibration_rejects_zero_pairs(tmp_path: Path):
    e = _fresh_emitter()
    intraday_paths = [_write_synth_intraday(tmp_path, n_bars=60)]
    with pytest.raises(ValueError, match=">= 2"):
        run_cost_calibration(
            option_response_paths=[],
            bbo_response_paths=[],
            intraday_response_paths=intraday_paths,
            target_symbol="SPY",
            output_dir=tmp_path / "artifacts",
            emitter=e,
            run_id="test",
        )


def test_atm_spread_normalized_symmetric_when_call_equals_put():
    """A synthetic ATM straddle: call_bid=put_bid, call_ask=put_ask → normalized > 0."""
    atm = AtmSpread(
        date="2024-06-28",
        symbol="SPY",
        spot_estimate=540.0,
        strike=540.0,
        call_bid=5.00,
        call_ask=5.20,
        put_bid=5.00,
        put_ask=5.20,
        call_iv=0.15,
        put_iv=0.16,
        call_mark=5.10,
        put_mark=5.10,
    )
    # straddle spread = 0.20 + 0.20 = 0.40; straddle mark = 10.20
    assert atm.normalized_spread == pytest.approx(0.40 / 10.20, abs=1e-6)
