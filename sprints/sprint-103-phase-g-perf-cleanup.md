# Sprint 103 -- Phase-G perf cleanup: vectorize prices + searchsorted + cached train_means + Literal kind

---

```yaml
---
id: 103
status: closed
phase: G
pass_kind: performance
determinism_budget: bit-deterministic
---
```

## scope

Four mechanical cleanups from the Phase F review that pay back at sweep scale but do not change any output. All are pure accumulator swaps or type tightenings.

- §3.1 vectorize `derive_prices_from_log_returns` -- `torch.where(isfinite, r, 0)` + `cumsum` + `exp` in one shot.
- §3.3 `searchsorted` in `build_equity_curve` -- `numpy.searchsorted(sorted_bar_ts, exit_epochs)` in one call, both branches (step-function and mark-to-market).
- §3.4 cached `train_means_tensor` on `BucketStats` -- `@cached_property` produces the `[V]` tensor once; walker + policy call sites read from it.
- §2.68 `SimResult.notes` typed as `Literal["skeleton", "predictions", "policy", "trades"]` -- string field doing enum work becomes a checkable discriminator.

## deliverables

- `src/price_space_llm/simulation/positions.py` -- rewrite `derive_prices_from_log_returns`:
  ```python
  safe = torch.where(torch.isfinite(raw_targets), raw_targets, torch.zeros_like(raw_targets))
  log_prices = torch.cumsum(safe, dim=0)
  return torch.exp(log_prices).to(torch.float64)
  ```
  Semantically identical to the loop: NaN log-return -> zero -> price unchanged. `p_0 = exp(safe[0])` which equals `1.0 * exp(safe[0])` -- matches the loop's `running = 1.0` anchor and first-multiply.
- `src/price_space_llm/simulation/metrics.py` -- rewrite the trade loops in `build_equity_curve` to compute `exit_indices = np.searchsorted(sorted_bar_ts, exit_epochs, side='right')` once. Per-trade unrealized loops remain (they slice per open interval); the O(n_trades × log n_bars) → O(n_trades + log n_bars) win lands at the exit-index computation.
- `src/price_space_llm/tokenizer/bucketize.py` -- add `@cached_property train_means_tensor` on `BucketStats`. Read call sites in `skeleton.py` and `policy.py` (via `variance_vn` callers) switch from constructing the tensor per bar to reading the cached property.
- `src/price_space_llm/simulation/skeleton.py` -- read `bucket_stats.train_means_tensor` instead of constructing `torch.tensor([row.train_mean for row in per_bucket], ...)` in every walker (three sites: `run_simulation_with_predictions`, `run_simulation_with_policy`, `run_simulation_with_trades`).
- `src/price_space_llm/simulation/skeleton.py` -- narrow `SimResult.notes` type: `notes: Literal["skeleton", "predictions", "policy", "trades"] = "skeleton"`.

## tests (+5)

1. `test_derive_prices_from_log_returns_vectorized_matches_loop_reference` -- 100-bar input with mixed NaN + finite log-returns; assert the vectorized output matches the Sprint 096 loop implementation bit-tight.
2. `test_derive_prices_from_log_returns_first_bar_holds_running_at_exp_of_first_return` -- verify `prices[0] == math.exp(raw[0])` on a finite-first-return input; on a NaN-first-return input, `prices[0] == 1.0`.
3. `test_bucket_stats_train_means_tensor_cached` -- two accesses return the same tensor object identity (`is`).
4. `test_build_equity_curve_searchsorted_matches_bisect_loop` -- hand-computed multi-trade ledger; vectorized `exit_indices` matches per-trade `bisect_right` iteration.
5. `test_sim_result_notes_rejects_arbitrary_string` -- mypy check via `assert_type` (no runtime enforcement without extra deps; a comment records the discriminator intent).

## artifact contract

Files created or modified:

- `src/price_space_llm/simulation/positions.py` -- rewrite one function.
- `src/price_space_llm/simulation/metrics.py` -- rewrite two loop patterns.
- `src/price_space_llm/tokenizer/bucketize.py` -- add cached property.
- `src/price_space_llm/simulation/skeleton.py` -- three walker call sites + notes type.
- `tests/test_simulation_perf_cleanup.py` -- new.
- 4 code files + 1 test file. Under hard rule 6.

Content assertions:

- `grep -q "torch.cumsum" src/price_space_llm/simulation/positions.py`
- `grep -q "np.searchsorted" src/price_space_llm/simulation/metrics.py`
- `grep -q "train_means_tensor" src/price_space_llm/tokenizer/bucketize.py`

## signal contract

No new tags. Every payload field carries the same value it did in Sprint 102. Pure accumulator swaps.

## observation contract

Re-run Sprint 100 smoke; assert every metric field matches Sprint 100's output to `1e-10`.

## commands

```
uv run ruff check .
uv run mypy
uv run pytest -q
```

## notes

- 4 code files + 1 test file. Under hard rule 6.
- Sprint 104 next: structural cleanups -- extract position helpers from `skeleton.py` (~130 lines) to `positions.py`; author shared axis-sweep helper for `capacity.py` + `sensitivity.py`.
- Sprint 105: walker → hooks refactor (§2 main). Bigger diff; own sprint arc.
