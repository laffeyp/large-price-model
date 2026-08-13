# Sprint 037 -- multi-month alignment CLI

---

```yaml
---
id: 037
status: closed
phase: 2
pass_kind: functional
determinism_budget: bit-deterministic
---
```

---

## scope

Extend `scripts/align.py` to alignment across a month range. Sprint 038's operational pull needs a single aligned parquet spanning 2015-01 through 2022-12 (training) plus 2024-01 through 2025-06 (test); the pre-Sprint-037 CLI only accepts one month per run.

`features.py` and `bucketize.py` already consume whatever parquet the previous stage wrote — their filename carries the range, so no CLI change is needed. Sprint intent named all three; verification below shows only `align.py` is month-parametric.

## halt-and-articulate

**Only align.py gained flags.** `features.py::main` reads a single `--aligned` parquet and writes a single features parquet, no dates in its interface. `bucketize.py::main` takes `--training-start` and `--training-end` as dates already, not months. Sprint scope originally listed all three; the honest execution touches one CLI, one operator, one test file. Two-line note here to make that visible; the sprint-scope-vs-actual-change gap is real and worth naming.

**Signature break, not deprecation.** `run_alignment(month: str, ...)` → `run_alignment(months: list[str], ...)`. Every call site migrates in the same commit. Two test call sites and one script call site. Keeping the old kwarg for backward compat would put every future reader through two code paths for a one-day-old API.

## signal contract

### Emits

No new emit sites. Existing `ALIGNMENT_RUN_STARTED` now reports the full range in `date_range_start` / `date_range_end` — first day of first month, last day of last month. `ALIGNMENT_ROW_EMITTED` fires per grid bar as before (65 weekdays × 26 bars = 1690 rows for the three-month smoke). `AS_OF_JOIN_MISS` fires per (channel, grid_ts) with no prior observation as before.

### Invariants

- Grid dates span `first_of(months[0])` through `last_of(months[-1])`. Empty months list raises `ValueError` (guarded by `test_run_alignment_rejects_empty_months`).
- Per-channel bars concatenate across months, dedupe on `known_at`, sort. Duplicate `known_at` values from month boundaries collapse to one row (Polars `.unique(subset="known_at")`).
- Backward-fill causality invariant unchanged. The join runs on the full concatenated bar frame; earlier months' bars are always in-scope for later months' grid rows.

## artifact contract

### Files modified

- `src/price_space_llm/alignment/join.py` — added `enumerate_months(start_month, end_month) -> list[str]`, `_month_first_day`, `_month_last_day`. Replaced `run_alignment(month: str, ...)` with `run_alignment(months: list[str], ...)`. Per-channel bar-load loop iterates months, `pl.concat` + `.unique(subset="known_at")` + `.sort("known_at")` before the join.
- `src/price_space_llm/alignment/__init__.py` — export `enumerate_months`.
- `scripts/align.py` — added `--start-month` / `--end-month`. Mutually exclusive with `--month`. Missing all three exits 2 with a message. `config_hash` inputs the comma-joined month list. `run_id` uses `range_tag` = `--month` value OR `{start_month}-{end_month}`.
- `tests/test_alignment.py` — updated two existing `run_alignment` call sites from `month="2024-06"` to `months=["2024-06"]`. Added 8 new tests: 6 covering `enumerate_months` (single, within-year, cross-year, reverse-rejected, malformed-rejected, out-of-range-rejected), 1 covering multi-month concatenation (`test_run_alignment_concatenates_across_months` — two months of SPY bars → 1118 rows in the aligned parquet, `date_range_start` and `date_range_end` reported at month boundaries), 1 covering the empty-months guard.

### Command exit codes

- ruff, ruff format, mypy, pytest all green.
- Test count 260 → 268 (+8).

### Live smoke

Three cached SPY + USO months (2024-06, 2024-07, 2024-08):

```
uv run python scripts/align.py \
    --manifest scratchpad/sprint037-manifest.json \
    --start-month 2024-06 --end-month 2024-08 \
    --output-dir data/aligned
```

Exit 0. `align: 1690 rows in 0.08s; missing_fractions=[target=0.000, market_context=0.000]; output=data/aligned/align-2024-06-2024-08-0000000000000000.parquet`.

Row-count arithmetic: 65 US weekdays across the three months × 26 15-min RTH bars/day = 1690. Matches.

Chained through the pipeline:

```
uv run python scripts/features.py \
    --aligned data/aligned/align-2024-06-2024-08-0000000000000000.parquet \
    --output-dir data/features
```

Exit 0. `features: 13373 emitted, 147 failed in 0.31s`. The 147 failures are the rolling-window burn-in at the series start (feature k needs the prior window_k bars).

```
uv run python scripts/bucketize.py \
    --features data/features/features-align-2024-06-2024-08-0000000000000000-0000000000000000.parquet \
    --training-start 2024-06-03 --training-end 2024-08-30
```

Exit 0. `tokenize: 1689 tokens in 0.08s; n_buckets=32 channels=2`. Wrote `artifacts/tokenizer/bucket_stats.tokenize-features-align-2024-06-2024-08-....json` with `.sha256` sidecar; `bucket_stats.latest.json` symlink flipped from the earlier June-only run to the new three-month run. Sprint 036 storage discipline held under a real chained smoke.

Read-back: `pl.read_parquet(tokens_parquet).height == 1690` (one row per grid bar); columns `grid_ts`, `target__SPY__bucket_id` present. Downstream trainer will consume this parquet unchanged.

---

## observation contract

Required (`pass_kind: functional`). Live smoke exit 0 across three chained scripts on the full 2024-06 through 2024-08 window. Emit surface unchanged. Grid arithmetic proven by direct calculation (65 weekdays × 26 bars = 1690).

Multi-month invariant proven at unit level: `test_run_alignment_concatenates_across_months` writes June and July SPY bar caches, aligns with `months=["2024-06", "2024-07"]`, asserts `total_rows == 1118` (43 weekdays × 26 bars) and `date_range_start == "2024-06-01"` / `date_range_end == "2024-07-31"` on `ALIGNMENT_RUN_STARTED`.

`enumerate_months` proven exhaustive: single-month identity, within-year sequence, cross-year sequence, reverse-input rejection, malformed-input rejection, out-of-range-index rejection.

---

## honest audit

**What landed.** Multi-month alignment as a single call. Full pipeline smoked on three months in under one second wall-clock. Storage discipline from Sprint 036 verified against a range-longer smoke: bucket_stats gets a distinct versioned filename, `.sha256` sidecar written, `latest` symlink flipped, prior single-month artifact preserved.

**What did not land.** No CLI-level integration test for `scripts/align.py` — the operator-level test covers the range logic and the CLI is a thin wrapper (arg parsing + one call). Sprint 038 (operational pull) will exercise the CLI directly and would surface any wiring gap immediately.

**What surfaced during execution.** The originally-scoped "extend all three scripts with --start-month --end-month" was wrong. `features.py` reads a parquet path; `bucketize.py` takes date ranges as `date` objects, not months. Named on the sprint card at scope rather than silently dropping two of the three deliverables.

**Determinism check.** Same `--start-month --end-month --seed` produces byte-identical output_path because `run_id` is deterministic; the aligned parquet's content is deterministic given cached inputs (as-of join is deterministic). Bit-deterministic budget holds.

---

## notes

**Why `pl.concat(...).unique(subset="known_at")`.** Alpha-Vantage's TIME_SERIES_INTRADAY response for month M includes some bars from adjacent months (the "extended_hours=true" default + boundary bars). Concatenating raw could produce duplicate `known_at` values from adjacent-month overlap. Dedupe on `known_at` picks the first occurrence; since both are the same bar (identical vendor payload), the choice is inert. Sorting after dedupe keeps the frame monotone for the as-of join.

**Grid arithmetic edge case.** If `enumerate_months("2024-01", "2024-12")` runs but no month has cached bars for the target, `load_channel_bars` raises `FileNotFoundError` on the first missing month — deliberate; the pull sprint (038) must land cached data before the range align runs.

**`--month` retained.** Backward-compat shorthand for single-month runs. Not deprecated. Two callers (the sprint 026 live smoke and this sprint's tests) still use it.

---

## plan-mode review checklist

- [x] Scope one paragraph, one concept (multi-month alignment).
- [x] Files under hard rule 6 (2 code + 1 script + 1 test file).
- [x] Signal contract: no new tags; existing tags carry accurate range info.
- [x] Observation contract (functional-band): live smoke + unit invariants.
- [x] Determinism budget declared (bit-deterministic).
- [x] Scope-vs-actual gap named honestly (only align.py needed flags).

---

## close (2026-08-12)

Landed. Three-month SPY + USO alignment runs in 0.08s. Full features → tokenize chain produces 1690 tokens over 65 weekdays. Storage discipline from Sprint 036 held under the longer smoke. Test count 260 → 268. Four tools green. Sprint 038 (operational pull + full pipeline over the tech-arch training + test ranges) proceeds against a range-aware alignment CLI.
