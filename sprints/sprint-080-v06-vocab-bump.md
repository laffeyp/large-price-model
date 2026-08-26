# Sprint 080 -- v0.6 vocab bump: TOKENIZED_ARTIFACT_WRITTEN + NORMALIZER_CHANNEL_UNDER_CLAMP

---

```yaml
---
id: 080
status: closed
phase: E
pass_kind: architecture
determinism_budget: bit-deterministic
---
```

## scope

Close two named vocabulary deferrals in a single v0.6 lock: `TOKENIZED_ARTIFACT_WRITTEN` (Sprint 052 → 078) and `NORMALIZER_CHANNEL_UNDER_CLAMP` (Sprint 076 → 079).

## deliverables

- `signals/0.6.json` (copy of 0.5 + 2 new tag entries + version bump + updated `_note` + updated Layer-9 `version_metadata`).
- `signals/0.6-rationale.md` (delta, migration notes, grammar-growth record).
- `src/price_space_llm/_vocab/0.6.json` (symlink to `signals/0.6.json`, matching 0.1-0.3 shape).
- `load_vocabulary` default 0.5 → 0.6 in `src/price_space_llm/signals.py`.
- `run_tokenizer_pt` emits `TOKENIZED_ARTIFACT_WRITTEN` at write-time (versioned path + sha256 + n_channels + n_rows + mask_semantics).
- `fit_frozen_normalizer` emits `NORMALIZER_CHANNEL_UNDER_CLAMP` per hit BEFORE raising in strict mode; also fires in lenient mode as a pure warning-side surface.
- `tests/test_signals.py::test_locked_vocabulary_loads_all_tags` pointer bumped to 0.6.

## tests (+2)

- `test_run_tokenizer_pt_emits_tokenized_artifact_written` in `tests/test_tokenizer.py`.
- `test_fit_frozen_normalizer_emits_normalizer_channel_under_clamp` in `tests/test_normalizer.py`.

## observation contract

Live smoke on the 2015-2022 training window: `TOKENIZED_ARTIFACT_WRITTEN` fires once in `logs/tokenize-…/signals.jsonl` at `t=0.1265` carrying the versioned path.
