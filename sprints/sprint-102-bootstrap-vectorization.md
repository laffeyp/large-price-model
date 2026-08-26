# Sprint 102 -- vectorize block_bootstrap_sharpe (review §3.2)

---

```yaml
---
id: 102
status: closed
phase: F.close
pass_kind: performance
determinism_budget: bit-deterministic
---
```

## scope

Replace the 10,000-iteration Python loop in `block_bootstrap_sharpe` with a one-pass numpy vectorization. Same `numpy.random.Generator` seed produces the same output — this is a rewrite of the accumulator, not a change of algorithm.

Review §3.2: "Bootstrap goes from ~0.5s to ~0.01s on a typical held-out run. Multiply by sweep size (six sizes × two ablations × four size configs × 3-look budget) and the win compounds."

## deliverables

- `src/price_space_llm/simulation/metrics.py` -- rewrite `block_bootstrap_sharpe`:
  - `idx = rng.integers(0, n_available, size=(n_resamples, n_blocks))`
  - `resamples = blocks[idx].reshape(n_resamples, n_blocks * bars_per_block)`
  - `means = resamples.mean(axis=1)`
  - `stds = resamples.std(axis=1, ddof=0)`
  - `sharpes = np.where(stds > 0, sqrt(bars_per_year) * means / stds, 0.0)`
  - `se = float(sharpes.std(ddof=0))`
  - `positive_fraction = float((sharpes > 0.0).mean())`
- Zero-std handling matches `compute_sharpe`'s guard: per-resample zero-std -> Sharpe 0.0.

## tests (+2)

1. `test_block_bootstrap_sharpe_vectorized_matches_loop_reference` -- author a small reference loop implementation in the test, seed both with the same rng, assert `(se, positive_fraction)` match to `~1e-12`.
2. `test_block_bootstrap_sharpe_wall_clock_under_100ms_at_10k_resamples` -- 546-bar blocks × 200 available × 10,000 resamples completes in under 100ms.

## artifact contract

- `src/price_space_llm/simulation/metrics.py` -- edits only.
- `tests/test_simulation_bootstrap_vectorization.py` -- new.
- 1 code file + 1 test file. Well under hard rule 6.

Content assertions:

- `! grep -A5 'def block_bootstrap_sharpe' src/price_space_llm/simulation/metrics.py | grep -q 'for i in range'`

## signal contract

No new tags. `SIM_RUN_COMPLETED.sharpe_se` and `.block_bootstrap_positive_fraction` continue firing with the same numeric values (deterministic given rng seed).

## observation contract

Re-run Sprint 100 smoke; assert identical numeric output on `sharpe_se` and `block_bootstrap_positive_fraction`.

## commands

```
uv run ruff check .
uv run mypy
uv run pytest -q
```

## notes

- Same seed, same output. The Python loop dispatches `rng.integers(size=n_blocks)` once per iteration; vectorized form dispatches `rng.integers(size=(n_resamples, n_blocks))` once total. Numpy Generators produce identical values when `size` unifies the two access patterns, but the assertion in test 1 pins the equality bit-tight against a reference loop.
- 10,000 resamples per call × 6 sizes × 6 multipliers × K configs multiplies fast on the Sprint 084 GPU sweep. This is the single perf item the review flagged as "before Sprint 088."
