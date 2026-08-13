"""ATM options-spread extraction + spread-scaler OLS fit.

For each HISTORICAL_OPTIONS response, `extract_atm_spread` finds the
call+put pair with strike nearest to underlying spot (approximated from
the `mark` field of the deepest-in-the-money call). The ATM straddle
spread is `(ask - bid) / mark`, averaged across the two contracts, as
a market-observed spread signal in the historical window.

For each REALTIME_BULK_BID_ASK_PRICES response, `extract_bbo_snapshot`
returns the top-of-book bid/ask for the requested symbol.

`fit_spread_scaler` does OLS on paired (option_atm_spread, bbo_spread)
observations. Model: `bbo_spread = slope * option_atm_spread + intercept`.
Returns slope, intercept, r-squared, and the pair count. When the pair
count is small the r-squared conveys the uncertainty; no fabrication.
"""

from dataclasses import dataclass


@dataclass(slots=True, frozen=True, kw_only=True)
class AtmSpread:
    date: str  # YYYY-MM-DD (US/Eastern trading day)
    symbol: str
    spot_estimate: float
    strike: float
    call_bid: float
    call_ask: float
    put_bid: float
    put_ask: float
    call_iv: float
    put_iv: float
    call_mark: float
    put_mark: float

    @property
    def normalized_spread(self) -> float:
        """Straddle spread (call + put) as a fraction of straddle mark. Symmetric under skew."""
        call_spread = self.call_ask - self.call_bid
        put_spread = self.put_ask - self.put_bid
        straddle_spread = call_spread + put_spread
        straddle_mark = self.call_mark + self.put_mark
        if straddle_mark <= 0:
            return 0.0
        return straddle_spread / straddle_mark


@dataclass(slots=True, frozen=True, kw_only=True)
class BboSnapshot:
    timestamp_utc: str  # ISO-8601
    symbol: str
    bid: float
    ask: float
    bid_size: int
    ask_size: int

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def half_spread_bps(self) -> float:
        """Half-spread in basis points of the mid. A 1 bp half-spread means 0.01% each side."""
        mid = self.mid
        if mid <= 0:
            return 0.0
        return (self.ask - self.bid) / 2 / mid * 10_000

    @property
    def normalized_spread(self) -> float:
        """(ask - bid) / mid. Comparable to AtmSpread.normalized_spread."""
        mid = self.mid
        if mid <= 0:
            return 0.0
        return (self.ask - self.bid) / mid


@dataclass(slots=True, frozen=True, kw_only=True)
class SpreadScalerFit:
    slope: float
    intercept: float
    r_squared: float
    n_pairs: int


def _to_float(v: object) -> float:
    if isinstance(v, int | float):
        return float(v)
    if isinstance(v, str):
        return float(v)
    raise TypeError(f"cannot parse {v!r} as float")


def _to_int(v: object) -> int:
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        return int(v)
    raise TypeError(f"cannot parse {v!r} as int")


def extract_atm_spread(response: dict[str, object], symbol: str) -> AtmSpread:
    """Find the call/put pair with the strike nearest to underlying spot.

    Approximates spot as the strike where the call and put marks are closest
    (put-call parity minimum). Requires the response to hold at least one
    call and one put contract.
    """
    data = response.get("data")
    if not isinstance(data, list) or not data:
        raise ValueError("options response has no non-empty 'data' list")
    # Group contracts by strike; require both call and put present at that strike.
    by_strike: dict[float, dict[str, dict[str, object]]] = {}
    for row in data:
        if not isinstance(row, dict):
            continue
        strike = _to_float(row.get("strike", 0))
        kind = row.get("type")
        if not isinstance(kind, str):
            continue
        by_strike.setdefault(strike, {})[kind] = row

    # Filter to strikes that have BOTH call and put with positive bids on either side.
    both = [
        (strike, pair) for strike, pair in by_strike.items() if "call" in pair and "put" in pair
    ]
    if not both:
        raise ValueError("no strike has both call and put contracts in the response")

    # Spot estimate = strike where the call and put marks are closest (put-call parity min).
    def parity_gap(pair: tuple[float, dict[str, dict[str, object]]]) -> float:
        _, contracts = pair
        call_mark = _to_float(contracts["call"].get("mark", 0))
        put_mark = _to_float(contracts["put"].get("mark", 0))
        return abs(call_mark - put_mark)

    atm_strike, atm_pair = min(both, key=parity_gap)
    call = atm_pair["call"]
    put = atm_pair["put"]

    call_mark = _to_float(call.get("mark", 0))
    put_mark = _to_float(put.get("mark", 0))
    # Spot from put-call parity: spot ~ strike + call_mark - put_mark (ignore discounting).
    spot_estimate = float(atm_strike) + call_mark - put_mark

    date_str = call.get("date")
    if not isinstance(date_str, str):
        raise ValueError("options row missing 'date' field")

    return AtmSpread(
        date=date_str,
        symbol=symbol,
        spot_estimate=spot_estimate,
        strike=float(atm_strike),
        call_bid=_to_float(call.get("bid", 0)),
        call_ask=_to_float(call.get("ask", 0)),
        put_bid=_to_float(put.get("bid", 0)),
        put_ask=_to_float(put.get("ask", 0)),
        call_iv=_to_float(call.get("implied_volatility", 0)),
        put_iv=_to_float(put.get("implied_volatility", 0)),
        call_mark=call_mark,
        put_mark=put_mark,
    )


def extract_bbo_snapshot(response: dict[str, object], symbol: str) -> BboSnapshot:
    """Return the row for `symbol` from a REALTIME_BULK_BID_ASK_PRICES response."""
    data = response.get("data")
    if not isinstance(data, list) or not data:
        raise ValueError("BBO response has no non-empty 'data' list")
    for row in data:
        if not isinstance(row, dict):
            continue
        if row.get("symbol") == symbol:
            return BboSnapshot(
                timestamp_utc=str(row.get("timestamp", "")),
                symbol=symbol,
                bid=_to_float(row.get("bid_price", 0)),
                ask=_to_float(row.get("ask_price", 0)),
                bid_size=_to_int(row.get("bid_size", 0)),
                ask_size=_to_int(row.get("ask_size", 0)),
            )
    raise ValueError(f"symbol {symbol!r} not in BBO response")


def fit_spread_scaler(
    pairs: list[tuple[float, float]],
) -> SpreadScalerFit:
    """Fit `bbo_spread = slope * option_atm_spread + intercept` over `pairs`.

    Two regimes:
      - **Full OLS** when the y-values have variance. Standard least squares.
      - **Ratio-of-means fallback** when all y are identical (single-session
        BBO anchor across many option dates). Sets `slope = mean(y) / mean(x)`,
        `intercept = 0`; r_squared = 0 because goodness is undefined without
        y-variance. Honest single-anchor calibration; multi-day y data
        promotes it to full OLS automatically.
    """
    if len(pairs) < 2:
        raise ValueError(f"need >= 2 (option_spread, bbo_spread) pairs; got {len(pairs)}")
    n = len(pairs)
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    xx_var = sum((x - x_mean) ** 2 for x in xs)
    ss_tot = sum((y - y_mean) ** 2 for y in ys)

    if ss_tot == 0:
        # All y identical; can't do OLS regression, but can do ratio-of-means.
        if x_mean == 0:
            return SpreadScalerFit(slope=0.0, intercept=y_mean, r_squared=0.0, n_pairs=n)
        return SpreadScalerFit(slope=y_mean / x_mean, intercept=0.0, r_squared=0.0, n_pairs=n)
    if xx_var == 0:
        # All x identical; return the mean-y as intercept with slope=0.
        return SpreadScalerFit(slope=0.0, intercept=y_mean, r_squared=0.0, n_pairs=n)
    xy_cov = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True))
    slope = xy_cov / xx_var
    intercept = y_mean - slope * x_mean
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys, strict=True))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return SpreadScalerFit(
        slope=slope,
        intercept=intercept,
        r_squared=r_squared,
        n_pairs=n,
    )
