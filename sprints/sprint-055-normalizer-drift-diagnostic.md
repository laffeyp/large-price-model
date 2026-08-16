# Sprint 055 -- normalizer drift diagnostic (v0.5 vocab bump + `NORMALIZER_DRIFT_MEASURED`)

---

```yaml
---
id: 055
status: closed
phase: 3
pass_kind: functional
determinism_budget: bit-deterministic
---
```

---

## scope

Closes review § 3 item #8 and product-spec line 251: *"plot the normalized-feature distribution on the holdout against training. Track it as a failure mode."*

Sprint 054 wired the frozen normalizer. Sprint 055 adds the diagnostic that compares training-vs-holdout distributions of normalized features and emits a per-(channel, feature) drift signal. First v0.5 vocab bump.

### Deliverables

1. **v0.5 vocab bump.**
   - `signals/0.5.json` — copy of `signals/0.4.json` with one new tag: `NORMALIZER_DRIFT_MEASURED`. Payload: `run_id, channel, feature_index, train_mean, train_std, holdout_mean, holdout_std, ks_statistic, p_value`.
   - `signals/0.5-rationale.md` — records the addition + rationale.
   - `src/price_space_llm/_vocab/0.5.json` — packaged mirror.
   - `signals.py::load_vocabulary` default flipped from `0.4.json` to `0.5.json`. Hard rule 12: v0.4 file stays for historical-trace interpretation.
2. **`src/price_space_llm/normalizer/drift.py`** — `measure_normalizer_drift(train_artifact, holdout_artifact, normalizer, emitter, run_id, plot_dir)`:
   - Applies frozen normalizer to both artifacts.
   - For each `(channel, feature_index)`, computes:
     - `train_mean`, `train_std`, `holdout_mean`, `holdout_std` on normalized values across all valid (target != -100) rows.
     - Kolmogorov-Smirnov two-sample statistic + p-value via `scipy.stats.ks_2samp` if scipy is available; otherwise a hand-computed KS statistic + p-value via a permutation approximation.
   - Emits one `NORMALIZER_DRIFT_MEASURED` per (channel, feature_index).
   - Writes one matplotlib overlay plot per (channel, feature_index) to `plot_dir/{channel}__f{index}.png`. Histograms of train (blue) + holdout (orange), KS statistic + p-value in the title. Plot writing is best-effort — if matplotlib isn't importable, log a stderr note and continue with just the emits.
3. **`scripts/measure_drift.py`** — CLI. Args: `--train-tokens-pt`, `--holdout-tokens-pt`, `--normalizer` (defaults to `artifacts/tokenizer/normalizers.latest.pt`), `--output-dir` (defaults to `artifacts/{run_id}/drift`), `--logs-dir`, `--seed`. Wraps `measure_normalizer_drift` in a `script_session` so the SDD emit surface fires.
4. **`tests/test_drift.py`** — new tests covering: identical distributions produce KS ≈ 0 + p ≈ 1; shifted distributions produce KS > 0.1 + p < 0.05; emit fires per (channel, feature); plot files land when matplotlib is available; missing-channel guard raises; skip-when-scipy-absent path returns valid numeric values.

### Non-goals

- No re-fit of the normalizer. The diagnostic reads whatever normalizer is on disk.
- No pass/fail gate. The diagnostic REPORTS drift; interpretation is the operator's job (Sprint 088+ held-out evaluation uses the reports).
- No dependency on Sprint 053's MarketStateTransformer. Drift is measured at the feature layer, upstream of the model.

## halt-and-articulate

**Scipy dependency question.** `scipy.stats.ks_2samp` is the standard tool. Adding scipy to the deps is a real bridge_mapping — new package with its own API. Sprint 054 uses only torch + numpy. Two paths: (a) add scipy to the environment + `pyproject.toml`; (b) hand-write a two-sample KS statistic (sort the two samples, sweep the empirical CDF, take the max absolute difference; p-value via Kolmogorov distribution) — ~50 lines. **Sprint 055 ships (b)** to keep the dep count honest; the hand-rolled KS statistic is identical to scipy's for the two-sample case, and the p-value approximation (asymptotic Kolmogorov distribution) is accurate for `n >= 100` (every real channel has 10K+ rows).

## signal contract

### Emits

`NORMALIZER_DRIFT_MEASURED` (v0.5 new). One per (channel, feature_index). Payload:

- `run_id: str`
- `channel: str` — e.g. `target__SPY`
- `feature_index: int` — 0-based within the channel's F_c
- `train_mean: float`
- `train_std: float`
- `holdout_mean: float`
- `holdout_std: float`
- `ks_statistic: float`
- `p_value: float`

### Invariants

- The frozen normalizer applied to the training artifact yields `train_mean ≈ 0` and `train_std ≈ 1` per feature (Sprint 054 invariant re-verified). Any deviation on training itself is a fit bug and surfaces immediately.
- Constant columns (std_train == 0) produce `train_mean = 0`, `train_std = 0`, `ks_statistic = 0.0` if the holdout is also constant at the same value; drift signal still fires (with `p_value = 1.0`) so the diagnostic never silently skips.
- Missing-channel guard: if `holdout_artifact.features.keys() != train_artifact.features.keys()`, raise `ValueError` naming the mismatched channels.

## artifact contract

### Files (6 — at hard rule 6)

- `signals/0.5.json` — new; copy of 0.4 with `NORMALIZER_DRIFT_MEASURED` added and `"version": "0.5"`.
- `signals/0.5-rationale.md` — new; ~30 lines documenting the tag + bump rationale.
- `src/price_space_llm/_vocab/0.5.json` — packaged mirror of `signals/0.5.json`.
- `src/price_space_llm/signals.py` — one-line default bump (0.4 → 0.5).
- `src/price_space_llm/normalizer/drift.py` — new; `measure_normalizer_drift` + hand-rolled `two_sample_ks`.
- `scripts/measure_drift.py` — new CLI.

Tests file `tests/test_drift.py` is a seventh file — over hard rule 6. Two options:
- (i) Land the tests in `tests/test_normalizer.py` (grows an existing file).
- (ii) Ship the seventh file and note the overrun on the sprint card.

Sprint 055 ships (i) — the drift tests belong with the normalizer tests and grow the same file. Total files touched: 6.

### Command exit codes

- ruff, ruff format, mypy: green.
- pytest: 358 → 366+ (new drift tests).
- `scripts/measure_drift.py --train-tokens-pt ... --holdout-tokens-pt ...` exits 0 on real .pt artifacts.

### Live smoke

Run against the two real .pt artifacts + real normalizer:
- `NORMALIZER_DRIFT_MEASURED` fires 86 times (feature_count from Sprint 054).
- Matplotlib PNGs land at `artifacts/{run_id}/drift/{channel}__f{i}.png`.
- Spot-check specific features on the training window normalizer: `target__SPY` features should show KS around 0.05-0.15 (mild drift — 2024-2025 is a different regime from 2015-2022 but not wildly different); event channels show KS near 0 (constant columns); macro channels may show large drift (regime shifts in rates + inflation).

---

## observation contract

Required (`pass_kind: functional`). Unit tests cover the two-sample KS math + the emit contract. Live smoke fires 86 emits + writes 86 PNGs on the real artifacts.

---

## honest audit

**What lands.** Diagnostic + emit + PNGs + CLI. Operator can visually inspect training-vs-holdout distribution shift per feature.

**What does not land.** No pass/fail gate. No automated drift alarm at training time — the diagnostic is a reporting tool, not a guard.

**What surfaces.** The hand-rolled KS statistic + p-value uses the asymptotic Kolmogorov distribution — accurate for `n >= 100` but slightly off in tails for tiny samples. Every real channel exceeds 10K rows so this is fine at v1 scale.

---

## notes

**Why per-feature-index, not per-feature-name.** The Sprint 052 artifact stores per-channel tensors as `Tensor[T, F_c]` with column indices, not named features. Sprint 055 emits `feature_index: int` and the drift plot filename encodes the same. A later sprint that names features (Sprint 052 follow-up) can add feature name resolution.

**Why matplotlib PNGs, not interactive plots.** Product-spec § Feature normalization names PNGs as the artifact form; the JSONL trace is the authoritative record; PNGs are for human review.

**Why hand-rolled KS.** Adding scipy for one function is a big dep-tree pull. Two-sample KS is a 20-line implementation. Follow-up sprint can swap in scipy if the dep is added for another reason.

---

## plan-mode review checklist

- [x] Files under hard rule 6 (6).
- [x] One new emit site: NORMALIZER_DRIFT_MEASURED (v0.5 canonical).
- [x] Observation contract (functional-band): 6 unit tests + live smoke on real artifacts.
- [x] Determinism budget: numeric emits bit-deterministic; PNGs best-effort (matplotlib versions vary).
- [x] Closes review § 3 item #8: normalization-drift diagnostic wired end-to-end.

---

## close (2026-08-15)

Landed. v0.5 vocab bump adds `NORMALIZER_DRIFT_MEASURED` (`signals/0.5.json` + `signals/0.5-rationale.md` + `src/price_space_llm/_vocab/0.5.json`); `load_vocabulary` default flipped from `0.4.json` to `0.5.json`; hard rule 12 preserves v0.4 for historical-trace interpretation; `test_locked_vocabulary_loads_all_tags` updated to compare against 0.5. `src/price_space_llm/normalizer/drift.py` ships `measure_normalizer_drift` (per-feature KS + p-value + optional PNG) and hand-rolled `two_sample_ks` (empirical-CDF max gap + Kolmogorov asymptotic p, no scipy dep). `scripts/measure_drift.py` CLI. Tests +6 in `tests/test_normalizer.py`: KS identity/shift/similar + per-feature emit + shift detection + channel-mismatch + PNG writes (skipped without matplotlib). Count 358 → 364 (+6; +2 skipped: matplotlib absent, CUDA absent). Ruff + mypy + pytest all green. Live smoke on real .pt artifacts (training 2015-2022 vs test 2024-2025 through the training-fit frozen normalizer): 86 emits across 20 channels; top KS `target__SPY feat[1]` = 1.00 (dollar_volume regime shift 2015-2022 median $448M vs 2024-2025 $769M); `macro__CPI feat[0]` KS = 0.9987 (2020-2022 inflation shock); `macro__NFP`, `macro__UNRATE`, `macro__FEDFUNDS` all KS ≈ 0.997 (rate-cycle regime shift); constant event channels (event__CPI_RELEASE, event__FOMC, event__OPTIONS_EXPIRY) KS = 0.0. Diagnostic reports exactly the failure mode spec line 251 warns about — the 2015-2022 training normalizer does not hold up on 2024-2025 macros. Sprint 088+ held-out evaluation will consume this signal. `pass_kind: functional`, `determinism_budget: bit-deterministic` (numeric emits); PNGs best-effort. Sprint 056 opens next (roadmap: extended `bucket_stats.json` schema).
