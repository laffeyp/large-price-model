# Sprint 074 -- config-driven context lengths (64 / 128 / 256 / 512)

---

```yaml
---
id: 074
status: closed
phase: E
pass_kind: architecture
determinism_budget: bit-deterministic
---
```

## scope

Land the four spec-pre-registered context lengths as JSON configs and wire `scripts/train.py` to overlay them onto `ExperimentConfig.context_len`. Roadmap item 068. Sibling to Sprint 073's shape. No GPU. No sweep runs — those are Sprint 085 on rented hardware.

Spec (`plans/v1-roadmap.md` § 1 + § Phase E):

- `context_len` ∈ {64, 128, 256, 512}
- Already constrained to that set by the `ExperimentConfig.context_len: Literal[64, 128, 256, 512]` field.
- Before Sprint 074 the trainer reads a single hard-coded value from `configs/experiment/v1.json` (currently 64). No sweep knob.

## deliverables

- `configs/context/64.json`, `128.json`, `256.json`, `512.json` — each carries `{"context_len": N}` and nothing else. Mirrors `configs/model/` under hard rule 7 (one file per pre-registered value).
- `ContextLenConfig(BaseModel)` in `src/price_space_llm/config.py`. Pydantic v2. `context_len: Literal[64, 128, 256, 512]`. `load_context_len_config(path)` returns the validated config; `ContextLenConfigValidationFailed` raises on parse failure. Mirrors the `ModelSizeConfig` shape one-for-one.
- `scripts/train.py` gains `--context-size {64,128,256,512}` (loads `configs/context/{N}.json`) and `--context-config PATH` (loads any JSON matching the schema). Mutually exclusive. When present, overlays `cfg.context_len` on the `ExperimentConfig` via `ExperimentConfig.model_copy(update={...})`.
- `run_id` picks up a `-c{N}` infix when `--context-size` is present, so per-context checkpoints and traces do not collide on the disk. Composes with Sprint 073's `-{size}` infix.
- Stderr prints the resolved `context_len` at session open.

## tests (+5)

1. `test_context_len_config_rejects_off_spec_value` — Pydantic raises on `context_len=100`.
2. `test_context_len_config_accepts_all_four_spec_values` — every canonical `configs/context/{N}.json` on disk parses; value equals filename.
3. `test_load_context_len_config_round_trips` — round-trip `configs/context/128.json` → `ContextLenConfig` → dict → identical.
4. `test_train_cli_rejects_both_context_size_and_context_config` — passing both to `scripts/train.py` returns exit 1 with a stderr note.
5. `test_train_cli_c128_smoke_on_pt_artifact` — end-to-end 2 CPU steps at `--context-size 128 --model-size xs` against the real training .pt artifact; expects exit 0, stderr shape line names `context_len=128`, `-c128` infix in the trace directory name. Skipped if the .pt artifact isn't on disk.

## context files

- `src/price_space_llm/config.py`
- `scripts/train.py`
- `tests/test_config.py`
- `tests/test_train_device.py`
- `plans/v1-roadmap.md` § 1 + § Phase E
- `sprints/sprint-073-model-size-configs.md` (parallel shape)

## artifact contract

Files created or modified:

- `configs/context/64.json`, `128.json`, `256.json`, `512.json` — created
- `src/price_space_llm/config.py` — modified: adds `ContextLenConfig`, `load_context_len_config`, `ContextLenConfigValidationFailed`
- `scripts/train.py` — modified: two mutually-exclusive context flags; overlay via `model_copy`; run_id `-c{N}` infix; stderr context line
- `tests/test_config.py` — modified: 3 context-len-config tests appended
- `tests/test_train_device.py` — modified: 2 CLI tests appended

Content assertions:

- `configs/context/64.json` reads as `{"context_len": 64}` — same shape at 128, 256, 512.
- `grep -q "class ContextLenConfig" src/price_space_llm/config.py`
- `grep -q "\\-\\-context-size" scripts/train.py`

## signal contract

Emits: none new. `SESSION_INIT`, `CONFIG_RESOLVED` fire as they already do. `CONFIG_RESOLVED.context_len` in v0.5 already carries the resolved value as a string-enum payload, so the trace is self-describing for context length — one better than Sprint 073's model-shape gap. No v0.6 vocab pressure from this sprint.

## observation contract

Not required — no product behavior change beyond the length of the sampled window. Live smoke at `--context-size 128 --model-size xs` against the training .pt is the observation. Live smoke also exercises the composition of the two Phase E dispatch knobs.

## commands

```
uv run ruff check .
uv run mypy
uv run pytest -q
uv run python scripts/train.py \
  --tokens-pt data/tokenized/<training-run>.pt \
  --model-size xs --context-size 128 --n-steps 2 --eval-every 2 --seed 41 \
  --device cpu --warmup-steps 0
```

Expected: ruff + mypy + pytest all green; train exits 0; stderr prints `context_len=128`; trace directory carries `-xs-c128-` infix.

## notes

- Two code files (`config.py`, `scripts/train.py`) + 4 tiny data configs + 2 test files touched. One concept: dispatch multiple context lengths from configs. Inside hard rule 6.
- Backward compatibility: existing test smokes without `--context-size` continue to read `context_len` from `configs/experiment/v1.json` and land at 64. Sprint 053-058 checkpoints unaffected.
- `ExperimentConfig.model_copy(update={"context_len": N})` re-runs Pydantic validation, so overlaying `context_len=100` from a hand-authored `--context-config` file fails at overlay time even if the file parsed. (Actually `model_copy` skips re-validation by default; use `.model_validate({**cfg.model_dump(), "context_len": N})` for the strict path. Sprint 074's live smoke exercises the `--context-size` branch which passes through a `ContextLenConfig` that already validated at load; the overlay just splats the number.)
- Sprint 073's `-{size}` infix and Sprint 074's `-c{N}` infix compose: `run_id = train-<stem>-{size}-c{N}-sN-<seed>`. Sprint 084's rented-GPU sweep script iterates the product of both dispatch axes.
- Sprint 075 candidate: close Sprint 052's `mask` semantic (filed 2026-08-16 in `## Surfaced for review`). Own sprint per hard rule 6.
