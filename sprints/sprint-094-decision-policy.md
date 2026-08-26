# Sprint 094 -- decision policy: DECISION_MADE + SIGNAL_DROPPED (roadmap 075 part 2)

---

```yaml
---
id: 094
status: closed
phase: F
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Add the decision rule per tech-arch § 11.4. Consumes each bar's PREDICTION_EMITTED scalars + a cost model + a risk penalty; produces `direction ∈ {long, short, flat}` with hysteresis; emits `DECISION_MADE` per bar and `SIGNAL_DROPPED` per flip that hysteresis suppresses. Roadmap 075 part 2. Sprint 095 lands the position state machine + trades; Sprint 094 tracks a scalar `current_direction` across bars — direction only, no size / entry price / P&L.

Edge formula (spec § 11.4, expressed in vol-normalized units for the payload):

```
edge = expected_vn_return
       - (spread_cost_frac + slippage_frac) / realized_vol
       - lambda_risk * variance_vn
```

`expected_vn_return`, `variance_vn` come from the same softmax + BucketStats used by Sprint 093's `derive_prediction_scalars`. `realized_vol` is the bar's `vol` field. Cost inputs are constants for now (Sprint 093's rescope note): `spread_cost_frac` and `slippage_frac` land as CLI flags. Sprint 097+ (kappa sensitivity) rescales slippage per bar.

## deliverables

- `src/price_space_llm/simulation/policy.py` — new module:
  - `PolicyConfig` dataclass carrying `threshold: float`, `hysteresis: float` (0.0 → no hysteresis), `lambda_risk: float`, `spread_cost_frac: float`, `slippage_frac: float`, `position_size_usd: float` (signed size the CLI reports; Sprint 095 adjusts).
  - `Decision` dataclass carrying `direction: str`, `size: float`, `edge: float`, `effective_threshold: float`, `reason: str`.
  - `compute_edge(expected_vn_return, variance_vn, realized_vol, spread_cost_frac, slippage_frac, lambda_risk) -> float`.
  - `variance_vn(probs, bucket_train_means) -> float` — `Σ p_i × mean_i² − (Σ p_i × mean_i)²`, NaN-safe like Sprint 093.
  - `decide(prev_direction, edge, policy) -> Decision` — flat if `|edge| < threshold`; long/short if past threshold in respective direction. Hysteresis: to flip direction, `|edge|` must exceed `threshold × (1 + hysteresis)`; otherwise decision holds `prev_direction` with `reason="hysteresis_hold"` and the caller emits `SIGNAL_DROPPED(dropped_reason="hysteresis_below_flip_threshold")`.
- Extend `src/price_space_llm/simulation/skeleton.py`:
  - `run_simulation_with_policy(artifact, model, bucket_stats, policy, *, emitter, run_id, checkpoint_run_id, cost_calibration_run_id, split, date_range_start, date_range_end)` — same walker shape as Sprint 093's `run_simulation_with_predictions` but adds `DECISION_MADE` per bar and `SIGNAL_DROPPED` per hysteresis-suppressed flip. `current_direction` starts `flat`; updates on real flips only.
- `simulation/__init__.py` exports `PolicyConfig`, `Decision`, `compute_edge`, `variance_vn`, `decide`, `run_simulation_with_policy`.
- `scripts/simulate.py` gains `--threshold`, `--hysteresis`, `--lambda-risk`, `--spread-cost-frac`, `--slippage-frac`, `--position-size-usd`; when present the CLI uses `run_simulation_with_policy`; without them it stays on `run_simulation_with_predictions` (Sprint 093 default).

## tests (+9)

1. `test_variance_vn_uniform_symmetric_returns_second_moment` — uniform on symmetric means → variance = mean(means²).
2. `test_variance_vn_confident_zero_variance` — point mass → 0.
3. `test_variance_vn_ignores_nan_train_means` — matches Sprint 093 semantics.
4. `test_compute_edge_reduces_to_expected_vn_when_costs_zero` — cost = 0, lambda_risk = 0 → edge = expected_vn_return.
5. `test_compute_edge_subtracts_cost_over_vol` — cost 5 bps, vol 0.01 → subtracts 0.05 vn units.
6. `test_decide_flat_below_threshold` — edge = 0.001, threshold = 0.1 → flat.
7. `test_decide_long_above_threshold` — edge = 0.5, threshold = 0.1, prev flat → long.
8. `test_decide_hysteresis_hold_between_threshold_and_effective_threshold` — prev long, edge = -0.11, threshold = 0.1, hysteresis = 0.5 → hold long (`|edge| = 0.11 < 0.15 = threshold * 1.5`); reason `hysteresis_hold`.
9. `test_run_simulation_with_policy_emits_decision_per_bar_and_dropped_on_hysteresis_flip` — synthetic .pt + tiny model + hand-tuned bucket stats produce a scripted flip-attempt; verify `DECISION_MADE` count == bars processed and `SIGNAL_DROPPED` count > 0 (real hysteresis holds happen on scripted inputs).

## context files

- `src/price_space_llm/simulation/prediction.py`
- `src/price_space_llm/simulation/skeleton.py`
- `specs/technical-architecture-v4.md` § 11.4
- BLACKBOARD 2026-08-17 Sprint 093 close

## signal contract

Emits: `DECISION_MADE` (event, seven required payload fields per v0.7); `SIGNAL_DROPPED` (incident, two required fields per v0.7). Both exist in vocabulary since v0.1. Sprint 094 fires only the `hysteresis_below_flip_threshold` reason on SIGNAL_DROPPED; Sprint 095 (position state) fires `same_direction_position_held`.

## observation contract

REQUIRED — two new emit sites fire from live code for the first time.

- **Input:** synthetic .pt + tiny model + tiny bucket_stats + `PolicyConfig(threshold=0.1, hysteresis=0.5, lambda_risk=0.0, spread_cost_frac=0.0001, slippage_frac=0.0, position_size_usd=1_000_000.0)`.
- **Expected:** `DECISION_MADE` fires per bar; `SIGNAL_DROPPED` fires per hysteresis-hold flip. Every `DECISION_MADE.direction` ∈ {"long","short","flat"}; every `.reason` in the four-element enum; every `.size` signed to match the direction.
- **Live smoke on real corpus:** 10-step xs checkpoint (Sprint 093 fixture); walk 200 bars; report `DECISION_MADE` distribution across the three directions + `SIGNAL_DROPPED` count.

## commands

```
uv run ruff check .
uv run mypy
uv run pytest -q
```

## notes

- 3 code files + 1 test file. Under hard rule 6 for the ablation-infrastructure precedent.
- `variance_vn` lands in `policy.py` even though it is conceptually a prediction-layer helper — placing it beside `compute_edge` keeps the risk-penalty math in one file. Sprint 095+ can promote to `simulation/prediction.py` if a second consumer appears.
- Cost model still a two-constant knob (spread + slippage). Sprint 097's kappa sensitivity plot rescales `slippage_frac` by `kappa × size` per bar.
- `size` in `DECISION_MADE.size` payload uses signed `position_size_usd`: `+size` long, `-size` short, `0` flat. Sprint 095's position tracking scales this by real notional per trade.
- Named on card: `DECISION_MADE` payload's `reason` enum has `position_held`; Sprint 094 fires it when `intended_direction == prev_direction` (holding what we have). That is not a "signal dropped" — nothing was dropped, the previous direction continues.
