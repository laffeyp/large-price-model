# Price-Space LLM — Product Specification

**Version:** v2 (15-minute bars, review fixes incorporated)

## What this is

A causal decoder transformer that reads market history as a token sequence and predicts what the market does next. Same architectural family as GPT. Different vocabulary. Different prompt. Different target.

The vocabulary is not English. Each token is a compressed *market state* at one moment in time: the target instrument's recent behavior at a 15-minute bar boundary, what correlated markets are doing on the same clock, current liquidity and spread, the most recent macro release, time-of-day and event context. All of that gets packed into one 512-dim vector per timestep. The model reads a sequence of these vectors and predicts the next *price-move token*: a volatility-normalized 15-minute forward return bucket, one of 32 discrete labels covering large-down to large-up.

Its output is a probability distribution over those 32 buckets. A cost-aware decision layer converts the distribution into a trade: long, short, or do nothing, sized by expected edge and the distribution's sharpness. The model produces the distribution. The decision layer commits capital.

Nothing published does this exact combination. Kronos tokenizes only OHLCV bars from one instrument and predicts candle reconstruction. MarketGPT tokenizes only order-book messages and generates simulated flows. The DeepLOB line supervises 3-class direction on order-book snapshots. Chronos quantizes raw scalars. This project tokenizes the joint state — target, correlated markets, liquidity, macro, event — and predicts a target aligned with what a trader actually cares about: edge measured in units of risk.

## Why this design

Three specific bets stacked on top of each other. Every one of them is a bet, not a claim.

First bet: attention across multi-modal market state does more than attention across one stream. If the next 15-minute move of SPY depends on what VIX did in the last hour, what oil did overnight, whether CPI dropped this morning, and where we are in the trading session — all at once — a model that gets those channels jointly is doing something a Kronos-style bar-only model can't.

Second bet: volatility-normalized return buckets are a better prediction target than raw returns or candle reconstruction. A one-sigma move in a calm market and a one-sigma move in a volatile one land in the same token. The vocabulary stays meaningful across regimes. The output is already denominated in the units the trading decision needs, so the decision layer inherits calibration from the loss.

Third bet: a cost-aware decision layer that consumes the full predicted distribution — not just a point forecast — produces trades that survive real-world costs. Existing work either skips the trading layer (Kronos, MarketGPT) or trains it separately from the predictor. Coupling them, even without RL, aligns the prediction with the decision.

The summation embedder assumes gradient descent will discover non-overlapping subspaces for each channel within the 512-dim market-state vector; if channels interfere, the target-only ablation may show no gap even when the extra channels carry real information. That is the assumption. It is a bet on optimization, not on markets.

None of the three bets is exotic on its own. The combination has not been built.

## v1 — the first build

One asset. One horizon. All channels. Full pipeline.

**Target instrument.** SPY at 15-minute bars.

**Training range.** 2015-01-01 through 2022-12-31 for training. 2023 for validation. 2024-01-01 through 2025-06-30 held out for the final test. The held-out period is opened exactly once, at the end. A filesystem guard on `data/aligned/*.parquet` refuses reads that overlap the held-out range unless a `--i-know-this-is-a-test-look` flag is passed; every use of the flag appends a wall-clock timestamped line to `experiments/test-looks.log`, which no code path rewrites.

**Why 15-minute.** The multi-modal claim needs per-bar variation in the extra channels. At 1-minute bars, the extra channels barely move between adjacent bars — cross-asset context drifts too slowly, the macro channels are constant for hours, and the problem collapses into microstructure territory, which is the wrong regime for this hypothesis. At daily bars, there are only ~2,500 SPY observations over ten years, too few for a 30M-parameter transformer to fit without severe regularization, and the multi-modal token loses most of its intraday event conditioning. 15-minute is where the tradeoff pays: cross-asset context drifts meaningfully per bar, the ratio of event-adjacent bars to flat bars is high enough that the event/macro channels earn their token, and — crucially for cost honesty — the expected move per bar is roughly 3x larger than at 5-minute, so half-spread plus slippage becomes a much smaller fraction of the edge the model is claiming. SPY at 15-min over ten years gives roughly 65,000 bars (~26 bars per trading day × 252 × 10), enough to train, hold out 18 months, and expect 200–500 trades on the holdout depending on decision-rule selectivity.

**Channels tokenized at every 15-minute timestep.**

Target: SPY open, high, low, close, volume, log return, 30-bar realized volatility (~7.5 trading hours of history), spread proxy from bar range calibrated against measured BBO data.

Cross-asset context: QQQ, IWM, VIX, TLT, DXY, GLD, USO — each contributes log return and rolling volume z-score on the same 15-minute grid.

Macro: CPI year-over-year, Fed funds rate, 10-year Treasury yield, unemployment rate, nonfarm payroll. Values held constant intra-day between releases. Countdown-to-next-release feature per series, measured in 15-minute bars.

Options: put/call ratio, options volume — daily, held constant intra-day.

Event: earnings-calendar density for SPY constituents, FOMC dates, CPI release dates, options expiry. Encoded as countdown-to-next and time-since-last, in bars.

Time: minute-of-day and day-of-week, sin/cos encoded.

**Tokenization.** Each timestep's per-channel feature vector goes through its own `nn.Linear` projection to a 512-dim embedding, sums with a learned channel-type embedding, and produces one 512-dim market-state vector per bar. The prediction target for that bar is a bucket ID from a 32-bucket vocabulary numbered 0–31. Buckets are set by percentile boundaries on vol-normalized next-bar returns from the training window: buckets 0 and 31 catch outer tails, buckets 1–30 cover the 0.5th–99.5th percentile range uniformly by count. Zero-indexed throughout the codebase and the docs.

**Model.** ~30M parameters. `d_model=512`, 8 transformer blocks, 8 attention heads per block, causal mask, rotary positional embeddings, pre-LayerNorm, GELU activation, dropout 0.1. Output head: linear projection to 32 logits. Loss: cross-entropy on next-bucket ID for the main run; magnitude-weighted cross-entropy for one of the required ablations (see below).

**Training.** Single A10 or A100 GPU. Mixed precision (bfloat16). AdamW, learning rate 3e-4 with cosine schedule and 1000-step warmup, weight decay 0.1, gradient clipping at 1.0. Batch size fills GPU memory (typically 64–128 sequences of length 512). Context length 512 bars covers about 2.5 trading weeks of 15-minute history per prediction — long enough for a Monday to condition a Friday, short enough to remain trainable on one GPU. W&B logs training loss, validation ECE, and top-3 accuracy every 100 steps; checkpoints are selected by validation ECE, not accuracy.

**Baselines and ablations trained on identical data, splits, and seeds.**

- 1-layer linear model: same input tokens, direct softmax over 32 buckets. Tests whether depth is doing anything.
- 3-layer MLP: 128 → 64 → 32 hidden dims, same input tokens. Tests whether attention buys anything past shallow nonlinearity.
- Target-only ablation: same 30M transformer, every non-target channel zeroed. Tests whether multi-modal tokenization pays off. The whole thesis rides on this comparison.
- Magnitude-weighted loss ablation: same 30M transformer, same channels, cross-entropy weighted by `w_t = 1 + alpha * |bucket_center(target_t)|` with `alpha` in the config. Tests whether prediction quality on large moves — which is what pays the trading strategy — is being sacrificed to prediction quality on the fat middle. This was floated as an open question in v1 of this spec; it is now a required v1 ablation.

**Simulator.** Bar-by-bar walk over the held-out period. At each bar close, assemble the market-state token from data available up to that bar, forward-pass the model, extract expected vol-normalized return and distribution sharpness. Fills happen at the *next* bar's open — the decision variable never touches the fill price. Decide: `edge = E[return] − half_spread − kappa * size − lambda * variance(p)`. Every parameter in that expression — `kappa`, `lambda`, the entry threshold — lives in `simulation.yaml`, not in code. If `edge > threshold`, take a position sized by `edge / distribution_std`. Positions are single-instrument and single-position; an entry signal that fires while a position is open is dropped. Track per-trade P&L, Sharpe, hit rate, max drawdown, and capacity — the largest position size at which Sharpe stays positive.

## v2 — multi-instrument

Same code. Same architecture. More assets and shared training.

Add SPY, QQQ, IWM, TLT, GLD, USO as trade targets. Each target's token stream uses the same channel schema — its own OHLCV as "target" channel, everything else as context. Two candidate training schemes: one shared model across all targets with target ID as an embedded conditioning token, or per-target fine-tuning from a shared pretrain. Which one wins is settled empirically once v1 is done.

The compute delta is modest: 6× the tokens for 6× the assets, still fits on a single A100. The model doesn't get bigger. Only the data does.

v2 is the next commit after v1 works, not a separate initiative.

## v3 and beyond

Each item is a bounded extension against v1's module boundaries.

**LOB tokens.** Add an ingestion module for level-2 order-book snapshots at 100ms resolution. New channel type in the tokenizer. Longer context window. Model, training loop, simulator unchanged. Kronos and MarketGPT have shown discrete tokenization at LOB frequency is tractable.

**Alternative data.** Satellite imagery of oil storage, container-shipping rates, credit-card aggregate spend, web traffic for consumer names. Each becomes a new channel with its own ingestion path. Everything after that is unchanged.

**News and text.** Small encoder (BERT-scale) processes news headlines into an embedding; the embedding becomes a new channel. Bloomberg or NewsAPI ingestion path.

**RL policy layer.** Replace the fixed decision rule with a learned policy that takes the predicted distribution and outputs continuous position size. Trained with PPO against the simulator. Model producing the distribution stays frozen or fine-tuned jointly.

**Live paper trading.** Add an inference server that produces predictions on live data at bar close. Route to Alpaca or IBKR paper endpoint. No architectural change; adds a real-time data ingestion path and an order-management wrapper.

Each of these lands as a discrete extension. None requires re-architecting v1.

## Success gates for v1

v1 succeeds if all of the following hold on the held-out test period (2024-01 through 2025-06). Every gate is pre-registered before the held-out set is opened.

- Training completes without NaN, divergence, or gradient explosion.
- Validation expected calibration error below 0.05.
- Validation cross-entropy at least 10% lower than the 1-layer linear baseline on identical data.
- Validation cross-entropy at least 5% lower than the target-only ablation on identical data. This is the specific test of whether multi-modal tokenization pays off.
- Held-out Sharpe reported with its standard error, where SE ≈ `sqrt((1 + 0.5·S²)/N)` at trade level, annualized by multiplying by `sqrt(bars_per_year / bars_per_trade)`. Minimum gate: `Sharpe − 1·SE > 0`. Stronger gate: `Sharpe > 0.5` with the point estimate and SE both reported. A held-out Sharpe of 0.5 with N ≈ 300 trades carries an SE around 0.15–0.25 annualized; the report must show the number, not hide behind it.
- Block-bootstrap distribution of Sharpe across monthly blocks of the holdout, reported as a histogram. Gate: ≥70% of block-bootstrap Sharpes positive. If the point estimate is 0.5 but half the monthly blocks are negative, the number is a coincidence and the gate fails.
- Held-out capacity at least $1M — the largest single-position size at which Sharpe stays positive. SPY at $1M is expected to absorb the trade without measurable impact except in the fastest bars (open, close, event bars); state that and prove it with the sensitivity plot below.
- The simulator's spread proxy is calibrated against measured SPY BBO data on the training window before the held-out set is opened. Any free source producing SPY BBO snapshots suffices. Uncalibrated Corwin-Schultz on an instrument with a near-zero spread is not acceptable. The slippage coefficient `kappa` is estimated by regression on the training window with a reported confidence interval, and the held-out Sharpe report includes a sensitivity plot showing Sharpe as `kappa` moves from 0.5x to 2x its point estimate.
- Every training run has its config, git SHA, data hash, and W&B URL logged in `experiments/logbook.csv`. Any run that touched the held-out test set is flagged. Test-set look budget: 3 for the full v1, enforced by the filesystem guard above.

**Reported, not gated.** Range of held-out Sharpe across 3 seeds. Below 3 seeds we cannot claim training-procedure stability, only observe the range. Reporting the range is required; passing a specific tolerance is not. If a serious stability claim is needed later, raise the seed count and set a tolerance with attached uncertainty.

**If ECE passes but Sharpe fails.** The model is doing its job — producing a calibrated distribution — and the decision layer is where the failure lives. In that case, v1 is a partial success: the prediction pipeline validates and the decision layer needs a rethink. Options in order of cost: tune the entry threshold on the validation window (cheap, one config sweep), recalibrate the cost model against BBO data (medium, requires the calibration work to have been done already), promote the magnitude-weighted loss ablation to the main run if it outperformed on validation (medium, one training run). Do not go back and reopen the held-out set; the honest report is "prediction validated, decision layer did not, here is what we would change."

Any other gate that fails is a specific thing to fix, not a verdict on the project.

## Regime evaluation

Aggregate metrics can hide regime failures. Required disclosure, not a gate.

Tag each held-out bar with a coarse VIX-regime label: terciles computed on the training window (2015–2022), producing low-VIX, mid-VIX, and high-VIX thresholds. Freeze the thresholds. Apply them unchanged to the 2023 validation window and the 2024–2025 holdout. Every held-out metric — cross-entropy, ECE, directional accuracy, Sharpe, capacity, hit rate, block-bootstrap Sharpe distribution — is reported both aggregate and per regime.

If aggregate Sharpe is 0.5 while one regime contributes 2.0 and another contributes −0.5, the aggregate is a lie of averages. The honest answer is that the strategy works in one regime and does not work in the other, and that is a useful answer: it tells you what v2 has to fix. If per-regime Sharpes are all within noise of the aggregate, that is also a useful answer: the strategy is regime-robust within the range of conditions it saw. Either way, aggregate-only reporting is not acceptable.

One diagnostic ships alongside: the realized bucket-frequency histogram on validation and on holdout, compared to training. If validation buckets 0 and 31 hold materially more or less than the training 0.5% each, that is direct evidence of tail-shape drift and the frozen bucket boundaries are less informative on the new regime. Note it. It affects how the ECE number is read.

## What v1 explicitly is not

Not HFT. 15-minute bars. Not tick data. Not order-book data. Not intra-bar timing.

Not reinforcement learning. Cross-entropy on next bucket, period. Decision rule is a fixed, config-parameterized function of the distribution.

Not text-conditioned. No news, no filings, no earnings-call transcripts.

Not real-time. Simulator only, running against historical data.

Not multi-instrument. SPY only.

Not multi-horizon. Next-bar prediction only. Whether the same tokens carry information at 1-hour, daily, or weekly horizons is a separate test v1 does not run.

Not an equal-weight foundation model. It's a bet on a specific architecture applied to a specific instrument. Whether it generalizes is what v2 tests.

Not a Kronos or MarketGPT re-implementation. Kronos tokenizes one OHLCV stream and predicts candles. MarketGPT tokenizes order messages and generates flows. This tokenizes joint multi-modal state and predicts vol-normalized return buckets.

## Dependencies

**Data.** Primary source is the financial-data MCP already available in the working environment. Relevant tools by channel:

| Channel | MCP tools |
| --- | --- |
| SPY / QQQ / IWM / VIX / TLT intraday | `TIME_SERIES_INTRADAY` (15-min interval) |
| GLD / USO intraday | `TIME_SERIES_INTRADAY` (15-min interval) |
| DXY / FX | `FX_INTRADAY`, `CURRENCY_EXCHANGE_RATE` |
| Macro | `CPI`, `FEDERAL_FUNDS_RATE`, `TREASURY_YIELD`, `UNEMPLOYMENT`, `NONFARM_PAYROLL`, `INFLATION`, `RETAIL_SALES` |
| Options | `HISTORICAL_PUT_CALL_RATIO`, `HISTORICAL_VOLUME_OPEN_INTEREST_RATIO`, `HISTORICAL_OPTIONS` |
| Event | `EARNINGS_CALENDAR` |
| BBO calibration | Any free source producing SPY BBO snapshots on the 2015–2022 window |
| Commodities (v2+) | `WTI`, `BRENT`, `NATURAL_GAS`, `COPPER`, `GOLD_SILVER_HISTORY`, `WHEAT`, `CORN` |

Fallback: Polygon.io ($200/month) for 15-minute equity bars if the MCP doesn't return the frequency or history needed.

**Compute.** One GPU. A10 ($1/hr) or A100 ($3/hr) on Lambda Labs, AWS EC2, or GCP. Total v1 compute budget: $500. That covers roughly 200–500 hours of GPU time, enough for the full training loop, all three baselines, the magnitude-weighted ablation, and 30–50 iteration cycles.

**Storage.** Local SSD, ~50GB for aligned Parquet + tokenized cache + all checkpoints. 65,000 SPY bars is small; the alt-channel joins and 3-seed runs are what fill the disk.

**Software.** Python 3.11, PyTorch 2.x, Polars for DataFrames (4s vs 90s on the aligned dataset against pandas), PyArrow for Parquet, Hydra + Pydantic v2 for typed configs, Weights & Biases for tracking, pytest for tests, `uv` for dependency management.

## Risks and mitigations

Execution risks. Not "will markets cooperate" risks.

**Data leakage.** Any place future information touches training features silently inflates every metric. Fix: causal normalization enforced as an invariant in the feature pipeline with a unit test that shuffles rows after `t*` and asserts feature values at `t ≤ t*` are byte-identical. Purged embargo of `H` bars at every split boundary, where `H` is the prediction horizon (H=1 bar for v1). Test set opened exactly once. Filesystem guard on held-out reads. Test-look log is append-only.

**Simulator dishonesty at the cost model.** A backtest that assumes cheap fills produces a fantasy Sharpe. The bar-range spread proxy is Corwin-Schultz; on 5-min SPY it systematically overestimates by an order of magnitude in normal conditions and underestimates near events. At 15-min the bar range is even more dominated by the actual move than by the spread, so the problem is worse in the same direction. Fix: calibrate the proxy against measured SPY BBO data on the training window before the holdout is opened, and either replace it or scale it. Report the calibration coefficient and the residual after fit. The slippage coefficient `kappa` is estimated by regression: dependent variable is next-bar return in the direction of the trade, independent variable is traded volume as a fraction of concurrent 15-min volume. Report `kappa` with its 95% CI. Include a Sharpe-vs-`kappa` sensitivity plot in the results, sweeping `kappa` from 0.5x to 2x the point estimate. For SPY at $1M capacity linear slippage is probably right; SPY absorbs $1M without measurable impact except at the open, the close, and event bars — state it, cite the number.

**Channel interference in the summed embedder.** The multi-modal claim depends on gradient descent finding non-overlapping subspaces for each channel in `d_model=512`. If channels collapse into one subspace, the target-only ablation may look identical to the full model even when the extra channels carry information. Diagnostic: at end of training, project each channel's contribution at a held-out set of bars and measure the cosine similarity between channel means. Near-orthogonal is the pass; collapse to a single direction is the fail. One plot. Ships alongside the eval report.

**Bucket-boundary shape drift.** Vol-normalization mitigates scale drift across regimes. It does not mitigate skew, kurtosis, or tail-mass shifts. Diagnostic: realized bucket-frequency histogram on validation and holdout, compared to training's 0.5% / 3.3% / ... / 3.3% / 0.5% target. Included in the run summary.

**Scope creep.** Building v2 features while v1 doesn't yet pass its gates. Fix: the v1 success gates are binary and pre-registered. Nothing about v2 gets touched until they hold.

**Losing count of experiments.** Every hyperparameter sweep is implicit multiple-testing. Fix: `experiments/logbook.csv` gets one row per training run. Runs that touched the held-out test are flagged in the CSV and in the test-look log. Test-set look budget: 3.

**Calibration drift within a run.** Model accuracy might look fine while its predicted probabilities are miscalibrated, breaking the decision layer. Fix: ECE tracked per epoch, checkpoint selection by ECE, not accuracy.

**Expanding-window normalization staleness.** The training-window normalizer freezes to a stable mean; on 2024–2025 the frozen normalizer is doing more work than the model expects. Diagnostic: plot the normalized-feature distribution on the holdout against training. This is not a bug, it is a failure mode to watch for.

## Open questions

Each has a candidate answer; the choice gets made during v1 or as an ablation.

Vol estimator for target definition. Candidate: 30-bar trailing realized volatility, which at 15-min covers ~7.5 trading hours. Alternates: EWMA(halflife=30 bars), GARCH(1,1), implied volatility from ATM options. Pick one for v1; expose the others as config alternates. The tech-arch doc settles on 30-bar realized vol for the reasons cited there (unambiguous semantics, matches DeepLOB baselines); this spec keeps the alternates named for later.

Channel combination inside the token. Candidate: per-channel `nn.Linear` projection to 512-dim, then sum with a learned channel-type embedding. Keeps `d_model` fixed as channels grow. Alternate: concatenate per-channel projections. Chosen because sum-plus-type scales cleanly to v2's multi-instrument case; validated at end of training by the channel-orthogonality diagnostic above.

Bucket boundaries. Candidate: percentile-uniform on training-set vol-normalized returns, 32 buckets numbered 0–31, outer 2 for tails. Alternate: learned via a VQ-VAE-style objective. Percentile is simpler and inspectable.

Positional encoding. Candidate: rotary (RoPE). Cheap to extend context in v3 to LOB timescales past 2k tokens without retraining position embeddings. Alternate: learned absolute.

Bar-close vs. bar-open target. Candidate: predict the return from bar close(t) to bar close(t+1). Alternate: close(t) to open(t+1), then open(t+1) to close(t+1) as separate tokens. Second option separates overnight-gap dynamics from intraday. Ablation for v2.

Regime labels beyond VIX terciles. VIX terciles are the coarse-and-obvious first cut. Trending-vs-mean-reverting SPY realized-vol regimes, or a three-state HMM fit only on the training window, would give a finer read. If v1 shows regime dependence on VIX, v2 fits a finer regime model.

## Glossary

**Causal transformer.** A neural network built from attention layers where each position can only attend to positions before it in the sequence. Same architecture as GPT.

**Token.** A single unit the model reads or predicts. In language models, a word-piece. Here, a compressed market-state vector as input; a discrete bucket ID (0–31) as output.

**Multi-modal market-state token.** A single input token per timestep that combines features from many data channels — target instrument, correlated markets, liquidity, macro, event — projected and summed into one 512-dim vector.

**Vol-normalized return.** The next-bar return divided by an estimate of current volatility (30-bar realized). Scale-invariant across regimes.

**Bucket / return bucket.** One of 32 discrete labels the model predicts, numbered 0 through 31. Each label covers a range of vol-normalized returns; buckets 0 and 31 catch outer tails. Predicting a bucket ID is the equivalent of predicting a word ID in a language model.

**Expected Calibration Error (ECE).** How well a model's predicted probabilities match observed frequencies. If the model says "80% chance up" on 100 occasions, the up-move should happen ~80 times. ECE measures the gap.

**Purged embargo.** A gap of `H` bars left at every train/validation or train/test boundary, where `H` is the prediction horizon. Prevents overlapping labels from bleeding across splits.

**Block bootstrap.** Resampling with replacement over contiguous monthly blocks rather than individual trades, preserving within-block autocorrelation. Used here to produce a distribution of Sharpe estimates for the ≥70% positive gate.

**Capacity.** The largest position size at which the strategy's Sharpe stays positive. Approximates how much money the edge can absorb before market impact eats it.

**Cost-aware decision layer.** The function that turns the model's predicted distribution into a trade decision. Compares expected edge against expected cost, decides direction and size. All parameters — entry threshold, `kappa`, `lambda` — live in `simulation.yaml`.

**Kappa (`kappa`).** The linear slippage coefficient in `edge = E[return] − half_spread − kappa * size − lambda * variance(p)`. Estimated by regression on the training window with a reported confidence interval; Sharpe reported with a sensitivity plot across 0.5x–2x `kappa`.

**Ablation.** A training run with one component removed or changed, to test whether that component was doing useful work. v1 ships four: linear, MLP, target-only, and magnitude-weighted loss.

**Regime label.** A discrete tag applied to each held-out bar (low-VIX / mid-VIX / high-VIX terciles from training). Every held-out metric is reported per label as well as in aggregate.
