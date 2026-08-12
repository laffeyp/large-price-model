# Sprint 032 -- evaluation (metrics + regimes + drift)

---

```yaml
---
id: 032
status: closed
phase: 2
pass_kind: functional
determinism_budget: bit-deterministic
---
```

---

## scope

Build the offline evaluator. Reads a Sprint 031 checkpoint, reconstructs the model, iterates every valid window in each split (deterministic; no random sampling), computes the seven real metrics per regime, emits every evaluate-category vocabulary tag, writes `artifacts/{run_id}/metrics.json` with a sha256, and un-lies Sprint 031's placeholder val_ece / val_brier / val_rps in the trainer's `CHECKPOINT_WRITTEN` payload.

## halt-and-articulate

**1. VIX substitution.** `REGIME_LABELS_FROZEN.note` says "VIX terciles." Sprint 023's probe dropped VIX (`^VIX` refused by Alpha-Vantage `TIME_SERIES_INTRADAY`). Sprint 032 uses `target__SPY__rolling_std_20` as a realized-volatility proxy. The v0.3 payload carries no "which proxy" field; the substitution lives in the module docstring, this card, and BLACKBOARD's drift-watchlist. A real-VIX rerun replaces the proxy when Databento or similar lands intraday VIX.

**2. Test partition absent.** The `Split` enum covers `{train, val, test}`. June 2024 tokens split 80/20 give 415 train + 104 val; no test. Sprint 032 emits per-metric per-regime for `train` and `val` only. Test partition lands with multi-month tokens (Sprint 033+).

**3. Hard rule 6 stretch.** Four code files (`__init__.py`, `metrics.py`, `regimes.py`, `evaluate.py`) + CLI + two test files. Same class of stretch as Sprint 031 -- one delivery, one smoke, inseparable.

**4. Baselines + W&B deferred.** `BASELINE_COMPARISON_ASSESSED` needs a second run (linear / mlp / gru_tcn) -- Sprint 033 candidate. `WANDB_UPLOAD_FAILED` needs W&B integration -- later. Both filed as adjacent scope, not this sprint.

---

## signal contract

### Emits per evaluation run

- `SESSION_INIT` with `run_kind=eval` (first live at this run_kind).
- `CONFIG_RESOLVED` at open.
- `REGIME_LABELS_FROZEN` once, with fitted terciles + training range.
- `METRIC_COMPUTED` x 7 metrics x n_splits x 3 regimes. At n_splits=2 (train+val), 42 emits.
- `BUCKET_FREQUENCY_DRIFT_MEASURED` on the val split, pooled across regimes.
- `METRIC_SNAPSHOT_WRITTEN` once per split, all with the same sha256 (the file is one JSON).
- `SESSION_COMPLETE`.

### Invariants

- Deterministic: no random sampling in the eval loop. Every valid start position contributes exactly one (input, target) window. Same checkpoint + same tokens → identical `sha256` in `METRIC_SNAPSHOT_WRITTEN`. Test proves it via two runs.
- Regime label falls at the target position (`s + context_len`), not the input positions -- the label of the bar we predict INTO, matching tech-arch intent.
- Frozen thresholds: computed once on training-window rolling_std_20; applied unchanged to val.

---

## artifact contract

### Files created

- `src/price_space_llm/evaluation/__init__.py`
- `src/price_space_llm/evaluation/metrics.py` (~150 lines: nll, top-k, dir_acc, brier, rps, ece, metric_set, bucket_frequency_drift)
- `src/price_space_llm/evaluation/regimes.py` (~50 lines: fit_regime_thresholds, assign_regime)
- `src/price_space_llm/evaluation/evaluate.py` (~280 lines: end-to-end run_evaluation)
- `scripts/evaluate.py` (~110 lines)
- `tests/test_metrics.py` (17 tests, 2 Hypothesis)
- `tests/test_evaluator.py` (10 tests including end-to-end + determinism)

### Files modified

- `src/price_space_llm/model/trainer.py` -- `_compute_val_metrics` rewired to call `compute_metric_set`. The `val_ece`/`val_brier`/`val_rps` placeholders Sprint 031 shipped are now real numbers from the same code path the offline evaluator uses.

### Command exit codes

- ruff, ruff format, mypy, pytest all green.
- Test count 159 -> 187 (+28).

### Live smoke

```
CHECKPOINT=$(ls artifacts/checkpoints/*.pt | head -1)
FEATURES=data/features/features-align-2024-06-0000000000000000-0000000000000000.parquet
TOKENS=data/tokenized/tokenize-features-align-2024-06-0000000000000000-0000000000000000-0000000000000000.parquet
uv run python scripts/evaluate.py --checkpoint "$CHECKPOINT" --tokens "$TOKENS" --features "$FEATURES"
```

Verified: exit 0 in 0.09s. Trace: SESSION_INIT + CONFIG_RESOLVED + REGIME_LABELS_FROZEN + 42x METRIC_COMPUTED + BUCKET_FREQUENCY_DRIFT_MEASURED + 2x METRIC_SNAPSHOT_WRITTEN + SESSION_COMPLETE. `artifacts/{run_id}/metrics.json` written with sha256'd body.

Val metrics per regime (all real, no placeholders):
- high: nll=3.528 ece=0.095 top1=0.000 n=20
- low: nll=3.601 ece=0.084 top1=0.000 n=6
- mid: nll=3.481 ece=0.098 top1=0.000 n=14

Drift: max_absolute_deviation=0.065, outer_bucket_ratio=1.035 (val tails 3.5% heavier than train's -- expected on a 519-token pooled fit).

Re-run of the training smoke confirms Sprint 031's placeholders un-lied:
`CHECKPOINT_WRITTEN` step 25 now carries `ece=0.067, brier=0.982, rps=0.180` instead of `0.0, 0.0, 0.0`.

---

## observation contract

Required. Live smoke ran. Two Hypothesis property tests over metric bounds. One determinism test comparing sha256 across paired runs.

---

## honest audit

**What actually landed.** Every metric implementation is real math (not a placeholder). ECE uses the standard Guo-2017 binned formulation. Brier is per-example squared-error to one-hot. RPS is the ranked-probability score with `(V-1)` normalisation. Regime labels use the tech-arch-prescribed tercile split, applied to the SPY-rolling-std proxy for the same reason the vocabulary declares the mechanism -- the label of the bar we predict into.

**Two dishonest paths avoided.** (a) The vocabulary requires `regime_label ∈ {low, mid, high}` on every `METRIC_COMPUTED`. Skipping regimes (or emitting a fake "all") would have violated the entity_ref. Real fix: partition positions by regime and emit 42 times. (b) The Sprint 031 `CHECKPOINT_WRITTEN` shipped `val_ece = val_brier = val_rps = 0.0` under a docstring that promised Sprint 032 would un-lie them. Sprint 032 un-lies them by importing the same code path the evaluator uses. Both `CHECKPOINT_WRITTEN` and offline `METRIC_COMPUTED` now agree bit-for-bit at the arithmetic level.

**Ruff / mypy findings surfaced during writing.** Multiple long docstring lines with the `x` multiplication symbol tripped RUF002. Batch-replaced to plain `x` + `->`. Numpy stubs required `python_version = 3.12` (Sprint 031 finding, still holds). No new dep beyond Sprint 031.

**One design choice worth naming.** `_partition_positions_by_regime` uses the volatility at the TARGET position (`s + context_len`) as the regime label. This is the regime of the bar we predict into, not the bars we predict from. Matches the tech-arch intent (regime is a property of the prediction event, not the input window). Alternative would be averaging over the input window; noted in the code comment.

---

## notes

**Small val partition.** June 2024's 104 val tokens partitioned across 3 regimes give 6/14/20 examples per regime. Statistical noise is huge; a Reviewer should not conclude "high-regime NLL beats mid-regime" from Sprint 032's numbers. The point of Sprint 032 is that the METRICS FIRE and CARRY REAL NUMBERS, not that the numbers are conclusive. Multi-month tokens (Sprint 033+) grow the sample.

**Baseline comparison unblocked but not filed.** With the evaluator producing real `val_nll` per split, the next honest step is Sprint 033: baselines (linear / mlp / gru_tcn / target_only / magnitude_weighted) with the same tokens + same eval pass, then `BASELINE_COMPARISON_ASSESSED` fires with `delta_pct` and `meets_gate` per the product-spec pre-registration.

---

## plan-mode review checklist

- [x] Scope one paragraph, one concept (offline evaluator + un-lie Sprint 031 placeholders).
- [x] Hard rule 6 stretched; halt-and-articulate above.
- [x] Signal contract cites v0.3 tags with real emit sites.
- [x] Observation contract present (functional-band); live smoke command verified.
- [x] Determinism budget declared (bit-deterministic; test proves via sha256 across paired runs).

---

## close (2026-08-12)

Landed. Four evaluate-category tags emit from live code (`REGIME_LABELS_FROZEN`, `METRIC_COMPUTED`, `BUCKET_FREQUENCY_DRIFT_MEASURED`, `METRIC_SNAPSHOT_WRITTEN`). Trainer's `CHECKPOINT_WRITTEN` placeholders replaced with real val_ece / val_brier / val_rps. Test count 159 -> 187 (+28). Four tools green. Signals-drive: 43 of 56 tags now live.
