# Sprint 070 -- macro features (delta_since_last_release + days_since_release)

---

```yaml
---
id: 070
status: closed
phase: 3
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Ships two of three macro features from spec § 6. `countdown_to_next` deferred to a separate sprint (needs release-schedule integration with Sprint 048's event tables).

## deliverables

- `MACRO_FEATURE_SPECS = ("delta_since_last_release", "days_since_release")` in `features/compute.py`.
- `compute_features` gains `macro` branch:
  - `delta_since_last_release`: `close.diff()` filtered to non-zero on release-day bars, forward-filled between releases; `fill_null(0.0)` on pre-first-release rows.
  - `days_since_release`: `age_since_known_at__{key} / BARS_PER_RTH_DAY` where `BARS_PER_RTH_DAY = 26`. Falls back to null when the aligned parquet lacks the staleness column (pre-Sprint-042).
- Per-channel emission accounting updated in `run_feature_pipeline` for macro channels.
- Tests +2: delta/days shape + values across a synthetic 10-bar frame with one release; macro features do not leak to non-macro channels.

## honest audit

- **`countdown_to_next` deferred.** Requires cross-referencing macro releases with the event channels' scheduled dates. Best implemented in a follow-up sprint that reads `event__CPI_RELEASE__known_at` (Sprint 048) and computes bars-until-next-release per macro channel.
- **`delta_since_last_release` on pre-first-release rows = 0.** Ambiguous choice; alternative was null. Zero keeps the model's input finite; the staleness pair (age_since_known_at) already tells the model "no observation yet" via a large age value.
- **`days_since_release` unit is RTH days at 15-min bars.** 26 bars/day; a 5-day-old release = ~130 bars = 5.0 days.

Tests +2. Count 426 → 428. Ruff + mypy + pytest green.
