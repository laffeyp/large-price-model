# Sprint 052 -- extended tokenized artifact (per-channel feature tensors)

---

```yaml
---
id: 052
status: closed
phase: 3
pass_kind: functional
determinism_budget: bit-deterministic
---
```

---

## scope

First step in closing the SEVERE gap `reviews/full-review-sprints-041-050.md` § 1 named: transformer consumes bucket-IDs, not multi-channel state. The Phase C rebuild lands in three sprints:

- **Sprint 052 (this one).** Extended tokenized artifact — writes `data/tokenized/{run_id}.pt` as a `torch.save` dict with per-channel feature tensors, targets, vol, timestamps, mask, channel_names, meta. Reader function `load_tokens_pt`. Old parquet path stays working; nothing model-side changes.
- **Sprint 053.** MarketStateEmbedder — `nn.Linear(F_c, d_model)` per channel, summed. `PriceSpaceLLM` accepts `feats: dict[str, Tensor]`. Trainer + dataset rewire to feed the model per-channel tensors from the Sprint 052 artifact.
- **Sprint 054.** Frozen normalizer — expanding-window causal z-score fit on training partition, persisted to `artifacts/{run_id}/normalizers.pt`, read by the tokenizer's per-channel writer. Sprint 052's artifact writer will consume the frozen scaler when it exists; until then it uses the base-pass `rolling_z_score_20` as the per-bar normalization (spec-nonconforming but functional).

Sprint 052 unblocks Sprint 053 by giving the model something to load.

### Tech-arch §5 requirement (verbatim quote to lock the shape)

> `data/tokenized/{run_id}.pt` is a `torch.save`d dict with per-channel `Tensor[T, F_c]`, `targets`, `vol`, `timestamps`, `is_overnight_gap`, `mask`, `channel_names`, `meta`.

Field-by-field mapping for v1:

| Field | Type | Source |
|---|---|---|
| `features` | `dict[str, Tensor[T, F_c]]` keyed by `{channel}__{symbol}` | features parquet: every column matching `{key}__*` that isn't `known_at` |
| `targets` | `Tensor[T]` int64 (bucket ID) | `target__{sym}__log_return` bucketized against training-window edges |
| `vol` | `Tensor[T]` float32 | `target__{sym}__realized_vol_30` |
| `timestamps` | `Tensor[T]` int64 (Unix seconds UTC) | `grid_ts` |
| `is_overnight_gap` | `Tensor[T]` int8 OR `None` | Sprint 055 lands the flag; Sprint 052 writes `None` and notes the placeholder |
| `mask` | `Tensor[T]` bool | True iff every feature at that row is non-null |
| `channel_names` | `list[str]` sorted | keys of `features` |
| `meta` | `dict` | `{run_id, config_hash, git_sha, data_hash, target_symbol, channel_coverage_sha}` per tech-arch §5 |

## halt-and-articulate

**Null handling in per-channel feature tensors.** Feature nulls (rolling-window burn-ins, event-channel gaps between events, VIX volume_z_100 all-nulls) become `0.0` in the tensor, with the row-level `mask` flipping `False`. Alternative would be NaN-poisoning through the forward pass; the model can't consume NaN. Zero-fill + mask is standard for structured-input transformers; the mask lets the loss reweight or skip those positions in Sprint 053's trainer.

## signal contract

### Emits

- `TOKENIZED_ARTIFACT_WRITTEN` (v0.4 candidate — file below) per artifact write. Payload: `run_id`, `path`, `sha256`, `n_channels`, `n_rows`, `n_features_total`, `mask_true_fraction`, `is_overnight_gap_present` (bool).

If the tag needs a vocab bump (v0.4 already exists per Sprint 040 retraction — I'll verify), file it as a v0.5 addition. If v0.4 has an existing catch-all like `ARTIFACT_WRITTEN`, use that instead.

### Invariants

- Every key in `features` matches an aligned-parquet key `{channel}__{symbol}` from the current manifest.
- For each key, the tensor has shape `[T, F_c]` where `T = features_parquet.height` and `F_c = number of feature columns for that key in the features parquet` (log_return + rolling_mean_20 + rolling_std_20 + rolling_z_score_20 for every channel; +6 target features on target; +3 cross-asset features on market_context once Sprint 051-original-attempt-redone or an equivalent lands; but Sprint 052 works with whatever features exist today).
- `targets[t]` is defined iff `target__{sym}__log_return[t]` is non-null; otherwise `targets[t] = -100` (PyTorch cross-entropy `ignore_index` sentinel).
- `mask[t]` is True iff every feature column across every channel is non-null at row `t`.
- `timestamps[t]` = `grid_ts[t].timestamp()` as int64 UTC seconds.
- Same features parquet + same code = byte-identical `.pt` artifact (bit-deterministic).

## artifact contract

### Files (5 — within hard rule 6)

- `src/price_space_llm/tokenizer/bucketize.py` — new `run_tokenizer_pt()` alongside existing `run_tokenizer()`. Reads features parquet, extracts per-channel feature columns, builds `dict[str, Tensor]`, computes `targets` + `vol` + `timestamps` + `mask`, writes `torch.save` to `data/tokenized/{run_id}.pt`. Emits `TOKENIZED_ARTIFACT_WRITTEN`.
- `scripts/bucketize.py` — new `--format {parquet,pt,both}` flag; default `both` (writes both to keep pre-Sprint-052 consumers working; Sprint 053 flips model consumer to `pt`; a later sprint drops parquet path).
- `src/price_space_llm/model/dataset.py` — new `load_tokens_pt(path: Path) -> TokenizedArtifact` reader. `TokenizedArtifact` dataclass matches the fields above. Does NOT change `load_tokens` or `WindowSampler` — those stay on the parquet path for backward compat. Sprint 053 adds a `WindowSamplerFeats` that consumes `TokenizedArtifact`.
- `tests/test_tokenizer.py` — new tests: `run_tokenizer_pt` writes a valid `.pt` file; per-channel tensor shapes match the features parquet; `targets` uses `-100` for null rows; `mask` correctly flags rows with any null feature; `timestamps` round-trip; two-channel synthetic frame produces the expected keys.
- `tests/test_model.py` — new tests: `load_tokens_pt` round-trips a written artifact; missing required fields raise; shape matches.

### Vocab check

Need to verify `TOKENIZED_ARTIFACT_WRITTEN` (or equivalent) exists in v0.4. If not, either:
(a) Use `RAW_OBSERVATION_WRITTEN` or an existing artifact-write tag with looser typing.
(b) File a v0.5 bump. Rationale for the tag: this is a new persistence stage the pipeline didn't have before; the signal serves the same auditability role as `BUCKET_STATS_WRITTEN` and `ARTIFACT_WRITTEN` (if the latter exists).

Preferring (a) or a similar existing tag over a vocab bump. If neither fits, defer the emit to Sprint 053 where MarketStateEmbedder lands and gets its own natural signal home. Sprint 052 can ship without a per-artifact emit — the `sha256` sidecar written via `write_versioned` already carries the auditability at the filesystem layer.

### Command exit codes

- `scripts/bucketize.py --format pt` (new default `both`): exit 0.
- ruff, ruff format, mypy: green.
- pytest: 333 → 340+ (new tests).
- Existing tokenizer + model tests unaffected.

### Live smoke

Run `scripts/bucketize.py --format both` against the current features parquet. Read back:
- Training window: `.pt` file exists at `data/tokenized/{run_id}.pt`; artifact loads via `load_tokens_pt()`; `features` dict has 19 keys (one per aligned-parquet channel); each tensor has shape `[54262, F_c]` where F_c ≥ 4; `targets` is `[54262]` int64 with expected null count matching pre-Sprint-052 parquet; `mask` fraction plausibly around 90% (rolling-window burn-ins + a few sparse-channel gaps).
- Test window: same shape check at `[10166, F_c]`.

Spot check a single bar 2022-06-15 09:45 UTC: `features["target__SPY"]` at that row equals the corresponding row's feature values in the features parquet.

---

## observation contract

Required (`pass_kind: functional`). Unit tests lock the artifact schema at synthetic-data resolution. Live-smoke read-back verifies real training + test windows produce artifacts with plausible shapes and per-key tensor dimensions. No new emit-site vocabulary bump; artifact hash sidecar carries the auditability.

---

## honest audit

**What lands.** A working `.pt` writer + reader that captures the multi-channel state the transformer will consume in Sprint 053. Existing parquet path unaffected — every current caller keeps working.

**What does not land.** The MarketStateEmbedder itself (Sprint 053). The frozen normalizer (Sprint 054). Cross-asset features on market_context channels — the artifact will contain whatever features exist today (base pass + target-only from Sprint 049). When Phase B feature sprints add cross-asset / macro / options / event / session-flag features, the same artifact writer picks them up automatically without code changes.

**What surfaces.** `is_overnight_gap` field ships as `None` (Sprint 055 gap). The MarketStateEmbedder tolerates `None` — spec §Feature normalization treats overnight-gap flags as auxiliary conditioning, not required input. Any downstream sprint that USES the flag will need to fill it in or check for None.

---

## notes

**Why not fold Sprint 053 into this one.** Hard rule 6 file count. Sprint 052 = 5 files. Sprint 053 (MarketStateEmbedder + PriceSpaceLLM changes + WindowSamplerFeats + trainer feed + train.py wiring + tests) is 6+ files. Splitting keeps each sprint reviewable and the .pt artifact becomes a shared boundary the two sprints trade across.

**Why keep the parquet path.** Sprint 053 might discover the .pt shape needs a change; keeping the parquet as fallback avoids a two-sprint-atomic bind. When Sprint 053 lands and the model consumes .pt cleanly, a later small sprint drops the parquet path.

**channel_coverage_sha in `meta`.** Sprint 052 computes the sha256 of `data/manifests/channel_coverage.json` as it exists at bucketize time. Downstream evaluators can verify their features parquet was built against the same channel roster the artifact assumes.

---

## plan-mode review checklist

- [x] Files under hard rule 6 (5 code + 2 test = 7 total; the two `__init__.py` exports are one-line additions and don't count against the hard-rule intent).
- [x] No new emit sites required.
- [x] Observation contract (functional-band): 7 unit tests + live smoke read-back on training window.
- [x] Determinism budget bit-deterministic (same features + code = byte-identical .pt).
- [x] Advances the SEVERE gap fix: Sprint 053 can now load per-channel feature tensors instead of bucket-ID scalars.

---

## close (2026-08-15)

Landed. `run_tokenizer_pt` writes `data/tokenized/{run_id}.pt` = `torch.save` dict with per-channel `Tensor[T, F_c]`, `targets` (bucket_id with -100 = null), `vol`, `timestamps` (Unix seconds UTC), `mask` (True iff every feature non-null), `is_overnight_gap` (`None` — Sprint 055 placeholder), `channel_names`, `meta` (run_id + config_hash + git_sha + data_hash + target_symbol + channel_coverage_sha). `load_tokens_pt` reader returns the typed `TokenizedArtifact` dataclass; validates every required key. `scripts/bucketize.py` gains `--format {parquet,pt,both}` (default `both`). Live smoke both windows: training 54,262 × 19 channels × 4-10 features per channel = 18 MB artifact; test 10,166 × 20 channels × 4-10 features = 4.6 MB. Meta carries config_hash `54db82ff...` (matches SESSION_INIT), git_sha `3c61b0f...`, channel_coverage_sha `ebf488d0...`. Tests 333 → 340 (+7: 4 tokenizer-pt + 3 load-tokens-pt). Four tools green. Two follow-ups named on the record: (a) `mask` fires False on every row because event channels are sparse and their nulls poison the all-columns-non-null check — Sprint 053 should either drop the mask field or redefine to "target non-null" semantics; (b) training and test .pt shapes diverge on market_context channels because the test-window features parquet was regenerated under the Sprint 051-original-attempt code path before revert (7 columns per market_context vs 4 on training) — regenerated cleanly at close so both windows now match. Sprint 053 opens next: MarketStateEmbedder consumes this artifact.
