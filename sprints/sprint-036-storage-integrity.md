# Sprint 036 -- storage integrity (cache index + provenance + freshness + artifact versioning)

---

```yaml
---
id: 036
status: closed
phase: 2
pass_kind: architecture
determinism_budget: bit-deterministic
---
```

---

## scope

The historical pull would have written ~200 opaque `sha256.json` files with no provenance, no freshness policy, and no downstream artifact chain. Sprint 036 lands the storage discipline BEFORE the pull:

1. **Cache provenance sidecars.** Every `write_with_meta` also writes `{sha256}.json.meta.json` with tool, channel, symbol, params, pulled_at_utc, pulled_by_run_id, git_sha, size_bytes, response_schema_hash.
2. **Append-only cache index.** Every write appends one JSON line to `data/raw/cache_index.jsonl`; a Reviewer can grep the index instead of computing sha256s by hand.
3. **Freshness windows per tool.** `TIME_SERIES_INTRADAY` + `HISTORICAL_OPTIONS` are immutable (`math.inf`); `REALTIME_BULK_BID_ASK_PRICES` and `REALTIME_OPTIONS` are 5s; `GLOBAL_QUOTE` is 30s. `read_with_freshness` returns `None` when the sidecar's `pulled_at` exceeds the tool's max age; caches without sidecars fail the freshness check under any non-infinite policy.
4. **Versioned artifacts.** `bucket_stats.{run_id}.json` + `bucket_stats.latest.json` symlink. Same shape for `spread_scaler`, `kappa`, and any future frozen artifact. `write_versioned` writes bytes + sha256 sidecar + flips the symlink. `resolve_latest` returns the current target; `list_versions` enumerates all writes.

`IngestionClient` migrates to `write_with_meta` + `read_with_freshness` in the same commit so the pull sprint (037) inherits the discipline automatically. `tokenizer.write_bucket_stats` + `cost_calibration._write_json_artifact` + `trainer.run_training` (checkpoint symlink) all adopt the versioned writer.

## halt-and-articulate

**Hard rule 6 stretch.** Files touched: `cache.py` (rewrite), `client.py` (call new API), `artifacts.py` (new), `tokenizer/bucketize.py`, `cost_calibration/calibrate.py`, `model/trainer.py`, `scripts/calibrate.py` (unchanged behavior, adopts new API through calls), plus two new test files (`test_cache_hygiene.py`, `test_artifacts.py`) plus updates in `test_ingest_cli.py`, `test_trainer.py`, `test_tokenizer.py`, `test_cost_calibration.py`. Above the ≤2 code files ceiling. Bundled because the API contract (write_with_meta + write_versioned) needs every consumer migrated in the same commit — a split would ship one caller on the new API while others still write with the legacy `write`, producing an inconsistent cache tree.

**Reader-side migration deferred.** `IngestionClient.call` uses `read_with_freshness` on cache-hit; the `HISTORICAL_OPTIONS` responses cached by earlier live smokes have no sidecar and would be served (immutable policy) but would not appear in the cache index. Not a bug — pre-Sprint-036 caches are legacy, still valid data. Filed as a drift-watchlist entry: any Reviewer counting `wc -l data/raw/cache_index.jsonl` under-counts the actual cached files by the pre-Sprint-036 total. Backfill script (walks `data/raw/**/*.json` and materialises meta + index rows) is a small follow-up sprint if the discrepancy matters.

**Legacy artifact files stay on disk.** `artifacts/tokenizer/bucket_stats.json` and `artifacts/cost_calibration/{spread_scaler,kappa}.json` from Sprints 030+035 remain. New writes land at `{stem}.{run_id}.json`; `{stem}.latest.json` symlinks flip to newest. Old files aren't deleted (append-only artifact philosophy). A `latest` symlink written into a directory with a pre-existing `bucket_stats.json` just adds a symlink alongside; no collision.

## signal contract

### Emits

No new emit sites. All existing sites (`INGESTION_CALL_ISSUED`, `INGESTION_CALL_CACHED`, `RAW_OBSERVATION_WRITTEN`, `REVISION_LANDED`, `BUCKET_STATS_WRITTEN`, `SPREAD_SCALER_WRITTEN`, `KAPPA_WRITTEN`, `CHECKPOINT_WRITTEN`) keep firing. The `path` fields on artifact-write tags now carry versioned filenames instead of logical base paths.

### Invariants

- Sidecar sha256 == content sha256 recorded in the artifact-write emit's payload.
- `latest` symlink target == the most-recently-written versioned file for that base path.
- Cache index has exactly one row per `write_with_meta` call. No duplicates from the same key (SDD note: the ingest client currently DOES call `write_with_meta` on every fresh fetch, including re-writes; the index accumulates a row per revision, which matches the `REVISION_LANDED` semantic).
- Freshness policy is per-tool. Missing sidecar → cache-miss under any bounded policy; cache-hit under immutable policy.

## artifact contract

### Files created

- `src/price_space_llm/artifacts.py` (~110 lines: `write_versioned`, `resolve_latest`, `list_versions`, `versioned_path`, `latest_symlink_path`).
- `tests/test_cache_hygiene.py` (14 tests).
- `tests/test_artifacts.py` (9 tests).

### Files modified

- `src/price_space_llm/ingestion/cache.py` -- gains `write_with_meta`, `read_with_freshness`, `read_meta`, `meta_path`, `CacheMeta` dataclass, `FRESHNESS_POLICY` dict, `_response_schema_hash`, `_write_meta`, `_append_index`. Legacy `read`/`write` retained.
- `src/price_space_llm/ingestion/client.py` -- calls `write_with_meta` on cache-miss; `read_with_freshness` on cache-hit; new `run_id` + `git_sha` constructor kwargs threaded into every write's provenance sidecar.
- `src/price_space_llm/tokenizer/bucketize.py::write_bucket_stats` -- routes through `write_versioned`; new `run_id` kwarg.
- `src/price_space_llm/cost_calibration/calibrate.py::_write_json_artifact` -- routes through `write_versioned`; returns `(sha256, versioned_path)` tuple.
- `src/price_space_llm/model/trainer.py` -- writes `{run_id}-latest.pt` symlink alongside each checkpoint save.
- Four test files updated (`test_ingest_cli.py`, `test_trainer.py`, `test_tokenizer.py`, `test_cost_calibration.py`) to filter `.meta.json` sidecars from `rglob`, exclude `-latest.pt` from checkpoint counts, and check versioned filenames.

### Command exit codes

- ruff, ruff format, mypy, pytest all green.
- Test count 238 -> 260 (+22: 14 cache-hygiene, 9 artifacts-versioning, -1 net from tightened assertions).

### Live smoke

Retokenize on Sprint 026's June 2024 features parquet:

```
uv run python scripts/bucketize.py --features data/features/features-align-2024-06-...parquet \
    --training-start 2024-06-03 --training-end 2024-06-28
```

Produces `bucket_stats.tokenize-features-align-...json` + `.sha256` sidecar + `bucket_stats.latest.json` symlink.

Cost-calibrate live with 2 fresh BBO polls (exercises cache_index + provenance sidecar):

```
uv run python scripts/calibrate.py --options-start 2024-04-15 --options-end 2024-06-15 \
    --bbo-snapshots 2 --bbo-interval-seconds 1 --kappa-bootstrap 100
```

Produces `data/raw/cache_index.jsonl` with 2 fresh rows (options were cache-hit, BBO polls fresh), `{sha256}.json.meta.json` sidecars for each new BBO fetch, versioned `spread_scaler.calibrate-....json` + `kappa.calibrate-....json` + `.latest.json` symlinks. CLI summary line prints versioned paths.

---

## observation contract

Required (`pass_kind: architecture`). Live smoke verified:
- Cache index appends per fresh write (2 BBO polls → 2 rows).
- Sidecar `.meta.json` written next to each fresh cache file.
- Versioned artifact + `.sha256` + `.latest` symlink triad for each `write_bucket_stats` and cost-calibration write.
- Emit payload's `path` field carries the versioned filename.
- Legacy immutable caches (pre-Sprint-036) still serve on cache-hit.

Freshness invariant proven by `test_read_with_freshness_returns_none_when_stale`: a REALTIME_BULK_BID_ASK_PRICES entry pulled 60s ago (past its 5s window) returns `None` from `read_with_freshness`; a fresh entry within the window returns the payload.

Versioning invariant proven by `test_second_write_flips_latest_symlink`: two `write_versioned` calls at different `run_id`s produce two versioned files and one symlink pointing at the newest.

---

## honest audit

**What actually landed.** A cache tree where every entry carries its own provenance, a policy per tool for what "fresh" means, and an append-only index a Reviewer can grep. Frozen artifacts where every write is namespaced by `run_id` and a `latest` symlink offers ergonomic access without hiding the version chain.

**What did not land.** No backfill for pre-Sprint-036 caches (7 `HISTORICAL_OPTIONS` + `TIME_SERIES_INTRADAY` entries with no sidecars, invisible in the index). No `REVISION_LANDED` handler that atomically re-versions downstream artifacts. No pruning policy. No cache-key rename to include a schema version. Each is a knowable follow-up, not a hidden gap.

**What surfaced during test writing.** Two class of test-drift showed up on the run after the migration:

1. `rglob("*.json")` counted `.meta.json` sidecars. Every test that counted cache files needed a filter (`if not p.name.endswith(".meta.json")`). Fixed at the assertion, not the sidecar naming — the sidecar suffix (`.meta.json`) is what the spec calls for.
2. Checkpoint `glob("*.pt")` counted the `-latest.pt` symlink. Same class: fix the assertion, keep the symlink shape.

Both are exactly the drift the storage-integrity refactor was meant to shake out. TypedDict-to-frozen-dataclass in Sprint 029 flushed similar test-writer assumptions. Pattern: introducing on-disk state alongside the primary artifact needs a test-suite audit; the audit's cheap when the tests exist.

**One SDD principle applied. Cost neutrality.** The pull sprint (037) will do ~200+ fresh fetches. Storage-integrity has to hold up under that volume before the pull runs — cost isn't a constraint but honesty about state is. If Sprint 037 writes 200 files with no sidecars and no index rows, a Reviewer six months later cannot tell why any given cache entry exists. That's the failure Sprint 036 prevents.

---

## notes

**Why not `wal` or `SQLite`.** JSONL is human-inspectable, append-only-safe under sequential single-writer workload, and requires no dep. When the pull sprint runs and generates ~200 rows, `less data/raw/cache_index.jsonl` still reads. A SQLite migration lands when the row count or concurrency demands it, not before.

**Why hardcode freshness in a Python constant.** `FRESHNESS_POLICY` is a module-level `dict[str, float]`. Config-file-driven would defer a change to config-parsing surface for zero present benefit. When a tool's semantics change (AV renames or the market microstructure requires a different window), the change is one line + one test.

**Symlink semantics.** `latest` symlinks use relative targets (`bucket_stats.r7.json` rather than an absolute path), so `data/` can move without breaking. `Path.resolve()` follows the symlink correctly.

**No emit for the storage-integrity work itself.** Sprint 036 does not introduce any new vocabulary tag. The SDD principle: infrastructure that supports the emit surface does not need its own emit. The cache-index rows are the audit trail; the sidecar is the provenance; neither is a signal.

---

## plan-mode review checklist

- [x] Scope one paragraph, one concept (storage integrity: cache + artifact versioning).
- [x] Files exceed hard rule 6; halt-and-articulate above.
- [x] Signal contract: no new tags, existing tags carry versioned paths in payload.
- [x] Observation contract (architecture-band): live smoke + invariant proofs.
- [x] Determinism budget declared (bit-deterministic — content-hashed writes, sha256 sidecars).
- [x] Retroactive backfill filed to drift-watchlist rather than done inline.
- [x] Cost-neutrality principle honored.

---

## close (2026-08-13)

Landed. Cache tree carries provenance. Artifacts carry version. Freshness policy per tool. Every downstream emit's `path` field records the versioned filename. Test count 238 -> 260. Four tools green. Storage discipline holds; Sprint 037 (multi-month CLIs) proceeds against a hardened storage layer.
