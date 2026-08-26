# Sprint 095 -- review 074-094 fixes

---

```yaml
---
id: 095
status: closed
phase: F
pass_kind: architecture
determinism_budget: bit-deterministic
---
```

## scope

Close the two actionable items from `reviews/full-review-sprints-074-094.md` § 7. Position state machine (originally the Sprint 095 slot) slides to Sprint 096; renumbers the Phase F tail: 096 = position + trades; 097 = metrics + block bootstrap; 098 = capacity sweep; 099 = kappa sensitivity plot.

## deliverables

- **§ 7.1 — `SimResult` tracks skipped-vol bar count.** `simulation/skeleton.py::run_simulation_with_policy` currently skips `vol <= 0` bars silently — no counter, no signal. The delta between "bars visited" and "bars decided" is invisible in the trace, so a Sprint 088+ held-out-eval reader parsing `BAR_PROCESSED` counts against `date_range` cannot distinguish "context-window truncation" from "vol-skipped." Fix: add `n_bars_skipped_undefined_vol: int = 0` to `SimResult`; increment on every skipped bar; print a summary line to stderr from `scripts/simulate.py` when non-zero. No new signal tag — deferred to a v0.8 vocab bump if the concern proves recurring; the `SimResult` field is inspectable by downstream code and the stderr line surfaces the count at run-close.
- **§ 7.4 — patch=4 alignment invariant test + comment.** `simulation/skeleton.py::_patch_targets` (moved from `model/trainer.py` — actually lives at `model/trainer.py:_patch_targets`, verify) has the arithmetic `targets[:, patch-1::patch]` documented at Sprint 087 in the sprint card but no docstring-level explanation and no dedicated invariant test. Fix: (a) add a doc-comment block naming the "patched position p corresponds to sampler slice index `(p+1)*patch - 1`" invariant with a worked example (patch=4, T=64, output positions `[3, 7, 11, ..., 63]`); (b) add `test_patch_targets_alignment_invariant_matches_paper_indexing` that constructs a known-shape target tensor and verifies element indexing byte-for-byte.

## tests (+2)

1. `test_patch_targets_alignment_invariant_matches_paper_indexing` — synthetic targets `[1, 16]` filled with `range(16)`; `_patch_targets(t, 4)` returns `[3, 7, 11, 15]`. Same for patch=1 (identity).
2. `test_run_simulation_with_policy_counts_vol_skipped_bars` — synthetic artifact where half the bars have `vol=0`; `SimResult.n_bars_skipped_undefined_vol` equals the null-vol count; `SimResult.n_bars_processed` counts only the non-skipped bars.

## artifact contract

Files created or modified:

- `src/price_space_llm/simulation/skeleton.py` — `SimResult.n_bars_skipped_undefined_vol`; walker increments + returns.
- `scripts/simulate.py` — stderr line reports skipped count when non-zero.
- `src/price_space_llm/model/trainer.py` — `_patch_targets` docstring gets the invariant + worked example.
- `tests/test_train_device.py` OR new `tests/test_patch_alignment.py` — invariant test.
- `tests/test_simulation_policy.py` — vol-skip counter test.

## signal contract

No new signal tags. The § 7.1 concern names a v0.8 vocab candidate (`BAR_SKIPPED_UNDEFINED_VOL` incident tag or `BAR_PROCESSED.processed: bool`); Sprint 095 lands the `SimResult` field + stderr line as the minimum-viable observability; a subsequent vocab-bump sprint can promote to signal-side if downstream consumers need it.

## observation contract

REQUIRED — `SimResult` shape changes; downstream consumers read one new field. Live smoke on the real 2015-2022 corpus rerun of Sprint 094's 400-row slice: expect same 336 processed bars; expect zero skipped bars (Sprint 094 already established the corpus has positive vol in the range).

## commands

```
uv run ruff check .
uv run mypy
uv run pytest -q
```

## notes

- 3 code files + 2 test files. Under hard rule 6.
- § 7.2 (val_nll slot rename under quantile head) — deferred to Sprint 090+ quantile-specific metrics work per Sprint 089's card.
- § 7.3 (chance-level predictions) — watch item; the fix is Sprint 084 GPU sweep producing non-chance predictions. No code action here.
- § 7.5 (bucket-count sweep at same context_len) — watch item; Sprint 084+ sweep script owns the axis-comparison discipline.
- Sprint 085 retracted card landed alongside this sprint as a paired hard-rule-12 audit-trail marker.
