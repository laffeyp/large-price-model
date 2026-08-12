# Sprint 026 — feature pipeline (strictly-causal rolling windows)

---

```yaml
---
id: 026
status: closed
phase: 1
pass_kind: functional
determinism_budget: bit-deterministic
---
```

---

## scope

Author `src/price_space_llm/features/{__init__.py, compute.py}` + `scripts/features.py`. Read an aligned parquet, compute four v1 features per channel with strictly-backward rolling windows (`log_return`, `rolling_mean_20`, `rolling_std_20`, `rolling_z_score_20`), emit `FEATURE_COMPUTED` on success and `FEATURE_COMPUTATION_FAILED` with honest enum reasons on failures, write `data/features/{run_id}.parquet`.

Tech-arch §6 alignment: every feature at time T sees only rows with `grid_ts <= T`. No forward references, no fill values (per the Sprint 023 correction).

---

## signal contract

### Emits

- `FEATURE_COMPUTED` ambient per (channel, feature, timestamp) with a non-null value.
- `FEATURE_COMPUTATION_FAILED` incident per (channel, feature, timestamp) with a null value. Reason enum: `{insufficient_history, divide_by_zero, nan_input, downstream_error}`. Classifier: first-row `log_return` → `insufficient_history`; rolling window before full window → `insufficient_history`; null upstream close → `nan_input`; zero rolling_std → `divide_by_zero`; else `downstream_error`.

### Invariants

- Rolling windows are backward-only; no leakage.
- Failures propagate as null cells in the output parquet + an incident emit; the downstream tokenizer's missing-mask reads the nulls (tech-arch §7).

---

## artifact contract

### Files created

- `src/price_space_llm/features/__init__.py`.
- `src/price_space_llm/features/compute.py` (~180 lines).
- `scripts/features.py` (~95 lines).
- `tests/test_features.py` (9 tests).

### Command exit codes

- ruff, ruff format, mypy, pytest all green.
- Test count 105 → 114 (+9).

### Live smoke

```
uv run python scripts/features.py --aligned data/aligned/align-2024-06-0000000000000000.parquet
```

Expected (verified): exit 0, ~0.10s, output parquet 520 rows × 9 columns, trace with 4025 FEATURE_COMPUTED and 135 FEATURE_COMPUTATION_FAILED.

---

## observation contract

Required (`pass_kind: functional`). Live smoke verified. Sample z-score at 2024-06-03T19:45 UTC = 1.10 (log_return 0.0012 was ~1 std dev above the 20-bar rolling mean).

---

## notes

**`run_kind="train"` for the feature-pipeline session.** The v0.3 SESSION_INIT.run_kind enum doesn't include a `feature` value; feature computation is the setup phase of training per tech-arch §6, so `train` is the closest fit. A future vocabulary bump could add `feature` if the distinction matters downstream.

**Emitter buffer.** Live run emits ~4100 signals; the default `max_buffer=500` in `StrictSignalEmitter` overflows the in-memory deque but the JSONL sink captures every emit correctly. Tests that inspect `snapshot()` bump the buffer to 16384.

---

## close (2026-08-11)

Landed. 4 features × 2 channels = 8 feature columns per aligned bar. Backward-only rolling. Null propagation with reason enums. Live smoke exit 0, honest trace, honest parquet.
