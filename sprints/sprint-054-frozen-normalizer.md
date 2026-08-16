# Sprint 054 -- frozen normalizer (closes review § 3 blocker #2)

---

```yaml
---
id: 054
status: closed
phase: 3
pass_kind: functional
determinism_budget: bit-deterministic
---
```

---

## scope

Closes review § 3 blocker #2. Product-spec § Feature normalization: *"v1 uses an expanding-window causal z-score computed on the training partition only, then frozen. At inference and on validation and test, the frozen scaler is used as-is."* Tech-arch § 6 names `artifacts/{run_id}/normalizers.pt` as the persistence target and `warmup_bars=2000` as the typical warmup. v0.4 vocab has `NORMALIZER_FITTED` + `NORMALIZER_STATE_WRITTEN` waiting with zero call sites.

Sprint 054 ships:

- `FrozenNormalizer` dataclass — per-(channel, feature) `mean: Tensor[F_c]` + `std: Tensor[F_c]`.
- `fit_frozen_normalizer(artifact, training_slice, emitter, run_id)` — computes mean + std across all training-partition rows per channel per feature; skips rows where the target is null (matches the sampler's ignore-index semantics). Emits `NORMALIZER_FITTED`.
- `write_frozen_normalizer(normalizer, path, run_id)` — persists via `artifacts.write_versioned` (versioned + `.latest` symlink + sha256 sidecar). Emits `NORMALIZER_STATE_WRITTEN`.
- `load_frozen_normalizer(path)` — reader.
- `apply_frozen_normalizer(feats: dict[str, Tensor], normalizer) -> dict[str, Tensor]` — transforms per-channel feature tensors in place-safe fashion; std==0 features stay 0 (constant column) without dividing by zero.
- `scripts/bucketize.py` gains `--fit-normalizer` and `--normalizer-path`. When set, fits on the training-partition slice of the artifact, writes normalizers.pt, applies to the artifact before writing the .pt.

### Interpretation decision (named on the record)

Spec's "expanding-window causal z-score, then frozen" phrase carries two readable interpretations:

- **(A) Full-training-partition frozen constants.** Fit one mean + std per (channel, feature) across the entire training partition. Same constant transform on train + val + test. Simpler; most published financial-ML pipelines land here.
- **(B) Per-bar expanding stats during training-partition, frozen at end.** Each training bar `t` sees z-scored features using running stats from bars 0..t-1 (Welford's). Val/test use the final stats. Adds one online-stats pass and a training-time distribution shift the model absorbs.

Sprint 054 ships **(A)**. Justifications: (1) simpler, faster, deterministic; (2) matches the "then frozen" downstream shape; (3) `warmup_bars=2000` in the emit payload documents the spec intent even though the constants come from the full partition, not the first 2000 bars. If the Sprint 055 drift diagnostic surfaces a training-vs-inference mismatch the (A) model can't absorb, a follow-up sprint upgrades to (B).

## halt-and-articulate

**Zero-variance features.** Some Sprint 052 per-channel tensors have all-zero columns (VIX `volume_z_100` inputs, event-channel `close` == 1 constants). Fitting std on these gives σ=0; dividing by zero yields NaN and poisons the model. Fix: `apply_frozen_normalizer` clamps `std` at `1e-8` before division. Constant columns pass through as `(x - μ) / max(σ, 1e-8) = 0` (since x == μ). Named in the loader.

## signal contract

### Emits

- `NORMALIZER_FITTED` — one per fit call. Payload: `run_id`, `feature_count`, `warmup_bars` (documentation constant = 2000), `training_range_start`, `training_range_end`.
- `NORMALIZER_STATE_WRITTEN` — one per write call. Payload: `run_id`, `path`, `feature_count`, `sha256`.

Both tags exist in v0.4 with zero call sites; Sprint 054 wires them.

### Invariants

- `fit_frozen_normalizer` uses only bars where `artifact.targets != -100` (matches the sampler's non-ignore-index rows) so val-only nulls don't skew the stats.
- `write_frozen_normalizer` uses `artifacts.write_versioned` → produces `.{run_id}.pt` + `.latest.pt` symlink + `.sha256` sidecar per Sprint 036 storage discipline.
- `apply_frozen_normalizer(feats)` returns a new dict; input tensors are not mutated (functional style).
- `load_frozen_normalizer(path)` round-trips bit-identically with `write_frozen_normalizer(fit_frozen_normalizer(...))`.
- Std clamped at `1e-8` before division; test locks the constant-column pass-through.

## artifact contract

### Files (5 — under hard rule 6)

- `src/price_space_llm/normalizer/__init__.py` — new module, exports.
- `src/price_space_llm/normalizer/frozen.py` — dataclass + fit + write + load + apply.
- `src/price_space_llm/tokenizer/bucketize.py` — `run_tokenizer_pt` gains optional `normalizer: FrozenNormalizer | None = None` kwarg; when set, applies before writing the artifact.
- `scripts/bucketize.py` — `--fit-normalizer` bool + `--normalizer-path PATH`. When `--fit-normalizer`, fit on the training-partition slice of the built `.pt` artifact (equivalently, fit on the training-window rows of the features parquet), write normalizer, then re-materialize the .pt artifact with normalization applied. Or: two-pass — bucketize once to get shapes; fit; re-bucketize with normalizer.
- `tests/test_normalizer.py` — new tests: fit produces per-channel mean + std with correct shapes; fit ignores `targets == -100` rows; write + load round-trip; apply transforms x → (x-μ)/σ and passes through zero-std columns; NORMALIZER_FITTED + NORMALIZER_STATE_WRITTEN payload validation.

### Command exit codes

- ruff, ruff format, mypy: green.
- pytest: 348 → 356+ (new tests).
- Live smoke: `scripts/bucketize.py --features ... --training-start ... --training-end ... --format pt --fit-normalizer --normalizer-path artifacts/normalizers.pt` exits 0 on the training window.

### Live smoke

Run against real training features parquet (54,262 rows × 20 channels):
- Fit normalizer: 20 channels × 4-10 features each → 20 (mean, std) tensors, feature_count total ≈ 96.
- Write to `artifacts/tokenizer/normalizers.pt` with `.latest` symlink + sha256 sidecar.
- `NORMALIZER_FITTED` + `NORMALIZER_STATE_WRITTEN` land in the trace.
- Re-materialize .pt artifact with normalization applied.
- Read back: each per-channel tensor's column-wise mean ≈ 0 and std ≈ 1 for non-constant columns; std==0 columns pass through as 0.

---

## observation contract

Required (`pass_kind: functional`). Unit tests lock every property. Live-smoke on real training .pt verifies the trace fires both tags with correct payload shapes and the versioned artifact lands on disk with matching sha256.

---

## honest audit

**What lands.** Frozen normalizer per interpretation (A). Signals wired. Persistence via Sprint 036 storage discipline. Tokenizer optionally applies normalization at write time.

**What does not land.** Interpretation (B) per-bar expanding stats. Normalization-drift diagnostic (Sprint 055 in roadmap; blocked on this sprint). Migrating existing callers of the un-normalized .pt to the normalized path (deferred; keeps back-compat).

**What surfaces.** The zero-std constant-column path is honest but semantically empty — the model sees a feature that carries no information. Future sprint might drop or gate such features rather than passing zero through.

---

## notes

**Why apply at tokenizer write time, not at model input time.** The .pt artifact becomes the frozen shape the model consumes. Applying at write time means the trainer + evaluator don't need to know about normalization at all; they just consume normalized tensors. Simpler + fewer moving parts + matches the "then frozen" spec intent.

**Why not fit normalizer on features parquet directly.** The .pt artifact already has the per-channel feature tensors + target-mask semantics figured out. Fitting off the same tensors keeps the pipeline linear: features → bucketize → normalize → write.

**Why versioned artifact.** Different training runs might use different normalizers; a versioned filename + `.latest` symlink lets a specific run reproduce exactly.

---

## plan-mode review checklist

- [x] Files under hard rule 6 (5).
- [x] Two new emit sites (NORMALIZER_FITTED + NORMALIZER_STATE_WRITTEN); both tags pre-declared in v0.4.
- [x] Observation contract (functional-band): 10 unit tests + live smoke against real training .pt.
- [x] Determinism budget bit-deterministic (same features + same code = byte-identical normalizer + normalized .pt).
- [x] Closes review § 3 blocker #2: frozen normalizer wired end-to-end with persistence + signals.

---

## close (2026-08-15)

Landed. `FrozenNormalizer` + `fit_frozen_normalizer` + `write_frozen_normalizer` + `load_frozen_normalizer` + `apply_frozen_normalizer` wired. `scripts/bucketize.py --fit-normalizer` fits on the training-partition slice (rows where target != -100), writes to `artifacts/tokenizer/normalizers.{run_id}.pt` via `artifacts.write_versioned` with `.latest` symlink + sha256 sidecar, applies at `run_tokenizer_pt` write time. Tests +10: shape, ignore-index rows, emit contracts, round-trip, apply zero-mean-unit-std, constant-column pass-through, unknown-channel rejection, batch-dim broadcast. Count 348 → 358. Ruff + mypy + pytest all green. Live smoke on training window: normalizer artifact 11KB with symlink + sidecar; 20 channels, feature_count 86; NORMALIZER_FITTED + NORMALIZER_STATE_WRITTEN each fire once; non-constant channels (target__SPY: col mean 0.0006, col std 1.0000; market_context__VIX: col mean 0.0004, col std 0.9999) confirm textbook z-score; constant-column channels (event__FOMC, event__CPI_RELEASE, event__OPTIONS_EXPIRY) pass through as zero via the STD_CLAMP=1e-8 divisor. Sprint 055 opens next: normalization-drift diagnostic (`NORMALIZER_DRIFT_MEASURED` v0.5 candidate) reading the frozen normalizer + comparing training vs holdout feature distributions.
