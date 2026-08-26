# Sprint 077 -- fail-loud loads for legacy artifacts + roadmap errata

---

```yaml
---
id: 077
status: closed
phase: E
pass_kind: architecture
determinism_budget: bit-deterministic
---
```

## scope

Tighten two SDD invariants that Sprints 075 and 076 left hand-tight instead of bit-tight, then annotate the sprint-vs-roadmap number drift the Architect just named.

Invariant 1 — legacy mask semantic. `load_tokens_pt` at `src/price_space_llm/model/dataset.py` accepts any `.pt` payload with a `mask` field; a pre-Sprint-075 artifact loads clean and returns all-False masks silently. Sprint 075 added `meta["mask_semantics"] = "target_valid_v075"` as a version marker but no consumer checks it.

Invariant 2 — legacy std_clamp. `load_frozen_normalizer` in `src/price_space_llm/normalizer/frozen.py` silently falls back to `STD_CLAMP=1e-8` when the persisted `std_clamp` key is absent. A caller loading a pre-Sprint-076 normalizer gets the module default and does not know the artifact predates the field.

Both loosenings match the pattern Sprint 065's `heldout_guard.guard_heldout_parquet` fixed: refuse by default, accept via explicit acknowledgment kwarg.

Errata — `plans/v1-roadmap.md` was written 2026-08-13 with sprint numbers `042-090` mapped to phases A-I. Real sprints 042-076 landed with feature-and-review work not on the plan; roadmap item 067 (model-size configs) shipped as Sprint 073; item 068 (context-length configs) shipped as Sprint 074. Every downstream number in the roadmap references a sprint slot the sprint log will not carry.

## deliverables

- `LegacyMaskSemanticRefused(RuntimeError)` in `src/price_space_llm/model/dataset.py`.
- `load_tokens_pt(path, *, allow_legacy_mask: bool = False)` — raises `LegacyMaskSemanticRefused` when `meta.get("mask_semantics") != "target_valid_v075"` and the caller has not opted in. Docstring names the acknowledgment shape.
- `LegacyStdClampMissing(RuntimeError)` in `src/price_space_llm/normalizer/frozen.py`.
- `load_frozen_normalizer(path, *, allow_legacy_std_clamp: bool = False)` — raises `LegacyStdClampMissing` when the persisted payload lacks a `std_clamp` key and the caller has not opted in.
- `scripts/train.py` continues to work unchanged — the training `.pt` regenerated in Sprint 075 carries the new marker, so `load_tokens_pt` on it passes without the kwarg. The normalizer artifact on disk was written Aug 15 (pre-Sprint-076); the trainer path does not currently invoke `load_frozen_normalizer`. No caller update needed this sprint.
- Errata block at the top of `plans/v1-roadmap.md` mapping every roadmap sprint number to the real sprint slot (or `deferred` where unresolved), plus a note that the mapping is authoritative going forward and the body of the roadmap will be re-rewritten under a new phase-plan sprint if the drift keeps widening.

## tests (+4)

1. `test_load_tokens_pt_refuses_legacy_mask` — synthetic `.pt` payload with `meta` missing the marker; `load_tokens_pt(p)` raises `LegacyMaskSemanticRefused`.
2. `test_load_tokens_pt_accepts_legacy_with_flag` — same payload; `load_tokens_pt(p, allow_legacy_mask=True)` returns an artifact.
3. `test_load_frozen_normalizer_refuses_legacy_std_clamp` — write a normalizer payload with no `std_clamp` key manually via `torch.save`; `load_frozen_normalizer(p)` raises `LegacyStdClampMissing`.
4. `test_load_frozen_normalizer_accepts_legacy_with_flag` — same file; `load_frozen_normalizer(p, allow_legacy_std_clamp=True)` returns a `FrozenNormalizer` with `std_clamp == STD_CLAMP`.

## context files

- `src/price_space_llm/model/dataset.py`
- `src/price_space_llm/normalizer/frozen.py`
- `src/price_space_llm/normalizer/__init__.py`
- `tests/test_tokenizer.py` (has the `load_tokens_pt` tests today)
- `tests/test_normalizer.py`
- `plans/v1-roadmap.md`
- BLACKBOARD 2026-08-17 entries surfacing the two loosened invariants

## artifact contract

Files created or modified:

- `src/price_space_llm/model/dataset.py` — modified: `LegacyMaskSemanticRefused` + `allow_legacy_mask` kwarg on `load_tokens_pt`.
- `src/price_space_llm/normalizer/frozen.py` — modified: `LegacyStdClampMissing` + `allow_legacy_std_clamp` kwarg on `load_frozen_normalizer`.
- `src/price_space_llm/normalizer/__init__.py` — modified: export `LegacyStdClampMissing`.
- `tests/test_tokenizer.py` — modified: +2 tests.
- `tests/test_normalizer.py` — modified: +2 tests.
- `plans/v1-roadmap.md` — modified: errata block at top with sprint-number mapping.

Content assertions:

- `grep -q "LegacyMaskSemanticRefused" src/price_space_llm/model/dataset.py`
- `grep -q "LegacyStdClampMissing" src/price_space_llm/normalizer/frozen.py`
- `grep -q "Errata (added 2026-08-17)" plans/v1-roadmap.md`

## signal contract

Emits: none new. The failure surface is exception-based, not signal-based; converting to a `LEGACY_ARTIFACT_LOADED` signal-side tag would need a v0.6 vocab bump and belongs in its own sprint.

## observation contract

REQUIRED — the load-time behavior changes on legacy artifacts.

- **Input:** legacy `.pt` on disk (Sprint 054-055 vintage normalizer; Sprint 052-052 vintage tokenized artifact).
- **Expected trace:** exception raised at load call, no partial state observed.
- **Expected artifact:** none; the failure is pre-load.
- **Expected behavior:** Sprint 073/074/075 downstream smokes on the regenerated Sprint-075 training `.pt` continue to exit 0 without opt-in flags because the current artifact carries `mask_semantics = "target_valid_v075"`.

Live smoke: `uv run python scripts/train.py --tokens-pt <regenerated .pt> --model-size xs --context-size 128 --n-steps 2 …` exits 0.

## commands

```
uv run ruff check .
uv run mypy
uv run pytest -q
uv run python scripts/train.py --tokens-pt data/tokenized/tokenize-features-align-2015-01-2022-12-….pt --model-size xs --context-size 128 --n-steps 2 --eval-every 2 --seed 41 --device cpu --warmup-steps 0
```

## notes

- Two code files + two test files + one roadmap-doc annotation. One concept: convert two silent fallbacks into fail-loud acknowledgments. Under hard rule 6.
- Sprint 078 candidate: promote `run_tokenizer_pt`'s bare-path `torch.save` to `artifacts.write_versioned` so future .pt writes chain via `.{run_id}` + `.latest.pt` + `.sha256` sidecar, matching Sprint 036 storage discipline. That's the second storage-integrity invariant the Sprint 075 in-place overwrite exposed. Own sprint per hard rule 6 (touches `bucketize.py` + `dataset.py` + every caller reading the bare path).
- The roadmap re-numbering itself is deferred. This sprint annotates; a phase-plan sprint that renumbers 042-090 lands separately, when the Architect calls it.
