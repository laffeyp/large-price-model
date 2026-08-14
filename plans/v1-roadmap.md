# Price-Space LLM v1 roadmap

**Written:** 2026-08-13, after Sprint 041 (`reviews/pre-gpu-deploy-holistic-review.md` + parallel spec audit).
**Baseline:** commit `d1a64fb`, sprints 001-041 landed, 286 tests green, four tools green.
**Scope:** everything from spec §v1 that is not yet built. v2 and v3+ deferred per `specs/product-spec-v4.md` line 253 ("Building v2 features while v1 does not yet pass its gates" = scope creep).

---

## 1. What v1 requires

Spec §v1 pins one target (SPY), 15-minute bars, 2015-01-01 through 2022-12-31 training, 2023 validation, 2024-01-01 through 2025-06-30 held-out. The deliverable is a report on all sweep + ablation curves, plus a held-out Sharpe with confidence, plus a capacity number, all consumed against pre-registered gates.

Concrete required subsystems, from tech-arch §§1-16 and product-spec §Success gates:

- Ingestion of ~19 channels across 5 categories (target OHLCV; 7 cross-asset; 5 macro; 2 options; ≥4 event; session flags).
- Aligned parquet with per-channel `{open, high, low, close, volume, missing_mask, age_since_known_at, observed_at_this_grid_step}` and event flags/countdowns.
- Feature layer per spec §6 including `bar_shape`, `range_pct`, `volume_z_100`, `dollar_volume`, `spread_proxy`, VIX-specific `vix_level`+`vix_change`, macro `delta_since_last_release`+`days_since_release`+countdown, options 20-day z-score, event release flag + `mins_to_next_release`, `is_overnight_gap`, `minute_of_day`+`day_of_week` sin/cos.
- Frozen expanding-window causal z-score persisted to `artifacts/{run_id}/normalizers.pt`, plus a holdout-vs-training drift diagnostic.
- Extended `bucket_stats.json` carrying `bucket_lower`, `bucket_upper`, `bucket_train_mean`, `bucket_train_median`, `bucket_train_frequency` per bucket.
- `MarketStateEmbedder` per spec §7.2: per-channel `nn.Linear(F_c, d_model)` summed to one `d_model` vector per bar. The transformer input is that vector sequence, not a bucket-id sequence.
- RoPE positional embeddings inside the attention product.
- Optimizer: AdamW with `lr=3e-4`, `betas=(0.9, 0.95)`, `weight_decay=0.1` on 2D params, cosine LR to 10% peak after 2000-step warmup, `bfloat16` mixed precision, grad clip 1.0.
- Random-window sampling with `samples_per_epoch`, all-position CE loss, purged embargo of `H` bars at every split boundary.
- Six baselines: linear head, small MLP (128→64→32), GRU (or TCN, 1M params), transformer at winning sweep point, target-only transformer (non-target channels zeroed at embedder), magnitude-weighted transformer (α=1.0).
- Four architecture ablations: linear-vs-channel-aware fusion, patch=1-vs-4, categorical-vs-quantile head, 16-vs-32-vs-64 buckets.
- Model-size sweep: xs=1M, sm=3M, md=10M, lg=30M (`d_model` ∈ {128,192,384,512}; `n_layers` ∈ {4,6,8,8}; `n_heads = d_model/64`).
- Context-length sweep: 64, 128, 256, 512 bars at winning size.
- Simulator: bar walker, cost model with calibrated spread scaler + kappa on the full training window, risk penalty `lambda_risk * variance(p)`, decision rule with hysteresis, block-bootstrap Sharpe over 18 monthly blocks × 10,000 resamples, capacity sweep, kappa sensitivity plot at {0.5×, 0.75×, 1×, 1.25×, 1.5×, 2×}.
- Held-out evaluation with a filesystem guard on the test partition and a 3-look budget enforced structurally.
- Evaluation metrics: NLL, top-1, top-3, entropy, Brier, RPS, ECE (15 bins), reliability diagram, directional calibration deciles, directional accuracy, rank IC, bucket-boundary drift diagnostic, channel-projection cosine diagnostic, regime-conditional metrics via VIX terciles.
- `experiments/logbook.csv` append-only with one row per training run; `scripts/register_run.py` writes it.
- `check_test_look.sh` pre-commit hook + filesystem guard on `data/aligned/*.parquet` for held-out reads.
- No-hardcoded-target grep test + one-source-of-truth channel test.
- SDD JSONL trace records per-step scalars + per-eval metrics via `TRAINING_STEP_COMPLETED` and `CHECKPOINT_WRITTEN`. `scripts/plot_run.py` reads the trace and writes reliability diagrams + predicted distributions on fixed diagnostic bars (2023-03-13 FOMC, 2023-08-10 CPI) to `artifacts/{run_id}/` as PNG.

Success gates (spec §Success gates for v1):
- Val NLL ≥10% lower than linear.
- Val NLL ≥5% lower than GRU/TCN.
- Val NLL ≥5% lower than target-only ablation.
- Val ECE < 0.05.
- Held-out `Sharpe - 1*SE > 0` and `Sharpe > 0.5`.
- Block-bootstrap ≥70% positive Sharpes.
- Held-out capacity ≥ $1M.
- Kappa sensitivity plot shows Sharpe does not cross zero in [0.5×, 2×].

---

## 2. Built as of Sprint 041

Ingestion, alignment, and cache land. Model, trainer, evaluator, cost calibration, baselines exist in some form. Storage discipline holds. The corpus (54,262 aligned rows for 2015-2022, 10,166 for 2024-2025) sits on disk with content-hashed provenance.

Concretely built (sprint history in `BLACKBOARD.md § Built`):

- `IngestionClient` (Sprint 019, 021) with rate limit, retry, cache-first via sha256 key. Freshness policy per tool (Sprint 036).
- `alignment/join.py::run_alignment` (Sprint 025, 037, 038) with multi-month range, per-channel `tool` dispatch (TIME_SERIES_INTRADAY, INDEX_DATA), `join_asof(strategy="backward")` on `known_at`.
- `features/compute.py` (Sprint 026) computes `log_return`, `rolling_mean_20`, `rolling_std_20`, `rolling_z_score_20` per channel.
- `tokenizer/bucketize.py` (Sprint 030) fits 32 quantile edges on the training partition, writes `bucket_stats.{run_id}.json` with `edges` + `training_range_start` + `training_range_end` (no `bucket_lower/upper/train_mean/train_median/train_frequency`).
- `model/transformer.py::PriceSpaceLLM` (Sprint 031) is a causal decoder with `nn.Embedding(vocab_size, d_model)` input on `tokens: Tensor(B,T)` of bucket-ids. Learned absolute positional embedding, not RoPE. `torch.optim.Adam`, no schedule.
- `model/trainer.py::run_training` (Sprint 031, 032, 041) fires the full training tag surface; val metrics via `compute_metric_set`; `WINDOW_SAMPLED.start_position` carries real starts; `EPOCH_COMPLETED.epoch` is `ceil(tokens_consumed / train_tokens)`.
- `evaluation/{metrics,regimes,evaluate}.py` (Sprint 032) computes 7 metrics; regimes bucket by SPY `rolling_std_20` (VIX substitute — stale since Sprint 038 landed real VIX).
- `baselines.py` (Sprint 033) ships `LinearBaseline`, `TargetOnlyBaseline` (marginal-frequency predictor — wrong shape per spec), `fit_linear` with `magnitude_weighted` variant.
- `cost_calibration/{spread,kappa}.py` (Sprint 035) fits spread scaler + Kyle's-lambda kappa on a 3-month smoke.
- `testlook.py` (Sprint 034) enforces 3-look budget via JSONL log. Not wired into any evaluation script.
- Storage discipline (Sprint 036): versioned artifacts + `.sha256` sidecars + `.latest` symlinks; cache sidecars + append-only index + per-tool freshness policy.
- Operational corpus (Sprint 039): 96 SPY monthly caches (2015-01 through 2022-12) + 18 monthly caches (2024-01 through 2025-06) + 1 VIX INDEX_DATA (1990 through today) = 116 cache_index rows. Aligned + features + tokens on disk for both windows.
- Fixes from Sprint 041: `config_hash` distinct from `data_hash` across 4 CLIs; `WINDOW_SAMPLED.start_position` real; `EPOCH_COMPLETED.epoch` real.

Test count 286. Four tools green. Determinism budget bit-deterministic on data path, statistically-deterministic on trainer.

---

## 3. Gap catalog

Every gap between §1 and §2. Grouped by subsystem, ranked by whether it blocks anything downstream. Sources: `reviews/pre-gpu-deploy-holistic-review.md` (12 items) + Sprint 041 parallel audit (19 items).

### 3.1 Data ingestion

- 16 of 19 spec channels not ingested. Only SPY intraday + VIX daily currently on disk. Missing: QQQ, IWM, TLT, DXY, GLD, USO intraday (6); CPI, FEDFUNDS, DGS10, UNRATE, NFP macro (5); put/call ratio + options volume (2); EARNINGS_CALENDAR + FOMC + CPI-release + options-expiry event tables (≥4).
- DXY needs FX_INTRADAY endpoint, not TIME_SERIES_INTRADAY. Different fetcher path.
- Macro + options + event handlers do not exist. Their `tool` dispatch in `run_alignment` will need per-tool loaders paralleling `load_channel_bars` and `load_index_daily_bars`.
- Fixed `US_EASTERN_OFFSET = timedelta(hours=-5)` is DST-wrong. Internally consistent inside the current SPY-only pipeline but breaks the moment BLS-timestamped macro releases join. Blocker before macro ingestion.

### 3.2 Alignment

- Per-channel columns are close-only. Spec §5 requires `{open, high, low, close, volume}` for target and each cross-asset channel.
- Three "load-bearing" staleness columns per channel absent: `missing_mask__{key}`, `age_since_known_at__{key}`, `observed_at_this_grid_step__{key}`.
- Event flags and countdowns not written.
- No filesystem guard on `data/aligned/*.parquet` for held-out reads.

### 3.3 Features

- Target-side features missing: `bar_shape`, `range_pct`, `volume_z_100`, `dollar_volume`, `spread_proxy`, `realized_vol_30`.
- Market-context features per symbol missing: `realized_vol_30`, `volume_z_100`, `bar_shape`; VIX-specific `vix_level`, `vix_change`.
- Macro features missing: `delta_since_last_release`, `days_since_release`, `age_since_known_at`, `observed_at_this_grid_step`, `countdown_to_next`.
- Options features missing: 20-day z-score + staleness pair.
- Event features missing: release flag + `mins_to_next_release` clipped to ±10 sessions.
- Session flags missing: `is_overnight_gap`, `minute_of_day` sin/cos, `day_of_week` sin/cos.
- Frozen normalizer missing entirely. Rolling z-score is a within-per-bar causal rolling, not the spec's training-partition-fit-then-frozen scaler. Zero writes to `artifacts/{run_id}/normalizers.pt`. Zero emits for `NORMALIZER_FITTED`, `NORMALIZER_STATE_WRITTEN`.
- Normalizer drift diagnostic missing. Product-spec line 251 mandates it. No signal home in v0.3 vocab; no plotting code.

### 3.4 Tokenizer

- `bucket_stats.json` schema missing `bucket_lower`, `bucket_upper`, `bucket_train_mean`, `bucket_train_median`, `bucket_train_frequency`.
- `baselines.py` fakes `bucket_train_mean` from edge midpoints. Simulator cannot decode outer buckets to a numeric expected return.
- `run_tokenizer` writes only `grid_ts` + `bucket_id` to the tokens parquet; tech-arch §5 requires a `meta` dict alongside (`run_id, config hash, git sha, data hash, target_symbol, channel_coverage_sha`).
- Per-channel tokenized tensors not written. Spec §5 requires `data/tokenized/{run_id}.pt` as a `torch.save`d dict with per-channel `Tensor[T, F_c]`, `targets`, `vol`, `timestamps`, `is_overnight_gap`, `mask`, `channel_names`, `meta`. Trainer currently reads bucket-ids only.
- No `apply_bucketizer` step. Test-window tokenization requires reading frozen edges and stamping the test parquet; not built.

### 3.5 Model

- **SEVERE.** `MarketStateEmbedder` absent. `model/transformer.py:36` uses `nn.Embedding(vocab_size, d_model)` on bucket-ids. Spec §7.2 requires per-channel `nn.Linear(F_c, d_model)` summed to one `d_model` vector per bar. Current transformer consumes zero channels. Val_top-1 ≈ 0.10 in the Sprint 040 smoke reflects this exactly. Every downstream test of the multi-channel claim, the target-only ablation, and the channel-mixer ablation is blocked on this.
- RoPE absent. `nn.Embedding(context_len, d_model)` learned absolute positional embedding used instead. `nn.TransformerEncoder` blocks the attention math; requires a hand-written block.
- Model-size sweep infrastructure absent. `TransformerConfig` defaults hardcode d_model=64, n_layers=4, n_heads=4. No CLI knob to sweep. Current ~208K model is below the smallest spec point (xs=1M).
- Context-length sweep infrastructure absent.

### 3.6 Training

- `torch.optim.Adam` (not `AdamW`), no cosine schedule, no 2000-step warmup, no `bfloat16` mixed precision, no `weight_decay=0.1`, no `betas=(0.9, 0.95)`.
- No `torch.use_deterministic_algorithms(True, warn_only=True)`, no `CUBLAS_WORKSPACE_CONFIG=:4096:8`.
- No purged embargo at split boundaries. `dataset.py::split_tokens` is a contiguous slice.
- Checkpoint selection is "latest," not "top-K by val NLL." `trainer.py:250-255` symlinks `latest.pt` to newest step.
- No device handling. Zero `.to(device)` calls; no `--device` arg on `scripts/train.py`. Blocker for the first GPU run.
- Fixed diagnostic-timestamp predicted-distribution logging (2023-03-13 FOMC, 2023-08-10 CPI) not implemented.

### 3.7 Baselines

- Small MLP (128→64→32 on last-position state) absent.
- GRU (1 hidden layer, 128 units, causal, ~1M params) or TCN alternate absent.
- `TargetOnlyBaseline` is a marginal-frequency predictor over training bucket-ids. Spec requires the same transformer architecture with non-target channels zeroed at the embedder. The gate "Val NLL ≥5% lower than target-only" is currently meaningless.
- `REQUIRED_DELTA_PCT` targets `magnitude_weighted` at 5%. Spec targets `gru_tcn` at 5%; `magnitude_weighted` is an ablation, not a gate.

### 3.8 Ablations

- Channel-aware fusion (one-block cross-channel mixer per spec §10 code sketch) absent.
- Patch=4 embedder + head absent.
- Quantile head (9 quantiles, pinball loss) absent.
- Bucket-count-16, bucket-count-64 tokenizer paths absent.

### 3.9 Simulator

- Entire subsystem absent. No `simulation/` dir, no bar walker, no `SimResult`, no `scripts/simulate.py`.
- Nine vocabulary tags have zero emit sites: `SIM_RUN_STARTED`, `SIM_RUN_COMPLETED`, `BAR_PROCESSED`, `PREDICTION_EMITTED`, `DECISION_MADE`, `POSITION_OPENED`, `POSITION_CLOSED`, `TRADE_LEDGERED`, `SIGNAL_DROPPED`.
- No capacity sweep (`CAPACITY_SWEEP_COMPLETED` unused). No sensitivity plot (`SENSITIVITY_PLOT_GENERATED` unused).
- Cost calibration (Sprint 035) ran on a 3-month smoke. Full 2015-2022 re-calibration required before held-out.

### 3.10 Evaluation

- Regime evaluator uses SPY `rolling_std_20` proxy. Sprint 038 landed real VIX; the evaluator has not migrated.
- Bucket-frequency drift diagnostic covers train-vs-val only; spec §10 also requires train-vs-test at final evaluation.
- Directional calibration deciles absent.
- Rank IC (Spearman) absent.
- Channel-projection cosine diagnostic absent.

### 3.11 Infrastructure

- `experiments/logbook.csv` absent. `experiments/` dir absent.
- `scripts/register_run.py` absent.
- `check_test_look.sh` pre-commit hook absent.
- `register_test_look` not auto-wired into `scripts/evaluate.py`.
- Filesystem guard on held-out reads absent.
- No-hardcoded-target grep test absent.
- One-source-of-truth channel test absent.
- No remote GPU provisioning; no `--device cuda` handling.
- Hydra config composition not adopted; single JSON config per stage instead of the spec's grouped YAML.

### 3.12 Signal-vocabulary evolution

- `NORMALIZER_FITTED` and `NORMALIZER_STATE_WRITTEN` exist in v0.3 but have zero emit sites — they land as soon as §3.3's normalizer does.
- `NORMALIZER_DRIFT_MEASURED` does not exist. v0.4 vocabulary bump when the drift diagnostic (§3.3) lands.
- Nine simulator tags exist but have zero emit sites — they land as §3.9 builds.

---

## 4. Sprint sequence

Ordering respects dependencies: data before features before model before training before ablations before simulator before held-out. Each row states the sprint, its scope in one line, the dependencies it clears, and whether it needs GPU. Sprint numbers continue from Sprint 041.

### Phase A: Data foundations

| # | Scope | Depends on | GPU |
|---|---|---|---|
| 042 | Enrich aligned parquet: keep OHLCV per channel; add `missing_mask__*`, `age_since_known_at__*`, `observed_at_this_grid_step__*` columns; live-re-align 2015-2022 + 2024-2025. | — | no |
| 043 | Adopt `zoneinfo("America/New_York")` in `alphavantage.py` and `alignment/join.py`; re-run alignment + features + tokenize on all cached data; test that a March bar and a November bar round-trip correctly. | 042 | no |
| 044 | Ingest 6 cross-asset intraday channels (QQQ, IWM, TLT, GLD, USO via TIME_SERIES_INTRADAY; DXY via FX_INTRADAY). Update `configs/channels/v1.json`. Live-verify probe coverage. Pull 2015-2022 + 2024-2025. Re-align. | 042, 043 | no |
| 045 | Ingest 5 macro series (CPI, FEDFUNDS, DGS10, UNRATE, NFP) via their respective MCP tools. Add per-tool loaders + extractors in `alphavantage.py` and `alignment/join.py`. Live-pull + re-align. | 042, 043 | no |
| 046 | Ingest 2 options series (HISTORICAL_PUT_CALL_RATIO, HISTORICAL_VOLUME_OPEN_INTEREST_RATIO). Live-pull + re-align. | 042, 043 | no |
| 047 | Ingest event tables (EARNINGS_CALENDAR + curated FOMC + CPI-release + options-expiry static tables). Event flags + countdowns land in aligned parquet. | 042, 043 | no |

### Phase B: Feature layer

| # | Scope | Depends on | GPU |
|---|---|---|---|
| 048 | Target features: `bar_shape`, `range_pct`, `volume_z_100`, `dollar_volume`, `spread_proxy`, `realized_vol_30`. Consumes OHLCV per Sprint 042. | 042 | no |
| 049 | Cross-asset features per symbol: `log_return`, `realized_vol_30`, `volume_z_100`, `bar_shape`; VIX-specific `vix_level`, `vix_change`. | 044, 048 | no |
| 050 | Macro features: `delta_since_last_release`, `days_since_release`, staleness pair, countdown-to-next. | 045 | no |
| 051 | Options features: 20-day z-score of each series, staleness pair. | 046 | no |
| 052 | Event features: binary release flag + `mins_to_next_release` clipped to ±10 sessions. | 047 | no |
| 053 | Session flags: `is_overnight_gap` (exact spec code sample), `minute_of_day`/`day_of_week` sin/cos. | 042 | no |
| 054 | Frozen normalizer: expanding-window causal z-score fit on training partition, persist to `artifacts/{run_id}/normalizers.pt`. Wire `NORMALIZER_FITTED` + `NORMALIZER_STATE_WRITTEN` emit sites. Reads use the frozen state. | 048-053 | no |
| 055 | v0.4 vocab: add `NORMALIZER_DRIFT_MEASURED` (payload: `feature_name`, `train_dist_summary`, `holdout_dist_summary`, `ks_statistic`, `p_value`). Wire the evaluator to emit per feature on holdout. Add plotting code (matplotlib). | 054 | no |

### Phase C: Tokenizer + Model rebuild

| # | Scope | Depends on | GPU |
|---|---|---|---|
| 056 | Extend `bucket_stats.json` schema: per-bucket `bucket_lower`, `bucket_upper`, `bucket_train_mean`, `bucket_train_median`, `bucket_train_frequency`. Downstream reads switch from midpoint fake to `bucket_train_mean`. | — | no |
| 057 | Extend tokenized artifact: `data/tokenized/{run_id}.pt` as a `torch.save` dict with per-channel `Tensor[T, F_c]`, `targets`, `vol`, `timestamps`, `is_overnight_gap`, `mask`, `channel_names`, `meta`. Trainer switches from parquet-bucket-ids to this dict. Add `apply_bucketizer` for test window. | 054, 056 | no |
| 058 | **`MarketStateEmbedder`** per spec §7.2. Per-channel `nn.Linear(F_c, d_model)` summed. `PriceSpaceLLM` gains `channel_dims: dict[str, int]` in config; forward takes `feats: dict[str, Tensor]`. Trainer + dataset rewire. Retrain locally against Sprint 057's tokenized dict. Val_top-1 should climb meaningfully above 0.10. | 057 | no (CPU smoke) |
| 059 | RoPE positional embeddings. Hand-write the transformer block since `nn.TransformerEncoder` blocks attention math. Test: causal-mask invariant still holds; a March-position bar and a September-position bar in the same context window get distinct positional rotations. | 058 | no |
| 060 | Trainer optimizer + schedule: `AdamW(lr=3e-4, betas=(0.9, 0.95), weight_decay=0.1)` on 2D params only; cosine LR decay to 10% peak after 2000-step warmup; `bfloat16` via `torch.amp.autocast`; grad clip 1.0. `torch.use_deterministic_algorithms(True, warn_only=True)`. | 058 | no (CPU smoke) |
| 061 | Purged embargo at split boundaries. `dataset.py` accepts `horizon: int` and drops `H` bars at each train/val/test boundary. | — | no |
| 062 | Checkpoint selection: keep top-K by val NLL (not "latest"). `trainer.py` maintains a rolling top-K priority queue on val_nll. | 060 | no |
| 063 | Device handling: `--device {cpu,cuda,mps,auto}` on `scripts/train.py`; move `model.to(device)` and batches inside the loop; test skipped-unless-CUDA. | 060 | no |

### Phase D: Baselines

| # | Scope | Depends on | GPU |
|---|---|---|---|
| 064 | MLP baseline (128 → 64 → 32 GELU) on last-position market-state vector. | 058 | no |
| 065 | GRU baseline (1 hidden layer, 128 units, causal, ~1M params) per spec §10 code sketch. TCN alternate exposed via config. | 058 | no |
| 066 | Rewrite `TargetOnlyBaseline` as spec's zeroed-channel transformer (same architecture as Sprint 058, non-target channels zeroed at embedder). Fix `REQUIRED_DELTA_PCT` to target `gru_tcn` at 5%. Keep `magnitude_weighted` as an ablation, not a gate. | 058, 065 | no |

### Phase E: Ablation infrastructure

| # | Scope | Depends on | GPU |
|---|---|---|---|
| 067 | Config-driven model sizes: `configs/model/{xs,sm,md,lg}.json` with `d_model` ∈ {128,192,384,512}; `n_layers` ∈ {4,6,8,8}; `n_heads = d_model/64`. | 058 | no |
| 068 | Config-driven context lengths: `configs/experiments/{context_64,128,256,512}.json`. | 067 | no |
| 069 | Channel-aware fusion (`ChannelMixerEmbedder` per spec §10 code sketch): per-channel `nn.Linear(F_c, mixer_dim)`, one causal attention block across channels at each timestep, mean-pool + `nn.Linear` back to `d_model`. Parameter-matched to linear fusion. | 058 | no |
| 070 | Patch=4 embedder: `nn.Linear(4 * F_c, d_model)` on packed 4-bar concatenation. Sequence length shrinks 4×. Target aligned to the bar following the last of the four. | 058 | no |
| 071 | Quantile head: 9-quantile output layer (0.1, 0.2, ..., 0.9) trained with pinball loss. Same backbone. | 058 | no |
| 072 | Bucket-count variants: tokenizer paths for `n_buckets ∈ {16, 32, 64}`, config-selectable. | 056 | no |

### Phase F: Cost calibration + Simulator

| # | Scope | Depends on | GPU |
|---|---|---|---|
| 073 | Full-window cost re-calibration: refit the transaction-cost model (`spread_scaler` + `kappa`) against the 2015-2022 training window. Requires historical SPY spread data — see "What this plan does not yet resolve" for the three vendor paths. Sprint 035 fit a 3-month smoke against 2024 live data; that scaler cannot cover the 8-year training window without extrapolation. | 042 | no |
| 074 | Simulator skeleton: `simulation/` dir, `SimResult` dataclass, bar walker over aligned parquet. `SIM_RUN_STARTED`, `SIM_RUN_COMPLETED`, `BAR_PROCESSED`, `PREDICTION_EMITTED` emit sites. | 056, 057, 073 | no |
| 075 | Decision policy: `edge = expected_return - spread_cost - slippage - risk_penalty`. `risk_penalty = lambda_risk * variance(p)`. Long/short/flat with hysteresis. `DECISION_MADE`, `POSITION_OPENED`, `POSITION_CLOSED`, `TRADE_LEDGERED`, `SIGNAL_DROPPED` emits. | 074 | no |
| 076 | Simulator metrics + block bootstrap: Sharpe ± SE, 18 non-overlapping monthly blocks × 10,000 resamples, hit rate, max drawdown, time-to-recovery, per-trade P&L histogram. `TRADING_SESSION_STARTED`/`ENDED` per RTH day. | 075 | no |
| 077 | Capacity sweep: sweep size from $100K through $10M in ~10 steps; report largest size where Sharpe stays positive. `CAPACITY_SWEEP_COMPLETED` payload. | 076 | no |
| 078 | Kappa sensitivity plot: run simulator at {0.5×, 0.75×, 1×, 1.25×, 1.5×, 2×} kappa; report Sharpe curve; fail loudly if Sharpe crosses zero in [0.5×, 2×]. `SENSITIVITY_PLOT_GENERATED` payload. | 076 | no |

### Phase G: Guards + instrumentation

| # | Scope | Depends on | GPU |
|---|---|---|---|
| 079 | `experiments/logbook.csv` writer + `scripts/register_run.py`. Row schema per tech-arch §13: `date, run_id, branch, git_sha, notes, target, model_size, context_len, patch_size, head_type, n_buckets, train_loss, val_nll, val_ece, val_brier, val_rps, val_dir_acc, held_out_sharpe, held_out_sharpe_se, lambda_risk, alpha_mag_weight, touched_test`. | — | no |
| 080 | `check_test_look.sh` pre-commit hook per tech-arch §13. Fails any commit whose changed config files carry dates ≥ 2024-01-01 unless the commit message contains `[test-look]`. Every `[test-look]` commit appends to `experiments/test_looks.log`. | 079 | no |
| 081 | Wire `register_test_look` into `scripts/evaluate.py` when `--split test`. Filesystem guard on `data/aligned/*.parquet` blocks holdout-range reads without `--i-know-this-is-a-test-look`. | — | no |
| 082 | `test_no_hardcoded_target.py` greps `src/` for word-boundary `SPY`, fails on hits outside docstrings. `test_channel_source_of_truth.py` recomputes each per-channel raw value from `data/raw/` and asserts byte-identical match against a random 1000-bar aligned window. Pre-commit hook wires both on staged paths matching `src/features/*` or `src/ingestion/*`. | — | no |

### Phase H: Remote GPU + sweeps + ablations (the actual training runs)

| # | Scope | Depends on | GPU |
|---|---|---|---|
| 083 | Provision AWS GPU (g5.xlarge with A10 for cheap dev, p4d for A100 production sweep points). Sync tokenized parquet + normalizers + bucket_stats + code via git + S3. Verify one end-to-end training run at xs=1M matches local CPU numbers within numerical noise. Trace lands at `logs/{run_id}/signals.jsonl`; `scripts/plot_run.py` writes loss curves to `artifacts/{run_id}/`. | 060, 063 | **yes** |
| 084 | Model-size sweep: 4 runs at xs/sm/md/lg on rented A10 or A100. Log to `experiments/logbook.csv`. Report validation NLL/ECE/Brier/RPS curves. | 083 | **yes** |
| 085 | Context-length sweep at winning model size from Sprint 084: 4 runs at 64/128/256/512. | 084 | **yes** |
| 086 | Baseline ladder (5 runs): linear, MLP (064), GRU (065), transformer at winning config (084 result), target-only ablation (066), magnitude-weighted ablation. | 064, 065, 066, 085 | **yes** |
| 087 | Architecture ablations (4-6 runs): channel-mixer (069), patch=4 (070), quantile head (071), bucket-count-16 + bucket-count-64 (072). | 069, 070, 071, 072, 085 | **yes** |

### Phase I: Held-out evaluation + reporting

| # | Scope | Depends on | GPU |
|---|---|---|---|
| 088 | First held-out test look: run winning-config model against 2024-01 through 2025-06 test partition. Bucket-frequency drift diagnostic (train-vs-test). Normalizer drift diagnostic (055) on holdout. Regime-conditional metrics via VIX terciles from training (evaluator switches from SPY `rolling_std_20` to real VIX per Sprint 038). Simulator run with full cost model. Sharpe ± SE, block-bootstrap distribution, capacity sweep, kappa sensitivity. Consumes 1 of 3 permitted looks. | 054, 055, 073, 076, 077, 078, 081, 084 | **yes** |
| 089 | v1 report: model-size curve, context-length curve, ablation results, baseline gate table, held-out Sharpe + block-bootstrap histogram, per-regime split, kappa sensitivity plot. Every gate from `product-spec-v4.md § Success gates for v1` marked pass/fail with the number. | 088 | no |
| 090 | Second/third test look budget as needed if gates fail on look 1. Each look burns one of the remaining budget. | 088 | **yes** |

Total: 48 sprints from Sprint 042 through Sprint 090 (some parallelizable within a phase; most are sequential).

---

## 5. Notes on this plan

**GPU-vs-CPU split.** Phases A through G run locally on the 28GB machine. First GPU rental starts at Sprint 083 after all model code and one CPU-verified end-to-end run at xs=1M. Cost is not a design constraint per the standing rule; the plan does not pace against a dollar budget.

**Determinism.** Every training run seeds torch/numpy/random/CUDA and calls `torch.use_deterministic_algorithms(True, warn_only=True)` (Sprint 060). Rerunning the same config reproduces metrics to within numerical noise per spec invariant.

**Test-look budget.** Three looks total for v1. Sprint 088 is look 1. Sprints 090+ are looks 2 and 3 if gates fail. The filesystem guard (Sprint 081) makes accidental looks structurally impossible.

**Sprint 042 is the current head of the queue.** It touches `src/price_space_llm/alignment/join.py` and one test file. Everything downstream depends on the enriched aligned parquet.

**What this plan does not do.** No v2 work (multi-instrument) until every v1 gate passes. No v3+ work (alt-data, cross-modal attention, LOB, RL, live paper trading) at all in the current planning horizon. The spec is explicit on both.

**What this plan does not yet resolve.**

- **GPU rental.** Decided 2026-08-13: AWS. Sprint 083 rents an EC2 GPU instance (g5.xlarge for A10 dev at ~$1/hr; p4d.24xlarge or similar for A100 production sweep points).
- **Run tracking.** Resolved 2026-08-13: local files only. The SDD JSONL trace at `logs/{run_id}/signals.jsonl` is the authoritative log. `scripts/plot_run.py` reads the trace and writes loss curves + metric tables to `artifacts/{run_id}/` as PNG. No hosted tracker, no third-party account, no credential.
- **Historical SPY spread data for cost calibration** (Sprint 073). The simulator's cost model subtracts a transaction cost from every simulated trade. That cost is half of the spread between the buy price and sell price on SPY at the trade instant. Sprint 035 pulled today's live spread from Alpha-Vantage for 3 months of 2024 and fit a scaler. To recalibrate against the full 2015-2022 training window, we need historical spread data from that period. Alpha-Vantage does not sell it. Three paths: (a) buy 8 years of SPY historical BBO from Databento (~$100-500), (b) drop ground-truth calibration and estimate spread from bar high/low ranges only via the Corwin-Schultz formula the spec names as a fallback, (c) apply Sprint 035's 2024 coefficient to the training window and assume spread dynamics did not shift across 8 years. Path (a) is the honest one; path (c) is the fastest and weakest.

**Revision policy.** Each sprint closes with its normal card + BLACKBOARD entry. If a sprint surfaces a new gap not in this plan, the plan gets amended in the same commit that files the gap. This document tracks the whole build; sprint cards track each build step.
