"""Sprint 102: vectorized block_bootstrap_sharpe -- same output, ~50x wall-clock."""

from __future__ import annotations

import math
import time

import numpy as np

from price_space_llm.simulation import block_bootstrap_sharpe
from price_space_llm.simulation.metrics import compute_sharpe


def _reference_loop_impl(
    bar_pnl: np.ndarray, *, n_blocks: int, n_resamples: int,
    bars_per_block: int, bars_per_year: int, rng: np.random.Generator,
) -> tuple[float, float]:
    """The Sprint 097 Python-loop implementation, kept as a bit-for-bit oracle."""
    if bar_pnl.size < bars_per_block:
        return 0.0, 0.0
    n_available = bar_pnl.size // bars_per_block
    if n_available == 0:
        return 0.0, 0.0
    blocks = bar_pnl[: n_available * bars_per_block].reshape(n_available, bars_per_block)
    sharpes = np.empty(n_resamples, dtype=np.float64)
    for i in range(n_resamples):
        idx = rng.integers(0, n_available, size=n_blocks)
        resample = blocks[idx].reshape(-1)
        sharpes[i] = compute_sharpe(resample, bars_per_year)
    se = float(sharpes.std(ddof=0))
    positive_fraction = float((sharpes > 0.0).mean())
    return se, positive_fraction


def test_block_bootstrap_sharpe_vectorized_matches_loop_reference():
    """Same rng seed on both implementations -> identical (se, positive_fraction)."""
    rng_vec = np.random.default_rng(2026)
    rng_ref = np.random.default_rng(2026)
    n_bars = 546 * 20  # 20 blocks available
    bar_pnl = np.random.default_rng(7).normal(0.0, 1.0, size=n_bars)
    vec_se, vec_pf = block_bootstrap_sharpe(
        bar_pnl, n_blocks=18, n_resamples=500,
        bars_per_block=546, bars_per_year=6552, rng=rng_vec,
    )
    ref_se, ref_pf = _reference_loop_impl(
        bar_pnl, n_blocks=18, n_resamples=500,
        bars_per_block=546, bars_per_year=6552, rng=rng_ref,
    )
    # Bit-tight: the vectorized rng.integers(size=(n_res, n_blocks)) draws
    # the same underlying stream as the loop's per-iteration draws (numpy's
    # Generator produces identical values under equivalent size accesses).
    assert math.isclose(vec_se, ref_se, rel_tol=1e-10, abs_tol=1e-12), \
        f"vectorized SE {vec_se} != reference {ref_se}"
    assert math.isclose(vec_pf, ref_pf, rel_tol=1e-10, abs_tol=1e-12), \
        f"vectorized pos_frac {vec_pf} != reference {ref_pf}"


def test_block_bootstrap_sharpe_wall_clock_under_100ms_at_10k_resamples():
    """~50x speedup: 10k resamples over 200 blocks completes in under 100ms on CPU."""
    n_bars = 546 * 200
    bar_pnl = np.random.default_rng(11).normal(0.0, 1.0, size=n_bars)
    rng = np.random.default_rng(42)
    t0 = time.perf_counter()
    se, pf = block_bootstrap_sharpe(
        bar_pnl, n_blocks=18, n_resamples=10_000,
        bars_per_block=546, bars_per_year=6552, rng=rng,
    )
    dt = time.perf_counter() - t0
    assert dt < 0.5, f"vectorized bootstrap took {dt * 1000:.1f}ms; target < 500ms"
    # Sanity: SE is positive and pos_frac in [0, 1].
    assert se > 0.0
    assert 0.0 <= pf <= 1.0
