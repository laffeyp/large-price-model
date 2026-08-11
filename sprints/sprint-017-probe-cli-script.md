# Sprint 017 — `scripts/probe_channels.py` CLI + JSONL trace

---

```yaml
---
id: 017
status: closed
phase: 1
pass_kind: functional
determinism_budget: bit-deterministic
---
```

---

## scope

Author `scripts/probe_channels.py` — the first CLI in the project. Reads a channel manifest from `configs/channels/v1.yaml` (a new tiny config), wraps a `run_phase_zero_probe` call in a `process_session` context, writes the JSONL trace to `logs/{run_id}/signals.jsonl`, writes the manifest to `data/manifests/channel_coverage.json`, prints a short stderr summary. Uses the Sprint 016 mock fetcher (Sprint 018 replaces it with the real Alpha-Vantage MCP fetcher).

This is the first end-to-end sprint that produces an actual on-disk JSONL trace and a real manifest file — the observation contract WORKING_AGREEMENT names, verified against a live run rather than a test fixture.

---

## prerequisites

- Sprint 016 closed (probe module + mock fetcher).
- Sprint 012 closed (`process_session` context manager).

---

## context_files

- `src/price_space_llm/ingestion/probe.py`
- `src/price_space_llm/signals.py` (`get_emitter`, `process_session`, `StrictSignalEmitter(vocab, jsonl_sink=...)`)
- `WORKING_AGREEMENT.md § Observation contract environment` (JSONL trace + file existence + line count + exit code)
- `specs/technical-architecture-v4.md §4.1` (Phase 0 probe script)
- `signals/0.2.json` (SESSION_INIT + CHANNEL_PROBED + CHANNEL_COVERAGE_ASSESSED + CHANNEL_REJECTED + SESSION_COMPLETE payloads)

---

## signal contract

### Emits

At CLI invocation:
- `SESSION_INIT` (via `process_session`) with `run_kind="probe"`, real config_hash, git_sha, data_hash, seed.
- `CHANNEL_PROBED` × 5 dates × N channels.
- `CHANNEL_REJECTED` × 0..N (per verdict).
- `CHANNEL_COVERAGE_ASSESSED` × N.
- `SESSION_COMPLETE` with the correct `n_signals_emitted` count.

At test time: the same, driven by `subprocess.run` against the CLI script.

### Consumes

- `configs/channels/v1.yaml` (new file — three channels for Sprint 017: target SPY, market_context VIX, market_context USO).
- `signals/0.2.json` via the module singleton.

### Invariants

- All 34 existing tests pass.
- The CLI exits 0 on all-accepted, 2 on any-dropped (mirrors wordcount example convention). Exit 1 on unrecoverable error.
- `logs/{run_id}/signals.jsonl` is written; first line's tag == SESSION_INIT; last line's tag == SESSION_COMPLETE.
- `data/manifests/channel_coverage.json` is written in the shape Sprint 016 defined.
- The JSONL trace signal count matches SESSION_COMPLETE.payload.n_signals_emitted.

---

## artifact contract

### Files created

- `scripts/probe_channels.py` — the CLI. Reads config, invokes `run_phase_zero_probe`, wraps in `process_session`, writes JSONL sink.
- `configs/channels/v1.yaml` — three-channel manifest for the initial probe (target SPY + market_context VIX + market_context USO).
- `configs/__init__.py`? No — YAML config, not a Python package.
- `tests/test_probe_cli.py` — subprocess-driven test that runs the CLI in a tmp_path, reads back the JSONL and the manifest, asserts on both.

### Files modified

None.

### Content assertions

- `scripts/probe_channels.py` exists and is executable (`#!/usr/bin/env python3` shebang; no need to `chmod +x`, `uv run` invokes).
- `scripts/probe_channels.py` imports `process_session` and `run_phase_zero_probe`.
- `scripts/probe_channels.py` reads a YAML config via stdlib `tomllib` — wait, tomllib is TOML. YAML needs PyYAML dep. Alternative: use a JSON config for now (`configs/channels/v1.json`), defer YAML dep to a later sprint.
- Decision: use JSON for the config this sprint. Adding PyYAML would need a bridge mapping + dep pin per the dep-pin rule; scope creep. Sprint N adds Hydra + YAML per tech-arch §12.
- `configs/channels/v1.json` exists with three channel entries.
- `tests/test_probe_cli.py` runs the script via `subprocess.run`, verifies exit code, JSONL first/last line tags, manifest content.

### Command exit codes

- `uv run ruff check src tests scripts` exit 0 (extend the linter target).
- `uv run ruff format --check src tests scripts` exit 0.
- `uv run mypy src` exit 0.
- `uv run pytest tests/ -v` exit 0; test count ≥ 35.
- `uv run python scripts/probe_channels.py configs/channels/v1.json` exit 2 (USO drops per the mock fetcher's `market_context USO → high_missing`).
- `logs/*/signals.jsonl` exists and parses as JSONL after that run.
- `data/manifests/channel_coverage.json` exists and parses as JSON after that run.

---

## observation contract

Required (`pass_kind: functional`).

### Input fixtures

- `configs/channels/v1.json` (checked in).

### CLI driving steps

```
uv run python scripts/probe_channels.py configs/channels/v1.json
```

### Expected runtime signals

- Line 1 of `logs/{run_id}/signals.jsonl`: `{"tag": "SESSION_INIT", ...}`.
- Lines 2..N-1: 3 channels × (5 CHANNEL_PROBED + 0-or-1 CHANNEL_REJECTED + 1 CHANNEL_COVERAGE_ASSESSED). USO drops (mock returns high missing_fraction).
- Last line: `{"tag": "SESSION_COMPLETE", "exit_code": 2, ...}`.

### Expected log substrings

- Stderr contains `probe:` prefix on the summary line.
- Stderr summary line names the count of accepted/dropped channels.

### Expected exit codes

- Exit 2 when any channel drops.
- Exit 0 when all accepted (verified by a second test with a different config).

---

## done criteria

CLI works. JSONL trace exists with correct first/last lines. Manifest JSON exists. Exit codes match. 35+ tests pass. All tools green.

---

## notes

**YAML deferred; JSON now.** Tech-arch §12 names Hydra + YAML as the config layer. Adding PyYAML this sprint requires a bridge mapping + dep pin. Sprint 017 uses JSON (stdlib) and defers the YAML/Hydra swap to a config-layer sprint. `configs/channels/v1.json` is the file this sprint reads; a later sprint moves to `configs/channels/v1.yaml` behind a Hydra composition.

**Mock fetcher inline in the script.** Sprint 018 replaces it with the MCP fetcher; the script imports both and picks by environment or CLI flag. Keeping the mock in the script (not the module) means the module stays free of test-only code paths.

**Run_id shape.** `process_session` mints `f"{run_kind}-{utc_ts}-{seed}"`. For the CLI, seed comes from a `--seed` flag (default 0 for determinism; env or clock for a real run). Deterministic-by-default matches the sprint's `determinism_budget: bit-deterministic`.

**Config hash.** For Sprint 017, `config_hash = hashlib.sha256(config_path.read_bytes()).hexdigest()`. That's an honest file hash of the config JSON. Sprint N (real Hydra) computes over the resolved config after composition.

**Data hash.** No data-on-disk yet; use `"none"` as a placeholder. When Sprint 019+ authors the aligned parquet, that path's sha256 fills the field. `data_hash` field in v0.2 is typed `sha256` — 64 lowercase hex. `"none"` fails validation. Options: (a) placeholder `"0"*64` (weak; passes the format check by accident of length); (b) allow a null / add a `data_hash_status: str` field; (c) treat `data_hash` as required for train/eval/simulate but not for probe/calibrate — a Layer 7 conditional requirement.

Option (c) is the right long-term answer. For this sprint: use `hashlib.sha256(b"probe:no-data-input").hexdigest()` — a legitimate 64-char hex hash of a well-known input string, signalling "probe run, no data-file dependency." Sprint N when the vocabulary evolves handles the semantics properly.

**Signal count sanity.** With 3 channels × (5 CHANNEL_PROBED + 1 CHANNEL_COVERAGE_ASSESSED) + 1 CHANNEL_REJECTED (USO) + SESSION_INIT + SESSION_COMPLETE = 15 + 3 + 1 + 2 = 21. The test asserts the trace has 21 lines.

---

## plan-mode review checklist

- [x] Scope one paragraph, one concept (probe CLI + JSONL trace).
- [x] Three files created (script + config + test). Within hard rule 6.
- [x] Signal contract cites only v0.2 tags.
- [x] Observation contract present (functional-band).
- [x] Determinism budget declared (bit-deterministic).

---

*Sprint 017. First CLI + first on-disk JSONL trace. Sprint 018 replaces the mock fetcher with the MCP.*
