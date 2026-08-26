# Sprint 090 -- bucket-count variants (roadmap 072) — closes Phase E

---

```yaml
---
id: 090
status: closed
phase: E
pass_kind: architecture
determinism_budget: bit-deterministic
---
```

## scope

Fifth (and last) Phase E ablation infrastructure sprint per tech-arch § 10. Compare validation NLL, top-1, RPS, and simulator Sharpe at `n_buckets ∈ {16, 32, 64}`. The `ExperimentConfig.n_buckets: Literal[16, 32, 64]` field (v0.3 vocabulary) already accepts every value; `fit_bucketizer(..., n_buckets)` computes the correct edges per count. The ablation is achievable via three separate experiment configs today, but a CLI-level `--n-buckets` override + a `-b{N}` run_id infix make sweep scripts (Sprint 087+ candidate) simpler and per-bucket-count artifacts non-colliding on disk.

## deliverables

- `scripts/bucketize.py` gains `--n-buckets {16,32,64}` override that supersedes the value in `configs/experiment/v1.json`. Emit payloads unaffected — `n_buckets` already sits in `CONFIG_RESOLVED` (v0.3+) and `BUCKETIZER_FITTED`.
- `scripts/train.py` gains `--n-buckets {16,32,64}` override that supersedes the config value and threads into `MarketStateTransformerConfig.vocab_size`. `run_id` picks up a `-b{N}` infix when the override is present (or when the config value is not the pre-Sprint-090 default of 32); the infix composes with `-{size}`, `-c{N}`, `-mix`, `-p4`, `-qh`.
- `ExperimentConfig.model_copy(update={"n_buckets": N})` overlay path in `scripts/train.py` re-runs Pydantic validation so an off-spec value raises at overlay time (same pattern as Sprint 074's context-len overlay).

## tests (+3)

1. `test_train_cli_bucketize_override_16_smoke_on_synthetic_pt` — subprocess `scripts/bucketize.py --n-buckets 16` on a synthetic parquet; expects exit 0, `bucket_stats.json` on disk with 15 edges.
2. `test_train_cli_bucketize_override_64_smoke_on_synthetic_pt` — same shape for 64 (63 edges).
3. `test_train_cli_n_buckets_override_infix` — subprocess `scripts/train.py --n-buckets 16` on synthetic tokens .pt; expects `-b16-` in the trace directory name and stderr shape line names `vocab_size=16` (via CONFIG_RESOLVED payload).

## context files

- `src/price_space_llm/config.py`
- `scripts/bucketize.py`
- `scripts/train.py`
- `tests/test_train_device.py`
- `tests/test_bucketize.py` (may need creating; else land in an existing test file)
- `specs/technical-architecture-v4.md` § 10

## artifact contract

Files modified:

- `scripts/bucketize.py` — modified: `--n-buckets` override.
- `scripts/train.py` — modified: `--n-buckets` override + `-b{N}` infix + `ExperimentConfig` overlay.
- `tests/test_train_device.py` — modified: +1 CLI infix test.
- New or existing test file for bucketize CLI — modified: +2 subprocess smokes.

Content assertions:

- `grep -q "\\-\\-n-buckets" scripts/train.py`
- `grep -q "\\-\\-n-buckets" scripts/bucketize.py`

## signal contract

Emits: none new. `CONFIG_RESOLVED.n_buckets` (enum<16|32|64>) already carries the resolved value from v0.3 onward; no vocab pressure.

## observation contract

Live smoke: run `scripts/bucketize.py --n-buckets 16 --features data/features/features-align-2015-01-2022-12-….parquet --training-start 2015-01-02 --training-end 2022-12-30 --format pt`; verify the resulting `bucket_stats.latest.json` carries 15 edges (16 − 1); verify `data/tokenized/tokens.latest.pt` targets are `int64` in `[0, 16)` ∪ `{-100}`.

## commands

```
uv run ruff check .
uv run mypy
uv run pytest -q
```

## notes

- 2 code files + 2 test files. Under hard rule 6.
- Closes Phase E ablation infrastructure. Phase F (cost calibration + simulator) opens next; a phase-plan sprint (or an Architect Decision on the historical-BBO question) precedes Phase F opening.
- With Sprint 090 landed, the full Phase E dispatch axes compose in `run_id`: `train-<stem>-{size}-c{N}-mix-p4-qh-b{V}-s{steps}-<seed>` (all six axes present in the extreme case). Sweep scripts iterate the axis product.
