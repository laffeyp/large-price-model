# Price-Space LLM — Technical Architecture

**Version:** v1
**Target:** SPY, 5-minute bars, ~10 years of history
**Stack:** Python 3.11, PyTorch 2.4+, single GPU (A10 or A100)

---

## 0. What this system is

A causal decoder transformer that reads market history as a token sequence and predicts what the market does next. Same architectural family as GPT; different vocabulary and different target.

Each input token is a compressed *market state* at one 5-minute bar: SPY's recent price and volume behavior, what QQQ/IWM/VIX/TLT/DXY/GLD/USO did, the latest macro readings (CPI, Fed funds, 10Y yield, unemployment, NFP), the put/call ratio, and calendar/event flags. Every channel goes through its own `nn.Linear` projection to a 512-dim embedding, gets summed with a learned channel-type embedding, and produces one 512-dim vector per bar. That vector is the token at that timestep.

Each output token is a discrete label — one of 32 buckets covering the *volatility-normalized* next-bar return. Bucket boundaries are percentile-uniform on the training set. Vol-normalization makes the vocabulary scale-invariant: a one-sigma move in a calm market and a one-sigma move in a volatile one land in the same bucket. The model's output is a probability distribution over those 32 buckets.

Downstream, a bar-by-bar simulator turns each distribution into a trade decision using an explicit cost model: `edge = E[return] − half_spread − k·size − risk_penalty(distribution)`. If `edge > threshold`, take a position sized by `edge / std(distribution)`.

That's the whole system. Everything below is how it's built.

---

## 1. The pipeline

Data flows one way: vendor sources → aligned Parquet → per-timestep token → 32-way softmax → cost-aware simulator → chronological holdout. Every stage is causal, config-driven, versioned, and independently testable.

```
                                                          Price-Space LLM v1
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
              │  alignment / join      │  UTC 5-min grid, forward-fill policies,
              │  → aligned dataset     │  missing_mask columns
              └───────────┬────────────┘         data/aligned/{run_id}.parquet
                          ▼
              ┌────────────────────────┐
              │  feature pipeline      │  per-channel causal features
              │  (all causal)          │  + causal z-score normalization
              └───────────┬────────────┘
                          ▼
              ┌────────────────────────┐
              │  tokenizer             │  return bucketizer (32 buckets)
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
              │                        │  baselines (linear / MLP / target-only)
              └───────────┬────────────┘
                          ▼
              ┌────────────────────────┐
              │  simulator             │  bar walker, cost-aware policy,
              │                        │  Sharpe / DD / capacity
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

**No magic numbers in code.** Window sizes, bucket counts, learning rates, date ranges, channel lists — all live in YAML. Code reads config; code never hard-codes hyperparameters.

**Reproducible training.** Every run seeds `torch`, `numpy`, `random`, and CUDA, enables deterministic algorithms, and logs the config, git SHA, and data hash. Rerunning the same config must reproduce metrics to within numerical noise.

**One source of truth per channel.** Each channel has exactly one ingestion module. Downstream code reads the canonical Parquet — it never re-fetches or recomputes raw values. This kills the class of bug where two callers get different values for "SPY 2023-01-03 14:35 close."

**Artifacts and configs ship together.** Every checkpoint sits next to its config, tokenizer boundaries, normalizer stats, and git SHA. A `.pt` file alone is not the deliverable.

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
    simulation/           # cost model, decision thresholds
    experiments/          # top-level configs composing the above
  data/
    raw/                  # vendor-native Parquet dumps, immutable
    aligned/              # joined multi-channel Parquet keyed by run_id
    tokenized/            # torch tensors ready for training
  artifacts/              # {run_id}/checkpoint.pt, config.yaml, normalizers.pt, buckets.pt
  src/
    ingestion/            # IngestionClient + per-channel fetchers
    features/             # causal feature computation + normalization
    tokenizer/            # return bucketizer + market-state embedder
    model/                # transformer blocks, model class, baselines
    training/             # dataloader, loop, checkpointing, logging
    simulation/           # bar walker, cost model, policy
    evaluation/           # metrics, calibration, plots
    utils/                # timezones, logging, hashing, config loading
  experiments/            # logbook.csv, saved run summaries
  notebooks/              # exploration only; nothing production runs from here
  tests/                  # pytest suite mirroring src/ structure
  scripts/                # fetch_data.py, align.py, train.py,
                          # evaluate.py, simulate.py, register_run.py
  pyproject.toml          # uv-managed
```

`configs/` is the only place hyperparameters live. `data/raw/` is write-once; corrupting it invalidates every downstream cache. `data/aligned/` and `data/tokenized/` are derived and regenerable. `artifacts/{run_id}/` is the reproducibility bundle. Nothing in `src/` is called directly by a human — humans run `scripts/`.

---

## 4. Ingestion

The primary source is the Alpha-Vantage-style financial-data MCP surfaced in this environment. Its tools cover intraday equities (`TIME_SERIES_INTRADAY`), daily adjusted OHLCV (`TIME_SERIES_DAILY_ADJUSTED`), macro series (`CPI`, `FEDERAL_FUNDS_RATE`, `TREASURY_YIELD`, `UNEMPLOYMENT`), options flow (`HISTORICAL_OPTIONS`, `HISTORICAL_PUT_CALL_RATIO`), event calendars (`EARNINGS_CALENDAR`), and news sentiment. One MCP delivers macro, options, and cross-asset series at the frequencies v1 needs.

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
              freq: Literal["1m","5m","1h","1d"]) -> pd.DataFrame: ...
```

Concrete fetchers for v1:

| Channel | Symbols / series | MCP tool | Native freq |
|---|---|---|---|
| target | SPY | `TIME_SERIES_INTRADAY` | 5m |
| market_context | QQQ, IWM, VIX, TLT, DXY, GLD, USO | `TIME_SERIES_INTRADAY` | 5m |
| macro | CPI, FEDFUNDS, DGS10, UNRATE | `CPI`, `FEDERAL_FUNDS_RATE`, `TREASURY_YIELD`, `UNEMPLOYMENT` | daily/monthly |
| options | put/call ratio, options volume | `HISTORICAL_PUT_CALL_RATIO`, `HISTORICAL_VOLUME_OPEN_INTEREST_RATIO` | daily |
| event | earnings, FOMC, CPI releases | `EARNINGS_CALENDAR` + curated static tables | date-only |

Fetchers return a DataFrame with a UTC `timestamp` index and channel-specific columns. The fetcher is the only code that touches vendor formats. Everything else — timezones, alignment, forward-fill — happens downstream.

Cache is content-addressed by request parameters, so parameter changes force refetch. Cached responses land at `data/raw/{source}/{channel}/{symbol}/{yyyy-mm}.parquet`.

---

## 5. Storage

**Raw.** `data/raw/{source}/{channel}/{symbol}/{yyyy-mm}.parquet`. Monthly partitioning keeps single-file scans under a second and lets ingestion refresh a single month without rewriting a decade.

**Aligned.** `data/aligned/{run_id}.parquet`. One wide table on a canonical 5-minute UTC grid over the configured date range. Rows exist only for RTH bars; pre- and post-market are dropped to keep the target's session-boundary semantics clean.

Columns follow `{channel}__{symbol}__{feature}`:

| Column | Type | Notes |
|---|---|---|
| `timestamp` | `datetime[ns, UTC]` | primary key, 5-min grid |
| `target__SPY__{open,high,low,close,volume}` | float64/int64 | OHLCV |
| `market__QQQ__close`, `market__VIX__close`, ... | float64 | close at the bar |
| `macro__CPI__value`, `macro__DGS10__value`, ... | float64 | last-known daily value carried intraday |
| `options__PCR__value`, `options__VOLOI__value` | float64 | last-known daily value |
| `event__{earnings,fomc,cpi_release}_flag` | int8 | 1 on release date |
| `event__mins_to_{fomc,cpi,earnings}` | float32 | signed countdown |
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

For the target (SPY) the suite is `log_return = log(close_t / close_{t-1})`, `realized_vol_30 = std(log_return[t-30:t])`, `bar_shape = (close - open) / (high - low + eps)`, `range_pct = (high - low) / close_{t-1}`, `volume_z_100 = (volume - roll_mean_100(volume)) / roll_std_100(volume)`, `dollar_volume = close * volume`, and a Corwin-Schultz-style `spread_proxy = 2 * |high - low| / (high + low)`. The 30-bar realized-vol window beats EWMA for v1 because its semantics are unambiguous and it lines up with DeepLOB-style baselines; EWMA is a config alternate at `vol.method: "ewma", vol.halflife: 20`. `spread_proxy` is a stand-in until quote data is wired in.

Market-context symbols (QQQ, IWM, VIX, TLT, DXY, GLD, USO) get `log_return`, `realized_vol_30`, `volume_z_100`, `bar_shape`. VIX additionally emits `vix_level` and `vix_change`.

Macro series (CPI, FEDFUNDS, DGS10, UNRATE) carry the last known value intraday and add `delta_since_last_release` and `days_since_release`. Both are causal because the release timestamp is the moment of publication.

Options channels (put/call ratio, options volume) carry the last daily value plus a 20-day z-score of each.

Event channels emit a binary flag for "bar falls on release day" plus a signed `mins_to_next_release` clipped to ±10 sessions to keep magnitudes usable.

Continuous features are normalized by expanding-window mean and standard deviation with a 5,000-bar (~60 trading days) warmup:

```
z_t = (x_t - mean(x_{0:t-1})) / (std(x_{0:t-1}) + eps),  t >= 5000
z_t = 0                                                    t <  5000  (masked in loss)
```

Expanding beats rolling because it discards nothing and the moments stabilize fast after warmup. Stats are computed once on the aligned dataset and saved to `artifacts/{run_id}/normalizers.pt`; inference uses the same fitted state as of the last training bar.

---

## 7. Tokenizer

Two frozen artifacts, both fit on the training split.

### 7.1 Return bucketizer

Fit on `target__SPY__log_return / realized_vol_30` over training bars only. 32 buckets. Buckets 1–30 are percentile-uniform bins between the 0.5th and 99.5th percentiles of training vol-normalized returns. Bucket 0 catches everything below the 0.5th percentile (deep-tail down). Bucket 31 catches everything above the 99.5th (deep-tail up). Vol-normalized tails have finite mass but irregular shape; forcing them into equal-mass bins wastes vocabulary on outliers.

```python
class ReturnBucketizer:
    boundaries: np.ndarray   # shape [31], monotone
    centers:    np.ndarray   # shape [32], representative return per bucket

    def encode(self, vol_norm_return: np.ndarray) -> np.ndarray:
        return np.digitize(vol_norm_return, self.boundaries)

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

The embedder output at `t` is the single `d_model`-vector the transformer treats as position `t`.

---

## 8. Model

A nanoGPT-style causal decoder. The novelty is upstream (tokens) and downstream (decisions); the transformer is deliberately boring.

| Field | Value | Rationale |
|---|---|---|
| `d_model` | 512 | Fits an A10 (24 GB) with context 512, batch 64, bf16 |
| `n_layers` | 8 | ~30M params; depth over width for sequence tasks |
| `n_heads` | 8 | `d_head = 64`, a stable head size |
| `d_ff` | 2048 | 4× MLP expansion |
| `context_len` | 512 | ~2 trading days of 5-min bars |
| `vocab_size` | 32 | Return-bucket count |
| `dropout` | 0.1 | On attention, MLP, and embedding |
| `positional` | RoPE | No learned position table to retune when context grows |
| `norm` | Pre-LayerNorm | Stable without warmup gymnastics |
| `activation` | GELU | Standard in decoder LMs |
| `attention` | Causal SDPA | `F.scaled_dot_product_attention` yields FlashAttention-2 for free |

RoPE is a bet on future context growth; when LOB tokens push sequences past 2k, RoPE extrapolates without a new embedding table.

Loss is cross-entropy over the 32-bucket next-token target. An optional magnitude-weighted variant:

```
loss_t = w_t * CE(logits_t, target_t)
w_t    = 1 + alpha * |center[target_t]|   # alpha ∈ [0, 1], config
```

`alpha = 0` is the unweighted baseline; nonzero is the trader-aligned variant.

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

| Split | Range | Purpose |
|---|---|---|
| train | 2015-01-01 → 2022-12-31 | ~8 years, all iteration |
| val | 2023-01-01 → 2023-12-31 | model selection, calibration |
| test | 2024-01-01 → 2025-06-30 | opened once at the end |

Embargo defaults to `horizon` bars — 1 for next-bar prediction, up to 12 for longer configured horizons.

Optimizer is AdamW with `lr=3e-4`, `betas=(0.9, 0.95)`, `weight_decay=0.1` on 2D params only (biases and LayerNorm excluded). Cosine LR decays to 10% of peak after a 2,000-step linear warmup. Global L2 gradient clip at 1.0. Mixed precision `bfloat16` via `torch.amp.autocast`; bf16 needs no loss scaler. Batch is 64 sequences × 512 tokens; drop it if you're memory-bound.

Every 2,000 steps, checkpoint `{model, optimizer, scheduler, rng_states, config, git_sha, data_hash, step, val_metrics}` into `artifacts/{run_id}/step_{step}.pt`. Keep top-K by **validation ECE**, not accuracy — calibration is what the trading layer consumes. A `latest.pt` symlink covers interruption recovery.

Determinism: `torch`, `numpy`, `random` seeded from `training.seed`; `torch.use_deterministic_algorithms(True, warn_only=True)`; `CUBLAS_WORKSPACE_CONFIG=:4096:8`. Deterministic kernels cost ~15% throughput on scatter-add and a few backward paths, which is fine. Single-worker DataLoader with `worker_init_fn` seeding is the default; multi-worker is only enabled when I/O binds, and the resulting batch-order nondeterminism is logged on the run.

W&B logs training loss, LR, grad norm, and throughput every step. Every eval interval logs val CE, top-1, top-3, ECE, entropy, directional accuracy, a reliability diagram, and predicted distributions on fixed diagnostic timestamps (2023-03-13 FOMC, 2023-08-10 CPI). Every run's metadata carries the full config, git SHA, and dataset SHA256.

---

## 10. Evaluation

The test period opens exactly once, at the end. Everything below runs on **val**.

Prediction metrics: cross-entropy (bits/token for interpretability), top-1 and top-3 bucket accuracy, and per-bar distribution entropy (diagnostic; sharper is not always better).

Calibration: expected calibration error with 15 confidence bins on the argmax probability, plus a reliability diagram uploaded to W&B each eval. Directional calibration is the one the trading layer actually eats — bin predicted `P(up)` into deciles and report realized up-frequency per decile.

Signal quality: directional accuracy is the sign of `sum(p * bucket_centers)` vs. realized sign. Rank IC is Spearman correlation between predicted expected return and realized return over the eval window.

Three baselines run on identical data, splits, seeds, and tokens. **Linear head** applies `nn.Linear(context_len * d_model, vocab_size)` to flattened market-state vectors — if the transformer doesn't clear this, depth is wasted. **Small MLP** puts three GELU hidden layers (128 → 64 → 32) on the last-position market-state vector, testing whether attention buys anything past a shallow nonlinear map. **Target-only** runs the same transformer with market, macro, options, and event channels zeroed at the embedder, testing whether the multi-modal token does work. Each baseline is a separate run under the same config skeleton with only model or channel-list overridden.

---

## 11. Simulator

A bar-by-bar walker over the test range. No vectorization tricks that risk peeking. Signature:

```python
def simulate(model, tokenized_test: dict, buckets: ReturnBucketizer,
             cost_cfg: CostConfig, policy_cfg: PolicyConfig) -> SimResult: ...
```

At each bar `t` the walker assembles the market-state token from features at times `≤ t`, runs a forward on the trailing `context_len` window, softmaxes the last-position logits to `p[t] ∈ ℝ^32`, then derives `expected_vn_return = sum(p * bucket_centers)`, `expected_return = expected_vn_return * realized_vol_30_t`, `p_up = p[center > 0].sum()`, and `sharpness = 1 - entropy(p) / log(32)`.

Cost and risk at intended size are `spread_cost = 0.5 * spread_proxy_t`, `slippage = kappa * size` (linear; `kappa` calibrated by regressing observed short-horizon return against traded size proxy on the training window — a starting value is 0.5 bps per 1% of median 5-min volume), and `risk_penalty = lambda * variance(p)` where variance uses `bucket_centers`.

The decision: `edge = expected_return - (spread_cost + slippage) - risk_penalty`. Long if `edge > threshold`, short if `edge < -threshold`, else flat. `size = clip(edge / uncertainty_scale, -max_size, +max_size)` with `uncertainty_scale ∝ sqrt(variance(p))`. Positions are single-instrument, single-position. Entries and exits print at the **next bar's open** so the decision variable never touches the fill.

Reported metrics: cumulative return, mean and std of daily returns, annualized Sharpe, hit rate (positive P&L after cost), max drawdown, time-to-recovery, per-trade P&L histogram with tail metrics, and a capacity sweep — the largest `max_size` at which Sharpe stays above 1.0. The capacity number is the honest bound on the economic edge.

---

## 12. Configs

Hydra 1.3+ composes YAML config groups. It beats plain YAML + Pydantic because config groups let you swap one axis at a time (`model=small`, `training=fast`, `data=spy_1m`) without an exponential set of full configs.

```yaml
# configs/experiments/mvp_spy_5m.yaml
defaults:
  - data: spy_5m
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
```

If a value is not in a config, it is not a hyperparameter.

---

## 13. Experiment tracking

W&B project `price-space-llm`. Each run logs the resolved config as metadata, `git rev-parse HEAD`, the dirty flag from `git status --porcelain`, the SHA256 of the tokenized dataset, per-step scalars (loss, LR, grad norm, throughput), per-eval metrics from §10, and predicted-distribution bar charts on fixed diagnostic bars.

`experiments/logbook.csv` is append-only, one row per run:

```
date,run_id,branch,git_sha,notes,train_loss,val_loss,val_ece,val_dir_acc,held_out_sharpe,touched_test
2026-06-14,20260614_140312_mvp_spy_5m,main,a1b2c3d,baseline full-channel,2.61,2.83,0.031,0.532,,no
```

`scripts/register_run.py` writes the row from W&B run metadata at the end of training. `touched_test` is a required boolean — the CLI refuses to register without it — and rows where it is `yes` count against a documented budget of **3 held-out looks** for the whole MVP. Blow the budget and the reported held-out number is not trustworthy.

---

## 14. Infrastructure

Compute is a single GPU rented on Lambda Labs: NVIDIA A10 (24 GB) at ~$0.75/hr for iteration and small runs, A100 40 GB at ~$1.30/hr for full training where wall-clock matters. The budget envelope is ~$500 of compute, which covers ~300 A10-hours or ~150 A100-hours across iteration, baselines, and simulation.

Storage sits on local NVMe, ~50 GB total: ~10 GB raw Parquet for 10 years across all channels, ~2 GB per aligned dataset, ~3 GB per tokenized tensor, and ~1 GB per artifact bundle × ~30 runs = ~30 GB.

The instance runs Ubuntu 22.04 with Python 3.11 and PyTorch 2.4+ on CUDA 12.x, giving `torch.compile` and current SDPA kernels. `uv sync` manages dependencies from `pyproject.toml`.

Raw Parquet is mirrored to an S3 or GCS bucket at ~$0.02/GB/mo as a resumability backup. Nothing in the runtime code path depends on the mirror existing.

---

## 15. Interfaces

Every module boundary is narrow, typed, and stable. This is where the pipeline earns its refactorability.

| Boundary | Interface | Contract |
|---|---|---|
| Vendor MCP → Ingestion | `IngestionClient.call(tool, **params) -> pd.DataFrame` | UTC timestamps, vendor-native columns, cache-first |
| Ingestion → Alignment | `fetch(...) -> pd.DataFrame` with UTC `timestamp` index | Common index type; channel-specific columns |
| Alignment → Features | wide `pd.DataFrame` on 5-min UTC grid with `missing_mask_*` columns | Row for every RTH bar; target never missing |
| Features → Tokenizer | same DataFrame shape, causally normalized | All columns finite; normalizer state written to `artifacts/` |
| Tokenizer → Training | `Dataset` yielding `(feats: dict[str, Tensor[T, F_c]], target: LongTensor[])` | Fixed context length; embargo enforced in sampler |
| Training → Artifacts | `artifacts/{run_id}/` with `checkpoint.pt`, `config.yaml`, `normalizers.pt`, `buckets.pt` | Self-contained; loadable without training repo state |
| Model → Simulator | `predict(state_sequence) -> Tensor[vocab_size]` | Pure function; no side effects; CPU or GPU |
| Simulator → Evaluation | `SimResult` dataclass: trade ledger, equity curve, per-bar decisions | JSON-serializable for the logbook |

Every function that crosses a boundary has type hints and a docstring stating the contract. `Protocol` types live in `src/utils/interfaces.py`; downstream modules import them without pulling in upstream implementations.

---

## 16. Tests

Unit tests target the modules where a subtle bug destroys the entire result.

For the tokenizer: `decode(encode(x))` maps `x` to the center of its bucket; boundaries are monotone. On a standard Gaussian sample, buckets 0 and 31 hold ~0.5% mass each.

For causal normalization the leakage test is the point of the whole suite: build a DataFrame with random values, compute the causally normalized column, shuffle rows with index `> t*`, and assert values at index `≤ t*` are byte-identical. A second test asserts rows before the 5,000-bar warmup are masked to zero.

Alignment tests inject known gaps into a synthetic multi-channel input and assert `missing_mask_*` columns match ground truth. Every timestamp in the aligned table must be UTC and monotone increasing.

For the model, forward-pass shapes: with `d_model=64`, `context=16`, `batch=4`, output logits are `[4, 16, 32]`. The causal-mask test is the single most important test in the suite: perturb the value at position `t+k` for any `k > 0` and assert the output at position `t` is bitwise unchanged. Deterministic forward: same seed and input, same output across two calls.

Simulator tests confirm a zero-alpha strategy books exactly zero P&L before costs and exactly `-2 * spread_cost` per round-trip after. The no-lookahead test shuffles bars after the decision index and asserts the equity curve up to that index is unchanged.

Integration lives at `tests/integration/test_end_to_end.py`. It runs the full pipeline on a synthetic 3-month SPY slice under `configs/experiments/smoke.yaml` and asserts val loss decreases from initial. Runs in under 5 minutes on CPU.

`pytest -q` is the command. No CI in v1; the developer runs the suite before every training run.

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

Polars over pandas is not stylistic. On the aligned dataset (~2 GB, ~500k rows × ~80 columns), a `join_asof` across five channels runs in ~4 seconds in Polars and ~90 seconds in pandas. Lazy scans mean the alignment stage streams from Parquet without materializing intermediates. pandas comes back in as a shim wherever a fetcher returns a `pd.DataFrame`; the aligned stage converts once at the entry point.

Workflow: `uv sync` → edit → `pytest tests/` → `python scripts/train.py experiments=mvp_spy_5m` → `python scripts/evaluate.py run_id=<...>` → `python scripts/simulate.py run_id=<...>` → `python scripts/register_run.py run_id=<...>`.

---

## 18. What v2 changes

Each of these is a bounded change, not a rewrite.

**LOB tokens** add a millisecond-resolution ingestion path (Polygon or LOBSTER) and a separate LOB tokenizer that emits its own stream. The transformer input becomes a fusion of the 5-min market-state token and an LOB-token embedding. Context length likely grows past 2,000; RoPE was chosen for exactly this.

**Multi-instrument** makes the channel schema hierarchical: `target[instrument].{feature}`, with an instrument-id embedding added to the market-state token the same way the channel-type embedding is. The dataset yields `(instrument_id, feats, target)` triples; the loss is masked to the instrument's active bars. Universe growth becomes a config change. This is the next version, not a strategic goal.

**RL trading policy** adds a policy net downstream of the distribution head, trained with a differentiable proxy for after-cost P&L or PPO against the simulator. The transformer weights either freeze or fine-tune under stop-gradient. The `SimResult` ledger is already differentiable-friendly.

**Real-time deployment** targets an end-to-end latency budget under 100 ms per 5-min-bar signal. Model is exported to ONNX or TorchScript. A warm inference process holds normalizer state, bucket boundaries, and weights in memory. Ingestion gains a streaming adapter that emits closed-bar features into a persistent state buffer. Training is unchanged; only serving is new.

Each of these respects the existing module boundaries. That is the payoff of §2.
