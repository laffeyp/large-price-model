# Sprint 072 -- event features (release_flag + mins_to_next_release)

---

```yaml
---
id: 072
status: closed
phase: 3
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Ships spec § 6 event features on `event__EARNINGS_DENSITY_SPX`, `event__FOMC`, `event__CPI_RELEASE`, `event__OPTIONS_EXPIRY` — the four event channels Sprint 048 built.

## deliverables

- `EVENT_FEATURE_SPECS = ("release_flag", "mins_to_next_release")`.
- `EVENT_CLIP_SESSIONS = 10` (spec-mandated ±10-session clip). `EVENT_CLIP_MINUTES = 10 × 26 × 15 = 3900`.
- `compute_features` gains `event` branch:
  - `release_flag`: reads `observed_at_this_grid_step__event__X` staleness column (Sprint 042); 1 iff fresh event bar, 0 elsewhere.
  - `mins_to_next_release`: reverse pass over the staleness column. Counts bars until the next fresh event, multiplies by 15 min, clips at 3900. Rows with no forthcoming event within the horizon land at the clip.
- Per-channel emission accounting updated for `event` channel.

Tests +2: two-event synthetic frame produces correct flag + minutes-to-next; no-event frame clips uniformly to `EVENT_CLIP_MINUTES`.

## honest audit

- **`mins_to_next_release` is future-peeking.** Non-leaking on FOMC / CPI / options-expiry because those schedules are public months in advance. On `event__EARNINGS_DENSITY_SPX` the schedule is public within weeks, less so — spec allows this as a countdown feature and the reverse-pass over the already-aligned staleness column is the simplest honest implementation.
- **`mins` unit is minutes, not bars.** 15 minutes per bar; clip at 3900 = 10 sessions × 26 bars × 15 min.
- **Fallback when staleness column absent.** Older aligned parquets pre-Sprint-042 have no `observed_at_this_grid_step__` column. Feature values land as null then.

Tests +2. Count 430 → 432. Ruff + mypy + pytest green.
