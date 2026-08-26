# Sprint 086 -- backfill pre-Sprint-036 cache sidecars + index rows

---

```yaml
---
id: 086
status: closed
phase: E
pass_kind: functional
determinism_budget: bit-deterministic
---
```

## scope

Backfill provenance sidecars + append-only index rows for pre-Sprint-036 cache entries. Closes the 2026-08-13 drift-watchlist item that Sprint 036 named as a follow-up.

## deliverables

- `scripts/backfill_cache_sidecars.py` — walks `data/raw/mcp_av/**/*.json`, synthesizes a `CacheMeta` per file lacking `.meta.json`, writes the sidecar, appends the matching row to `data/raw/cache_index.jsonl`. Idempotent by `cache_key` check.
- Live backfill: 11 sidecars written, 11 index rows appended, no in-place modification of existing data.

## tests +4

Single-file sidecar+row; idempotent second-pass; skip-index-row-when-cache-key-already-present; dry-run writes nothing.

## observation contract

Live smoke on `data/raw/`: pre-backfill `find -name "*.json" -not -name "*.meta.json" | wc -l = 11,119`, `find -name "*.meta.json" | wc -l = 11,108`, `wc -l data/raw/cache_index.jsonl = 11,108`. Post-backfill all three counts equal 11,119.
