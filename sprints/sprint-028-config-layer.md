# Sprint 028 — config layer (Pydantic v2 + CONFIG_RESOLVED)

---

```yaml
---
id: 028
status: closed
phase: 1
pass_kind: functional
determinism_budget: bit-deterministic
---
```

---

## scope

Adopt `pydantic>=2`. Author `src/price_space_llm/config.py` — an `ExperimentConfig` Pydantic v2 model (`target_symbol`, `context_len`, `n_buckets`, `lambda_risk`, `alpha_mag_weight` — all required, matching v0.3's `CONFIG_RESOLVED.typed_payload`) plus a `load_config` helper that emits `CONFIG_RESOLVED` on success and `CONFIG_VALIDATION_FAILED` on any parse/validation error. Author `configs/experiment/v1.json` (a real config on disk). Wire the resolver into `scripts/features.py` so `CONFIG_RESOLVED` fires for the first time from a live run. Tech-arch §11.3 gate — `lambda_risk` and `alpha_mag_weight` presence — enforced at parse time.

---

## signal contract

### Emits

- `CONFIG_RESOLVED` — event, fires after successful parse. Payload matches v0.3 typed_payload exactly.
- `CONFIG_VALIDATION_FAILED` — incident, fires on missing file / malformed JSON / Pydantic validation error. Payload: `config_path`, `missing_or_invalid_fields` (list of dotted paths), `error_message`.

### Invariants

- Every required v0.3 payload field on `CONFIG_RESOLVED` is derived from real values: `config_hash` is `sha256(config_bytes)`, `resolved_at` is `datetime.now(UTC)`, everything else is either from the resolved config or the caller.
- `context_len` and `n_buckets` in the Pydantic model use `Literal[int, ...]` to reject out-of-enum values at parse time; the emit casts to string for the vocabulary's textual enum check.
- Missing required field → `ConfigValidationFailed` raised AND `CONFIG_VALIDATION_FAILED` emitted; the caller sees both.

---

## artifact contract

### Files created

- `src/price_space_llm/config.py` — model + loader (~130 lines).
- `configs/experiment/v1.json` — canonical experiment config.
- `tests/test_config.py` — 11 tests (6 model-level, 5 loader-level).

### Files modified

- `scripts/features.py` — `--config` flag (default `configs/experiment/v1.json`); calls `load_config` inside `process_session` before `run_feature_pipeline`; exits 1 on validation failure.
- `pyproject.toml` — `pydantic>=2` added; version 0.13 → 0.14.

### Command exit codes

- ruff, ruff format, mypy, pytest all green.
- Test count 117 → 128 (+11).

### Live smoke

```
uv run python scripts/features.py --aligned data/aligned/align-2024-06-0000000000000000.parquet
```

Expected (verified): exit 0. Trace contains `CONFIG_RESOLVED` between `SESSION_INIT` and the feature emits, with real `config_hash` (`4d3ce12131fd8ffd49474a0f60d6a3e7e3ef13cfdff487f99e6504c0d090a032`), real `git_sha`, real `resolved_at` (UTC), and the resolved config values (`lambda_risk=1.0`, `alpha_mag_weight=0.5`, `target_symbol=SPY`, `context_len=128`, `n_buckets=32`).

---

## observation contract

Live smoke verified. Trace now emits 6 categories: session (INIT, COMPLETE), config (RESOLVED), feature (COMPUTED × 4025, COMPUTATION_FAILED × 135).

---

## notes

**Why no Hydra.** Tech-arch §12 names Hydra as the future config-composition layer. Sprint 028 lands the validated-model boundary; Hydra composition sits above it (overlays, environment vars, CLI overrides). A future config sprint adopts Hydra when a run actually needs to compose across YAML files. Sprint 028 is the smallest step that closes the CONFIG_RESOLVED emit gap without over-engineering.

**JSON over TOML.** Stdlib support for both exists (Python 3.11 has `tomllib`); JSON was picked for continuity with the manifest and cache formats. Trivial to add TOML support in the loader when a config's structure grows to warrant it.

**Integer-vs-string enum mismatch.** The v0.3 vocabulary declares `context_len` and `n_buckets` as `enum<64|128|256|512>` and `enum<16|32|64>` — string-token enums per PRINCIPLES.md. The Pydantic model uses `Literal[int, ...]` for parse-time integrity; the emit casts to string. Documented in the emit call comment.

---

## close (2026-08-11)

Landed. `CONFIG_RESOLVED` fires from live code. `CONFIG_VALIDATION_FAILED` verified by five loader tests covering missing file, malformed JSON, missing required field, out-of-enum value, invalid target_symbol. Six of six sprint 026-028 goals delivered end-to-end.
