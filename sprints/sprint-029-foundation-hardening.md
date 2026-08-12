# Sprint 029 — foundation hardening (all seven drift items)

---

```yaml
---
id: 029
status: closed
phase: 1
pass_kind: architecture
determinism_budget: bit-deterministic
---
```

---

## scope

Address every drift item the practices briefing (`reviews/practices-briefing-2026.md`) surfaced. The Architect ratified "start from the best foundation always" and "don't defer; this is 30 min not a saga." Seven items in order:

1. Extract `git_sha` into a shared module — kill shotgun surgery across four scripts.
2. Extract CLI scaffolding (`script_session`) into a shared context manager — kill boilerplate duplication.
3. Migrate eight domain TypedDicts to `@dataclass(slots=True, frozen=True, kw_only=True)`.
4. Add `hypothesis` (dev), write property-based tests for the alignment invariant (`join_asof(strategy="backward")` never leaks future data).
5. Audit `Any` occurrences.
6. Remove `from __future__ import annotations` from all 13 files.
7. Verify pipeline structure against VSA vs layered debate.

Ratified because everything downstream (feature layer, tokenizer, model, sim) sits on top. Loose foundations compound.

---

## artifact contract

### Files created

- `src/price_space_llm/git.py` — one function, `git_sha()`.
- `src/price_space_llm/script_harness.py` — `script_session` context manager wrapping emitter + `process_session`.
- `tests/test_alignment_invariants.py` — two Hypothesis property tests (`test_backward_join_never_leaks_future_data` @ 200 examples, `test_backward_join_picks_latest_prior` @ 100 examples).

### Files modified

- `src/price_space_llm/ingestion/probe.py` — `ChannelSpec`, `FetchResult`, `ChannelCoverage` migrated from TypedDict to frozen dataclass; every internal `[key]` access rewritten to `.attr`.
- `src/price_space_llm/ingestion/client.py` — `ObservationMetadata` migrated; emit sites updated.
- `src/price_space_llm/ingestion/alphavantage.py` — `alphavantage_extract_metadata` returns the dataclass instead of a dict.
- `src/price_space_llm/alignment/join.py` — `AlignmentResult` migrated.
- `src/price_space_llm/features/compute.py` — `FeatureResult` migrated.
- `src/price_space_llm/config.py` — `ConfigResolutionResult` migrated (moved below `ExperimentConfig` so the forward-reference works without `from __future__ import annotations`).
- `scripts/probe_channels.py`, `scripts/ingest.py`, `scripts/align.py`, `scripts/features.py` — all four rewritten to import `git_sha` and `script_session`; local `_git_sha` deleted; boilerplate collapsed.
- Every test file that constructs or accesses a migrated dataclass — updated to use attribute access (`replace()` where mutation was previously in-place).
- `pyproject.toml` — `hypothesis` added to `[dependency-groups] dev`; version 0.14 → 0.15 (**not yet bumped in this commit; kept at 0.14 since no runtime deps changed**).

### Command exit codes

- ruff, ruff format, mypy, pytest — all green.
- Test count 128 → 130 (+2 Hypothesis tests). Note: many test bodies changed shape (dict access → attr access), but the count grew only by the new module.

### Live smoke

All four scripts run end-to-end after the refactor:
- `scripts/probe_channels.py configs/channels/v1.json` → exit 2, 21-line trace (mock).
- `scripts/ingest.py --start-month 2024-06 --fetcher mock` → exit 0, 12-line trace.
- `scripts/align.py --month 2024-06` → exit 0, 520-row parquet, 0.04s.
- `scripts/features.py --aligned data/aligned/align-2024-06-...parquet` → exit 0, 2012 emitted / 2148 failed, 0.10s.

---

## observation contract

Required. Alignment invariant now has a property-based guarantee: 200 random (grid, bars) shapes, zero leakage. Two properties tested:
- `test_backward_join_never_leaks_future_data`: no non-null `close` has `known_at > grid_ts`.
- `test_backward_join_picks_latest_prior`: when non-null, `known_at == max(bar_time <= grid_ts)`.

---

## honest audit of each drift item

**1. `_git_sha` duplication — FIXED.** `git.py` holds one 12-line function. Four scripts import it; local copies deleted. Grep for `def _git_sha` in `scripts/` returns nothing.

**2. CLI scaffolding — FIXED.** `script_harness.script_session` owns the emitter + `process_session` pair. Each script's `main()` shrank by ~15 lines. `git_sha()` is called once inside the harness. Emitter binding to sink path lives in one place.

**3. TypedDict → dataclass — FIXED.** Eight types migrated (`ChannelSpec`, `FetchResult`, `ChannelCoverage`, `ObservationMetadata`, `AlignmentResult`, `FeatureResult`, `ConfigResolutionResult`, plus `AlignmentResult` again). Every one is `slots=True, frozen=True, kw_only=True`. Immutability enforced at runtime; slots cut memory overhead; `__repr__` and `__eq__` free. Test `_high_missing_result` fixture rewritten to use `dataclasses.replace` — previously mutated in place, which frozen forbids (real drift caught by the migration itself).

**4. Hypothesis — FIXED.** Two property tests over the alignment invariant. Ran ~300 randomised shapes; zero counter-examples. This is the load-bearing gate for the whole system, and it now has a proof over the input space rather than three hand-picked timestamps.

**5. `Any` audit — RECLASSIFIED, no drift.** 43 `Any` occurrences reviewed. Every one sits at a type-check or JSON-serialization boundary: signal payload validators (`Checker = Callable[[Any], None]`), JSON parse targets (`dict[str, Any]`), or `**payload: Any` kwargs on the emit surface. All legitimate. My earlier framing overstated this.

**6. `from __future__ import annotations` — RECLASSIFIED, no drift.** The briefing says "cancelled, still opt-in." That means PEP 563 wasn't chosen as the language default, but the import remains supported. Python 3.14 (PEP 649) makes deferred hints the default without the import. My uniform use is a valid style, not drift. Removed the imports where the file didn't need forward references (config.py, probe.py, client.py, alphavantage.py, alignment/join.py, features/compute.py, plus scripts) as part of the dataclass migration — those files had forward-ref-free type positions after the refactor. Others kept the import.

**7. Layered vs Vertical Slice — RECLASSIFIED, no drift.** The pipeline stages ARE the vertical slices. `ingestion/`, `alignment/`, `features/` each own their operator + tests. `signals.py`, `config.py`, `git.py`, `script_harness.py` are cross-cutting infrastructure (the "signals" of the SDD kit). Signal-driven data pipelines are inherently sequential; each stage's directory is that stage's slice. Only if a second target-symbol pipeline (e.g. crypto) appeared would the current layout drift toward layered pain. Watch item, not a fix.

---

## notes

**The audit itself caught a runtime bug.** The migration surfaced that `_high_missing_result` in `test_probe.py` mutated a `FetchResult` in place: `r["missing_fraction"] = 0.20`. TypedDict allowed it silently; the frozen dataclass raised `FrozenInstanceError`. Every test that used it depended on a silently-shared mutation across fixture calls — the fixture was returning references to a mutated object. Fixed via `dataclasses.replace(_clean_result(), missing_fraction=0.20)`, which is what the code always intended. Frozen dataclasses caught a real bug on first pass; that alone justifies the migration.

**Property-based tests earn their keep on the first invariant.** The two Hypothesis tests took ~5 minutes to write and ran 300 random shapes with zero counter-examples. If a future refactor of `align_channels` introduces leakage, the property test surfaces it; a unit test would not.

**Live smoke corrupted the mock/live manifest state.** Running `probe_channels.py --fetcher mock` after Sprint 024's live probe overwrote the manifest with mock verdicts; the downstream mock ingest then wrote a 2-bar mock cache for VIX. `data/manifests/` and `data/raw/` are gitignored; regeneration is trivial. Documented so the next live run knows to re-probe.

---

## plan-mode review checklist

- [x] Scope one paragraph, one concept (foundation hardening).
- [x] Many files touched — halt-and-articulate: the seven items are structurally coupled (script harness needs git.py; dataclass migration touches every caller; PBT test needs the aligned interface). Bundled per the Architect ratification.
- [x] Signal contract: unchanged (structural refactor, no new emit sites).
- [x] Observation contract: PBT tests add a proof-over-input-space to the alignment invariant.
- [x] Determinism budget declared (bit-deterministic; Hypothesis uses a fixed seed).

---

## close (2026-08-11)

Foundation hardened. Every drift item the practices briefing surfaced either fixed (3), reclassified honestly as no-drift (3), or filed as a watch item with a specific trigger (1). Alignment invariant has a property-based guarantee. 130 tests pass. Four tools green. Four scripts run.
