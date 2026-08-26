# Sprint 076 -- std-clamp configurability + under-clamp warn helper

---

```yaml
---
id: 076
status: closed
phase: E
pass_kind: architecture
determinism_budget: bit-deterministic
---
```

## scope

Close the 2026-08-16 `## Drift watchlist` entry from the review's § 11 first small finding. `normalizer/frozen.py` uses a module-level `STD_CLAMP = 1e-8` in `apply_frozen_normalizer`; for known-constant event channels (`event__FOMC`, `event__CPI_RELEASE`, `event__OPTIONS_EXPIRY`) the clamped division correctly yields 0/1e-8 = 0. A future engineered feature whose genuine std lies inside `[1e-9, 1e-7]` would silently over-normalize with no signal.

Fix: promote `std_clamp` to a `FrozenNormalizer` field with default 1e-8 that round-trips through write / load; ship a `warn_channels_under_clamp(normalizer, exempt=EXPECTED_CONSTANTS) -> list[(channel, feature_index, std)]` helper the caller can invoke to surface any non-exempt channel whose std sits inside the clamp band. Opt-in — no live behavior change unless a caller wires the check.

## deliverables

- `FrozenNormalizer` gains `std_clamp: float = 1e-8` as a keyword-only field. The dataclass is frozen; the field participates in equality and in the persisted payload.
- `apply_frozen_normalizer` uses `normalizer.std_clamp` instead of the module constant. `STD_CLAMP` remains as a module-level default so existing test-callers that construct `FrozenNormalizer` with no `std_clamp` still see `1e-8`.
- `write_frozen_normalizer` payload dict adds a `"std_clamp"` key. `load_frozen_normalizer` reads the key; missing key (pre-Sprint-076 artifacts on disk) falls back to `STD_CLAMP` for backward compatibility.
- New `EXPECTED_CONSTANT_CHANNELS: frozenset[str]` — the three event channels ship as always-zero-std by construction; the helper's default `exempt` set.
- New `warn_channels_under_clamp(normalizer, *, exempt=EXPECTED_CONSTANT_CHANNELS) -> list[tuple[str, int, float]]` returns `(channel, feature_index, std_value)` tuples for every non-exempt (channel, feature_index) where `std < std_clamp`. Empty list means every non-exempt std is safely above the floor.
- Docstring on `apply_frozen_normalizer` names the new field and the warn-helper's role.

## tests (+4)

1. `test_frozen_normalizer_default_std_clamp` — new `FrozenNormalizer(mean={...}, std={...}, feature_count=N)` reports `std_clamp == 1e-8`.
2. `test_apply_uses_normalizer_std_clamp_not_module_constant` — build a `FrozenNormalizer` with `std_clamp=1.0` on a constant column; assert the apply divides by 1.0, not 1e-8.
3. `test_write_load_round_trip_preserves_std_clamp` — write a normalizer with `std_clamp=1e-6`; load; assert the loaded value equals 1e-6.
4. `test_warn_channels_under_clamp_reports_non_exempt_only` — construct a normalizer with two channels: one `event__FOMC` with std=0 (exempt), one `target__SPY` with `std[3]=1e-10` (below default clamp). Assert helper returns `[("target__SPY", 3, ~1e-10)]` and does not report `event__FOMC`.

## context files

- `src/price_space_llm/normalizer/frozen.py`
- `src/price_space_llm/normalizer/__init__.py`
- `tests/test_normalizer.py`
- `BLACKBOARD.md ## Drift watchlist` (2026-08-16 STD_CLAMP entry)

## artifact contract

Files created or modified:

- `src/price_space_llm/normalizer/frozen.py` — modified: field, apply, write/load, helper, constant set
- `src/price_space_llm/normalizer/__init__.py` — modified: export `warn_channels_under_clamp` and `EXPECTED_CONSTANT_CHANNELS`
- `tests/test_normalizer.py` — modified: +4 tests

Content assertions:

- `grep -q "std_clamp" src/price_space_llm/normalizer/frozen.py`
- `grep -q "warn_channels_under_clamp" src/price_space_llm/normalizer/frozen.py`
- `grep -q "EXPECTED_CONSTANT_CHANNELS" src/price_space_llm/normalizer/frozen.py`

## signal contract

Emits: none new. The helper returns a list; the caller decides whether to log, raise, or continue. If a future sprint wants a `NORMALIZER_CHANNEL_UNDER_CLAMP` emit tag, that's a v0.6 vocab bump on its own; Sprint 076 does not force it.

## observation contract

No product behavior change unless a caller wires `warn_channels_under_clamp`. Sprint 076 does not add the wiring to `scripts/measure_drift.py` or the trainer path; that is a follow-up sprint's job. Live smoke: re-run the training-partition drift measurement against the regenerated Sprint 075 .pt and assert the emitted `NORMALIZER_DRIFT_MEASURED` payloads stay bit-identical to the Sprint 055 baseline (the STD_CLAMP behavior only fires on constant columns which pass through unchanged).

## commands

```
uv run ruff check .
uv run mypy
uv run pytest -q
```

## notes

- Two code files + one test file — inside hard rule 6.
- Backward compatibility: pre-Sprint-076 `.pt` normalizer artifacts on disk have no `std_clamp` key; `load_frozen_normalizer` falls back to the module `STD_CLAMP=1e-8`. Existing consumers of `FrozenNormalizer` that skip the new kwarg get the same default.
- `EXPECTED_CONSTANT_CHANNELS` lives in the same module as the helper; a project that adds a fourth known-constant channel edits the frozenset and reruns the check.
- Follow-up sprints: (a) wire the warn helper into `scripts/measure_drift.py` so a fit surfaces suspicious channels at the CLI level. (b) v0.6 vocab bump adding a `NORMALIZER_CHANNEL_UNDER_CLAMP` incident-stratum tag for structured signal-side reporting.
