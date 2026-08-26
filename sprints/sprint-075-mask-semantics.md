# Sprint 075 -- mask redefinition (target-valid semantics)

---

```yaml
---
id: 075
status: closed
phase: E
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Close the Sprint 052 mask open item that the 2026-08-16 review-verify surfaced. Redefine `TokenizedArtifact.mask` from "every feature column non-null across every channel" to "this row is a valid training example for the target." The current semantic collapses to all-False on the real corpus because sparse event channels (options-expiry ~12/year, macro releases monthly-to-quarterly) poison the all-non-null check on every 15-minute bar.

## deliverables

- `run_tokenizer_pt` in `src/price_space_llm/tokenizer/bucketize.py` computes `mask[t] = target_features_non_null[t] AND targets[t] != -100`. Target key = `f"target__{target_symbol}"`.
- Docstring at `run_tokenizer_pt` and at `TokenizedArtifact.mask` in `src/price_space_llm/model/dataset.py` updated to name the new semantic. Old text ("True iff every feature column is non-null") removed.
- `meta["mask_semantics"] = "target_valid_v075"` added to the saved payload — a version marker so a future consumer can distinguish pre- vs post-Sprint-075 artifacts on disk. Consumers that don't check the field just read the tensor.
- Regenerate both live `.pt` artifacts (2015-2022 training, 2024-2025 test) as the sprint's live smoke. Verify `mask.sum() > 0` on both — the fix works when at least one row survives.

## tests (+3)

1. `test_mask_target_valid_on_synthetic_frame` — synthetic 4-row frame with rows carrying valid/null target features and valid/-100 targets in a 2×2 truth table; asserts `mask` reads `[True, False, False, False]`.
2. `test_mask_ignores_non_target_null_columns` — synthetic 3-row frame with a non-target column all-null; asserts `mask` = `[True, True, True]` (non-target nulls do not depress mask).
3. `test_mask_present_on_real_corpus` — loads the training `.pt` (skipped if absent); asserts `mask.sum() > 0` (was 0 pre-Sprint-075) and `meta["mask_semantics"] == "target_valid_v075"`.

## context files

- `src/price_space_llm/tokenizer/bucketize.py`
- `src/price_space_llm/model/dataset.py`
- `tests/test_tokenizer.py`
- `BLACKBOARD.md ## Surfaced for review` (2026-08-16 entry naming the mask gap)
- Sprint 052 built entry naming the original follow-up

## artifact contract

Files created or modified:

- `src/price_space_llm/tokenizer/bucketize.py` — modified: mask block + docstring + meta marker
- `src/price_space_llm/model/dataset.py` — modified: `TokenizedArtifact.mask` docstring
- `tests/test_tokenizer.py` — modified: 3 tests appended
- `data/tokenized/tokenize-features-align-2015-01-2022-12-…pt` — regenerated via `scripts/bucketize.py` at live smoke (versioned write; old file stays on disk per Sprint 036 storage integrity)
- `data/tokenized/tokenize-features-align-2024-01-2025-06-…pt` — regenerated same shape

Content assertions:

- `grep -q "target_valid_v075" src/price_space_llm/tokenizer/bucketize.py`
- `python -c "import torch; d=torch.load('data/tokenized/tokenize-features-align-2015-01-2022-12-….pt', weights_only=False); print(int(d['mask'].sum()))"` returns a positive integer.

## signal contract

Emits: none new. The tokenize step already fires no dedicated vocabulary tag (Sprint 052 named this and deferred; still deferred). No v0.6 pressure from this sprint.

## observation contract

REQUIRED (behavior-touching): the mask field's semantic changes; downstream consumers (Sprint 088 held-out evaluation likely) read a different tensor going forward.

- **Input:** `scripts/bucketize.py --features data/features/features-align-2015-01-2022-12-…parquet --stats-in artifacts/bucket_stats/... --format pt --target-symbol SPY`
- **Expected trace:** SESSION_INIT + config-resolved + tokenize-run-completed emit path unchanged.
- **Expected artifact:** new `.pt` at `data/tokenized/{run_id}.pt` with `mask.sum() > 0`.
- **Expected behavior:** existing training smokes (`run_training_feats` on the regenerated artifact) still complete with the full training tag surface. `zero_non_target_features` still passes `mask` through unchanged. `WindowSamplerFeats` continues to ignore `mask` (Sprint 075 does not add gating; a follow-up sprint that gates on mask is separate).

## commands

```
uv run ruff check .
uv run mypy
uv run pytest -q
uv run python scripts/bucketize.py \
  --features data/features/features-align-2015-01-2022-12-…parquet \
  --stats-in artifacts/bucket_stats/bucket_stats.latest.json \
  --format pt --target-symbol SPY \
  --run-id tokenize-features-align-2015-01-2022-12-0000000000000000-0000000000000000-0000000000000000
```

Expected: exit 0; new `.pt` on disk; `mask.sum() > 0`; Sprint 073 xs smoke against the regenerated artifact still exits 0.

## notes

- Two code files + one test file — inside hard rule 6.
- `mask_semantics` version marker is `target_valid_v075` so a future v076 redefinition (say, adding non-target-feature validity) can distinguish. Pre-Sprint-075 artifacts have no marker; consumers that care can treat absent-marker as the old semantic.
- `WindowSamplerFeats` gating on `mask` is a separate concern — sampled windows that overlap invalid rows would need per-position loss weighting or start-position filtering. Sprint 088+ candidate; not this sprint.
- The 2015-2022 training .pt currently reports `mask.sum() == 0`. Sprint 075's success criterion is `mask.sum() > 0` on both regenerated artifacts.
