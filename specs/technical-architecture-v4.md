# Price-Space LLM — Technical Architecture

**Version:** v4 (architecture-review fixes, first-principles justified)
**Target:** SPY, 15-minute bars, ~10 years of history
**Stack:** Python 3.11, PyTorch 2.4+, single GPU (A10 or A100)

---

## 0. What this system is

A decoder-only causal transformer over continuous market-state embeddings. Each input token is a learned continuous embedding of the market state at one 15-minute boundary. The output space is a discrete vocabulary of 32 forward-return buckets. The product name is Price-Space LLM. The technical claim is narrower: LLM-style causal decoder trained with per-position next-token cross-entropy, where "next token" is the bucket that will contain the volatility-normalized return over the interval that starts at the current bar's close.

The architecture is **multimodal linear fusion followed by temporal attention**. At each 15-minute bar, every channel — target OHLCV features, cross-asset context (QQQ, IWM, VIX, TLT, DXY, GLD, USO), macro readings (CPI, Fed funds, 10Y yield, unemployment, NFP), options flow (put/call ratio, options volume), calendar and event flags — is passed through its own `nn.Linear` projection into a common `d_model`-dim space. The projections are summed. That sum is a continuous state vector. There is no per-channel additive embedding inside the sum; the per-channel projection matrices already encode channel identity because each is a distinct learned linear map. Adding a channel-type embedding inside the sum would inject a constant across every timestep and carry no per-channel signal. §7.2 justifies this from first principles.

The temporal transformer then operates over the sequence of these per-bar state vectors. Attention does not run between channels within a single timestep in v1. The default fusion is one linear map from all channels to one state; a one-block cross-channel attention mixer is a required v1 ablation (§10), because the linear-fusion default asserts that within-timestep channel interactions are adequately captured by a single linear projection, and that assertion deserves a test.

Each output token is a discrete label from a 32-bucket vocabulary indexed 0–31 covering the volatility-normalized forward return over the interval starting at the current bar's close. Bucket boundaries are percentile-uniform on the training set, so the categorical vocabulary is scale-invariant across regimes: a one-sigma move in a calm market and a one-sigma move in a volatile one land in the same bucket. The model's output at each position is a probability distribution over those 32 buckets. Whether 32 is the right count and whether a categorical head is the right head are both ablations in §10, not assumptions.

Downstream, a bar-by-bar simulator turns each distribution into a trade decision using an explicit cost model: `edge = E[return] − half_spread − k·size − risk_penalty(distribution)`. If `edge > threshold`, take a position sized by `edge / std(distribution)`.

That is the whole system. Everything below is how it is built.

The move from 5-min to 15-min bars was deliberate. At 15-min the expected per-bar move on SPY is roughly three times larger than at 5-min, which shrinks costs as a fraction of edge proportionally and directly addresses the concern that Corwin-Schultz on 5-min SPY bars overestimates the true spread by an order of magnitude. It also gives each macro countdown feature per-bar semantics that were essentially constant at 5-min. The dataset shrinks from ~197k to ~65k training bars, which is enough to fit a small-to-mid-scale transformer once the model-size sweep in §8 has picked the right point on the curve.

---

## 1. The pipeline

Data flows one way: vendor sources → channel-coverage probe → aligned Parquet → per-timestep state vector → 32-way softmax at every position → cost-aware simulator → chronological holdout. Every stage is causal, config-driven, versioned, and independently testable.

```
                                                          Price-Space LLM v4
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
              │  probe_channels.py     │  Phase 0 availability probe
              │  → channel_coverage    │  data/manifests/channel_coverage.json
              └───────────┬────────────┘
                          ▼
              ┌────────────────────────┐
              │  ingestion layer       │  IngestionClient → per-channel modules
              │  (rate-limit + cache)  │  writes Parquet with value_time,
              │                        │  released_at, known_at, revision_id
              └───────────┬────────────┘
                          ▼
              ┌────────────────────────┐
              │  alignment / join      │  as-of join on known_at against
              │  → aligned dataset     │  UTC 15-min grid; missing_mask,
              │                        │  age_since_known_at, observed_here
              └───────────┬────────────┘         data/aligned/{run_id}.parquet
                          ▼
              ┌────────────────────────┐
              │  feature pipeline      │  per-channel causal features
              │  (all causal)          │  + expanding-window causal z-score,
              │                        │  frozen at end of training
              │                        │  + is_overnight_gap flag
              └───────────┬────────────┘
                          ▼
              ┌────────────────────────┐
              │  tokenizer             │  return bucketizer (32 buckets, 0–31)
              │  + per-channel proj.   │  → artifacts/tokenizer/bucket_stats.json
              │                        │  → data/tokenized/{run_id}.pt
              └───────────┬────────────┘         (dict[str, Tensor[T, F_c]])
                          ▼
              ┌────────────────────────┐
              │  training loop         │  AdamW, bf16, cosine LR, W&B
              │  (causal transformer,  │  all-position CE, random-window
              │   per-position CE)     │  sampling; checkpoint by val NLL
              └───────────┬────────────┘         artifacts/{run_id}/*.ckpt
                          ▼
              ┌────────────────────────┐
              │  evaluation            │  NLL, top-k, ECE, Brier, RPS, dir acc,
              │                        │  baselines (linear / MLP / GRU /
              │                        │  transformer / target-only /
              │                        │  magnitude-weighted / channel-mixer /
              │                        │  patch=4 / quantile-head / buckets={16,64})
              │                        │  regime split
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

Seven rules. Violating one is a bug.

**Causal by construction.** A feature at time `t` is a pure function of data with `known_at < t`. Rolling-window utilities refuse to read past the current row. A unit test shuffles rows with index `> t*` and asserts feature vectors at `t ≤ t*` are byte-identical. This is a secondary sanity check; the primary leakage defense is the `known_at` join in §4.

**Time-based splits with embargo.** Train, val, and test boundaries are dates in the config. Between any two boundaries the loader drops `H` bars, where `H` is the prediction horizon, so labels cannot leak. Random splits are forbidden.

**No magic numbers in code.** Window sizes, bucket counts, learning rates, date ranges, channel lists, the risk-penalty `lambda`, the magnitude-weight `alpha`, the patch size — all live in YAML. Code reads config; code never hard-codes hyperparameters.

**Reproducible training.** Every run seeds `torch`, `numpy`, `random`, and CUDA, enables deterministic algorithms, and logs the config, git SHA, and data hash. Rerunning the same config must reproduce metrics to within numerical noise.

**One source of truth per channel.** Each channel has exactly one ingestion module. Downstream code reads the canonical Parquet — it never re-fetches or recomputes raw values. This kills the class of bug where two callers get different values for the same bar. A per-commit test enforces it (§16).

**Artifacts and configs ship together.** Every checkpoint sits next to its config, tokenizer boundaries, normalizer stats, cost-calibration artifacts, and git SHA. A `.pt` file alone is not the deliverable.

**No hardcoded target instrument.** The target instrument is a runtime parameter. `SPY` appears only in `configs/target/spy.yaml`, in test fixtures, and in default arguments. It never appears in class names, module paths, table names, feature names, or code paths. Ingestion, features, tokenizer, training, and simulator take the target symbol as an argument. This is what makes v2 (multi-instrument) an extension rather than a rewrite; if a `grep -r "SPY" src/` returns any hit outside of docstrings, that is a bug.

---

## 3. Repository layout

```
price_space_llm/
  configs/                # YAML experiment configs
    data/                 # channel lists, date ranges, ingestion params
    target/               # target-instrument specs (spy.yaml, qqq.yaml, ...)
    channels/             # channel manifests (v1.yaml)
    features/             # per-channel feature specs
    tokenizer/            # bucket count, boundary policy, head type
    model/                # architecture hyperparameters
    training/             # optimizer, schedule, batch, seeds
    simulation/           # cost model, decision thresholds, lambda, alpha
    experiments/          # top-level configs composing the above
  data/
    raw/                  # vendor-native Parquet dumps, immutable
    manifests/            # channel_coverage.json
    aligned/              # joined multi-channel Parquet keyed by run_id
    tokenized/            # torch tensors ready for training
  artifacts/
    {run_id}/             # checkpoint.pt, config.yaml, normalizers.pt
    tokenizer/            # bucket_stats.json (frozen dequantizer)
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
  scripts/                # probe_channels.py, fetch_data.py, align.py,
                          # train.py, evaluate.py, simulate.py,
                          # register_run.py, calibrate_spread.py,
                          # calibrate_kappa.py, check_test_look.sh (pre-commit)
  pyproject.toml          # uv-managed
```

`configs/` is the only place hyperparameters live. `data/raw/` is write-once. `data/aligned/` and `data/tokenized/` are derived and regenerable. `artifacts/tokenizer/bucket_stats.json` is the shared dequantizer every downstream consumer reads.

---

## 4. Ingestion

### 4.1 Phase 0 channel-coverage probe

Before any pipeline stage runs, `scripts/probe_channels.py` walks every channel in `configs/channels/v1.yaml` and asks the vendor what it actually returns. For each channel the probe hits the source at five sample dates — 2015-06-15, 2018-06-15, 2020-06-15, 2022-06-15, 2025-01-15 — and records what came back. The output lands at `data/manifests/channel_coverage.json` with one entry per channel:

| Key | Meaning |
|---|---|
| `source` | vendor identifier (`mcp_av`, `polygon`) |
| `symbol` | the exact symbol string requested |
| `requested_frequency` | what the fetcher asked for (`15min`, `1d`, ...) |
| `actual_frequency` | what the vendor actually returned |
| `earliest_timestamp` | first observation the vendor served on any probe date |
| `latest_timestamp` | most recent observation returned |
| `missing_fraction` | fraction of expected 15-min bars absent inside the training range |
| `timezone` | vendor-reported timezone of the raw stamps |
| `timestamp_semantics` | `bar_open` or `bar_close` |
| `revision_behavior` | `immutable`, `revisable`, or `restated` |

The manifest is committed to the repository. Any channel with `missing_fraction > 0.05` or an `earliest_timestamp` later than 2015-06-15 is either dropped from v1 or added with an explicit note in the channel manifest explaining the shortfall. The feature pipeline refuses to run without a fresh manifest — `align.py` opens `channel_coverage.json`, checks its `generated_at` timestamp against the channel-config mtime, and hard-fails if the probe is stale or missing. This turns "the vendor might not have that series at 15-min in 2015" from a runtime surprise into a Phase 0 gate.

### 4.2 Sources and fetchers

The primary source is the Alpha-Vantage-style financial-data MCP surfaced in this environment. Its tools cover intraday equities (`TIME_SERIES_INTRADAY`), daily adjusted OHLCV (`TIME_SERIES_DAILY_ADJUSTED`), macro series (`CPI`, `FEDERAL_FUNDS_RATE`, `TREASURY_YIELD`, `UNEMPLOYMENT`), options flow (`HISTORICAL_OPTIONS`, `HISTORICAL_PUT_CALL_RATIO`), event calendars (`EARNINGS_CALENDAR`), and news sentiment. Fallback is Polygon.io for equities minute bars when the MCP's intraday coverage or history depth falls short. Every ingestion module has a `source` knob; switching is a one-line config change.

`IngestionClient` is a thin façade with a token-bucket rate limiter (75 req/min default), retry-with-backoff on 429/5xx, response validation, and Parquet caching keyed by `sha256(tool, params)`:

```python
class IngestionClient:
    def __init__(self, source: Literal["mcp_av", "polygon"], cache_root: Path,
                 rate_limit_per_min: int = 75): ...

    def call(self, tool: str, **params) -> pd.DataFrame:
        """Cache-first: hash(tool, params) → parquet key. Miss → network → write."""
```

Every channel implements one interface. The `symbol` argument is passed at construction time, not baked into the class:

```python
class ChannelFetcher(Protocol):
    channel: str  # "target" | "market_context" | "macro" | "options" | "event"
    def fetch(self, symbol: str, start: dt.datetime, end: dt.datetime,
              freq: Literal["1min","5min","15min","1h","1d"]) -> pd.DataFrame: ...
```

`fetch` requests `15min` where the vendor supports it natively. For series only exposed at 5-min or 1-min, the fetcher downsamples by taking the last bar of each 15-minute interval — `open` from the first sub-bar, `close` from the last, `high`/`low` from the interval extrema, `volume` summed. Downsampling happens in the fetcher, not downstream, so alignment always sees a canonical 15-min grid.

### 4.3 The `known_at` schema

Every raw observation written to `data/raw/` carries four columns. These are the load-bearing primitive that makes causality a data-model property rather than a downstream unit test:

| Column | Meaning |
|---|---|
| `value_time` | the period the value describes (e.g. bar-close for OHLCV, reference month for CPI) |
| `released_at` | the first wall-clock instant the value became publicly available |
| `known_at` | the wall-clock instant at which the pipeline may legally consume it |
| `revision_id` | optional; monotone within `(source, channel, symbol, value_time)` for revisable series |

For intraday equity bars, `value_time` is the bar close, `released_at` equals `value_time` (bars publish at close), and `known_at` equals `released_at` plus a conservative vendor-latency budget from the channel manifest. For monthly macro series like CPI, `value_time` is the reference month, `released_at` is the BLS publication timestamp, and `known_at` equals `released_at`. For revisable series, each revision writes a new row with a new `revision_id`; the alignment layer selects the latest revision whose `known_at ≤ t`.

The alignment layer performs an **as-of join on `known_at`** against every timestamp on the 15-min UTC target grid. For each grid timestamp `t`, the join picks, per channel, the most recent row satisfying `known_at ≤ t`. There is no separate forward-fill pass; the as-of join is the forward-fill. The schema makes leakage a well-typed error. The shuffle-based unit test remains in place as a secondary sanity check on the feature functions themselves.

Concrete fetchers for v1:

| Channel | Symbols / series | MCP tool | Native freq | Ingested freq |
|---|---|---|---|---|
| target | (config) | `TIME_SERIES_INTRADAY` | 5min | 15min (downsampled) |
| market_context | QQQ, IWM, VIX, TLT, DXY, GLD, USO | `TIME_SERIES_INTRADAY` | 5min | 15min (downsampled) |
| macro | CPI, FEDFUNDS, DGS10, UNRATE, NFP | `CPI`, `FEDERAL_FUNDS_RATE`, `TREASURY_YIELD`, `UNEMPLOYMENT`, `NONFARM_PAYROLL` | daily/monthly | as-of joined on `known_at` |
| options | put/call ratio, options volume | `HISTORICAL_PUT_CALL_RATIO`, `HISTORICAL_VOLUME_OPEN_INTEREST_RATIO` | daily | as-of joined on `known_at` |
| event | earnings, FOMC, CPI releases | `EARNINGS_CALENDAR` + curated static tables | date-only | per-bar countdown |

Cache is content-addressed by request parameters, so parameter changes force refetch. Cached responses land at `data/raw/{source}/{channel}/{symbol}/{yyyy-mm}.parquet`.

---

## 5. Storage

**Raw.** `data/raw/{source}/{channel}/{symbol}/{yyyy-mm}.parquet`. Monthly partitioning keeps single-file scans under a second and lets ingestion refresh a single month without rewriting a decade. Every raw file carries `value_time`, `released_at`, `known_at`, and (where applicable) `revision_id`.

**Aligned.** `data/aligned/{run_id}.parquet`. One wide table on a canonical 15-minute UTC grid over the configured date range. Rows exist only for RTH bars; pre- and post-market are dropped to keep the target's session-boundary semantics clean. At 15-min RTH, each session yields 26 bars (6.5 hours × 4 bars/hour), and ten years yields ~65,000 rows.

Columns follow `{channel}__{symbol}__{feature}`:

| Column | Type | Notes |
|---|---|---|
| `timestamp` | `datetime[ns, UTC]` | primary key, 15-min grid; this is the grid `t` used in the as-of join |
| `target__{sym}__{open,high,low,close,volume}` | float64/int64 | OHLCV |
| `market__QQQ__close`, `market__VIX__close`, ... | float64 | close at the bar |
| `macro__CPI__value`, `macro__DGS10__value`, ... | float64 | last row with `known_at ≤ t` |
| `macro__CPI__known_at` | `datetime[ns, UTC]` | `known_at` from the selected row; carried through for audit |
| `options__PCR__value`, `options__VOLOI__value` | float64 | last row with `known_at ≤ t` |
| `event__{earnings,fomc,cpi_release}_flag` | int8 | 1 on release date |
| `event__mins_to_{fomc,cpi,earnings}` | float32 | signed countdown |
| `event__is_overnight_gap` | int8 | 1 iff the row's target-return period spans a session boundary |
| `missing_mask__{channel}__{symbol}` | bool | true iff the as-of join found no eligible row |
| `age_since_known_at__{channel}__{symbol}` | int32 | number of 15-min bars since the value was last observed; 0 on fresh observation |
| `observed_at_this_grid_step__{channel}__{symbol}` | bool | True iff a fresh observation for this channel arrived exactly at this grid step |

Bars where the target itself is missing (halt, holiday) are dropped. For every other channel, the as-of join carries the last known value forward and the matching `missing_mask_*` bit flips to `True` when no eligible row existed. Zero-imputation is banned because it collides with legitimate zero returns.

The staleness pair — `age_since_known_at` and `observed_at_this_grid_step` — is new in v4 and load-bearing. Reason: after a channel has been observed once, the as-of join always finds a row, so the `missing_mask` flips to false regardless of how stale the value is. A CPI value from 30 days ago and one from 30 minutes ago produce the same feature after the join but carry very different information about how much the market has already digested the print. The model needs staleness expressed as an input feature, not left implicit. `observed_at_this_grid_step` gives a hard binary flag at the moment of release; `age_since_known_at` gives a continuous count that decays into the past. Together they let the model condition on "is this a fresh macro print" and on "how long since the last one" separately.

**Tokenized.** `data/tokenized/{run_id}.pt` — a `torch.save`'d dict. The prior spec's `features: Tensor[T, C, F]` shape cannot hold different `F_c` per channel without padding, and there is no reason to invent packed storage at 65k rows. v4 uses one tensor per channel:

```python
{
  "features": {                       # dict[str, Tensor[T, F_c]] (float32)
      "target":         Tensor[T, F_target],
      "market_context": Tensor[T, F_market],
      "macro":          Tensor[T, F_macro],
      "options":        Tensor[T, F_options],
      "event":          Tensor[T, F_event],
  },
  "targets":           Tensor[T],     # bucket id in [0, 32) for the interval
                                      # immediately following position t (int64)
  "vol":               Tensor[T],     # trailing realized vol at t (float32)
  "timestamps":        Tensor[T],     # epoch nanoseconds (int64)
  "is_overnight_gap":  Tensor[T],     # int8
  "mask":              Tensor[T],     # bool: eligible target position?
  "channel_names":     list[str],
  "meta":              dict,          # run_id, config hash, git sha, data hash,
                                      # target_symbol, channel_coverage_sha
}
```

The training loop reads this one file. Each `targets[j]` is the bucket for the interval immediately following input position `j`; positions with missing critical data, positions inside the embargo, and the last position of a valid contiguous run have `mask[j] = False`.

---

## 6. Features

Every feature is computed with strictly causal utilities: `rolling(...).apply(...)` with `min_periods` set, and `.shift(1)` on anything label-adjacent.

For the target instrument the suite is `log_return = log(close_t / close_{t-1})`, `realized_vol_30 = std(log_return[t-30:t])`, `bar_shape = (close - open) / (high - low + eps)`, `range_pct = (high - low) / close_{t-1}`, `volume_z_100 = (volume - roll_mean_100(volume)) / roll_std_100(volume)`, `dollar_volume = close * volume`, and a Corwin-Schultz-style `spread_proxy = 2 * |high - low| / (high + low)`. `spread_proxy` is a raw feature; its calibration into a real half-spread happens in the simulator's cost model (§11).

**Vol estimator.** v1 uses 30-bar trailing realized volatility. At 15-min this covers 30 bars ≈ 7.5 hours ≈ just over one trading session. Alternates — EWMA, GARCH(1,1), and VIX-implied — are wired into the config schema but not run as ablations in v1. Committing to 30-bar realized keeps the target's units unambiguous.

Market-context symbols (QQQ, IWM, VIX, TLT, DXY, GLD, USO) get `log_return`, `realized_vol_30`, `volume_z_100`, `bar_shape`. VIX additionally emits `vix_level` and `vix_change`.

Macro series (CPI, FEDFUNDS, DGS10, UNRATE, NFP) carry the last row with `known_at ≤ t` and add `delta_since_last_release`, `days_since_release`, and the new v4 pair `age_since_known_at` and `observed_at_this_grid_step`. Both are causal because `known_at` is when the value became legal to consume. The countdown-to-next-release features carry per-bar variation across a trading day; the model now has a distinguishable pre-release, at-release, and post-release position within each session, and it can distinguish "the last CPI was ninety minutes ago" from "the last CPI was three weeks ago."

Options channels (put/call ratio, options volume) carry the last daily value plus a 20-day z-score of each, plus the same staleness pair.

Event channels emit a binary flag for "bar falls on release day" plus a signed `mins_to_next_release` clipped to ±10 sessions.

**Session-boundary handling.** Overnight gaps are real events, not artifacts to hide. Each training row carries a boolean `is_overnight_gap`. It is `True` iff the target-return period for that row spans a session boundary — i.e. the last regular-session bar of day `N` predicts the first regular-session bar of day `N+1`. The flag is added to the event channel as a scalar feature so the transformer conditions on it directly. Overnight examples are not dropped; there are roughly 252 per year and they carry information about the overnight risk premium and about how much macro news accumulated while the market was closed.

```python
def compute_overnight_gap(timestamps: pd.DatetimeIndex, tz: str = "America/New_York") -> np.ndarray:
    """Return an int8 array marking bars whose next-bar target is across a session close."""
    local = timestamps.tz_convert(tz)
    session_date = local.date
    next_date = np.roll(session_date, -1)
    is_gap = (next_date != session_date).astype(np.int8)
    is_gap[-1] = 0  # last bar has no next bar
    return is_gap
```

**Normalization — one scheme, committed.** Continuous features are normalized by expanding-window causal z-score, fitted on the training partition and then frozen at the end of training. Inference, validation, and test use the frozen scaler. The formula on the training window is:

```
z_t = (x_t - mean(x_{0:t-1})) / (std(x_{0:t-1}) + eps),  t >= 2000
z_t = 0                                                    t <  2000  (masked in loss)
```

Warmup covers roughly a calendar quarter and gives stable moments. Stats are computed once on the training partition and saved to `artifacts/{run_id}/normalizers.pt`; inference uses the same fitted state. Rationale for freezing: reproducibility, and no train/eval distribution mismatch introduced by a scaler that keeps changing at inference. An online scaler that keeps updating after training is a future ablation, not v1.

---

## 7. Tokenizer

Two frozen artifacts, both fit on the training split.

### 7.1 Return bucketizer

Fit on `target__{sym}__log_return / realized_vol_30` over training bars only. **32 buckets, indexed 0 through 31, in the default v1 configuration.** Buckets 1–30 are percentile-uniform bins between the 0.5th and 99.5th percentiles of training vol-normalized returns. Bucket 0 catches everything below the 0.5th percentile; bucket 31 catches everything above the 99.5th. Vol-normalized tails have finite mass but irregular shape; forcing them into equal-mass bins wastes vocabulary on outliers.

The count 32 is a starting number, not a derived quantity. A bucket-count ablation in §10 sweeps 16, 32, and 64 at the winning size × context × patch configuration. Bucket count trades classification difficulty against resolution: too few and neighboring vol-normalized returns collapse into the same class, hiding the fine structure the decision layer needs; too many and each class has too little training data to fit, and cross-entropy on a rare class carries most of its gradient noise. Three points establish the curve.

After fitting, the bucketizer persists a frozen dequantizer at `artifacts/tokenizer/bucket_stats.json`. This is the file every downstream consumer — evaluator, simulator, notebooks — reads to convert a bucket id back to an expected return. It has one entry per bucket with the following keys:

| Key | Meaning |
|---|---|
| `bucket_lower` | left edge of the bucket in vol-normalized units; `-inf` for bucket 0 |
| `bucket_upper` | right edge; `+inf` for bucket 31 |
| `bucket_train_mean` | mean vol-normalized return of training observations in the bucket |
| `bucket_train_median` | median of the same |
| `bucket_train_frequency` | fraction of training observations landing in this bucket |

All values are computed on the training partition only; val and test never touch this file's fitting step. The outer-bucket means are what the simulator uses to convert an outer-bucket prediction into an expected return.

```python
class ReturnBucketizer:
    boundaries: np.ndarray   # shape [n_buckets - 1], monotone

    def encode(self, vol_norm_return: np.ndarray) -> np.ndarray:
        return np.digitize(vol_norm_return, self.boundaries)  # returns 0..n_buckets-1

    def decode(self, bucket_id: np.ndarray) -> np.ndarray:
        """Read expected return per bucket from the frozen bucket_stats.json."""
        stats = self._stats  # loaded from artifacts/tokenizer/bucket_stats.json
        means = np.array([stats[str(k)]["bucket_train_mean"]
                          for k in range(len(stats))])
        return means[bucket_id]

    def save(self, path: Path): ...
    @classmethod
    def load(cls, path: Path) -> "ReturnBucketizer": ...
```

`decode` is the unbiased dequantizer the trading layer uses to compute expected return from a bucket distribution.

### 7.2 Market-state embedder

At each `t`, each channel produces a raw feature vector of channel-specific dimension `F_c`. A per-channel `nn.Linear(F_c, d_model)` projects to a common dimension. The projections are **summed** to produce one `d_model`-vector per timestep:

```python
class MarketStateEmbedder(nn.Module):
    def __init__(self, channel_dims: dict[str, int], d_model: int):
        super().__init__()
        self.projections = nn.ModuleDict({
            name: nn.Linear(dim, d_model) for name, dim in channel_dims.items()
        })

    def forward(self, feats: dict[str, Tensor]) -> Tensor:
        out = 0
        for name, x in feats.items():
            out = out + self.projections[name](x)   # [B, T, d_model]
        return out                                  # [B, T, d_model]
```

The v3 spec added a per-channel learned embedding inside this sum. v4 removes it. First-principles reason: if channels are present at every timestep, then the extra term `Σ_c e_c` is a single constant vector added to every state, i.e., a learned scalar bias with no per-channel identifying signal. The per-channel projection matrices `W_c` already encode channel identity because each is a distinct learned linear map — the target channel's projection can rotate, scale, and mix its raw features into any subspace of `d_model` that gradient descent finds useful, and so can every other channel's. Adding a channel-type embedding inside the sum was either redundant or contributed only a constant offset, and it was hiding that fact behind the appearance of doing something.

**On summation vs. concatenation.** `Σ_c W_c x_c` and `W_concat [x_1; ...; x_n]`, where `W_concat = [W_1 ... W_n]`, produce identical outputs and use the same number of parameters. There is no expressivity claim to make about the choice, and prior drafts that said summation "keeps `d_model` fixed" or "scales more cleanly to more channels" were wrong on both counts: concatenation with a single linear layer is also `d_model` at the output and has the same parameter cost. Per-channel projections are implemented as a `ModuleDict` for one reason: modular channel interfaces. Each channel's projection can be added, removed, or replaced without touching the others; a channel dropped in the target-only ablation is one dict-key deletion, not a slice into a concatenated weight matrix. The decomposition is an implementation boundary, not an expressivity claim. After summation the two forms are mathematically identical.

The embedder output at `t` is the single `d_model`-vector the transformer treats as position `t`. The temporal transformer then attends across the sequence of these vectors. There is no attention operation between channels within a timestep in the default v1. Whether there should be is answered by the channel-mixer ablation in §10; a code sketch for the mixer is provided in that section.

---

## 8. Model

A causal decoder over the sequence of per-bar market-state vectors, with **RoPE positional embeddings**. The novelty is upstream (multimodal fusion into continuous state) and downstream (decisions); the transformer is deliberately boring.

Fixed choices:

| Field | Value | Rationale |
|---|---|---|
| `d_head` | 64 | Stable head size |
| `d_ff / d_model` | 4 | Standard MLP expansion |
| `vocab_size` | 32 (default; ablated at 16/64) | Categorical target bucket count |
| `dropout` | 0.1 | On attention, MLP, and embedding |
| `positional` | RoPE | Relative positional structure inside the attention product |
| `norm` | Pre-LayerNorm | Stable without warmup gymnastics |
| `activation` | GELU | Standard in decoder LMs |
| `attention` | Causal SDPA | `F.scaled_dot_product_attention` yields FlashAttention-2 for free |

**On RoPE.** RoPE provides relative positional structure by applying a position-dependent rotation to query and key vectors inside the attention product. It does not require a learned absolute-position embedding table, which is a small but real simplification in the checkpoint. That is the whole reason it is here. v1 never evaluates on sequences longer than the maximum context length seen during training, so RoPE's behavior in that regime is untested and is not a claim of this document. Extending the context beyond training length is a separate research question that requires interpolation or scaling techniques v4 does not commit to. Any reference in the repo to a learned absolute position table is stale and should be treated as a bug.

**On the input side.** The input is not a discrete vocabulary in the language-model sense. It is a continuous per-channel feature vector projected through learned linear maps into a `d_model`-dim state at each timestep. There is no lookup into an embedding table on the input side. The output side is a discrete vocabulary of 32 forward-return buckets in the default configuration. The product name "Price-Space LLM" captures the resemblance to causal-language-model training on the output side and the shape of the training loop; the technical description is "decoder-only causal transformer over continuous market-state embeddings producing a discrete 32-bucket forward-return distribution at every position."

### 8.1 Model-size sweep — required v1 experiment

The dataset is ~65,000 bars with heavy context overlap. Fixing `d_model=512, n_layers=8` up-front would be an unforced choice. v1 replaces it with a four-point sweep in which `d_model`, `n_layers`, `d_ff`, and `n_heads` all scale together. `d_head` is fixed at 64 throughout, so `n_heads = d_model / 64`:

| Config | `d_model` | `n_layers` | `n_heads` | `d_ff` | Params (approx) |
|---|---|---|---|---|---|
| xs | 128 | 4 | 2 | 512 | ~1M |
| sm | 192 | 6 | 3 | 768 | ~3M |
| md | 384 | 8 | 6 | 1536 | ~10M |
| lg | 512 | 8 | 8 | 2048 | ~30M |

The v3 product spec had inconsistently held `d_model = 512` at all four sizes and had said "8 heads" throughout; both were errors — a size sweep that only varies `n_layers` and `d_ff` at fixed width is not a size sweep, it is a depth sweep. v4 fixes this at the tech-arch level and the v4 product spec is being updated to match.

Each configuration is trained under an otherwise identical config (same context length, same optimizer, same seed, same channels). Validation NLL vs model size is reported as a curve. **The default v1 model is the smallest configuration whose validation NLL is within 1% of the best point on the curve.** On a training set this size with this much context overlap, the expected winner is somewhere in the 3M–10M range; the 30M configuration is included to confirm the curve has flattened and to check whether it has already overfit.

Loss is cross-entropy over the 32-bucket next-bucket target, evaluated at **every** valid position in the sequence, not only the last one. A magnitude-weighted variant is a required v1 baseline (§10):

```
loss_t = w_t * CE(logits_t, target_t)
w_t    = 1 + alpha * |bucket_train_mean[target_t]|   # alpha in config, default 1.0
```

`alpha = 0` recovers unweighted CE. `alpha` lives in the training config, not in code.

```python
class PriceSpaceLLM(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        self.embed = MarketStateEmbedder(cfg.channel_dims, cfg.d_model)
        self.blocks = nn.ModuleList([TransformerBlock(cfg) for _ in range(cfg.n_layers)])
        self.norm_f = nn.LayerNorm(cfg.d_model)
        self.head   = nn.Linear(cfg.d_model, cfg.vocab_size, bias=False)

    def forward(self, feats: dict[str, Tensor]) -> Tensor:
        x = self.embed(feats)                       # [B, L, d_model]
        for blk in self.blocks:
            x = blk(x)                              # causal SDPA + RoPE inside
        x = self.norm_f(x)
        return self.head(x)                         # [B, L, vocab_size]
```

Training computes cross-entropy on **all** valid `L` positions per window; inference reads `logits[:, -1, :]` from the current context.

---

## 9. Training

### 9.1 Context-length sweep — required v1 experiment

Context length is the second required ablation. At the winning model size from §8.1, run four configurations at context lengths **64, 128, 256, and 512** 15-min bars. Report validation NLL vs context length.

A 15-min RTH session is 26 bars, so the wall-clock coverage of each configuration is:

| Context (bars) | Trading days | Rough calendar |
|---|---|---|
| 64 | ≈ 2.46 | roughly two and a half trading days |
| 128 | ≈ 4.9 | roughly one trading week |
| 256 | ≈ 9.85 | roughly two trading weeks |
| 512 | ≈ 19.69 | roughly four trading weeks |

Prior drafts said "64 bars ≈ one trading day" and "512 bars ≈ 2.5 trading weeks." Both were arithmetic errors; the numbers above are the correct ones and every downstream reference — evaluation tables, notebook plots, product spec — reads from them.

### 9.2 Dataset, splits, optimizer

`PriceSpaceDataset` mmaps `data/tokenized/{run_id}.pt` once and yields fixed-length windows with **random starting positions** on every epoch. Each window carries per-position targets, not a single scalar target:

```python
class PriceSpaceDataset(Dataset):
    def __init__(self, tokenized_path: Path, context_len: int, horizon: int,
                 date_range: tuple[str, str], embargo: int,
                 samples_per_epoch: int):
        blob = torch.load(tokenized_path, mmap=True)
        self.features       = blob["features"]        # dict[str, Tensor[T, F_c]]
        self.targets        = blob["targets"]         # Tensor[T]
        self.mask           = build_split_mask(       # excludes embargo, missing
            blob["timestamps"], blob["mask"], date_range, embargo,
        )
        self.valid_starts   = np.where(
            rolling_all_valid(self.mask, context_len)
        )[0]
        self.context_len    = context_len
        self.samples_per_epoch = samples_per_epoch

    def __len__(self):
        return self.samples_per_epoch

    def __getitem__(self, _):
        # random-window sampling: uniform over valid starts each draw
        s = int(np.random.choice(self.valid_starts))
        L = self.context_len
        feats  = {c: t[s : s + L] for c, t in self.features.items()}
        target = self.targets[s : s + L]              # Tensor[L]
        mask   = self.mask[s : s + L]                 # Tensor[L]
        return feats, target, mask
```

`build_split_mask` enforces the date range, forbids any window from spanning a split boundary within `horizon` bars, and excludes positions with missing critical data. `rolling_all_valid` picks starting positions such that the whole window's targets are usable.

The model forward returns `logits: [B, L, 32]`. The training step is:

```python
def training_step(model, batch):
    feats, target, mask = batch                        # feats: dict; target: [B, L]; mask: [B, L]
    logits = model(feats)                              # [B, L, 32]
    loss_per_pos = F.cross_entropy(
        logits.view(-1, 32), target.view(-1), reduction="none"
    ).view_as(target)                                  # [B, L]
    if cfg.alpha_mag_weight > 0:
        w = 1 + cfg.alpha_mag_weight * bucket_train_mean_abs[target]
        loss_per_pos = loss_per_pos * w
    loss = (loss_per_pos * mask.float()).sum() / mask.float().sum().clamp_min(1)
    return loss
```

First-principles reason for the switch to all-position causal loss with random-window sampling: predicting the next bucket at **every** position is the training regime a causal decoder is designed for. It gives the model `L` supervision signals per window instead of one, which for `L = 256` is a 256× denser training signal per forward pass at roughly the same compute. Enumerating every overlapping window and taking one prediction from each — the v3 approach — pretends that near-identical contexts are independent examples, so the gradient statistics are dominated by redundant passes over the same neighborhoods. Random-window sampling gives cleaner statistics because each epoch draws a different subset of windows, and each drawn window contributes a full `L`-position gradient rather than one scalar. This is what makes the model "LLM-style" in a technical sense — matching the causal next-token training that made decoder transformers work in the first place.

Splits are date-boundaried in config. For 2015–2025:

| Split | Range | Approx bars | Purpose |
|---|---|---|---|
| train | 2015-01-01 → 2022-12-31 | ~52,000 | ~8 years, all iteration |
| val | 2023-01-01 → 2023-12-31 | ~6,500 | model selection, calibration |
| test | 2024-01-01 → 2025-06-30 | ~9,700 | opened three times total |

Embargo defaults to `horizon` bars — 1 for next-bar prediction, up to 12 for longer configured horizons.

Optimizer is AdamW with `lr=3e-4`, `betas=(0.9, 0.95)`, `weight_decay=0.1` on 2D params only. Cosine LR decays to 10% of peak after a 2,000-step linear warmup. Global L2 gradient clip at 1.0. Mixed precision `bfloat16` via `torch.amp.autocast`; bf16 needs no loss scaler. Batch is 64 sequences at the chosen context length.

### 9.3 Checkpoint selection

Every 2,000 steps, checkpoint `{model, optimizer, scheduler, rng_states, config, git_sha, data_hash, step, val_metrics}` into `artifacts/{run_id}/step_{step}.pt`. **Keep top-K by validation NLL (cross-entropy).** A `latest.pt` symlink covers interruption recovery.

Validation NLL is computed the same way training loss is: per-position cross-entropy averaged over valid positions in the val window. Every other metric is logged per epoch but does not drive selection: expected calibration error (ECE) on 15 confidence bins, Brier score against the one-hot target, ranked probability score (RPS — an ordinal metric that penalizes predictions far in bucket-distance from the target and is the right calibration score for an ordered vocabulary), directional accuracy, and top-1/top-3 accuracy. Selecting on NLL rather than ECE is the corrected decision: a model that predicts a flat distribution scores well on calibration for the trivial reason that it never commits, while its information content collapses; NLL directly measures how much probability mass the model puts on the true bucket. Miscalibration on top of high information is a fixable downstream problem (temperature scaling on val); low information under a well-calibrated head is not.

Determinism: `torch`, `numpy`, `random` seeded from `training.seed`; `torch.use_deterministic_algorithms(True, warn_only=True)`; `CUBLAS_WORKSPACE_CONFIG=:4096:8`. Single-worker DataLoader with `worker_init_fn` seeding is the default.

W&B logs training loss, LR, grad norm, and throughput every step. Every eval interval logs val NLL, top-1, top-3, ECE, Brier, RPS, entropy, directional accuracy, a reliability diagram, and predicted distributions on fixed diagnostic timestamps (2023-03-13 FOMC, 2023-08-10 CPI).

---

## 10. Evaluation

The test period opens exactly three times over the life of v1 — a budget enforced structurally (§13). Everything below runs on **val**.

**Prediction metrics.** Cross-entropy in bits/token (this is what checkpoint selection reads), top-1 and top-3 bucket accuracy, per-bar distribution entropy (diagnostic; sharper is not always better), Brier score, and ranked probability score. RPS is reported because the vocabulary is ordinal — predicting bucket 15 when the truth is 16 should score better than predicting bucket 0, and CE alone does not capture that.

**Calibration.** Expected calibration error with 15 confidence bins on the argmax probability, plus a reliability diagram uploaded to W&B each eval. Directional calibration is the one the trading layer actually eats — bin predicted `P(up)` into deciles and report realized up-frequency per decile.

**Signal quality.** Directional accuracy is the sign of `sum(p * bucket_train_mean)` vs. realized sign. Rank IC is Spearman correlation between predicted expected return and realized return over the eval window.

**Bucket-boundary drift diagnostic.** On the validation split, report the realized bucket-frequency histogram against the frozen `bucket_train_frequency` from `bucket_stats.json`. If validation buckets 0 or 31 hold materially more or less mass than the trained 0.5% each, that is direct evidence of tail-shape drift and belongs in the run summary. Same check on the test set at final evaluation. Vol-normalization mitigates scale drift; it does not mitigate shape drift, and this diagnostic makes shape drift visible.

**Channel-projection cosine diagnostic (exploratory).** After training, compute the mean channel-contribution vector for each channel on 1,000 held-out bars and report the pairwise cosine similarity matrix. This is retained as an exploratory diagnostic — it is useful for looking at what the embedder ended up doing — but it is **not a pass/fail criterion**. Since summed projections are linearly equivalent to a projection of the concatenation, there is no "discovery step" to hold the embedder to. The actual test of whether extra channels contribute is the target-only ablation below.

**Regime-conditional evaluation.** Tag each held-out bar with a coarse regime label using VIX terciles computed on the training window. Report every metric — NLL, top-1 accuracy, ECE, directional accuracy, Sharpe, hit rate, capacity — per regime. This is required disclosure, not a gate.

**Baselines — the ladder.** Six required baselines on identical data, splits, seeds, and tokens. Each isolates a distinct source of predictive power:

- **Linear head** applies `nn.Linear(context_len * d_model, vocab_size)` to flattened market-state vectors. Tests **basic feature information** — how much a single-layer readout of the fused market state can already predict.
- **Small MLP** puts three GELU hidden layers (128 → 64 → 32) on the last-position market-state vector. Tests **same-state nonlinearity** — whether a nonlinear read of one bar's fused state adds anything past linear.
- **GRU baseline** — 1 hidden layer, 128 units, causal — runs on the same fused market-state token stream. Roughly 1M parameters. Tests **basic temporal modeling** — whether any recurrence over the token sequence captures most of the temporal information a transformer would find. A 1D TCN with causal dilated convolutions is an equivalent substitute at the same parameter budget; the config picks one.
- **Transformer** is the model from §8 at the winning sweep point. Tests whether **attention adds anything beyond the GRU's temporal modeling**.
- **Target-only transformer** runs the same transformer with market, macro, options, and event channels zeroed at the embedder. Tests whether **extra channels contribute** — the specific test of the multimodal claim.
- **Magnitude-weighted transformer** runs the full model with `alpha = 1.0` on the loss weight. Tests **loss-shape alignment** — whether prediction quality on the tail moves that pay the strategy is being sacrificed to prediction quality on the fat middle.

Each baseline is a separate run under the same config skeleton with only model, channel-list, or loss overridden.

```python
class GRUBaseline(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        self.embed  = MarketStateEmbedder(cfg.channel_dims, cfg.d_model)
        self.gru    = nn.GRU(input_size=cfg.d_model, hidden_size=128,
                             num_layers=1, batch_first=True)
        self.norm_f = nn.LayerNorm(128)
        self.head   = nn.Linear(128, cfg.vocab_size, bias=False)

    def forward(self, feats: dict[str, Tensor]) -> Tensor:
        x = self.embed(feats)                       # [B, L, d_model]
        h, _ = self.gru(x)                          # [B, L, 128], causal by construction
        return self.head(self.norm_f(h))            # [B, L, vocab_size]
```

**Architecture and target ablations — required v1.** Four additional runs beyond the baseline ladder, all at the winning configuration from the size and context sweeps, changing exactly one axis each.

*Channel-aware fusion.* Compare linear fusion (default) against a one-block cross-channel attention mixer. The mixer produces one embedding per channel per timestep from the same `W_c` projections, runs one causal-attention block with `d_model = 64–128` and 1 layer across the `n_channels` embeddings at each timestep, then reduces to a single `state_t` (either the target channel's output or a pooled output) which feeds into the same temporal transformer. Parameter counts are matched to linear fusion by adjusting the mixer's hidden width. The linear-fusion default asserts that within-timestep channel interactions are adequately captured by a single linear projection. That is a strong assumption. A one-block mixer gives the model a route to compute nonlinear channel interactions before the temporal transformer sees the state. If linear fusion wins, the assertion holds. If the mixer wins, nonlinear channel interactions matter and v2 should use them. Both numbers get reported.

```python
class ChannelMixerEmbedder(nn.Module):
    def __init__(self, channel_dims: dict[str, int], d_model: int,
                 mixer_dim: int = 96, n_heads: int = 2):
        super().__init__()
        self.projections = nn.ModuleDict({
            name: nn.Linear(dim, mixer_dim) for name, dim in channel_dims.items()
        })
        self.channel_order = list(channel_dims.keys())
        self.attn = nn.MultiheadAttention(mixer_dim, n_heads, batch_first=True)
        self.out  = nn.Linear(mixer_dim, d_model)

    def forward(self, feats: dict[str, Tensor]) -> Tensor:
        # Per-channel projection: list of [B, T, mixer_dim]
        per_ch = [self.projections[name](feats[name]) for name in self.channel_order]
        # Stack along a new "channel" axis: [B, T, n_channels, mixer_dim]
        stacked = torch.stack(per_ch, dim=2)
        B, T, C, D = stacked.shape
        # One attention pass across channels at each timestep
        x = stacked.reshape(B * T, C, D)                # [(B*T), C, D]
        mixed, _ = self.attn(x, x, x, need_weights=False)
        mixed = mixed.reshape(B, T, C, D)
        # Reduce to one state per timestep — mean pool across channels
        state = mixed.mean(dim=2)                       # [B, T, mixer_dim]
        return self.out(state)                          # [B, T, d_model]
```

*Patching.* At the winning size × context configuration, compare `patch_size = 1` (default) against `patch_size = 4`. A patch of size 4 concatenates the four consecutive bars ending at position `t` into a single feature vector of length `Σ_c 4 · F_c`, projects the concatenation into one `d_model` state via a per-channel `nn.Linear(4 · F_c, d_model)` (or equivalent), and reduces sequence length by 4×. The target aligned with the resulting position is the bucket for the bar immediately following the last of the four packed bars. Aggregating four bars into one token trades sub-hour timing resolution for smoothing of microstructure noise. Which wins is data-dependent. One comparison settles it; a full sweep is unnecessary at v1.

*Output-head form.* At the winning size × context × patch configuration, compare the categorical 32-bucket head (default) against a quantile head with nine quantiles (0.1, 0.2, ..., 0.9) trained with pinball loss. Backbone identical. The two heads impose different inductive biases. The categorical head assumes discrete modes and treats bucket boundaries as hard decision points, with cross-entropy giving equal loss to all misclassifications regardless of magnitude. The quantile head assumes a smooth continuous distribution and its pinball loss respects magnitude directly. One of the project's central bets is that the discrete vocabulary is the better target for a trading system that consumes the whole distribution; that bet deserves a test. The categorical head is the primary v1 model because it is the hypothesis under test.

*Bucket count.* At the winning size × context × patch × categorical configuration, run three points: 16, 32, and 64 buckets. Report validation NLL, top-1, RPS, and simulator Sharpe for each. This is the ablation §7.1 promised.

Every ablation appears in the logbook with a distinct run_id and the axis it varied called out explicitly.

---

## 11. Simulator

A bar-by-bar walker over the test range. No vectorization tricks that risk peeking. Signature:

```python
def simulate(model, tokenized_test: dict, buckets: ReturnBucketizer,
             cost_cfg: CostConfig, policy_cfg: PolicyConfig) -> SimResult: ...
```

At each bar `t` the walker assembles the state vector from features at times `≤ t`, runs a forward on the trailing `context_len` window, reads `logits[:, -1, :]` at the last position, softmaxes to `p[t] ∈ ℝ^V` (where `V` is the trained bucket count), then derives `expected_vn_return = sum(p * bucket_train_mean)`, `expected_return = expected_vn_return * realized_vol_30_t`, `p_up = p[bucket_train_mean > 0].sum()`, and `sharpness = 1 - entropy(p) / log(V)`.

### 11.1 Cost model — spread calibration

Cost at intended size is `spread_cost = 0.5 * calibrated_spread_t`. The Corwin-Schultz proxy is retained as the initial estimate; it must be calibrated against measured BBO data before the held-out test opens.

Procedure, run by `scripts/calibrate_spread.py`:

1. Pull BBO snapshots at 15-minute intervals for a 30-day window inside the training range.
2. Compute the true half-spread per bar as `(ask - bid) / 2 / mid`.
3. Regress the Corwin-Schultz estimate against the truth.
4. Either replace the estimate with the regression line, or scale the raw value by the coefficient if the intercept is within one standard error of zero.
5. Save the fit as `artifacts/cost_calibration/spread_scaler.json`.

A missing calibration file is a hard failure, not a fallback to raw Corwin-Schultz.

### 11.2 Cost model — slippage coefficient (kappa)

Slippage is `kappa * size`, linear in position size. Kappa is a measurement, not a starting value: OLS `abs(observed_return) ~ kappa * size_proxy` on the training window with heteroskedasticity-robust standard errors. Report point estimate, standard error, 95% CI, R², N. Save to `artifacts/cost_calibration/kappa.json`. The held-out Sharpe report includes a sensitivity plot at 0.5×, 0.75×, 1.0×, 1.25×, 1.5×, and 2.0× the point estimate. If Sharpe crosses zero anywhere in `[0.5×, 2×]`, the reported number is not a robust claim.

At $1M single-position size on SPY, impact is expected to be immaterial except in the fastest bars. Linear-in-size slippage is the right functional form at that scale.

### 11.3 Risk penalty

`risk_penalty = lambda_risk * variance(p)` where variance is taken over `bucket_train_mean` weighted by `p`. `lambda_risk` is declared in the Pydantic schema:

```python
class SimulationConfig(BaseModel):
    lambda_risk: float = 1.0         # risk_penalty scale
    threshold: float = 0.0002        # edge threshold in vol-normalized units
    hysteresis: float = 0.5          # times threshold, for direction flip
    max_size: float = 1.0            # in units of "$1M target"
```

A run without an explicit `lambda_risk` in its resolved config fails registration.

### 11.4 Decision rule

`edge = expected_return - (spread_cost + slippage) - risk_penalty`. Long if `edge > threshold`, short if `edge < -threshold`, else flat. `size = clip(edge / uncertainty_scale, -max_size, +max_size)` with `uncertainty_scale ∝ sqrt(variance(p))`.

**Overlapping signals.** The simulator holds a single position at a time. Same-direction re-entries are dropped. Opposite-direction signals require `|edge| > threshold + hysteresis * threshold` to flip. Entries and exits print at the **next bar's open**.

### 11.5 Metrics with confidence

Reported metrics: cumulative return, mean and std of daily returns, annualized Sharpe, hit rate, max drawdown, time-to-recovery, per-trade P&L histogram with tail metrics, and a capacity sweep.

Sharpe is reported with its standard error. Every Sharpe number appears as `Sharpe ± SE`. A block bootstrap over 18 non-overlapping monthly blocks of the holdout resamples 10,000 times and reports the mean, the 5th and 95th percentiles, and the fraction of blocks with positive Sharpe.

---

## 12. Configs

Hydra 1.3+ composes YAML config groups. It beats plain YAML + Pydantic because config groups let you swap one axis at a time (`model=md`, `training=fast`, `target=spy`) without an exponential set of full configs.

```yaml
# configs/experiments/mvp_15m.yaml
defaults:
  - target: spy
  - data: standard_15m
  - features: standard
  - tokenizer: buckets_32
  - model: transformer_md          # winner of the size sweep
  - training: single_a10
  - simulation: default_costs
  - _self_

run_id: ${now:%Y%m%d_%H%M%S}_${hydra.job.name}
seed: 1337
notes: "MVP baseline. Full-channel."
```

The `target:` axis is what makes the "no hardcoded SPY" invariant enforceable in practice: `configs/target/spy.yaml` names the symbol, and swapping to `qqq` is a config change.

Each run writes its resolved config to `artifacts/{run_id}/config.yaml`. Reproducing a run: `python scripts/train.py --config-path artifacts/{run_id} --config-name config`.

---

## 13. Experiment tracking

W&B project `price-space-llm`. Each run logs the resolved config as metadata, `git rev-parse HEAD`, the dirty flag, the SHA256 of the tokenized dataset, the SHA256 of `channel_coverage.json`, per-step scalars, per-eval metrics from §10, and predicted-distribution bar charts on fixed diagnostic bars.

`experiments/logbook.csv` is append-only, one row per run:

```
date,run_id,branch,git_sha,notes,target,model_size,context_len,patch_size,
head_type,n_buckets,train_loss,val_nll,val_ece,val_brier,val_rps,val_dir_acc,
held_out_sharpe,held_out_sharpe_se,lambda_risk,alpha_mag_weight,touched_test
```

`scripts/register_run.py` writes the row from W&B run metadata at the end of training.

**Structural enforcement of the 3-look budget.** `scripts/check_test_look.sh` is a pre-commit hook. It fails any commit whose changed config files contain dates on or after `2024-01-01` unless the commit message includes the literal token `[test-look]`. Every `[test-look]` commit is appended to `experiments/test_looks.log`. The budget is three lines in that file for the whole MVP.

---

## 14. Infrastructure

Compute is a single GPU rented on Lambda Labs: A10 (24 GB) at ~$0.75/hr for iteration and the smaller sweep points, A100 40 GB at ~$1.30/hr for the full runs. The budget envelope is ~$500 of compute. The model-size sweep, context-length sweep, channel-mixer / patching / head-form / bucket-count ablations, and all baselines fit inside this budget because the small configurations train quickly and the largest one only runs once. All-position causal training gives `L`× the supervision per forward pass, which shortens the number of steps needed for the loss to plateau and helps offset the cost of the added ablations.

Storage sits on local NVMe, ~30 GB total: raw Parquet, aligned datasets, tokenized tensors, and artifact bundles.

The instance runs Ubuntu 22.04 with Python 3.11 and PyTorch 2.4+ on CUDA 12.x. `uv sync` manages dependencies from `pyproject.toml`.

Raw Parquet is mirrored to an S3 or GCS bucket as a resumability backup. Nothing in the runtime path depends on the mirror existing.

---

## 15. Interfaces

Every module boundary is narrow, typed, and stable.

| Boundary | Interface | Contract |
|---|---|---|
| Vendor MCP → Ingestion | `IngestionClient.call(tool, **params) -> pd.DataFrame` | UTC timestamps, vendor-native columns, cache-first |
| Ingestion → Alignment | `fetch(symbol, start, end, freq) -> pd.DataFrame` | Rows carry `value_time`, `released_at`, `known_at`, optional `revision_id`; `symbol` is a parameter |
| Alignment → Features | wide `pd.DataFrame` on 15-min UTC grid with `missing_mask_*`, `age_since_known_at_*`, `observed_at_this_grid_step_*` columns | Row for every RTH bar; target never missing; as-of joined on `known_at` |
| Features → Tokenizer | same DataFrame shape, causally normalized with the frozen scaler | All columns finite; normalizer state written to `artifacts/` |
| Tokenizer → Downstream | `artifacts/tokenizer/bucket_stats.json` | Frozen dequantizer; read by evaluator, simulator, notebooks |
| Tokenizer → Training | `Dataset` yielding `(feats: dict[str, Tensor[L, F_c]], targets: LongTensor[L], mask: BoolTensor[L])` | Fixed context length; embargo enforced in the mask |
| Training → Artifacts | `artifacts/{run_id}/` with `checkpoint.pt`, `config.yaml`, `normalizers.pt` | Self-contained; loadable without training repo state |
| Calibration → Simulator | `artifacts/cost_calibration/{spread_scaler,kappa}.json` | Required at simulator startup; missing = hard fail |
| Model → Simulator | `predict(state_sequence) -> Tensor[V]` returning `logits[:, -1, :]` softmaxed | Pure function; no side effects |
| Simulator → Evaluation | `SimResult` dataclass: trade ledger, equity curve, per-bar decisions, per-regime metrics | JSON-serializable for the logbook |

Every function that crosses a boundary has type hints and a docstring stating the contract. `Protocol` types live in `src/utils/interfaces.py`.

---

## 16. Tests

Unit tests target the modules where a subtle bug destroys the entire result.

For the tokenizer: `decode(encode(x))` maps `x` to its bucket's `bucket_train_mean` from `bucket_stats.json`; boundaries are monotone; the output range is `[0, V)`, exclusive of `V`. On a standard Gaussian sample with `V = 32`, buckets 0 and 31 each hold ~0.5% mass.

For the `known_at` schema: a test injects a revisable macro series with three revisions of the same `value_time`. It asserts the as-of join at a grid `t` between the second and third revisions returns the value from revision two, never revision three, and that a later join returns revision three. The shuffle-based causal-normalization test remains and runs on every commit.

For the staleness fields: a test with a synthetic macro series that observes at bars 0, 100, and 250 asserts `observed_at_this_grid_step` is True only at those three bars and `age_since_known_at` counts up monotonically between them, resetting to zero on observation.

Alignment tests inject known gaps into a synthetic multi-channel input and assert `missing_mask_*` columns match ground truth. Every timestamp in the aligned table must be UTC and monotone increasing at 15-minute spacing.

**One-source-of-truth channel test.** `test_channel_source_of_truth.py` reads a random 1,000-bar window from the aligned Parquet, recomputes each per-channel raw value from `data/raw/` sources, and asserts byte-identical match. Runs on the pre-commit hook on staged paths matching `src/features/*` or `src/ingestion/*`.

**No-hardcoded-target test.** `test_no_hardcoded_target.py` greps `src/` for the literal string `SPY` (case-sensitive, word-boundary) and fails on any hit outside a comment or docstring. This is what makes invariant #7 mechanical.

For the model, forward-pass shapes: with `d_model=64`, `context=16`, `batch=4`, `vocab_size=32`, output logits are `[4, 16, 32]`. The causal-mask test perturbs the value at position `t+k` for any `k > 0` and asserts the output at position `t` is bitwise unchanged.

For the training loop: a test asserts that switching from all-position CE to last-position-only CE on the same batch produces a strictly larger reduction-per-position on the last position and no gradient signal on earlier ones — a direct check that the loop is doing what §9 says.

Simulator tests confirm a zero-alpha strategy books exactly zero P&L before costs and `-2 * spread_cost` per round-trip after. The no-lookahead test shuffles bars after the decision index and asserts the equity curve up to that index is unchanged.

Integration lives at `tests/integration/test_end_to_end.py`. It runs the full pipeline on a synthetic 3-month slice under `configs/experiments/smoke.yaml` and asserts val NLL decreases from initial. Runs in under 5 minutes on CPU.

---

## 17. Stack

| Layer | Choice | Reason |
|---|---|---|
| Language | Python 3.11 | Pattern matching, faster startup |
| Deep learning | PyTorch 2.4+ | `torch.compile`, SDPA/FlashAttention |
| DataFrames | Polars 1.x | 5–20× pandas on Parquet joins; `join_asof` on `known_at` runs in ~1s |
| Parquet I/O | pyarrow | Native to Polars |
| Config | Hydra + Pydantic v2 | Composable YAML plus typed validation |
| Tracking | Weights & Biases | Free tier suffices |
| Testing | pytest | Parametrize-heavy for tokenizer, normalizer, `known_at`, staleness tests |
| Dependency mgmt | uv | Fast resolves, lockfile-first |
| Compute | Lambda Labs A10/A100 | Cheapest hourly for the GPU class |
| Storage | Local NVMe + S3/GCS mirror | Fast local, cheap cold backup |
| Plotting | matplotlib + W&B charts | matplotlib for saved figures, W&B for live |
| Numerics | numpy 2.x | Pre-tensor arithmetic |
| Stats | statsmodels | Robust SE on kappa; block bootstrap on Sharpe |

Polars' `join_asof` is what makes the `known_at` schema tractable at scale — it is the primitive the alignment layer is built around.

Workflow: `uv sync` → `python scripts/probe_channels.py` → edit → `pytest tests/` → `python scripts/calibrate_spread.py` → `python scripts/calibrate_kappa.py` → sweep sizes → sweep context lengths → run the four architecture and target ablations (channel mixer, patch=4, quantile head, bucket count) → `python scripts/train.py experiments=mvp_15m` → `python scripts/evaluate.py run_id=<...>` → `python scripts/simulate.py run_id=<...>` → `python scripts/register_run.py run_id=<...>`.

---

## 18. Beyond v1 — and where the architecture ends

Two of the natural extensions fit inside the current module boundaries. One does not.

**Multi-instrument (v2).** Makes the channel schema hierarchical: `target[instrument].{feature}`, with an instrument-id embedding added to the market-state vector at the state level (not inside the per-channel sum, where it would be a constant). The dataset yields `(instrument_id, feats, target)` triples; the loss is masked to the instrument's active bars. Because the target instrument is already a runtime parameter (invariant #7), this is a config and schema change, not a rewrite.

**RL trading policy.** Adds a policy net downstream of the distribution head, trained with a differentiable proxy for after-cost P&L or PPO against the simulator. Transformer weights either freeze or fine-tune. The `SimResult` ledger is already differentiable-friendly.

**LOB tokens — a different architectural regime.** Adding a level-2 order-book channel is not "just another channel at a longer context." The arithmetic makes the boundary clear. Context 512 at 100 ms is 51.2 seconds; a full trading day at 100 ms is roughly **234,000 timestamps**. The v1 transformer, built around causal SDPA over a sequence of per-bar state vectors, cannot ingest 234,000-step sequences directly. Attention is O(N²) in sequence length, memory is linear in it, and even with FlashAttention-2 the constant on 234k tokens across an eight-layer decoder is a different machine.

Something has to compress the millisecond stream before the current transformer can consume it. The options are known and none of them are free:

- **Hierarchical temporal aggregation.** A separate encoder over LOB events emits a per-second or per-100ms summary; the main transformer attends over those summaries. This is the closest fit to v1's module boundary because the outer transformer is unchanged.
- **Local attention or sparse attention.** Windowed, strided, or long-range patterns cap the O(N²) cost. This changes the attention primitive inside the transformer.
- **State-space or recurrent compression.** A structured state-space model or a stacked GRU compresses the LOB stream into a fixed-size state carried across time.
- **Multi-rate tokenization.** Two token streams at different rates (15-min market state and 100-ms LOB), fused at the attention layer with rate-aware positional encoding.
- **Event-based sampling.** Emit an LOB token only on order-book events rather than on a fixed 100-ms grid; irregular time deltas become a feature.
- **Separate high-frequency encoder.** A dedicated LOB model trained independently emits a small embedding per 15-min bar; the v1 transformer treats that embedding as another channel.

None of these is "add a channel and lengthen the context." Every one of them changes what "the model" is. The honest position is that LOB is a legitimate future project that crosses an architectural boundary — a new module has to be inserted, at minimum, between features and the temporal transformer.

The v1 module boundaries stay clean specifically to make that insertion tractable later. The tokenizer's output — one `d_model` vector per bar — is a clean seam. A hierarchical LOB encoder that emits one `d_model` vector per 15-min bar could plug into that seam without touching the transformer, the training loop, or the simulator. Building v1 well is what buys the option to build LOB later. What v1 does not do is pretend that option is a config change.

**On prior work.** In the literature surveyed through August 2026, we have not found a published system combining this exact input schema, causal 15-minute state representation, volatility-normalized categorical target, and cost-aware evaluation setup. That is not a claim that no such system exists — it is a claim about what a survey of the public record turned up. The design in this document does not rest on being first; it rests on the arguments above being right.

Each of the three extensions above respects — or explicitly identifies where it does not respect — the existing module boundaries. That is the payoff of §2 and §15.
