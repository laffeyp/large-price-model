# Sprint 078 -- tokenized `.pt` writes through `write_versioned`

---

```yaml
---
id: 078
status: closed
phase: E
pass_kind: architecture
determinism_budget: bit-deterministic
---
```

## scope

Close the third storage-integrity invariant Sprint 077 named. `run_tokenizer_pt` in `src/price_space_llm/tokenizer/bucketize.py` writes `.pt` via raw `torch.save` at a bare path — no `.{run_id}` versioning, no `.latest.pt` symlink, no `.sha256` sidecar. Every other frozen artifact class in the project (bucket_stats, normalizers, spread_scaler, kappa, checkpoints) routes through `artifacts.write_versioned` per Sprint 036 storage discipline. The tokenized `.pt` alone slipped that gate.

Sprint 075's in-place overwrite of `data/tokenized/tokenize-features-align-2015-01-2022-12-….pt` on 2026-08-17 00:11 is unrecoverable — the prior byte content was clobbered. Sprint 078 makes every future `.pt` regeneration land at a fresh `.{run_id}.pt` path with its own sha256 sidecar, so hard rule 12 (no deletions) holds mechanically.

## deliverables

- `run_tokenizer_pt` in `src/price_space_llm/tokenizer/bucketize.py` writes via `artifacts.write_versioned` at `base_path = output_dir / "tokens.pt"`. Return value becomes the versioned `.{run_id}.pt` path.
- Output shape at `data/tokenized/`:
  - `tokens.{run_id}.pt` — the raw payload (as before, now under a versioned filename).
  - `tokens.{run_id}.pt.sha256` — hex digest sidecar (Sprint 036 convention).
  - `tokens.latest.pt` — symlink to the most-recent versioned file (CLI convenience, not for reproducibility per `artifacts.py` docstring).
- `scripts/bucketize.py`'s two-pass normalizer-fit path (`--fit-normalizer` branch, `intermediate_artifact = load_tokens_pt(intermediate)` at line 210) updated to load from the returned versioned path.
- Live smoke: regenerate the training `.pt` at the new shape. Old bare-path `.pt` file preserved on disk per hard rule 12; new writes land alongside it.
- `scripts/train.py --tokens-pt PATH`, `scripts/evaluate.py --tokens-pt PATH`, `scripts/measure_drift.py --train-tokens-pt PATH` — no code change. User passes the versioned path (or the `latest` symlink). Test smokes that reference the bare path update.

## tests (+3)

1. `test_run_tokenizer_pt_writes_versioned_with_sidecar` — synthetic 4-channel frame; asserts the write produces `tokens.<run_id>.pt` + `tokens.<run_id>.pt.sha256` + `tokens.latest.pt` symlink; the sha256 sidecar content matches `sha256(payload_bytes)`.
2. `test_run_tokenizer_pt_returns_versioned_path` — asserts the return value is the versioned path (not the bare `tokens.pt` base).
3. `test_run_tokenizer_pt_second_write_flips_symlink` — write twice with distinct `run_id` values; assert both `.pt` files land on disk (audit trail preserved), and `tokens.latest.pt` resolves to the second file.

Existing tests updated in place (not counted in the +3 above):

- `tests/test_tokenizer.py::test_mask_present_on_regenerated_real_corpus` — path shifts from `data/tokenized/tokenize-features-align-….pt` to `data/tokenized/tokens.<run_id>.pt` OR the `tokens.latest.pt` symlink; test discovers via glob to survive future regens.
- `tests/test_train_device.py::test_train_cli_xs_smoke_on_pt_artifact` and `test_train_cli_c128_xs_smoke_on_pt_artifact` — subprocess `--tokens-pt` arg points at the new-shape file.
- `tests/test_tokenizer.py::test_run_tokenizer_pt_*` (three existing tests) — assertions on the returned path shape update from `output_dir / "test-run.pt"` to `output_dir / "tokens.test-run.pt"`.

## context files

- `src/price_space_llm/tokenizer/bucketize.py`
- `src/price_space_llm/artifacts.py` (already stable — the target infrastructure)
- `scripts/bucketize.py`
- `tests/test_tokenizer.py`
- `tests/test_train_device.py`

## artifact contract

Files created or modified:

- `src/price_space_llm/tokenizer/bucketize.py` — modified: `run_tokenizer_pt` writes through `write_versioned`; returns versioned path.
- `scripts/bucketize.py` — modified: self-loop for normalizer fit uses the returned versioned path.
- `tests/test_tokenizer.py` — modified: +3 tests, ~5 existing assertions updated for the new path shape.
- `tests/test_train_device.py` — modified: 2 subprocess `--tokens-pt` args point at the new shape.
- `data/tokenized/tokens.<run_id>.pt` — created (regenerated training window as live smoke).
- `data/tokenized/tokens.<run_id>.pt.sha256` — created.
- `data/tokenized/tokens.latest.pt` — created (symlink).

Old file `data/tokenized/tokenize-features-align-2015-01-2022-12-….pt` stays on disk unchanged. Hard rule 12 preserved.

Content assertions:

- `ls data/tokenized/tokens.*.pt` returns at least one file post-live-smoke.
- `ls data/tokenized/tokens.*.pt.sha256` returns at least one file.
- `test -L data/tokenized/tokens.latest.pt` returns true.
- The sha256 sidecar's hex matches `shasum -a 256` of the corresponding `.pt`.

## signal contract

Emits: none new. Sprint 052 already deferred a `TOKENIZED_ARTIFACT_WRITTEN` tag; still deferred. The sidecar carries the audit trail without a signal-side surface until a v0.6 vocab bump lands the tag.

## observation contract

REQUIRED — the `.pt` output path shape changes.

- **Input:** `uv run python scripts/bucketize.py --features data/features/features-align-2015-01-2022-12-….parquet --training-start 2015-01-02 --training-end 2022-12-30 --format pt`.
- **Expected artifact:** `data/tokenized/tokens.<run_id>.pt` + `.sha256` sidecar + `tokens.latest.pt` symlink flipped.
- **Expected behavior:** downstream `scripts/train.py --tokens-pt data/tokenized/tokens.latest.pt --model-size xs --context-size 128 --n-steps 2 --eval-every 2 --seed 41 --device cpu --warmup-steps 0` exits 0; `load_tokens_pt` on the new artifact passes without opt-in flags (marker present, sha sidecar present).
- **Expected trace:** SESSION_INIT → CONFIG_RESOLVED → 2×WINDOW_SAMPLED → 2×TRAINING_STEP_COMPLETED → CHECKPOINT_WRITTEN → EPOCH_COMPLETED → SESSION_COMPLETE.

## commands

```
uv run ruff check .
uv run mypy
uv run pytest -q
uv run python scripts/bucketize.py --features data/features/features-align-2015-01-2022-12-….parquet --training-start 2015-01-02 --training-end 2022-12-30 --format pt
uv run python scripts/train.py --tokens-pt data/tokenized/tokens.latest.pt --model-size xs --context-size 128 --n-steps 2 --eval-every 2 --seed 41 --device cpu --warmup-steps 0
```

## notes

- Two code files (`tokenizer/bucketize.py` module + `scripts/bucketize.py`) + two test files touched. One concept: bring tokenized `.pt` writes under Sprint 036 storage discipline. Under hard rule 6.
- Backward compatibility: old bare-path `.pt` files stay on disk; consumers reading the old bare paths continue to work if they pass the old path explicitly. Consumers using the new versioned path or `latest` symlink get sidecar-verifiable freshness.
- Test-window `.pt` regeneration still deferred to Sprint 088 held-out evaluation prep (heldout guard requires a test-look draw).
- Follow-up sprint candidate: v0.6 vocab bump adding `TOKENIZED_ARTIFACT_WRITTEN` (feature-category, summary-stratum tag; payload `run_id`, `path`, `sha256`, `n_channels`, `n_rows`, `mask_semantics`). That closes the signal-side reporting the Sprint 052 card originally deferred.
