"""Kyle's-lambda kappa fit from intraday volume + returns, with bootstrap CI.

Model: `|log_return_t| = kappa * sqrt(volume_t / ADV_t) + noise`.

Rolling ADV over a 20-bar window. OLS on (`sqrt(volume/ADV)`, `|log_return|`)
pairs across the training window's intraday bars. Bootstrap N resamples
give kappa's standard error and 5th/95th percentile confidence interval.
`kappa_r2` reports the fit's goodness on the point estimate.

Kyle's lambda framework: price impact per unit sqrt-volume signal is a
canonical liquidity coefficient in market microstructure (Kyle 1985, plus
Almgren-Chriss 2000 for the sqrt scaling). Positive kappa: buying pressure
moves price up. Higher kappa = shallower book = harder to trade in size.
"""

import math
from dataclasses import dataclass

import torch
from torch import Tensor


@dataclass(slots=True, frozen=True, kw_only=True)
class KappaFit:
    kappa_point: float
    kappa_se: float
    kappa_ci_low: float
    kappa_ci_high: float
    kappa_r2: float
    n: int


def _rolling_mean(values: list[float], window: int) -> list[float | None]:
    """Trailing mean of length `window`. First `window - 1` outputs are None."""
    out: list[float | None] = []
    acc = 0.0
    for i, v in enumerate(values):
        acc += v
        if i >= window:
            acc -= values[i - window]
        if i >= window - 1:
            out.append(acc / window)
        else:
            out.append(None)
    return out


def _pair_signals(
    close_prices: list[float],
    volumes: list[float],
    adv_window: int,
) -> list[tuple[float, float]]:
    """Return (sqrt(volume/ADV), |log_return|) pairs. Drops rows with insufficient history."""
    if len(close_prices) != len(volumes):
        raise ValueError(
            f"close_prices and volumes have different lengths: "
            f"{len(close_prices)} vs {len(volumes)}"
        )
    adv = _rolling_mean(volumes, adv_window)
    pairs: list[tuple[float, float]] = []
    for i in range(1, len(close_prices)):
        prev = close_prices[i - 1]
        curr = close_prices[i]
        if prev <= 0 or curr <= 0:
            continue
        adv_i = adv[i]
        if adv_i is None or adv_i <= 0:
            continue
        vol_ratio = volumes[i] / adv_i
        if vol_ratio < 0:
            continue
        x = math.sqrt(vol_ratio)
        y = abs(math.log(curr / prev))
        if not (math.isfinite(x) and math.isfinite(y)):
            continue
        pairs.append((x, y))
    return pairs


def _ols_no_intercept(pairs: list[tuple[float, float]]) -> tuple[float, float]:
    """OLS through the origin: y = kappa * x. Returns (kappa, r_squared)."""
    n = len(pairs)
    if n == 0:
        return 0.0, 0.0
    xs = torch.tensor([p[0] for p in pairs], dtype=torch.float64)
    ys = torch.tensor([p[1] for p in pairs], dtype=torch.float64)
    xy = float((xs * ys).sum().item())
    xx = float((xs * xs).sum().item())
    if xx == 0:
        return 0.0, 0.0
    kappa = xy / xx
    predicted = kappa * xs
    residuals = ys - predicted
    ss_res = float((residuals * residuals).sum().item())
    y_mean = float(ys.mean().item())
    ss_tot = float(((ys - y_mean) ** 2).sum().item())
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return kappa, r_squared


def _bootstrap_kappa(
    pairs: list[tuple[float, float]],
    n_bootstrap: int,
    seed: int,
) -> Tensor:
    """Return a 1-D tensor of `n_bootstrap` kappa estimates from resampled pairs."""
    n = len(pairs)
    xs = torch.tensor([p[0] for p in pairs], dtype=torch.float64)
    ys = torch.tensor([p[1] for p in pairs], dtype=torch.float64)
    generator = torch.Generator()
    generator.manual_seed(seed)
    kappas = torch.empty(n_bootstrap, dtype=torch.float64)
    for i in range(n_bootstrap):
        idx = torch.randint(0, n, (n,), generator=generator)
        x_r = xs[idx]
        y_r = ys[idx]
        xy = float((x_r * y_r).sum().item())
        xx = float((x_r * x_r).sum().item())
        kappas[i] = xy / xx if xx > 0 else 0.0
    return kappas


def fit_kappa(
    close_prices: list[float],
    volumes: list[float],
    adv_window: int = 20,
    n_bootstrap: int = 500,
    seed: int = 0,
) -> KappaFit:
    """Full Kyle's-lambda fit with bootstrap SE + 5th/95th CI."""
    pairs = _pair_signals(close_prices, volumes, adv_window)
    n = len(pairs)
    if n < 10:
        raise ValueError(f"need >= 10 (sqrt(vol/ADV), |log_return|) pairs for a bootstrap; got {n}")
    kappa_point, r_squared = _ols_no_intercept(pairs)
    kappas = _bootstrap_kappa(pairs, n_bootstrap, seed)
    kappa_se = float(kappas.std(unbiased=True).item())
    quantiles = torch.quantile(kappas, torch.tensor([0.05, 0.95], dtype=torch.float64))
    return KappaFit(
        kappa_point=kappa_point,
        kappa_se=kappa_se,
        kappa_ci_low=float(quantiles[0].item()),
        kappa_ci_high=float(quantiles[1].item()),
        kappa_r2=r_squared,
        n=n,
    )
