"""Corwin-Schultz two-day proportional-spread estimator + 2024 bias correction.

Sprint 091 (Phase F opens). Full-window `SpreadScaler` re-fit path chosen by
the 2026-08-17 Architect Decision (path (b) — CS on OHL + bias correction
against Sprint 035's 2024 known BBO). Path (a) Databento reserved for a
follow-up sprint after the first held-out evaluation reveals whether the
extra fidelity is worth the vendor cost.

Formula (Corwin & Schultz, Journal of Finance 2012):

    Given two consecutive bars (t-1, t) with highs H_1, H_2 and lows L_1, L_2:
        beta_t  = (ln(H_1 / L_1))**2 + (ln(H_2 / L_2))**2
        gamma_t = (ln(max(H_1, H_2) / min(L_1, L_2)))**2
        k1      = 4 * ln(2)          # = 2 * (2*ln(2))
        alpha_t = (sqrt(2 * beta_t) - sqrt(beta_t)) / (3 - 2*sqrt(2))
                  - sqrt(gamma_t / (3 - 2*sqrt(2)))
        S_t     = 2 * (exp(alpha_t) - 1) / (1 + exp(alpha_t))

`S_t` is a proportional spread estimate for the two-bar window ending at t.

Documented boundary behavior (paper § 3):
  * When alpha < 0 (usually a low-volatility bar where the two-day range
    doesn't cover the sum of one-day ranges) the estimator returns a
    negative spread; the paper recommends dropping those. This module
    returns `math.nan` for those pairs so the caller can filter cleanly.

Downward bias on sub-day intervals (Abdi-Ranaldo 2017): CS underestimates
true bid-ask spread on <1-day windows by 20-40% depending on the venue's
microstructure. The bias correction step below applies a scalar ratio
computed against Sprint 035's 2024 known SPY BBO, closing the mean-level
gap. Residual regime-dependent bias (worse on stress bars) is documented in
the v1 report's cost-model section per the Sprint 091 sprint card.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def corwin_schultz_spread(
    highs: list[float],
    lows: list[float],
) -> list[float]:
    """Return per-bar-pair Corwin-Schultz proportional spread estimates.

    Input `highs` and `lows` are per-bar OHL sequences of equal length N.
    Output is length N-1; index `i` in the output corresponds to the pair
    (bar i, bar i+1). Non-positive H or L produces `math.nan`; negative-alpha
    pairs also produce `math.nan` (paper's boundary recommendation).
    """
    if len(highs) != len(lows):
        raise ValueError(
            f"corwin_schultz_spread: highs and lows must be the same length; "
            f"got {len(highs)} vs {len(lows)}"
        )
    if len(highs) < 2:
        return []
    inv_denom = 1.0 / (3.0 - 2.0 * math.sqrt(2.0))
    out: list[float] = []
    for i in range(len(highs) - 1):
        h1, l1 = highs[i], lows[i]
        h2, l2 = highs[i + 1], lows[i + 1]
        if h1 <= 0 or l1 <= 0 or h2 <= 0 or l2 <= 0:
            out.append(math.nan)
            continue
        log_hl_1 = math.log(h1 / l1)
        log_hl_2 = math.log(h2 / l2)
        beta = log_hl_1 * log_hl_1 + log_hl_2 * log_hl_2
        h_max = max(h1, h2)
        l_min = min(l1, l2)
        log_hl_2day = math.log(h_max / l_min)
        gamma = log_hl_2day * log_hl_2day
        alpha = (
            (math.sqrt(2.0 * beta) - math.sqrt(beta)) * inv_denom
            - math.sqrt(gamma * inv_denom)
        )
        if alpha < 0:
            out.append(math.nan)
            continue
        exp_alpha = math.exp(alpha)
        s = 2.0 * (exp_alpha - 1.0) / (1.0 + exp_alpha)
        out.append(s)
    return out


@dataclass(slots=True, frozen=True, kw_only=True)
class BiasCorrection:
    """Scalar bias correction fitted against a ground-truth series.

    `ratio = mean(known) / mean(estimated)` — multiply CS estimates by
    `ratio` to close the mean-level gap. `n_known` and `n_estimated` count
    non-NaN entries used in the means; `provenance` names the ground-truth
    source (e.g. `"sprint035-2024-known-bbo"`).
    """

    ratio: float
    n_known: int
    n_estimated: int
    provenance: str


def _mean_ignore_nan(values: list[float]) -> tuple[float, int]:
    total = 0.0
    n = 0
    for v in values:
        if math.isnan(v):
            continue
        total += v
        n += 1
    if n == 0:
        raise ValueError("_mean_ignore_nan: no finite values")
    return total / n, n


def fit_bias_correction(
    known_bbo: list[float],
    cs_estimated: list[float],
    *,
    provenance: str,
) -> BiasCorrection:
    """Fit `ratio = mean(known) / mean(estimated)` over non-NaN entries.

    NaN entries in either series are dropped independently (means are
    computed over each series' finite entries). Raises if either series
    has zero finite values or if the estimated mean is non-positive.
    """
    known_mean, n_known = _mean_ignore_nan(known_bbo)
    est_mean, n_est = _mean_ignore_nan(cs_estimated)
    if est_mean <= 0:
        raise ValueError(
            f"fit_bias_correction: CS estimated mean is non-positive ({est_mean}); "
            "cannot compute ratio."
        )
    return BiasCorrection(
        ratio=known_mean / est_mean,
        n_known=n_known,
        n_estimated=n_est,
        provenance=provenance,
    )


def apply_bias_correction(
    cs_series: list[float], correction: BiasCorrection
) -> list[float]:
    """Elementwise multiply the CS series by the bias-correction ratio.

    NaN entries pass through unchanged. Output length matches input.
    """
    return [v if math.isnan(v) else v * correction.ratio for v in cs_series]


__all__ = [
    "BiasCorrection",
    "apply_bias_correction",
    "corwin_schultz_spread",
    "fit_bias_correction",
]
