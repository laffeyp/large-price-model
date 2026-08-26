# Sprint 093 -- PREDICTION_EMITTED per bar (roadmap 075 part 1)

---

```yaml
---
id: 093
status: closed
phase: F
pass_kind: functional
determinism_budget: statistically-deterministic
---
```

## scope

Wire the model into the walker: load a Sprint 053 market-state checkpoint + Sprint 056 `bucket_stats.json`, iterate bars in the Sprint 052 `.pt` in grid order, and emit `PREDICTION_EMITTED` per bar. Roadmap 075 splits across Sprints 093-096 to stay under hard rule 6; Sprint 093 lands prediction only. Sprint 094 lands decision policy + `DECISION_MADE` + `SIGNAL_DROPPED`; Sprint 095 lands position tracking + trades (`POSITION_OPENED`, `POSITION_CLOSED`, `TRADE_LEDGERED`); Sprint 096 lands metrics + block bootstrap.

## deliverables

- `src/price_space_llm/simulation/prediction.py` — new module:
  - `derive_prediction_scalars(probs, bucket_train_means, realized_vol) -> PredictionScalars` computing `expected_vn_return`, `expected_return`, `p_up`, `sharpness`, `entropy` from a `[V]` softmax distribution + `[V]` per-bucket-mean vector (Sprint 056 field) + a scalar `realized_vol` for the bar (Sprint 052's `vol` field on the tokenized artifact).
  - `PredictionScalars` dataclass carrying the five values.
  - Uses stdlib `math` + `torch` primitives; no scipy.
- Extend `src/price_space_llm/simulation/skeleton.py`:
  - `run_simulation_with_predictions(artifact, model, bucket_stats, *, split, date_range_start, date_range_end, emitter, run_id, checkpoint_run_id, cost_calibration_run_id, context_len)`:
    - Emits `SIM_RUN_STARTED`.
    - For each valid start position `s` in the .pt, slices feats over `[s, s+context_len)`, forwards, takes last-position softmax → `probs`, calls `derive_prediction_scalars`, emits `PREDICTION_EMITTED` with the four required payload scalars, emits `BAR_PROCESSED`.
    - Emits `SIM_RUN_COMPLETED` with zeros for the trade-side summary fields (Sprint 095+ fills them).
    - Returns `SimResult(n_bars_processed=N, n_trades=0, notes="predictions-only")`.
- `scripts/simulate.py` gains `--tokens-pt PATH` + `--checkpoint PATH` + `--bucket-stats PATH` (all required for the predictions path; mutually exclusive with skeleton-only path via a check).
- Tests in `tests/test_simulation_prediction.py`.

## tests (+6)

1. `test_derive_prediction_scalars_uniform_distribution` — uniform probs over V=4 buckets, means [-1, -0.5, 0.5, 1] → `expected_vn_return = 0`, `p_up = 0.5`, `entropy = ln(4)`, `sharpness = 0`.
2. `test_derive_prediction_scalars_confident_up` — probs = [0, 0, 0, 1], means [-1, -0.5, 0.5, 1] → `expected_vn_return = 1`, `p_up = 1.0`, `entropy = 0`, `sharpness = 1.0`.
3. `test_derive_prediction_scalars_expected_return_scales_by_vol` — same distribution at two different `realized_vol` values → `expected_return` scales linearly.
4. `test_derive_prediction_scalars_p_up_matches_upper_half_mass` — asymmetric distribution; p_up equals sum over the upper half.
5. `test_run_simulation_with_predictions_emits_per_bar` — synthetic .pt + tiny checkpoint + tiny bucket_stats; N-context-len valid bars → N-context-len PREDICTION_EMITTED emits between SIM_RUN_STARTED and SIM_RUN_COMPLETED.
6. `test_simulate_cli_predictions_smoke_on_synthetic` — subprocess `scripts/simulate.py --tokens-pt <syn> --checkpoint <syn> --bucket-stats <syn>` exits 0; trace shows the full prediction sequence.

## context files

- `src/price_space_llm/model/transformer.py` (MarketStateTransformer forward)
- `src/price_space_llm/model/dataset.py` (TokenizedArtifact)
- `src/price_space_llm/tokenizer/bucketize.py` (BucketStats / BucketRow)
- `src/price_space_llm/evaluation/evaluate.py` (`_load_market_state_checkpoint` — reuse pattern)
- `src/price_space_llm/simulation/skeleton.py`
- `scripts/simulate.py`
- `specs/technical-architecture-v4.md` § 11

## artifact contract

Files created or modified:

- `src/price_space_llm/simulation/prediction.py` — new.
- `src/price_space_llm/simulation/__init__.py` — modified: export `PredictionScalars`, `derive_prediction_scalars`, `run_simulation_with_predictions`.
- `src/price_space_llm/simulation/skeleton.py` — modified: add `run_simulation_with_predictions` alongside the existing skeleton.
- `scripts/simulate.py` — modified: three new flags + branch on whether the checkpoint set is passed.
- `tests/test_simulation_prediction.py` — new.

Content assertions:

- `grep -q "def derive_prediction_scalars" src/price_space_llm/simulation/prediction.py`
- `grep -q "run_simulation_with_predictions" src/price_space_llm/simulation/skeleton.py`
- `grep -q "\\-\\-checkpoint" scripts/simulate.py`

## signal contract

Emits: `SIM_RUN_STARTED`, `PREDICTION_EMITTED`, `BAR_PROCESSED`, `SIM_RUN_COMPLETED`. All four in v0.7 vocabulary. `PREDICTION_EMITTED` payload has five required scalars (timestamp + four floats); every field is computed live from the model output + bucket stats, not fabricated.

## observation contract

REQUIRED — new signal (PREDICTION_EMITTED) fires for the first time in live code.

- **Input:** synthetic .pt + tiny transformer checkpoint + tiny bucket_stats.
- **Expected trace:** `[SIM_RUN_STARTED, PREDICTION_EMITTED × N, BAR_PROCESSED × N, SIM_RUN_COMPLETED]` OR interleaved per-bar.
- **Expected behavior:** every `PREDICTION_EMITTED` payload's `expected_vn_return` and `expected_return` land as finite floats; `p_up ∈ [0, 1]`; `entropy ∈ [0, log(V)]`; `sharpness ∈ [0, 1]`.

## commands

```
uv run ruff check .
uv run mypy
uv run pytest -q
```

## notes

- 3 code files + 1 test file. Under hard rule 6.
- Cost model consumption still deferred — Sprint 094 wires it into `DECISION_MADE.edge`. Sprint 093 emits PREDICTION_EMITTED only.
- Sprint 095 lands the position state machine + trades. Sprint 096 lands metrics + block bootstrap.
- Bucket-training-mean semantics: `BucketRow.train_mean` (Sprint 056) is the per-bucket mean of log_return / realized_vol_30 on the training partition; already in vol-normalized units. `expected_vn_return = sum(p_i * train_mean_i)`; `expected_return = expected_vn_return * realized_vol`.
