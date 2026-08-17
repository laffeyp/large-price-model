# Sprint 066 -- spec guard tests (no-hardcoded-target + channel source-of-truth)

---

```yaml
---
id: 066
status: closed
phase: 4
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Closes review § 3 aggregate-audit HIGH item: *"No-hardcoded-target grep test + one-source-of-truth channel test absent."* Both tests are pure guards — no product code changes.

## deliverables

- `tests/test_spec_guards.py`:
  - `test_no_hardcoded_target_in_source` — walks `src/price_space_llm/**/*.py`, tokenizes with `tokenize`, greps NAME tokens for `SPY`. String literals + comments skip because they aren't NAME tokens. Fails on any bare NAME hit that isn't in `NAME_EXEMPTIONS` (empty at Sprint 066).
  - `test_no_hardcoded_target_helper_survives_edge_cases` — verifies the helper ignores SPY in docstrings, comments, string literals, and f-strings.
  - `test_no_hardcoded_target_helper_catches_bare_name` — verifies the helper catches `SPY = 42` as a NAME token.
  - `test_channel_source_of_truth_pt_matches_features_parquet` — samples a random 1000-row window on the training aligned parquet and the training features parquet at the same start, then for each row asserts `log(close_t / close_{t-1}) == target__SPY__log_return`. Skips if the corpus isn't present in this checkout.

## honest audit

- **Grep test is currently vacuous** — Sprint 066 verified zero hardcoded SPY names in the current source (only string-literal + docstring references, all filtered). The guard fires when a future change introduces a bare NAME.
- **Channel source-of-truth test uses log_return derivation as a proxy for the raw-to-aligned journey.** A stricter version would rehash the raw JSON cache for a channel and byte-compare — deferred until a real regression makes it worth the fixture cost.

Tests +4. Count 415 → 419. Ruff + mypy + pytest green.
