# Price-Space LLM — Technical Architecture

**Version:** v2 (15-minute bars, review fixes incorporated)
**Target:** SPY, 15-minute bars, ~10 years of history
**Stack:** Python 3.11, PyTorch 2.4+, single GPU (A10 or A100)

---

## 0. What this system is

A causal decoder transformer that reads market history as a token sequence and predicts what the market does next. Same architectural family as GPT; different vocabulary and different target.

Each input token is a compressed *market state* at one 15-minute bar: SPY's recent price and volume behavior, what QQQ/IWM/VIX/TLT/DXY/GLD/USO did, the latest macro readings (CPI, Fed funds, 10Y yield, unemployment, NFP), the put/call ratio, and calendar/event flags. Every channel goes through its own `nn.Linear` projection to a 512-dim embedding, gets summed with a learned channel-type embedding, and produces one 512-dim vector per bar. That vector is the token at that timestep.

Each output token is a discrete label — one of 32 buckets (indexed 0–31) covering the *volatility-normalized* next-bar return. Bucket boundaries are percentile-uniform on the training set. Vol-normalization makes the vocabulary scale-invariant: a one-sigma move in a calm market and a one-sigma move in a volatile one land in the same bucket. The model's output is a probability distribution over those 32 buckets.

Downstream, a bar-by-bar simulator turns each distribution into a trade decision using an explicit cost model: `edge = E[return] − half_spread − k·size − risk_penalty(distribution)`. If `edge > threshold`, take a position sized by `edge / std(distribution)`.

That's the whole system. Everything below is how it's built.

The move from 5-min to 15-min bars in v2 was deliberate. At 15-min the expected per-bar move on SPY is roughly three times larger than at 5-min, which shrinks costs as a fraction of edge proportionally and directly answers the review's warning that Corwin-Schultz on 5-min SPY bars overestimates the true spread by an order of magnitude. It also gives each macro countdown feature per-bar semantics that were essentially constant at 5-min. The dataset shrinks from ~197k to ~65k training bars, which is still enough for a 30M-parameter model.

---

## 1. The pipeline

Data flows one way: vendor sources → aligned Parquet → per-timestep token → 32-way softmax → cost-aware simulator → chronological holdout. Every stage is causal, config-driven, versioned, and independently testable.

```
                                                          Price-Space LLM v2
                                                          ==================

  ┌─────────────────────┐
  │  raw sources        │   Alpha-Vantage MCP (primary) + Polygon (HF fallback)
  │  - equities/ETFs    │
  │  - macro / rates    │──┐
  │  - options / P/C    │  │
  │  - events / cal.    │  │
  └─────────────────────┘  │
                           ▼
              ┌────────────────────────┐
              │  ingestion layer       │  IngestionClient → per-channel modules
              │  (rate-limit + cache)  │  writes Parquet: data/raw/{src}/{ch}/{sym}/YYYY-MM.parquet
              └───────────┬────────────┘
                          ▼
              ┌────────────────────────┐
              │  alignment / join      │  UTC 15-min grid, forward-fill policies,
              │  → aligned dataset     │  missing_mask columns
              └───────────┬────────────┘         data/aligned/{run_id}.parquet
                          ▼
              ┌────────────────────────┐
              │  feature pipeline      │  per-channel causal features
              │  (all causal)          │  + causal z-score normalization
              └───────────┬────────────┘
                          ▼
              ┌────────────────────────┐
              │  tokenizer             │  return bucketizer (32 buckets, 0–31)
              │  + market-state embed  │  + per-channel projection heads
              └───────────┬────────────┘         data/tokenized/{run_id}.pt
                          ▼
              ┌────────────────────────┐
              │  training loop         │  AdamW, bf16, cosine LR, W&B
              │  (transformer)         │  checkpoint by val calibration
              └───────────┬────────────┘         artifacts/{run_id}/*.ckpt
                          ▼
              ┌────────────────────────┐
              │  evaluation            │  CE, top-k, ECE, directional acc,
              │                        │  baselines (linear / MLP / target-only /
              │                        │  magnitude-weighted), regime split,
              │                        │  channel-orthogonality diagnostic
              └───────────┬────────────┘
                          ▼
              ┌────────────────────────┐
              │  simulator             │  bar walker, calibrated cost model,
              │                        │  Sharpe ± SE / DD / capacity
              └───────────┬────────────┘
                          ▼
              ┌────────────────────────┐
              │  results / logbook     │  experiments/logbook.csv + W&B run
              └────────────────────────┘
```

---

## 2. Invariants

Six rules. Violating one is a bug.

**Causal by construction.** A feature at time `t` is a pure function of data with timestamp `< t`. Rolling-window utilities refuse to read past the current row. A unit test shuffles rows with index `> t*` and asserts feature vectors at `t ≤ t*` are byte-identical.

**Time-based splits with embargo.** Train, val, and test boundaries are dates in the config. Between any two boundaries the loader drops `H` bars, where `H` is the prediction horizon, so labels cannot leak. Random splits are forbidden.

**No magic numbers in code.** Window sizes, bucket counts, learning rates, date ranges, channel lists, the risk-penalty `lambda`, the magnitude-weight `alpha` — all live in YAML. Code reads config; code never hard-codes hyperparameters.

**Reproducible training.** Every run seeds `torch`, `numpy`, `random`, and CUDA, enables deterministic algorithms, and logs the config, git SHA, and data hash. Rerunning the same config must reproduce metrics to within numerical noise.

**One source of truth per channel.** Each channel has exactly one ingestion module. Downstream code reads the canonical Parquet — it never re-fetches or recomputes raw values. This kills the class of bug where two callers get different values for "SPY 2023-01-03 14:30 close." A per-commit test enforces it (§16).

**Artifacts and configs ship together.** Every checkpoint sits next to its config, tokenizer boundaries, normalizer stats, cost-calibration artifacts, and git SHA. A `.pt` file alone is not the deliverable.

---

## 3. Repository layout

```
price_space_llm/
  configs/                # YAML experiment configs
    data/                 # channel lists, date ranges, ingestion params
    features/             # per-channel feature specs
    tokenizer/            # bucket count, boundary policy
    model/                # architecture hyperparameters
    training/             # optimizer, schedule, batch, seeds
    simulation/           # cost model, decision thresholds, lambda, alpha
    experiments/          # top-level configs composing the above
  data/
    raw/                  # vendor-native Parquet dumps, immutable
    aligned/              # joined multi-channel Parquet keyed by run_id
    tokenized/            # torch tensors ready for training
  artifacts/              # {run_id}/checkpoint.pt, config.yaml, normalizers.pt, buckets.pt
    cost_calibration/     # spread_scaler.json, kappa.json
  src/
    ingestion/            # IngestionClient + per-channel fetchers
    features/             # causal feature computation + normalization
    tokenizer/            # return bucketizer + market-state embedder
    model/                # transformer blocks, model class, baselines
    training/             # dataloader, loop, checkpointing, logging
    simulation/           # bar walker, cost model, policy
    evaluation/           # metrics, calibration, regime split, plots
    utils/                # timezones, logging, hashing, config loading
  experiments/            # logbook.csv, test_looks.log, saved run summaries
  notebooks/              # exploration only; nothing production runs from here
  tests/                  # pytest suite mirroring src/ structure
  scripts/                # fetch_data.py, align.py, train.py,
                          # evaluate.py, simulate.py, register_run.py,
                          # calibrate_spread.py, calibrate_kappa.py,
                          # check_test_look.sh (pre-commit)
  pyproject.toml          # uv-managed
```

`configs/` is the only place hyperparameters live. `data/raw/` is write-once; corrupting it invalidates every downstream cache. `data/aligned/` and `data/tokenized/` are derived and regenerable. `artifacts/{run_id}/` is the reproducibility bundle. `artifacts/cost_calibration/` is the run-independent bundle that feeds the simulator. Nothing in `src/` is called directly by a human — humans run `scripts/`.

---

## 4. Ingestion

The primary source is the Alpha-Vantage-style financial-data MCP surfaced in this environment. Its tools cover intraday equities (`TIME_SERIES_INTRADAY`), daily adjusted OHLCV (`TIME_SERIES_DAILY_ADJUSTED`), macro series (`CPI`, `FEDERAL_FUNDS_RATE`, `TREASURY_YIELD`, `UNEMPLOYMENT`), options flow (`HISTORICAL_OPTIONS`, `HISTORICAL_PUT_CALL_RATIO`), event calendars (`EARNINGS_CALENDAR`), and news sentiment. One MCP delivers macro, options, and cross-asset series at the frequencies v2 needs.

Fallback is Polygon.io for equities minute bars when the MCP's intraday coverage or history depth falls short. Every ingestion module has a `source` knob; switching is a one-line config change.

`IngestionClient` is a thin façade with a token-bucket rate limiter (75 req/min default), retry-with-backoff on 429/5xx, response validation, and Parquet caching keyed by `sha256(tool, params)`:

```python
class IngestionClient:
    def __init__(self, source: Literal["mcp_av", "polygon"], cache_root: Path,
                 rate_limit_per_min: int = 75): ...

    def call(self, tool: str, **params) -> pd.DataFrame:
        """Cache-first: hash(tool, params) → parquet key. Miss → network → write."""
```

Every channel implements one interface:

```python
class ChannelFetcher(Protocol):
    channel: str  # "target" | "market_context" | "macro" | "options" | "event"
    symbol: str
    def fetch(self, start: dt.datetime, end: dt.datetime,
              freq: Literal["1min","5min","15min","1h","1d"]) -> pd.DataFrame: ...
```

`fetch` requests `15min` where the vendor supports it natively. For series only exposed at 5-min or 1-min, the fetcher downsamples by taking the last bar of each 15-minute interval — `open` from the first sub-bar, `close` from the last, `high`/`low` from the interval extrema, `volume` summed. Downsampling happens in the fetcher, not downstream, so alignment always sees a canonical 15-min grid.

Concrete fetchers for v2:

| Channel | Symbols / series | MCP tool | Native freq | Ingested freq |
|---|---|---|---|---|
| target | SPY | `TIME_SERIES_INTRADAY` | 5min | 15min (downsampled) |
| market_context | QQQ, IWM, VIX, TLT, DXY, GLD, USO | `TIME_SERIES_INTRADAY` | 5min | 15min (downsampled) |
| macro | CPI, FEDFUNDS, DGS10, UNRATE | `CPI`, `FEDERAL_FUNDS_RATE`, `TREASURY_YIELD`, `UNEMPLOYMENT` | daily/monthly | 15min (ffill) |
| options | put/call ratio, options volume | `HISTORICAL_PUT_CALL_RATIO`, `HISTORICAL_VOLUME_OPEN_INTEREST_RATIO` | daily | 15min (ffill) |
| event | earnings, FOMC, CPI releases | `EARNINGS_CALENDAR` + curated static tables | date-only | per-bar countdown |

Fetchers return a DataFrame with a UTC `timestamp` index and channel-specific columns. The fetcher is the only code that touches vendor formats. Everything else — timezones, alignment, forward-fill — happens downstream.

Cache is content-addressed by request parameters, so parameter changes force refetch. Cached responses land at `data/raw/{source}/{channel}/{symbol}/{yyyy-mm}.parquet`.

---

## 5. Storage

**Raw.** `data/raw/{source}/{channel}/{symbol}/{yyyy-mm}.parquet`. Monthly partitioning keeps single-file scans under a second and lets ingestion refresh a single month without rewriting a decade.

**Aligned.** `data/aligned/{run_id}.parquet`. One wide table on a canonical 15-minute UTC grid over the configured date range. Rows exist only for RTH bars; pre- and post-market are dropped to keep the target's session-boundary semantics clean. At 15-min RTH, each session yields 26 bars (6.5 hours × 4 bars/hour), and ten years yields ~65,000 rows.

Columns follow `{channel}__{symbol}__{feature}`:

| Column | Type | Notes |
|---|---|---|
| `timestamp` | `datetime[ns, UTC]` | primary key, 15-min grid |
| `target__SPY__{open,high,low,close,volume}` | float64/int64 | OHLCV |
| `market__QQQ__close`, `market__VIX__close`, ... | float64 | close at the bar |
| `macro__CPI__value`, `macro__DGS10__value`, ... | float64 | last-known daily value carried intraday |
| `options__PCR__value`, `options__VOLOI__value` | float64 | last-known daily value |
| `event__{earnings,fomc,cpi_release}_flag` | int8 | 1 on release date |
| `event__mins_to_{fomc,cpi,earnings}` | float32 | signed countdown, per-bar meaningful at 15-min |
| `missing_mask__{channel}__{symbol}` | bool | true iff raw value was absent at alignment |

Bars where the target itself is missing (halt, holiday) are dropped. For every other channel, missing values are forward-filled and the matching `missing_mask_*` bit flips to `True`. The mask is fed as an input feature so the model conditions on staleness. Zero-imputation is banned because it collides with legitimate zero returns.

**Tokenized.** `data/tokenized/{run_id}.pt` — a `torch.save`'d dict:

```python
{
  "features":  Tensor[T, C, F],      # per-channel raw feature matrix (float32)
  "targets":   Tensor[T],            # bucket id in [0, 32) (int64)
  "vol":       Tensor[T],            # trailing realized vol at t (float32)
  "timestamps": Tensor[T],           # epoch nanoseconds (int64)
  "channel_ids": Tensor[C],          # channel-type index (int64)
  "meta":      dict,                 # run_id, config hash, git sha, data hash
}
```

The training loop reads this one file.

---

## 6. Features

Every feature is computed with strictly causal utilities: `rolling(...).apply(...)` with `min_periods` set, and `.shift(1)` on anything label-adjacent.

For the target (SPY) the suite is `log_return = log(close_t / close_{t-1})`, `realized_vol_30 = std(log_return[t-30:t])`, `bar_shape = (close - open) / (high - low + eps)`, `range_pct = (high - low) / close_{t-1}`, `volume_z_100 = (volume - roll_mean_100(volume)) / roll_std_100(volume)`, `dollar_volume = close * volume`, and a Corwin-Schultz-style `spread_proxy = 2 * |high - low| / (high + low)`. `spread_proxy` is a raw feature; its calibration into a real half-spread happens in the simulator's cost model (§11).

**Vol estimator.** v1 uses 30-bar trailing realized volatility. At 15-min this covers 30 bars ≈ 7.5 hours ≈ just over one trading session. The doc's earlier 60-bar wording was a scoping error; the committed value is 30. Alternates — EWMA (`vol.method: "ewma"`, `vol.halflife: 20`), GARCH(1,1), and VIX-implied — are wired into the config schema but not run as ablations in v1. Committing to 30-bar realized keeps the target's units unambiguous and matches DeepLOB-style baselines.

Market-context symbols (QQQ, IWM, VIX, TLT, DXY, GLD, USO) get `log_return`, `realized_vol_30`, `volume_z_100`, `bar_shape`. VIX additionally emits `vix_level` and `vix_change`.

Macro series (CPI, FEDFUNDS, DGS10, UNRATE) carry the last known value intraday and add `delta_since_last_release` and `days_since_release`. Both are causal because the release timestamp is the moment of publication. At 15-min the countdown-to-next-release features carry per-bar variation across a trading day that they did not at 5-min; the model now has a distinguishable pre-release, at-release, and post-release position within each session.

Options channels (put/call ratio, options volume) carry the last daily value plus a 20-day z-score of each.

Event channels emit a binary flag for "bar falls on release day" plus a signed `mins_to_next_release` clipped to ±10 sessions to keep magnitudes usable.

Continuous features are normalized by expanding-window mean and standard deviation with a 2,000-bar (~77 trading days) warmup:

```
z_t = (x_t - mean(x_{0:t-1})) / (std(x_{0:t-1}) + eps),  t >= 2000
z_t = 0                                                    t <  2000  (masked in loss)
```

Warmup shrinks from v1's 5,000 bars because at 15-min a 5k warmup would burn ~190 trading days; 2,000 covers roughly a calendar quarter and still gives stable moments. Stats are computed once on the aligned dataset and saved to `artifacts/{run_id}/normalizers.pt`; inference uses the same fitted state as of the last training bar.

---

## 7. Tokenizer

Two frozen artifacts, both fit on the training split.

### 7.1 Return bucketizer

Fit on `target__SPY__log_return / realized_vol_30` over training bars only. **32 buckets, indexed 0 through 31.** Buckets 1–30 are percentile-uniform bins between the 0.5th and 99.5th percentiles of training vol-normalized returns. Bucket 0 catches everything below the 0.5th percentile (deep-tail down). Bucket 31 catches everything above the 99.5th (deep-tail up). Vol-normalized tails have finite mass but irregular shape; forcing them into equal-mass bins wastes vocabulary on outliers.

```python
class ReturnBucketizer:
    boundaries: np.ndarray   # shape [31], monotone
    centers:    np.ndarray   # shape [32], representative return per bucket

    def encode(self, vol_norm_return: np.ndarray) -> np.ndarray:
        return np.digitize(vol_norm_return, self.boundaries)  # returns 0..31

    def decode(self, bucket_id: np.ndarray) -> np.ndarray:
        return self.centers[bucket_id]

    def save(self, path: Path): ...
    @classmethod
    def load(cls, path: Path) -> "ReturnBucketizer": ...
```

`centers[k]` is the training-set mean vol-normalized return in bucket `k` — an unbiased dequantizer the trading layer uses to compute expected return from a bucket distribution.

### 7.2 Market-state embedder

At each `t`, each channel produces a raw feature vector of channel-specific dimension `F_c`. A per-channel `nn.Linear(F_c, d_model)` projects to a common dimension. The projections are **summed**, not concatenated, with an added learned channel-type embedding:

```python
class MarketStateEmbedder(nn.Module):
    def __init__(self, channel_dims: dict[str, int], d_model: int = 512, n_channels: int = 5):
        super().__init__()
        self.projections = nn.ModuleDict({
            name: nn.Linear(dim, d_model) for name, dim in channel_dims.items()
        })
        self.channel_type_emb = nn.Embedding(n_channels, d_model)

    def forward(self, feats: dict[str, Tensor], channel_ids: dict[str, int]) -> Tensor:
        out = 0
        for name, x in feats.items():
            proj = self.projections[name](x)                       # [B, T, d_model]
            proj = proj + self.channel_type_emb(
                torch.tensor(channel_ids[name], device=x.device))  # broadcast add
            out = out + proj
        return out                                                 # [B, T, d_model]
```

Concatenation is cleaner on paper but scales `d_model` with the channel count, which blows up the parameter budget when the next version adds channels. Summing holds `d_model` fixed as the channel set grows, and the per-channel `nn.Linear` heads let each channel choose its own subspace of the hidden state. The channel-type embedding plays the role of BERT's segment embedding — the model can tell which channel contributed which content and route attention. This mirrors Moirai's any-variate handling and Lag-Llama's auxiliary-feature embedding.

**Assumption made explicit.** Summation asks gradient descent to discover non-overlapping subspaces for each channel. The channel-type embedding gives the model a route to disentangle them; whether it takes that route is an empirical question, not a guarantee. The diagnostic in §10 verifies it.

The embedder output at `t` is the single `d_model`-vector the transformer treats as position `t`.

---

## 8. Model

A nanoGPT-style causal decoder with **RoPE positional embeddings** — not learned absolute. The novelty is upstream (tokens) and downstream (decisions); the transformer is deliberately boring.

| Field | Value | Rationale |
|---|---|---|
| `d_model` | 512 | Fits an A10 (24 GB) with context 512, batch 64, bf16 |
| `n_layers` | 8 | ~30M params; depth over width for sequence tasks |
| `n_heads` | 8 | `d_head = 64`, a stable head size |
| `d_ff` | 2048 | 4× MLP expansion |
| `context_len` | 512 | ~2.5 trading weeks of 15-min bars |
| `vocab_size` | 32 | Return-bucket count, indexed 0–31 |
| `dropout` | 0.1 | On attention, MLP, and embedding |
| `positional` | RoPE | No learned position table to retune when context grows |
| `norm` | Pre-LayerNorm | Stable without warmup gymnastics |
| `activation` | GELU | Standard in decoder LMs |
| `attention` | Causal SDPA | `F.scaled_dot_product_attention` yields FlashAttention-2 for free |

RoPE is a bet on future context growth; when LOB tokens push sequences past 2k, RoPE extrapolates without a new embedding table. Any reference elsewhere in the repo to a learned absolute position table is stale and should be treated as a bug.

Loss is cross-entropy over the 32-bucket next-token target. A magnitude-weighted variant is a **required v1 baseline** (§10), not future work:

```
loss_t = w_t * CE(logits_t, target_t)
w_t    = 1 + alpha * |center[target_t]|   # alpha in config, default 1.0
```

`alpha = 0` recovers unweighted CE; `alpha = 1.0` is the trader-aligned default. `alpha` lives in the training config, not in code.

Parameter count: transformer stack is `8 * (4 * d_model^2 + 2 * d_model * d_ff) ≈ 25M`, output head `d_model * vocab = 16k`, embedder projections negligible. Total ~30M, fits any modern GPU at batch 64 bf16.

```python
class PriceSpaceLLM(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        self.embed = MarketStateEmbedder(cfg.channel_dims, cfg.d_model, cfg.n_channels)
        self.blocks = nn.ModuleList([TransformerBlock(cfg) for _ in range(cfg.n_layers)])
        self.norm_f = nn.LayerNorm(cfg.d_model)
        self.head   = nn.Linear(cfg.d_model, cfg.vocab_size, bias=False)

    def forward(self, feats: dict[str, Tensor], channel_ids: dict[str, int]) -> Tensor:
        x = self.embed(feats, channel_ids)          # [B, T, d_model]
        for blk in self.blocks:
            x = blk(x)                              # causal SDPA + RoPE inside
        x = self.norm_f(x)
        return self.head(x)                         # [B, T, vocab_size]

class TransformerBlock(nn.Module):
    def forward(self, x):
        x = x + self.attn(self.ln1(x))              # RoPE applied to q,k in self.attn
        x = x + self.mlp(self.ln2(x))
        return x
```

Training computes loss on all `T` positions (shifted targets). Inference reads logits at the last position.

---

## 9. Training

`PriceSpaceDataset` mmaps `data/tokenized/{run_id}.pt` once and yields fixed-length windows:

```python
class PriceSpaceDataset(Dataset):
    def __init__(self, tokenized_path: Path, context_len: int, horizon: int,
                 date_range: tuple[str, str], embargo: int):
        self.data = torch.load(tokenized_path, mmap=True)
        self.mask = build_split_mask(self.data["timestamps"], date_range, embargo)
        self.starts = np.where(self.mask)[0]
        self.context_len = context_len
        self.horizon = horizon

    def __getitem__(self, i):
        s = self.starts[i]
        feats  = {c: self.data["features"][s:s+self.context_len, ci, :]
                  for c, ci in self.channel_ids.items()}
        target = self.data["targets"][s + self.context_len + self.horizon - 1]
        return feats, target
```

`build_split_mask` enforces the date range (train, val, test) and forbids any window from spanning a split boundary within `horizon` bars.

Splits are date-boundaried in config. For SPY 2015–2025:

| Split | Range | Approx bars | Purpose |
|---|---|---|---|
| train | 2015-01-01 → 2022-12-31 | ~52,000 | ~8 years, all iteration |
| val | 2023-01-01 → 2023-12-31 | ~6,500 | model selection, calibration |
| test | 2024-01-01 → 2025-06-30 | ~9,700 | opened three times total |

Embargo defaults to `horizon` bars — 1 for next-bar prediction, up to 12 for longer configured horizons.

Optimizer is AdamW with `lr=3e-4`, `betas=(0.9, 0.95)`, `weight_decay=0.1` on 2D params only (biases and LayerNorm excluded). Cosine LR decays to 10% of peak after a 2,000-step linear warmup. Global L2 gradient clip at 1.0. Mixed precision `bfloat16` via `torch.amp.autocast`; bf16 needs no loss scaler. Batch is 64 sequences × 512 tokens; drop it if you're memory-bound.

Every 2,000 steps, checkpoint `{model, optimizer, scheduler, rng_states, config, git_sha, data_hash, step, val_metrics}` into `artifacts/{run_id}/step_{step}.pt`. Keep top-K by **validation ECE**, not accuracy — calibration is what the trading layer consumes. A `latest.pt` symlink covers interruption recovery.

Determinism: `torch`, `numpy`, `random` seeded from `training.seed`; `torch.use_deterministic_algorithms(True, warn_only=True)`; `CUBLAS_WORKSPACE_CONFIG=:4096:8`. Deterministic kernels cost ~15% throughput on scatter-add and a few backward paths, which is fine. Single-worker DataLoader with `worker_init_fn` seeding is the default; multi-worker is only enabled when I/O binds, and the resulting batch-order nondeterminism is logged on the run.

W&B logs training loss, LR, grad norm, and throughput every step. Every eval interval logs val CE, top-1, top-3, ECE, entropy, directional accuracy, a reliability diagram, and predicted distributions on fixed diagnostic timestamps (2023-03-13 FOMC, 2023-08-10 CPI). Every run's metadata carries the full config, git SHA, and dataset SHA256.

---

## 10. Evaluation

The test period opens exactly three times over the life of v1 — a budget enforced structurally (§13). Everything below runs on **val**.

Prediction metrics: cross-entropy (bits/token for interpretability), top-1 and top-3 bucket accuracy, and per-bar distribution entropy (diagnostic; sharper is not always better).

Calibration: expected calibration error with 15 confidence bins on the argmax probability, plus a reliability diagram uploaded to W&B each eval. Directional calibration is the one the trading layer actually eats — bin predicted `P(up)` into deciles and report realized up-frequency per decile.

Signal quality: directional accuracy is the sign of `sum(p * bucket_centers)` vs. realized sign. Rank IC is Spearman correlation between predicted expected return and realized return over the eval window.

**Bucket-boundary drift diagnostic.** On the validation split, report the realized bucket-frequency histogram against the training-set frequencies. If validation buckets 0 or 31 hold materially more or less mass than the trained 0.5% each, that is direct evidence of tail-shape drift and belongs in the run summary. Same check on the test set at final evaluation. Vol-normalization mitigates scale drift; it does not mitigate shape drift, and this diagnostic makes shape drift visible.

**Channel-orthogonality diagnostic.** After training, compute the mean channel-contribution vector for each channel on 1,000 held-out bars — each channel's per-channel projection output, averaged across the sample — and report the pairwise cosine similarity matrix. If similarities cluster near zero, summation discovered per-channel subspaces. If they cluster near ±1, the model routed multiple channels through the same subspace and the multi-modal architecture undermined itself regardless of the ablation result. This is one plot; it belongs on every run.

**Regime-conditional evaluation.** Tag each held-out bar with a coarse regime label using VIX terciles computed on the training window (VIX split at the 33rd and 67th percentiles of training-window VIX values). Report every metric — CE, top-1 accuracy, ECE, directional accuracy, Sharpe, hit rate, capacity — per regime. This is required disclosure, not a gate. Aggregate Sharpe of 0.5 that splits 2.0 / 0.2 / -0.5 across regimes is a lie of averages, and the honest answer is which regime the strategy works in.

**Baselines.** Four baselines run on identical data, splits, seeds, and tokens.

- **Linear head** applies `nn.Linear(context_len * d_model, vocab_size)` to flattened market-state vectors — if the transformer doesn't clear this, depth is wasted.
- **Small MLP** puts three GELU hidden layers (128 → 64 → 32) on the last-position market-state vector, testing whether attention buys anything past a shallow nonlinear map.
- **Target-only** runs the same transformer with market, macro, options, and event channels zeroed at the embedder, testing whether the multi-modal token does work.
- **Magnitude-weighted CE** runs the full model with `alpha = 1.0` on the loss weight. This tests whether prediction quality on the moves that pay — the tails — is being sacrificed to prediction quality on the fat middle.

Each baseline is a separate run under the same config skeleton with only model, channel-list, or loss overridden.

---

## 11. Simulator

A bar-by-bar walker over the test range. No vectorization tricks that risk peeking. Signature:

```python
def simulate(model, tokenized_test: dict, buckets: ReturnBucketizer,
             cost_cfg: CostConfig, policy_cfg: PolicyConfig) -> SimResult: ...
```

At each bar `t` the walker assembles the market-state token from features at times `≤ t`, runs a forward on the trailing `context_len` window, softmaxes the last-position logits to `p[t] ∈ ℝ^32`, then derives `expected_vn_return = sum(p * bucket_centers)`, `expected_return = expected_vn_return * realized_vol_30_t`, `p_up = p[center > 0].sum()`, and `sharpness = 1 - entropy(p) / log(32)`.

### 11.1 Cost model — spread calibration

Cost at intended size is `spread_cost = 0.5 * calibrated_spread_t`. The Corwin-Schultz proxy is retained as the *initial estimate*; it must be calibrated against measured SPY BBO data before the held-out test opens.

Procedure, run by `scripts/calibrate_spread.py`:

1. Pull SPY BBO snapshots at 15-minute intervals for a 30-day window inside the training range (default: last 30 trading days of 2022).
2. Compute the true half-spread per bar as `(ask - bid) / 2 / mid`.
3. Regress the Corwin-Schultz estimate against the truth: `true_half_spread ~ beta * cs_estimate + intercept`.
4. Either replace the estimate with the regression line, or scale the raw Corwin-Schultz value by `beta` if the intercept is within one standard error of zero.
5. Save the fit — coefficient, intercept, standard errors, R² — as `artifacts/cost_calibration/spread_scaler.json`.

The simulator loads `spread_scaler.json` at startup and applies the scaling per bar. A missing calibration file is a hard failure, not a fallback to raw Corwin-Schultz. The shift to 15-min bars makes this correction less severe than at 5-min — bar range no longer swamps the true spread by an order of magnitude — but calibration is still required.

### 11.2 Cost model — slippage coefficient (kappa)

Slippage is `kappa * size`, linear in position size. Kappa is a **measurement**, not a starting value.

- **Observed variable.** 5-bar-forward return on the target instrument, i.e. return from `t+1 open` to `t+6 open` (~75 minutes at 15-min bars). This is short enough that microstructure effects dominate, long enough to average over one 15-min bar of noise.
- **Size proxy.** Hypothetical position size divided by concurrent 15-min bar volume, expressed as a fraction (e.g. 0.05 = 5% of that bar's traded volume).
- **Estimation.** OLS regression `abs(observed_return) ~ kappa * size_proxy` on the training window; kappa is the coefficient. Fit with heteroskedasticity-robust standard errors.
- **Report.** Point estimate, standard error, 95% confidence interval, R², N.
- **Save.** `artifacts/cost_calibration/kappa.json`, loaded by the simulator at startup.
- **Sensitivity.** The held-out Sharpe report must include a plot of Sharpe as a function of kappa at 0.5×, 0.75×, 1.0×, 1.25×, 1.5×, and 2.0× the point estimate. If Sharpe crosses zero anywhere in `[0.5×, 2×]`, the reported number is not a robust claim.

**SPY-at-$1M scale.** At $1M single-position size on SPY (roughly 2,500 shares at $400/share), impact is expected to be immaterial except in the fastest bars around market open, market close, and event releases. Linear-in-size slippage is the right functional form at that scale — the nonlinear regime starts several orders of magnitude higher. This is the operating assumption; the sensitivity plot is what defends it.

### 11.3 Risk penalty

`risk_penalty = lambda * variance(p)` where variance is taken over `bucket_centers` weighted by `p`. The `lambda` hyperparameter is declared in the simulation config's Pydantic schema:

```python
class SimulationConfig(BaseModel):
    lambda_risk: float = 1.0         # risk_penalty scale
    threshold: float = 0.0002        # edge threshold in vol-normalized units
    hysteresis: float = 0.5          # times threshold, for direction flip
    max_size: float = 1.0            # in units of "$1M SPY"
    ...
```

Every run logs the resolved `lambda_risk` value into the logbook. A run without an explicit `lambda_risk` in its resolved config fails registration.

### 11.4 Decision rule

`edge = expected_return - (spread_cost + slippage) - risk_penalty`. Long if `edge > threshold`, short if `edge < -threshold`, else flat. `size = clip(edge / uncertainty_scale, -max_size, +max_size)` with `uncertainty_scale ∝ sqrt(variance(p))`.

**Overlapping signals.** The simulator holds a single position at a time. If an entry signal fires while a position is still open in the same direction, the signal is dropped (no size increase). If the signal fires in the opposite direction and its `|edge|` exceeds `threshold + hysteresis * threshold`, the current position is closed at the next bar's open and the new position is opened at the same fill. Otherwise the signal is dropped. Hysteresis lives in config (`policy_cfg.hysteresis`, default 0.5) and defends against churn on ambiguous bars.

Entries and exits print at the **next bar's open** so the decision variable never touches the fill.

### 11.5 Metrics with confidence

Reported metrics: cumulative return, mean and std of daily returns, annualized Sharpe, hit rate (positive P&L after cost), max drawdown, time-to-recovery, per-trade P&L histogram with tail metrics, and a capacity sweep — the largest `max_size` at which Sharpe stays above 1.0.

Sharpe is reported with its standard error, not as a point estimate. Trade-level SE is `sqrt((1 + 0.5 * S^2) / N_trades)`, annualized by `sqrt(252 * 26 / bars_per_trade)`. Every Sharpe number appears as `Sharpe ± SE`. Additionally, the holdout is split into 18 non-overlapping 1-month blocks; a block bootstrap resamples those 18 blocks 10,000 times and reports the mean, the 5th and 95th percentiles, and the fraction of blocks with positive Sharpe. A Sharpe of 0.6 ± 0.2 with 15/18 positive-Sharpe blocks is a real claim; 0.6 ± 0.4 with 9/18 positive is a coincidence.

The capacity number is the honest bound on the economic edge.

---

## 12. Configs

Hydra 1.3+ composes YAML config groups. It beats plain YAML + Pydantic because config groups let you swap one axis at a time (`model=small`, `training=fast`, `data=spy_15m`) without an exponential set of full configs.

```yaml
# configs/experiments/mvp_spy_15m.yaml
defaults:
  - data: spy_15m
  - features: standard
  - tokenizer: buckets_32
  - model: transformer_30m
  - training: single_a10
  - simulation: default_costs
  - _self_

run_id: ${now:%Y%m%d_%H%M%S}_${hydra.job.name}
seed: 1337
notes: "MVP baseline. Full-channel."
```

Each run writes its resolved config to `artifacts/{run_id}/config.yaml`. Reproducing a run: `python scripts/train.py --config-path artifacts/{run_id} --config-name config`.

Pydantic v2 wraps the Hydra dict at load time so type errors fail fast:

```python
class TrainingConfig(BaseModel):
    optimizer: Literal["adamw"] = "adamw"
    lr: float = 3e-4
    weight_decay: float = 0.1
    batch_size: int = 64
    max_steps: int = 200_000
    warmup_steps: int = 2000
    grad_clip: float = 1.0
    seed: int = 1337
    deterministic: bool = True
    alpha_mag_weight: float = 1.0    # magnitude-weighted CE, 0 disables

class SimulationConfig(BaseModel):
    lambda_risk: float = 1.0
    threshold: float = 0.0002
    hysteresis: float = 0.5
    max_size: float = 1.0
```

If a value is not in a config, it is not a hyperparameter. `lambda_risk` and `alpha_mag_weight` are both required log entries per run.

---

## 13. Experiment tracking

W&B project `price-space-llm`. Each run logs the resolved config as metadata, `git rev-parse HEAD`, the dirty flag from `git status --porcelain`, the SHA256 of the tokenized dataset, per-step scalars (loss, LR, grad norm, throughput), per-eval metrics from §10, and predicted-distribution bar charts on fixed diagnostic bars.

`experiments/logbook.csv` is append-only, one row per run:

```
date,run_id,branch,git_sha,notes,train_loss,val_loss,val_ece,val_dir_acc,held_out_sharpe,held_out_sharpe_se,lambda_risk,alpha_mag_weight,touched_test
2026-06-14,20260614_140312_mvp_spy_15m,main,a1b2c3d,baseline full-channel,2.61,2.83,0.031,0.532,,,1.0,1.0,no
```

`scripts/register_run.py` writes the row from W&B run metadata at the end of training.

**Structural enforcement of the 3-look budget.** `scripts/check_test_look.sh` is a pre-commit hook. It fails any commit whose changed config files contain dates on or after `2024-01-01` unless the commit message includes the literal token `[test-look]`. Every `[test-look]` commit is appended to `experiments/test_looks.log` — an append-only file with the commit SHA, timestamp, author, and message. The budget is three lines in that file for the whole MVP. This replaces the v1 honor-system boolean. The hook is not paranoia; it is what the "three looks" number is worth if it is not enforced.

---

## 14. Infrastructure

Compute is a single GPU rented on Lambda Labs: NVIDIA A10 (24 GB) at ~$0.75/hr for iteration and small runs, A100 40 GB at ~$1.30/hr for full training where wall-clock matters. The budget envelope is ~$500 of compute, which covers ~300 A10-hours or ~150 A100-hours across iteration, baselines, and simulation. At 15-min bars the training set is ~30% the size of the 5-min version, so wall-clock per epoch drops proportionally.

Storage sits on local NVMe, ~30 GB total: ~4 GB raw Parquet for 10 years across all channels at 15-min, ~1 GB per aligned dataset, ~1 GB per tokenized tensor, and ~1 GB per artifact bundle × ~30 runs = ~30 GB.

The instance runs Ubuntu 22.04 with Python 3.11 and PyTorch 2.4+ on CUDA 12.x, giving `torch.compile` and current SDPA kernels. `uv sync` manages dependencies from `pyproject.toml`.

Raw Parquet is mirrored to an S3 or GCS bucket at ~$0.02/GB/mo as a resumability backup. Nothing in the runtime code path depends on the mirror existing.

---

## 15. Interfaces

Every module boundary is narrow, typed, and stable. This is where the pipeline earns its refactorability.

| Boundary | Interface | Contract |
|---|---|---|
| Vendor MCP → Ingestion | `IngestionClient.call(tool, **params) -> pd.DataFrame` | UTC timestamps, vendor-native columns, cache-first |
| Ingestion → Alignment | `fetch(symbol, start, end, freq) -> pd.DataFrame` | UTC `timestamp` index; downsampled to 15-min inside fetcher |
| Alignment → Features | wide `pd.DataFrame` on 15-min UTC grid with `missing_mask_*` columns | Row for every RTH bar; target never missing |
| Features → Tokenizer | same DataFrame shape, causally normalized | All columns finite; normalizer state written to `artifacts/` |
| Tokenizer → Training | `Dataset` yielding `(feats: dict[str, Tensor[T, F_c]], target: LongTensor[])` | Fixed context length; embargo enforced in sampler |
| Training → Artifacts | `artifacts/{run_id}/` with `checkpoint.pt`, `config.yaml`, `normalizers.pt`, `buckets.pt` | Self-contained; loadable without training repo state |
| Calibration → Simulator | `artifacts/cost_calibration/{spread_scaler,kappa}.json` | Required at simulator startup; missing = hard fail |
| Model → Simulator | `predict(state_sequence) -> Tensor[vocab_size]` | Pure function; no side effects; CPU or GPU |
| Simulator → Evaluation | `SimResult` dataclass: trade ledger, equity curve, per-bar decisions, per-regime metrics | JSON-serializable for the logbook |

Every function that crosses a boundary has type hints and a docstring stating the contract. `Protocol` types live in `src/utils/interfaces.py`; downstream modules import them without pulling in upstream implementations.

---

## 16. Tests

Unit tests target the modules where a subtle bug destroys the entire result.

For the tokenizer: `decode(encode(x))` maps `x` to the center of its bucket; boundaries are monotone; the output range is `[0, 32)`, exclusive of 32. On a standard Gaussian sample, buckets 0 and 31 each hold ~0.5% mass.

For causal normalization the leakage test is the point of the whole suite: build a DataFrame with random values, compute the causally normalized column, shuffle rows with index `> t*`, and assert values at index `≤ t*` are byte-identical. A second test asserts rows before the 2,000-bar warmup are masked to zero.

Alignment tests inject known gaps into a synthetic multi-channel input and assert `missing_mask_*` columns match ground truth. Every timestamp in the aligned table must be UTC and monotone increasing at 15-minute spacing.

**One-source-of-truth channel test.** `test_channel_source_of_truth.py` reads a random 1,000-bar window from the aligned Parquet, recomputes each per-channel raw value from `data/raw/` sources, and asserts byte-identical match. It runs on every commit that touches feature or ingestion code — the pre-commit hook triggers it on staged paths matching `src/features/*` or `src/ingestion/*`. This closes the gap in invariant #5.

For the model, forward-pass shapes: with `d_model=64`, `context=16`, `batch=4`, output logits are `[4, 16, 32]`. The causal-mask test is the single most important test in the suite: perturb the value at position `t+k` for any `k > 0` and assert the output at position `t` is bitwise unchanged. Deterministic forward: same seed and input, same output across two calls.

Simulator tests confirm a zero-alpha strategy books exactly zero P&L before costs and exactly `-2 * spread_cost` per round-trip after. The no-lookahead test shuffles bars after the decision index and asserts the equity curve up to that index is unchanged. The overlapping-signal test constructs a synthetic same-direction re-entry and asserts position size does not increase; a follow-up test constructs an opposite-direction signal above `threshold + hysteresis * threshold` and asserts the flip fires cleanly.

Integration lives at `tests/integration/test_end_to_end.py`. It runs the full pipeline on a synthetic 3-month SPY slice under `configs/experiments/smoke.yaml` and asserts val loss decreases from initial. Runs in under 5 minutes on CPU.

`pytest -q` is the command. No CI in v1; the developer runs the suite before every training run and the pre-commit hook enforces the source-of-truth and test-look checks per commit.

---

## 17. Stack

| Layer | Choice | Reason |
|---|---|---|
| Language | Python 3.11 | Pattern matching, faster startup |
| Deep learning | PyTorch 2.4+ | `torch.compile`, SDPA/FlashAttention |
| DataFrames | Polars 1.x | 5–20× pandas on large Parquet joins; lazy scans free during alignment |
| Parquet I/O | pyarrow | Native to Polars; column-pruning reads |
| Config | Hydra + Pydantic v2 | Composable YAML plus typed validation |
| Tracking | Weights & Biases | Free tier suffices; hosted UI removes friction |
| Testing | pytest | Parametrize-heavy suite for tokenizer and normalizer tests |
| Dependency mgmt | uv | Fast resolves, lockfile-first |
| Compute | Lambda Labs A10/A100 | Cheapest hourly for the GPU class |
| Storage | Local NVMe + S3/GCS mirror | Fast local, cheap cold backup |
| Plotting | matplotlib + W&B charts | matplotlib for saved figures, W&B for live |
| Numerics | numpy 2.x | Pre-tensor arithmetic |
| Stats | statsmodels | Robust SE on kappa; block bootstrap on Sharpe |

Polars over pandas is not stylistic. On the aligned 15-min dataset (~0.6 GB, ~65k rows × ~80 columns), a `join_asof` across five channels runs in ~1 second in Polars; the same operation in pandas takes tens of seconds. Lazy scans mean the alignment stage streams from Parquet without materializing intermediates. pandas comes back in as a shim wherever a fetcher returns a `pd.DataFrame`; the aligned stage converts once at the entry point.

Workflow: `uv sync` → edit → `pytest tests/` → `python scripts/calibrate_spread.py` → `python scripts/calibrate_kappa.py` → `python scripts/train.py experiments=mvp_spy_15m` → `python scripts/evaluate.py run_id=<...>` → `python scripts/simulate.py run_id=<...>` → `python scripts/register_run.py run_id=<...>`.

---

## 18. What v3 changes

Each of these is a bounded change, not a rewrite.

**LOB tokens** add a millisecond-resolution ingestion path (Polygon or LOBSTER) and a separate LOB tokenizer that emits its own stream. The transformer input becomes a fusion of the 15-min market-state token and an LOB-token embedding. Context length likely grows past 2,000; RoPE was chosen for exactly this.

**Multi-instrument** makes the channel schema hierarchical: `target[instrument].{feature}`, with an instrument-id embedding added to the market-state token the same way the channel-type embedding is. The dataset yields `(instrument_id, feats, target)` triples; the loss is masked to the instrument's active bars. Universe growth becomes a config change. This is the next version, not a strategic goal.

**RL trading policy** adds a policy net downstream of the distribution head, trained with a differentiable proxy for after-cost P&L or PPO against the simulator. The transformer weights either freeze or fine-tune under stop-gradient. The `SimResult` ledger is already differentiable-friendly.

**Real-time deployment** targets an end-to-end latency budget under 100 ms per 15-min-bar signal. Model is exported to ONNX or TorchScript. A warm inference process holds normalizer state, bucket boundaries, cost calibrations, and weights in memory. Ingestion gains a streaming adapter that emits closed-bar features into a persistent state buffer. Training is unchanged; only serving is new.

Each of these respects the existing module boundaries. That is the payoff of §2.
