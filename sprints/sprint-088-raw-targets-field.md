# Sprint 088 -- raw_targets field on TokenizedArtifact

---

```yaml
---
id: 088
status: closed
phase: E
pass_kind: architecture
determinism_budget: bit-deterministic
---
```

## scope

Foundation for the quantile head ablation (Sprint 089, roadmap 071). Pinball loss consumes raw float log returns, not bucket IDs. `TokenizedArtifact.targets` (Sprint 052) is `int64` bucket IDs; a parallel `raw_targets` field carries the float log return per grid position. This sprint lands the field only; Sprint 089 lands the head + loss + CLI.

## deliverables

- `TokenizedArtifact.raw_targets: torch.Tensor | None` in `src/price_space_llm/model/dataset.py`. Shape `[T]` float32; NaN where the target's log_return is null (same rows where `targets == -100`). `None` on pre-Sprint-088 artifacts.
- `run_tokenizer_pt` in `src/price_space_llm/tokenizer/bucketize.py` reads `target__{sym}__log_return`, converts to float32, stores as `raw_targets` in the payload. `meta["raw_targets_stamped"] = "v088"` marker.
- `load_tokens_pt` reads `raw_targets` when present; returns `None` otherwise (backward-compat with pre-Sprint-088 artifacts on disk).
- Regenerate the training `.pt` as live smoke.

## tests (+3)

1. `test_run_tokenizer_pt_writes_raw_targets` — synthetic frame; asserts `raw_targets` shape + dtype; float value matches source log_return column.
2. `test_load_tokens_pt_reads_raw_targets` — round-trip through load path.
3. `test_load_tokens_pt_pre_sprint_088_artifact_returns_none` — synthetic payload without the `raw_targets` key loads with `raw_targets=None` (`allow_legacy_mask=True` opt-in to bypass Sprint 077's mask marker check).

## artifact contract

Files created or modified:

- `src/price_space_llm/model/dataset.py` — `TokenizedArtifact.raw_targets` field; `load_tokens_pt` reads with fallback.
- `src/price_space_llm/tokenizer/bucketize.py` — computes and stores raw_targets; adds meta marker.
- `tests/test_model.py` — +2 tests for load path.
- `tests/test_tokenizer.py` — +1 test for write path.
- `data/tokenized/tokens.<run_id>.pt` — regenerated via live smoke.

Content assertions:

- `grep -q "raw_targets" src/price_space_llm/tokenizer/bucketize.py`
- `grep -q "raw_targets_stamped" src/price_space_llm/tokenizer/bucketize.py`

## signal contract

Emits: none new. `TOKENIZED_ARTIFACT_WRITTEN` payload does not gain a field this sprint; a v0.8 vocab bump (Sprint 089 or a follow-up) adds `head_type` + `raw_targets_stamped` + `patch_size` as required fields together.

## observation contract

Live smoke: regenerate training .pt through `scripts/bucketize.py --format pt`; verify `raw_targets` present and float32 with NaN sentinels where `targets == -100`.

## notes

- 2 code files + 2 test files. Under hard rule 6.
- Pre-Sprint-088 artifacts on disk continue to load with `raw_targets=None`; Sprint 089's quantile-head path refuses `None` via `QuantileHeadRequiresRawTargets` — same fail-loud contract shape as Sprint 084's `UnnormalizedArtifactRefused`.
