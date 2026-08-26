# Sprint 073 -- config-driven model sizes (xs / sm / md / lg)

---

```yaml
---
id: 073
status: closed
phase: E
pass_kind: architecture
determinism_budget: bit-deterministic
---
```

## scope

Land the four spec-pre-registered model sizes as JSON configs and wire `scripts/train.py` to consume them. Opens Phase E (ablation infrastructure). Roadmap item 067. No GPU. No sweep runs — those are Sprint 084 on rented hardware.

Spec (`plans/v1-roadmap.md` § 1 + § Phase E):

- `d_model` ∈ {128, 192, 384, 512}
- `n_layers` ∈ {4, 6, 8, 8}
- `n_heads = d_model / 64` → {2, 3, 6, 8}
- rough param counts: xs ≈ 1M, sm ≈ 3M, md ≈ 10M, lg ≈ 30M

Before Sprint 073 `MarketStateTransformerConfig` and `TransformerConfig` hardcode `d_model=64, n_layers=4, n_heads=4` (~200K params, below the smallest sweep point). The trainer CLI has no knob.

## deliverables

- `configs/model/xs.json`, `sm.json`, `md.json`, `lg.json` — each carries `{d_model, n_layers, n_heads}` and nothing else. Bucket count and context length still live in `configs/experiment/v1.json`.
- `ModelSizeConfig(BaseModel)` in `src/price_space_llm/config.py`. Pydantic v2. `d_model: Literal[128, 192, 384, 512]`, `n_layers: Literal[4, 6, 8]`, `n_heads: Literal[2, 3, 6, 8]`. `load_model_size_config(path)` returns the validated config.
- `scripts/train.py` gains `--model-size {xs,sm,md,lg}` (loads `configs/model/{name}.json` from repo root) and `--model-config PATH` (loads any JSON matching the schema). Mutually exclusive. Default: neither present → keep current 64/4/4 shape for back-compat with existing test smokes and Sprint 053-058 checkpoints.
- Both model builders read the resolved shape: `TransformerConfig(..., d_model=m.d_model, n_layers=m.n_layers, n_heads=m.n_heads)` and same on `MarketStateTransformerConfig`.
- `run_id` gains `-{size}` suffix when `--model-size` is present, so per-size checkpoints and traces do not collide on the disk.
- Print the resolved shape and parameter count to stderr on session open.

## tests (+5)

1. `test_model_size_config_rejects_off_spec_d_model` — Pydantic raises on `d_model=256`.
2. `test_model_size_config_accepts_all_four_spec_sizes` — every canonical `{xs,sm,md,lg}` file on disk parses clean; head-dim = 64 for every one.
3. `test_load_model_size_config_matches_configs_on_disk` — round-trip `configs/model/xs.json` → `ModelSizeConfig` → dict → identical.
4. `test_train_cli_rejects_both_model_size_and_model_config` — passing both to `scripts/train.py` returns exit 1 with a stderr note.
5. `test_train_cli_xs_smoke_on_pt_artifact` — end-to-end 2 CPU steps at `--model-size xs` against the real training .pt artifact; expects exit 0, params ≥ 500K, trace file exists. Skipped if the .pt artifact isn't on disk (mirrors the Sprint 057 live-smoke test pattern).

## context files

- `src/price_space_llm/config.py`
- `src/price_space_llm/model/transformer.py`
- `scripts/train.py`
- `tests/test_config.py`
- `plans/v1-roadmap.md` § 1 + § Phase E
- `specs/technical-architecture-v4.md` § 9

## artifact contract

Files created or modified:

- `configs/model/xs.json` — created
- `configs/model/sm.json` — created
- `configs/model/md.json` — created
- `configs/model/lg.json` — created
- `src/price_space_llm/config.py` — modified: adds `ModelSizeConfig`, `load_model_size_config`, `ModelSizeConfigValidationFailed`
- `scripts/train.py` — modified: two mutually-exclusive model-shape flags; run_id suffix; stderr trace
- `tests/test_config.py` — modified: 3 model-size-config tests appended
- `tests/test_train_device.py` — modified: 2 CLI tests appended (mutually-exclusive; xs smoke)

Content assertions:

- `configs/model/xs.json` reads as `{"d_model": 128, "n_layers": 4, "n_heads": 2}`.
- `configs/model/sm.json` reads as `{"d_model": 192, "n_layers": 6, "n_heads": 3}`.
- `configs/model/md.json` reads as `{"d_model": 384, "n_layers": 8, "n_heads": 6}`.
- `configs/model/lg.json` reads as `{"d_model": 512, "n_layers": 8, "n_heads": 8}`.
- `grep -q "class ModelSizeConfig" src/price_space_llm/config.py`
- `grep -q "\\-\\-model-size" scripts/train.py`

## signal contract

Emits: none new. `SESSION_INIT` and `CONFIG_RESOLVED` fire as they already do. `CONFIG_RESOLVED` still carries only `context_len` / `n_buckets` from the experiment config — the four model-shape fields are NOT in the v0.5 vocabulary. The trace stays reproducible from source (`configs/model/{size}.json` + git SHA) but not from the trace alone. Surface as drift-watchlist entry for a v0.6 vocab bump that adds `d_model`, `n_layers`, `n_heads` to `CONFIG_RESOLVED.typed_payload`; that bump is its own sprint per hard rule 6.

## observation contract

Not required — no product behavior change beyond the shape of the model built. Live smoke on `--model-size xs` against the training .pt artifact (short step count, CPU) is the observation.

## commands

```
uv run ruff check .
uv run mypy src tests
uv run pytest -q
uv run python scripts/train.py \
  --tokens-pt data/tokenized/<training-run>.pt \
  --model-size xs --n-steps 2 --eval-every 2 --seed 41
```

Expected: ruff + mypy + pytest all green; train exits 0; stderr prints resolved shape (`d_model=128 n_layers=4 n_heads=2 params~1M`); one checkpoint on disk; trace file at `logs/{run_id}/signals.jsonl`.

## notes

- Bounding hard rule 6: 2 code files (`config.py`, `train.py`) + 4 tiny data configs + 2 test files touched. One concept: dispatch multiple model sizes from configs.
- Backward compatibility: existing sprints (053, 057, 058) that call `run_training_feats` or `run_training` with a hand-built `MarketStateTransformerConfig(...)` continue to work — the constructor defaults still land at 64/4/4.
- Vocabulary gap left open (v0.6 candidate): `CONFIG_RESOLVED` payload has no `d_model` / `n_layers` / `n_heads`. Sprint 073 files this on the drift watchlist rather than absorbing the vocab bump.
- Deferred to Sprint 074 (roadmap 068): context-length configs. Landing the two concepts in sibling sprints keeps the diff small and the sprint-close pass legible.
