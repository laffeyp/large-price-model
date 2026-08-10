# Price-Space LLM — Product Specification

**Version:** v3 (15-minute bars, feasibility-review fixes incorporated)

## What this is

A causal decoder transformer that reads market history as a token sequence and predicts what the market does next. Same architectural family as GPT. Different vocabulary. Different prompt. Different target.

The vocabulary is not English. Each input token is a compressed *market state* at one moment in time: the target instrument's recent behavior at a 15-minute bar boundary, what correlated markets are doing on the same clock, current liquidity and spread, the most recent macro release, time-of-day and event context. At every timestep, each channel is projected by its own `nn.Linear` head into a shared 512-dim space and the projections are summed with a learned channel-type embedding. That sum is one 512-dim market-state vector per bar. The transformer then reads the sequence of those vectors and attends across time.

The model does not attend *across channels within a bar*. Channels are fused into a single vector before the transformer sees them; the attention layers see a stream of already-fused states. This is multimodal linear fusion followed by temporal attention. Cross-modal attention — letting the target token attend to the VIX token attend to the CPI token within one timestep — is a legitimate v3+ architecture, not a v1 property. Every sentence below reflects that boundary.

The output is a probability distribution over 32 buckets covering the volatility-normalized 15-minute forward return, large-down to large-up. A cost-aware decision layer converts the distribution into a trade — long, short, or flat — sized by expected edge and the distribution's sharpness. The model produces the distribution. The decision layer commits capital.

Nothing published does this exact combination. Kronos tokenizes only OHLCV bars from one instrument and predicts candle reconstruction. MarketGPT tokenizes only order-book messages and generates simulated flows. The DeepLOB line supervises 3-class direction on order-book snapshots. Chronos quantizes raw scalars. This project fuses the joint state — target, correlated markets, liquidity, macro, event — into per-bar tokens and predicts a target aligned with what a trader actually cares about: edge measured in units of risk.

## Why this design

Three specific bets stacked on top of each other. Every one of them is a bet, not a claim.

First bet: fusing multi-modal channels into a per-bar market-state vector and then attending temporally over that stream does more than attending temporally over a single-channel stream. If the next 15-minute move of the target depends on what VIX did in the last hour, what oil did overnight, whether CPI dropped this morning, and where we are in the trading session — all at once — a temporal attention model that sees those channels fused into every input vector is doing something a bar-only model can't. The attention is temporal, not cross-modal. What is being tested is whether the fused representation is a richer per-position signal than the target-only representation.

Second bet: volatility-normalized return buckets are a better prediction target than raw returns or candle reconstruction. A one-sigma move in a calm market and a one-sigma move in a volatile one land in the same token. The vocabulary stays meaningful across regimes. The output is already denominated in the units the trading decision needs, so the decision layer inherits calibration from the loss.

Third bet: a cost-aware decision layer that consumes the full predicted distribution — not just a point forecast — produces trades that survive real-world costs. Existing work either skips the trading layer (Kronos, MarketGPT) or trains it separately from the predictor. Coupling them, even without RL, aligns the prediction with the decision.

The summation embedder is mathematically equivalent to concatenating the per-channel feature vectors and applying one linear projection: `W₁x₁ + W₂x₂ = [W₁ W₂][x₁; x₂]`. It is not asking gradient descent to discover any special structure. The real question is whether the extra channels carry information at all — a question the target-only ablation answers directly.

None of the three bets is exotic on its own. The combination has not been built.

## v1 — the first build

One asset. One horizon. All channels. Full pipeline.

**Target instrument.** The v1 default configuration binds `target_instrument = SPY` at 15-minute bars. The name `SPY` appears only in default configs and test data. No class, module, path, or feature definition hardcodes it. Every stage — ingestion, alignment, features, tokenizer, model, simulator, evaluation — accepts `target_instrument` as a runtime parameter. This is what makes v2 a config change rather than a rewrite.

**Training range.** 2015-01-01 through 2022-12-31 for training. 2023 for validation. 2024-01-01 through 2025-06-30 held out for the final test. The held-out period is opened exactly once, at the end. A filesystem guard on `data/aligned/*.parquet` refuses reads that overlap the held-out range unless a `--i-know-this-is-a-test-look` flag is passed; every use of the flag appends a wall-clock timestamped line to `experiments/test-looks.log`, which no code path rewrites.

**Why 15-minute.** The multi-channel claim needs per-bar variation in the extra channels. At 1-minute bars, the extra channels barely move between adjacent bars — cross-asset context drifts too slowly, the macro channels are constant for hours, and the problem collapses into microstructure territory, which is the wrong regime for this hypothesis. At daily bars, there are only ~2,500 target-instrument observations over ten years, too few for a large transformer to fit without severe regularization, and the fused token loses most of its intraday event conditioning. 15-minute is where the tradeoff pays: cross-asset context drifts meaningfully per bar, the ratio of event-adjacent bars to flat bars is high enough that the event/macro channels earn their token, and — crucially for cost honesty — the expected move per bar is roughly 3x larger than at 5-minute, so half-spread plus slippage becomes a much smaller fraction of the edge the model is claiming. The default target at 15-min over ten years gives roughly 65,000 bars (~26 bars per trading day × 252 × 10), enough to train, hold out 18 months, and expect 200–500 trades on the holdout depending on decision-rule selectivity.

**Data time semantics — the primary leakage defense.** Every raw observation carries four timestamps: `value_time` (the period the value describes), `released_at` (the first wall-clock instant the value became available anywhere), `known_at` (the first instant the pipeline may legally consume it, which folds in vendor delay), and an optional `revision_id` for series that are restated. Every feature join is an as-of join constrained by `known_at`. This is the primary abstraction that prevents look-ahead across the macro, event, options, and future news channels. A CPI print released 2023-05-10 08:30 ET describing April 2023 has `value_time = 2023-04-30`, `released_at = 2023-05-10 12:30 UTC`, and (with a five-minute vendor lag) `known_at = 2023-05-10 12:35 UTC`; no 15-min bar closing before 12:35 UTC may see it. The as-of join enforces that mechanically. The row-shuffle causal unit test that appeared in v2 remains, but it is now the *secondary* defense — a paranoid check that the as-of joins were built right — not the primary claim.

**Phase 0 data-availability probe.** Before any feature or model code lands, `scripts/probe_channels.py` retrieves each requested channel at 2015, 2018, 2020, 2022, and 2025 sample dates and writes `data/manifests/channel_coverage.json`. Each entry records `source`, `symbol`, `requested_frequency`, `actual_frequency`, `earliest_timestamp`, `latest_timestamp`, `missing_fraction`, `timezone`, `timestamp_semantics` (does the timestamp mean the bar's open, its close, or its release?), and `revision_behavior` (does the vendor overwrite historical values on restate?). If any required channel fails coverage — history too short, frequency wrong, timestamp semantics ambiguous, or missing fraction above threshold — that channel is dropped from v1 or the schedule is renegotiated. This is a hard prerequisite. No feature pipeline runs against a channel that has not been probed.

**Channels tokenized at every 15-minute timestep.**

Target: the configured target instrument's open, high, low, close, volume, log return, 30-bar realized volatility (~7.5 trading hours of history), spread proxy from bar range calibrated against measured BBO data.

Cross-asset context: QQQ, IWM, VIX, TLT, DXY, GLD, USO — each contributes log return and rolling volume z-score on the same 15-minute grid.

Macro: CPI year-over-year, Fed funds rate, 10-year Treasury yield, unemployment rate, nonfarm payroll. Values held constant intra-day between releases, joined by `known_at`. Countdown-to-next-release feature per series, measured in 15-minute bars.

Options: put/call ratio, options volume — daily, held constant intra-day, joined by `known_at`.

Event: earnings-calendar density for the target instrument's constituents, FOMC dates, CPI release dates, options expiry. Encoded as countdown-to-next and time-since-last, in bars.

Time and session: minute-of-day and day-of-week, sin/cos encoded. Every sample also carries an `is_overnight_gap` boolean flag: `True` when the target return is the return from the last regular-session bar of day N to the first regular-session bar of day N+1, `False` otherwise. Overnight-gap returns are a different data-generating process than intraday returns — the flag lets the model condition on which regime the current prediction sits in. Dropping the observation was the alternative; it was rejected because it discards 252 overnight examples per year that carry real information about how the market opens.

**Tokenization.** Each timestep's per-channel feature vector goes through its own `nn.Linear` projection to a 512-dim embedding, sums with a learned channel-type embedding, and produces one 512-dim market-state vector per bar. The prediction target for that bar is a bucket ID from a 32-bucket vocabulary numbered 0–31. Buckets are set by percentile boundaries on vol-normalized next-bar returns from the training window: buckets 0 and 31 catch outer tails, buckets 1–30 cover the 0.5th–99.5th percentile range uniformly by count. Zero-indexed throughout the codebase and the docs.

**Frozen bucket artifacts.** For all 32 buckets, `artifacts/tokenizer/bucket_stats.json` persists `bucket_lower`, `bucket_upper`, `bucket_train_mean`, `bucket_train_median`, and `bucket_frequency`. Values are computed on the training partition only and frozen before any validation or test bar is scored. The outer buckets (0 and 31) have no finite bound on one side — `bucket_lower[0] = -inf`, `bucket_upper[31] = +inf` — so downstream code that needs a numeric expected return per bucket reads `bucket_train_mean`, not a midpoint that does not exist. Every downstream computation that converts a bucket ID to a return magnitude — the decision layer's `E[return]`, the magnitude-weighted loss, the capacity sweep — reads from this file. There is no other source.

**Model.** Model size is an experiment, not a constant. The v1 sweep runs 1M, 3M, 10M, and 30M parameter configurations as required baselines, all with `d_model = 512` and RoPE positional embeddings, varying `n_layers` and `d_ff` to hit each parameter target. The default v1 checkpoint is whatever the sweep settles on. With ~65,000 training bars and heavily overlapping context windows, the expectation is that 3M–10M lands on the flat part of the curve; 30M is probably over-parameterized for the effective sample size and 1M is probably under. Reporting the curve is required, not optional. Every published headline number cites its parameter count.

Context length is likewise an experiment. The v1 sweep runs 64, 128, 256, and 512 bars as required ablations. At 15-min bars with ~26 bars per trading day, 512 bars covers ~19.7 trading days — roughly four trading weeks. (An earlier draft called this 2.5 trading weeks; that was arithmetic error, corrected here.) 64 bars is about 2.5 trading days; 128 bars is about a trading week. Reporting the context-length curve is required. The default checkpoint is whichever length wins on validation NLL.

The default block is causal, pre-LayerNorm, GELU, dropout 0.1, rotary positional embeddings, 8 attention heads. The output head is a linear projection to 32 logits. Loss is cross-entropy on next-bucket ID for the main run; magnitude-weighted cross-entropy is one of the required ablations (see below).

**Training.** Single A10 or A100 GPU. Mixed precision (bfloat16). AdamW, learning rate 3e-4 with cosine schedule and 1000-step warmup, weight decay 0.1, gradient clipping at 1.0. Batch size fills GPU memory (typically 64–128 sequences at the chosen context length). W&B logs training loss and validation NLL, ECE, Brier, ranked probability score, and top-3 accuracy every 100 steps.

Checkpoints are selected by **validation NLL**, not ECE. ECE, Brier, and RPS are logged and reported per epoch but are not the selection criterion. The reason is simple: a model can lower ECE while losing information — a predictor that spreads probability more evenly across buckets looks better calibrated but carries less signal, and the decision layer is starved by the flatter distribution. NLL penalizes both miscalibration and information loss and is the objective the model is trained on; using it for checkpoint selection avoids the second-order failure where the selection metric fights the training loss.

**Baselines and ablations trained on identical data, splits, and seeds.**

- 1-layer linear model: same input tokens, direct softmax over 32 buckets. Tests whether depth is doing anything.
- 3-layer MLP: 128 → 64 → 32 hidden dims on the last-position market-state vector. Tests whether temporal modeling of any kind buys anything past shallow nonlinearity applied to a single bar.
- Small causal sequence model: a compact GRU (or 1D TCN), roughly 1M parameters. Tests whether attention specifically adds value beyond simple temporal modeling. This baseline sits between the MLP and the transformer for exactly that reason — without it, a transformer that beats an MLP could be winning on sequence modeling alone, not on attention.
- Target-only ablation: same architecture as the default transformer, every non-target channel zeroed at the embedder. Tests whether the multi-channel token pays off. The whole thesis rides on this comparison.
- Magnitude-weighted loss ablation: same architecture, same channels, cross-entropy weighted by `w_t = 1 + alpha * |bucket_train_mean(target_t)|` with `alpha` in the config. Tests whether prediction quality on large moves — which is what pays the trading strategy — is being sacrificed to prediction quality on the fat middle.

The baseline ladder is therefore: linear → MLP → GRU/TCN → transformer → target-only transformer → magnitude-weighted transformer. Each step tests one increment.

**Simulator.** Bar-by-bar walk over the held-out period. At each bar close, assemble the market-state token from data available up to that bar (all joins constrained by `known_at`), forward-pass the model, extract expected vol-normalized return and distribution sharpness. Fills happen at the *next* bar's open — the decision variable never touches the fill price. Decide: `edge = E[return] − half_spread − kappa * size − lambda * variance(p)`. Every parameter in that expression — `kappa`, `lambda`, the entry threshold — lives in `simulation.yaml`, not in code. If `edge > threshold`, take a position sized by `edge / distribution_std`. Positions are single-instrument and single-position; an entry signal that fires while a position is open is dropped. Track per-trade P&L, Sharpe, hit rate, max drawdown, and capacity — the largest position size at which Sharpe stays positive.

## v2 — multi-instrument

Same code. Same architecture. More assets and shared training.

Add QQQ, IWM, TLT, GLD, USO as trade targets alongside the v1 default. Each target's token stream uses the same channel schema — its own OHLCV as the "target" channel, everything else as context — swapped in via the same `target_instrument` runtime parameter that already exists in v1. Two candidate training schemes: one shared model across all targets with target ID as an embedded conditioning token, or per-target fine-tuning from a shared pretrain. Which one wins is settled empirically once v1 is done.

The compute delta is modest: 6× the tokens for 6× the assets, still fits on a single A100. The model doesn't get bigger. Only the data does.

v2 is the next commit after v1 works, not a separate initiative. Because v1 refuses to hardcode the target-instrument name anywhere except a default config, v2 is a config-graph change with no touch to `src/`.

## v3 and beyond

Each item is a bounded extension against v1's module boundaries — except one, called out explicitly.

**Alternative data.** Satellite imagery of oil storage, container-shipping rates, credit-card aggregate spend, web traffic for consumer names. Each becomes a new channel with its own ingestion path, its own `known_at` semantics, its own Phase 0 probe. Everything after that is unchanged.

**News and text.** A small encoder (BERT-scale) processes news headlines into an embedding; the embedding becomes a new channel indexed by its `released_at` timestamp and joined by `known_at`. Bloomberg or NewsAPI ingestion path.

**Cross-modal attention.** Let the transformer attend *across channels within a bar* as well as across bars — the actual multi-modal architecture. Each channel becomes its own per-timestep token; attention runs over the (channel × time) grid instead of the time axis alone. This is a distinct architectural choice from v1's fusion-then-temporal-attention design, tested only after v1 has produced a working baseline for comparison.

**RL policy layer.** Replace the fixed decision rule with a learned policy that takes the predicted distribution and outputs continuous position size. Trained with PPO against the simulator. Model producing the distribution stays frozen or fine-tuned jointly.

**Live paper trading.** Add an inference server that produces predictions on live data at bar close. Route to Alpaca or IBKR paper endpoint. No architectural change; adds a real-time data ingestion path and an order-management wrapper.

**LOB tokens — crosses an architectural boundary.** Level-2 order-book snapshots at 100ms resolution are legitimate as a future project, but they do not fit inside the v1 architecture by adding a channel and a longer context. 512 tokens at 100ms cadence is 51.2 seconds of coverage. Reaching a single trading day at 100ms takes roughly 234,000 timestamps. That is a different sequence-length regime and needs some combination of hierarchical temporal aggregation (100ms → 1s → 15s levels feeding a coarse encoder), local or sparse attention, state-space or recurrent compression, multi-rate tokenization (one stream at 15-min, another at 100ms, cross-attended), event-based sampling (tokens only on order-book state changes), or a separate high-frequency encoder whose output is fused into the 15-min stream. Any of those is a real architectural project, not "add a channel and stretch the context." LOB is on the roadmap; it will not be sold as architecture-preserving.

Each of the first five lands as a discrete extension. LOB requires design work before implementation.

## Success gates for v1

v1 succeeds if all of the following hold on the held-out test period (2024-01 through 2025-06). Every gate is pre-registered before the held-out set is opened.

- Training completes without NaN, divergence, or gradient explosion.
- The model-size sweep is reported as a curve — validation NLL, ECE, Brier, and RPS for each of 1M, 3M, 10M, and 30M parameters — before any single checkpoint is anointed as the v1 default. The default checkpoint is the model-size / context-length combination that wins on validation NLL.
- The context-length sweep is reported as a curve — same metrics, for 64, 128, 256, and 512 bars — under the winning model size.
- `artifacts/tokenizer/bucket_stats.json` is written, frozen on the training partition, and every downstream consumer that needs a bucket-to-return mapping reads from it. The file is a versioned artifact.
- Checkpoint selection uses validation NLL. ECE, Brier, and RPS appear in every run report but do not gate checkpoint selection.
- Validation NLL at least 10% lower than the 1-layer linear baseline on identical data.
- Validation NLL at least 5% lower than the GRU/TCN baseline on identical data. This is the specific test of whether attention adds value beyond simple temporal modeling.
- Validation NLL at least 5% lower than the target-only ablation on identical data. This is the specific test of whether the extra channels contribute. The summation embedder is mathematically equivalent to one linear projection of the concatenated feature vector, so the ablation — not any orthogonality diagnostic — is what settles the question.
- Validation ECE below 0.05.
- Held-out Sharpe reported with its standard error, where SE ≈ `sqrt((1 + 0.5·S²)/N)` at trade level, annualized by multiplying by `sqrt(bars_per_year / bars_per_trade)`. Minimum gate: `Sharpe − 1·SE > 0`. Stronger gate: `Sharpe > 0.5` with the point estimate and SE both reported.
- Block-bootstrap distribution of Sharpe across monthly blocks of the holdout, reported as a histogram. Gate: ≥70% of block-bootstrap Sharpes positive.
- Held-out capacity at least $1M — the largest single-position size at which Sharpe stays positive. The target instrument at $1M is expected to absorb the trade without measurable impact except in the fastest bars (open, close, event bars); state that and prove it with the sensitivity plot below.
- The simulator's spread proxy is calibrated against measured BBO data on the training window before the held-out set is opened. Uncalibrated Corwin-Schultz on an instrument with a near-zero spread is not acceptable. The slippage coefficient `kappa` is estimated by regression on the training window with a reported confidence interval, and the held-out Sharpe report includes a sensitivity plot showing Sharpe as `kappa` moves from 0.5x to 2x its point estimate.
- Every training run has its config, git SHA, data hash, and W&B URL logged in `experiments/logbook.csv`. Any run that touched the held-out test set is flagged. Test-set look budget: 3 for the full v1, enforced by the filesystem guard above.

**Reported, not gated.** Range of held-out Sharpe across 3 seeds. Below 3 seeds we cannot claim training-procedure stability, only observe the range.

**If NLL and ECE pass but Sharpe fails.** The model is doing its job — producing a calibrated, informative distribution — and the decision layer is where the failure lives. In that case, v1 is a partial success: the prediction pipeline validates and the decision layer needs a rethink. Options in order of cost: tune the entry threshold on the validation window, recalibrate the cost model against BBO data, promote the magnitude-weighted loss ablation to the main run if it outperformed on validation. Do not go back and reopen the held-out set.

Any other gate that fails is a specific thing to fix, not a verdict on the project.

## Regime evaluation

Aggregate metrics can hide regime failures. Required disclosure, not a gate.

Tag each held-out bar with a coarse VIX-regime label: terciles computed on the training window (2015–2022), producing low-VIX, mid-VIX, and high-VIX thresholds. Freeze the thresholds. Apply them unchanged to the 2023 validation window and the 2024–2025 holdout. Every held-out metric — NLL, ECE, directional accuracy, Sharpe, capacity, hit rate, block-bootstrap Sharpe distribution — is reported both aggregate and per regime.

If aggregate Sharpe is 0.5 while one regime contributes 2.0 and another contributes −0.5, the aggregate is a lie of averages. The honest answer is that the strategy works in one regime and does not work in the other, and that tells you what v2 has to fix. If per-regime Sharpes are all within noise of the aggregate, that is also a useful answer.

One diagnostic ships alongside: the realized bucket-frequency histogram on validation and on holdout, compared to training. If validation buckets 0 and 31 hold materially more or less than the training 0.5% each, that is direct evidence of tail-shape drift and the frozen bucket boundaries are less informative on the new regime. Note it. It affects how the ECE number is read.

## What v1 explicitly is not

Not HFT. 15-minute bars. Not tick data. Not order-book data.

Not reinforcement learning. Cross-entropy on next bucket, period. Decision rule is a fixed, config-parameterized function of the distribution.

Not text-conditioned. No news, no filings, no earnings-call transcripts.

Not real-time. Simulator only, running against historical data.

Not multi-instrument. One target instrument (default: SPY). But nothing in the codebase hardcodes that name — v2 is a config change.

Not cross-modal attention. The transformer attends over time. Channels are fused into per-timestep vectors before the transformer sees them.

Not multi-horizon. Next-bar prediction only.

Not a Kronos or MarketGPT re-implementation. Kronos tokenizes one OHLCV stream and predicts candles. MarketGPT tokenizes order messages and generates flows. This fuses joint multi-channel state at every timestep and predicts vol-normalized return buckets.

## Non-functional requirements and design invariants

**No hardcoded target instrument.** The v1 dataset schema, tokenizer, feature computation, config schema, and model must accept `target_instrument` as a runtime parameter. `SPY` appears only in default configs and test fixtures, never in class names, path components, or feature definitions. Any commit that introduces a `SPY`-specific symbol outside `configs/` or `tests/` fails review. This is what makes v2 an extension rather than a rewrite.

**As-of joins throughout.** Every feature join uses `known_at` as the temporal key. The rolling-window utilities refuse to read past the current row. The row-shuffle unit test remains as a paranoid check.

**Frozen tokenizer artifacts.** `artifacts/tokenizer/bucket_stats.json` is written once from the training partition and never overwritten. Any code path that computes a bucket-to-return mapping reads from it.

**Reproducible training.** Every run seeds `torch`, `numpy`, `random`, and CUDA, logs the config, git SHA, and data hash. Rerunning the same config reproduces metrics to within numerical noise.

## Dependencies

**Data.** Primary source is the financial-data MCP already available in the working environment. Relevant tools by channel:

| Channel | MCP tools |
| --- | --- |
| Target and cross-asset intraday | `TIME_SERIES_INTRADAY` (15-min interval) |
| DXY / FX | `FX_INTRADAY`, `CURRENCY_EXCHANGE_RATE` |
| Macro | `CPI`, `FEDERAL_FUNDS_RATE`, `TREASURY_YIELD`, `UNEMPLOYMENT`, `NONFARM_PAYROLL`, `INFLATION`, `RETAIL_SALES` |
| Options | `HISTORICAL_PUT_CALL_RATIO`, `HISTORICAL_VOLUME_OPEN_INTEREST_RATIO`, `HISTORICAL_OPTIONS` |
| Event | `EARNINGS_CALENDAR` |
| BBO calibration | Any free source producing target-instrument BBO snapshots on the 2015–2022 window |
| Commodities (v2+) | `WTI`, `BRENT`, `NATURAL_GAS`, `COPPER`, `GOLD_SILVER_HISTORY`, `WHEAT`, `CORN` |

Every channel above passes through Phase 0 probing before being wired into the feature pipeline. Every record carries `value_time`, `released_at`, `known_at`, and `revision_id`.

Fallback: Polygon.io for 15-minute equity bars if the MCP doesn't return the frequency or history needed.

**Compute.** One GPU. A10 (~$1/hr) or A100 (~$3/hr). Total v1 compute budget: $500. Covers the model-size sweep, the context-length sweep, all baselines including the GRU/TCN, the magnitude-weighted ablation, and 30–50 iteration cycles.

**Storage.** Local SSD, ~50GB for aligned Parquet + tokenized cache + all checkpoints.

**Software.** Python 3.11, PyTorch 2.x, Polars for DataFrames, PyArrow for Parquet, Hydra + Pydantic v2 for typed configs, Weights & Biases for tracking, pytest for tests, `uv` for dependency management.

## Risks and mitigations

Execution risks. Not "will markets cooperate" risks.

**Data leakage.** Any place future information touches training features silently inflates every metric. Fix: as-of joins on `known_at` throughout the feature pipeline, backed by the row-shuffle unit test as a secondary check. Purged embargo of `H` bars at every split boundary. Test set opened exactly once. Filesystem guard on held-out reads. Test-look log is append-only.

**Data availability turning out worse than assumed.** A channel that looks live in 2025 may not exist in 2015, may change timestamp semantics mid-window, or may revise history silently. Fix: the Phase 0 probe. Every channel writes a coverage manifest before any feature code runs. A channel that fails coverage is dropped or the schedule renegotiates.

**Simulator dishonesty at the cost model.** A backtest that assumes cheap fills produces a fantasy Sharpe. Fix: calibrate the Corwin-Schultz proxy against measured BBO data on the training window before the holdout is opened. Report the calibration coefficient and the residual after fit. `kappa` is estimated by regression with a 95% CI, and the results include a Sharpe-vs-`kappa` sensitivity plot from 0.5x to 2x.

**Extra channels adding no information.** If the target-only ablation is not beaten by the full model, the multi-channel bet has failed for the current combination of channels, target, and horizon. Fix: report the gap directly. Do not lean on any orthogonality claim about the embedder — the summation is equivalent to one linear projection of the concatenated features, so orthogonality was never the mechanism.

**Bucket-boundary shape drift.** Vol-normalization mitigates scale drift across regimes but not skew, kurtosis, or tail-mass shifts. Diagnostic: realized bucket-frequency histogram on validation and holdout, compared to training's target frequencies. Included in every run summary.

**Scope creep.** Building v2 features while v1 doesn't yet pass its gates. Fix: the v1 success gates are binary and pre-registered.

**Losing count of experiments.** Every hyperparameter sweep is implicit multiple-testing. Fix: `experiments/logbook.csv` gets one row per training run. Test-set look budget: 3.

**Metric-selection drift.** Selecting checkpoints on ECE while training on cross-entropy is a subtle way to lose information. Fix: checkpoint selection by validation NLL. ECE, Brier, and RPS are reported per run but not selection criteria.

**Expanding-window normalization staleness.** The training-window normalizer freezes to a stable mean; on 2024–2025 the frozen normalizer is doing more work than the model expects. Diagnostic: plot the normalized-feature distribution on the holdout against training. This is not a bug, it is a failure mode to watch for.

## Open questions

Each has a candidate answer; the choice gets made during v1 or as an ablation.

**Cosine-similarity of channel projections — exploratory only.** The end-of-training cosine-similarity matrix between per-channel mean projections is worth plotting because it is a cheap diagnostic on what the model actually did with the fused representation. It is not a gate and not a claim about the architecture. It is a diagnostic.

**Vol estimator for target definition.** Candidate: 30-bar trailing realized volatility. Alternates: EWMA, GARCH(1,1), implied volatility from ATM options. Pick one for v1; expose the others as config alternates.

**Channel combination inside the token.** Candidate: per-channel `nn.Linear` projection to 512-dim, then sum with a learned channel-type embedding. Alternate: concatenate per-channel projections. Sum is chosen because it holds `d_model` fixed as channels grow; the two are equivalent in expressive power for a linear embedder, but sum scales more cleanly to v2.

**Bucket boundaries.** Candidate: percentile-uniform on training-set vol-normalized returns, 32 buckets, outer 2 for tails. Alternate: learned via a VQ-VAE-style objective.

**Bar-close vs. bar-open target.** Candidate: predict the return from bar close(t) to bar close(t+1). Overnight-gap samples carry the `is_overnight_gap` flag. Ablation for v2: split overnight-gap and intraday returns into separate targets and predict each with its own head.

**Regime labels beyond VIX terciles.** VIX terciles are the coarse-and-obvious first cut. If v1 shows regime dependence on VIX, v2 fits a finer regime model.

## Glossary

**Causal transformer.** A neural network built from attention layers where each position can only attend to positions before it in the sequence. Same architecture as GPT.

**Token.** A single unit the model reads or predicts. In language models, a word-piece. Here, a fused market-state vector as input; a discrete bucket ID (0–31) as output.

**Multimodal linear fusion.** The v1 embedder projects each channel through its own linear head to a shared dimension and sums the projections, plus a channel-type embedding, into one per-timestep vector. Mathematically equivalent to concatenating the channels and applying one linear projection.

**Temporal attention.** Self-attention run over the sequence of already-fused per-timestep vectors. The transformer attends over time only; it does not attend across channels within a bar.

**Cross-modal attention.** A distinct architecture in which each (channel, time) pair is its own token and attention runs over the two-dimensional grid. Not in v1.

**Vol-normalized return.** The next-bar return divided by an estimate of current volatility (30-bar realized). Scale-invariant across regimes.

**Bucket / return bucket.** One of 32 discrete labels the model predicts, numbered 0 through 31. Each label covers a range of vol-normalized returns; buckets 0 and 31 catch outer tails.

**`known_at`.** The first wall-clock instant a value may legally enter the training pipeline. Distinct from `value_time` (the period the value describes) and `released_at` (the moment of first public availability). `known_at` folds in vendor delay and is the temporal key for every feature join.

**As-of join.** A join operator that pairs each left row at time `t` with the most recent right row satisfying `right.known_at ≤ t`. The primary defense against look-ahead across channels.

**`is_overnight_gap`.** A per-sample boolean flag: `True` on samples whose target is the close-to-open return spanning a session boundary, `False` otherwise. Lets the model condition on which regime the current prediction sits in.

**NLL (negative log-likelihood, cross-entropy).** The training objective and the checkpoint-selection criterion. Penalizes both miscalibration and information loss.

**ECE (expected calibration error).** How well predicted probabilities match observed frequencies. Reported per run; not the checkpoint-selection criterion.

**Brier score.** Mean squared error between predicted probability vectors and one-hot outcomes. Reported per run.

**RPS (ranked probability score).** A proper scoring rule for ordered categorical predictions that penalizes probability mass placed far from the realized bucket. Reported per run.

**Magnitude-weighted loss.** Cross-entropy weighted by `1 + alpha * |bucket_train_mean(target_t)|`. Reweights each training example so that predictions on large-magnitude buckets contribute proportionally more to the loss. Tests whether prediction quality on the moves that pay is being sacrificed to prediction quality on the fat middle.

**Purged embargo.** A gap of `H` bars left at every train/validation or train/test boundary, where `H` is the prediction horizon.

**Block bootstrap.** Resampling with replacement over contiguous monthly blocks rather than individual trades, preserving within-block autocorrelation.

**Capacity.** The largest position size at which the strategy's Sharpe stays positive.

**Cost-aware decision layer.** The function that turns the model's predicted distribution into a trade decision.

**Kappa (`kappa`).** The linear slippage coefficient in `edge = E[return] − half_spread − kappa * size − lambda * variance(p)`.

**Ablation.** A training run with one component removed or changed, to test whether that component was doing useful work. v1 ships five: linear, MLP, GRU/TCN, target-only, and magnitude-weighted loss.

**Regime label.** A discrete tag applied to each held-out bar (low-VIX / mid-VIX / high-VIX terciles from training). Every held-out metric is reported per label as well as in aggregate.
