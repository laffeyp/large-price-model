# Price-Space LLM — Product Specification

## What this is

A causal decoder transformer that reads market history as a token sequence and predicts what the market does next. Same architectural family as GPT. Different vocabulary. Different prompt. Different target.

The vocabulary is not English. Each token is a compressed *market state* at one moment in time: the target instrument's recent behavior, what correlated markets are doing, current liquidity and spread, recent macro releases, time-of-day and event context. All of that gets packed into one vector per timestep. The model reads a sequence of these vectors and predicts the next *price-move token*: a volatility-normalized return bucket, one of 32 discrete labels covering large-down to large-up.

Its output is a probability distribution over those 32 buckets. A cost-aware decision layer downstream converts the distribution into a trade: long, short, or do nothing, sized by the expected edge and the model's confidence.

Nothing published does this exact combination. Kronos, the closest existing system, tokenizes only OHLCV bars from one instrument and predicts candle reconstruction. MarketGPT tokenizes only order-book messages and generates simulated flows. The DeepLOB line supervises 3-class direction on order-book snapshots. This project tokenizes the joint state — target, correlated markets, liquidity, macro, event — and predicts a target that's aligned with what a trader actually cares about: edge measured in units of risk.

## Why this design

Three specific bets stacked on top of each other.

First bet: attention across multi-modal market state does more than attention across one stream. If the next move of SPY depends on what VIX did in the last hour, what oil did overnight, whether CPI dropped this morning, and where we are in the trading session — all at once — a model that gets those channels jointly is doing something a Kronos-style bar-only model can't.

Second bet: volatility-normalized return buckets are a better prediction target than raw returns or candle reconstruction. A one-sigma move in a calm market and a one-sigma move in a volatile one land in the same token. The vocabulary stays meaningful across regimes. The output is already in the units the trading decision needs.

Third bet: a cost-aware decision layer that consumes the full predicted distribution — not just a point forecast — produces trades that survive real-world costs. Existing work either skips the trading layer (Kronos, MarketGPT) or trains it separately from the predictor. Coupling them, even without RL, aligns the prediction with the decision.

None of the three bets is exotic on its own. The combination has not been built.

## v1 — the first build

One asset. One horizon. All channels. Full pipeline.

**Target instrument.** SPY at 5-minute bars.

**Training range.** 2015-01-01 through 2022-12-31 for training. 2023 for validation. 2024-01-01 through 2025-06-30 held out for the final test. The held-out period is opened exactly once, at the end.

**Channels tokenized at every timestep.**

Target: SPY open, high, low, close, volume, log return, 30-bar realized volatility, spread proxy from bar range.

Cross-asset context: QQQ, IWM, VIX, TLT, DXY, GLD, USO — each contributes log return and rolling volume z-score.

Macro: CPI year-over-year, Fed funds rate, 10-year Treasury yield, unemployment rate, nonfarm payroll. Values held constant intra-day between releases. Countdown-to-next-release feature per series.

Options: put/call ratio, options volume — daily, held constant intra-day.

Event: earnings-calendar density for SPY constituents, FOMC dates, CPI release dates, options expiry. Encoded as countdown-to-next and time-since-last.

Time: minute-of-day and day-of-week, sin/cos encoded.

**Tokenization.** Each timestep's per-channel feature vector goes through its own `nn.Linear` projection to a 512-dim embedding, gets summed with a learned channel-type embedding, and produces one 512-dim market-state vector per bar. The prediction target for that bar is a bucket ID from a 32-bucket vocabulary. Buckets are set by percentile boundaries on vol-normalized next-bar returns from the training window: buckets 1 and 32 catch outer tails, buckets 2–31 cover the 0.5th–99.5th percentile range uniformly by count.

**Model.** ~30M parameters. `d_model=512`, 8 transformer blocks, 8 attention heads per block, causal mask, rotary positional embeddings, pre-LayerNorm, GELU activation, dropout 0.1. Output head: linear projection to 32 logits. Loss: cross-entropy on next-bucket ID.

**Training.** Single A10 or A100 GPU. Mixed precision (bfloat16). AdamW, learning rate 3e-4 with cosine schedule and 1000-step warmup, weight decay 0.1, gradient clipping at 1.0. Batch size fills GPU memory (typically 64–128 sequences of length 512). Context length 512 bars (~two trading days at 5-min).

**Baselines trained on identical data, splits, and seeds.**

- 1-layer linear model: same input tokens, direct softmax over 32 buckets.
- 3-layer MLP: 128 → 64 → 32 hidden dims, same input tokens.
- Target-only ablation: same 30M transformer, but every non-target channel zeroed. Tests whether multi-modal tokenization adds anything.

**Simulator.** Bar-by-bar walk over the held-out period. At each bar, assemble the market-state token from data available up to that bar, forward-pass the model, extract expected vol-normalized return and distribution sharpness. Decide: `edge = E[return] − half_spread − k * size − risk_penalty(distribution)`. If `edge > threshold`, take a position sized by `edge / distribution_std`. Track per-trade P&L, Sharpe, hit rate, max drawdown, and capacity — the largest position size at which Sharpe stays positive.

## v2 — multi-instrument

Same code. Same architecture. More assets and shared training.

Add SPY, QQQ, IWM, TLT, GLD, USO as trade targets. Each target's token stream uses the same channel schema — its own OHLCV as "target" channel, everything else as context. Two candidate training schemes: one shared model across all targets (target ID as an embedded conditioning token), or per-target fine-tuning from a shared pretrain. Which one wins is settled empirically once v1 is done.

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

v1 succeeds if all of the following hold on the held-out test period (2024-01 through 2025-06).

- Training completes without NaN, divergence, or gradient explosion across three seeds.
- Validation expected calibration error below 0.05.
- Validation cross-entropy at least 10% lower than the 1-layer linear baseline on identical data.
- Validation cross-entropy at least 5% lower than the target-only ablation on identical data. This is the specific test of whether multi-modal tokenization pays off.
- Held-out Sharpe ratio at least 0.5 after realistic costs (half-spread + linear slippage).
- Held-out capacity at least $1M — the largest single-position size at which Sharpe stays positive.
- Three seeds produce held-out Sharpe within 0.3 of each other. Not a stability claim about markets; a stability claim about the training procedure.
- Every training run has its config, git SHA, data hash, and W&B URL logged in `experiments/logbook.csv`. Any run that touched the held-out test set is flagged.

Any gate that fails is a specific thing to fix, not a verdict on the project.

## What v1 explicitly is not

Not HFT. 5-minute bars. Not tick data. Not order-book data.

Not reinforcement learning. Cross-entropy on next bucket, period. Decision rule is a fixed function of the distribution.

Not text-conditioned. No news, no filings, no earnings-call transcripts.

Not real-time. Simulator only, running against historical data.

Not multi-instrument. SPY only.

Not an equal-weight foundation model. It's a bet on a specific architecture applied to a specific instrument. Whether it generalizes is what v2 tests.

Not a Kronos or MarketGPT re-implementation. Kronos tokenizes one OHLCV stream and predicts candles. MarketGPT tokenizes order messages and generates flows. This tokenizes joint multi-modal state and predicts vol-normalized return buckets.

## Dependencies

**Data.** Primary source is the financial-data MCP already available in the working environment. Relevant tools by channel:

| Channel | MCP tools |
| --- | --- |
| SPY / QQQ / IWM / VIX / TLT intraday | `TIME_SERIES_INTRADAY` |
| GLD / USO intraday | `TIME_SERIES_INTRADAY` |
| DXY / FX | `FX_INTRADAY`, `CURRENCY_EXCHANGE_RATE` |
| Macro | `CPI`, `FEDERAL_FUNDS_RATE`, `TREASURY_YIELD`, `UNEMPLOYMENT`, `NONFARM_PAYROLL`, `INFLATION`, `RETAIL_SALES` |
| Options | `HISTORICAL_PUT_CALL_RATIO`, `HISTORICAL_VOLUME_OPEN_INTEREST_RATIO`, `HISTORICAL_OPTIONS` |
| Event | `EARNINGS_CALENDAR` |
| Commodities (v2+) | `WTI`, `BRENT`, `NATURAL_GAS`, `COPPER`, `GOLD_SILVER_HISTORY`, `WHEAT`, `CORN` |

Fallback: Polygon.io ($200/month) for 5-minute equity bars if the MCP doesn't return the frequency or history we need.

**Compute.** One GPU. A10 ($1/hr) or A100 ($3/hr) on Lambda Labs, AWS EC2, or GCP. Total v1 compute budget: $500. That covers roughly 200–500 hours of GPU time, enough for the full training loop, all baselines, all ablations, and 30–50 iteration cycles.

**Storage.** Local SSD, ~50GB for aligned Parquet + tokenized cache + all checkpoints.

**Software.** Python 3.11, PyTorch 2.x, Polars for DataFrames, PyArrow for Parquet, Hydra + Pydantic for configs, Weights & Biases for tracking, pytest for tests, `uv` for dependency management.

## Risks and mitigations

Execution risks. Not "will markets cooperate" risks.

**Data leakage.** Any place future information touches training features silently inflates every metric. Fix: causal normalization enforced as an invariant in the feature pipeline with a unit test that shuffles future data and asserts feature values at time `t` are unchanged. Purged embargo of `H` bars at every split boundary, where `H` is the prediction horizon. Test set opened exactly once.

**Scope creep.** Building v2 features while v1 doesn't yet pass its gates. Fix: the eight v1 success gates are binary. Nothing about v2 gets touched until all eight hold.

**Losing count of experiments.** Every hyperparameter sweep is implicit multiple-testing. Fix: `experiments/logbook.csv` gets one row per training run. Runs that touched the held-out test are flagged. Test-set look budget: 3 for the full v1.

**Silent simulator dishonesty.** A backtest that assumes zero-cost fills produces a fantasy Sharpe. Fix: cost model is half-spread (from data) + linear slippage coefficient calibrated against observed impact. Capacity metric — largest size at which Sharpe stays positive — surfaces the honest bound on the edge.

**Calibration drift.** Model accuracy might look fine while its predicted probabilities are miscalibrated, breaking the decision layer. Fix: ECE tracked per epoch, checkpoint selection is by calibration, not accuracy.

## Open questions

Each has a candidate answer; the choice gets made during v1 or as an ablation.

Vol estimator for target definition. Candidate: 30-bar trailing realized volatility. Alternates: EWMA(halflife=30), GARCH(1,1), implied volatility from ATM options. Pick one for v1; expose the others as config alternates.

Channel combination inside the token. Candidate: per-channel `nn.Linear` projection to 512-dim, then sum with a learned channel-type embedding. Keeps `d_model` fixed as channels grow. Alternate: concatenate per-channel projections. Chosen because sum-plus-type scales cleanly to v2's multi-instrument case.

Bucket boundaries. Candidate: percentile-uniform on training-set vol-normalized returns, 32 buckets, outer 2 for tails. Alternate: learned via a VQ-VAE-style objective. Percentile is simpler and inspectable.

Loss weighting. Candidate: uniform cross-entropy for v1. Ablation: cross-entropy weighted by bucket magnitude (reward the model more for being right about large moves). If the weighted version consistently wins on held-out Sharpe, promote it.

Positional encoding. Candidate: rotary (RoPE). Cheap to extend context in v2 without retraining position embeddings. Alternate: learned absolute.

Bar-close vs. bar-open target. Candidate: predict the return from bar close(t) to bar close(t+1). Alternate: close(t) to open(t+1), then open(t+1) to close(t+1) as separate tokens. Second option separates overnight-gap dynamics from intraday. Ablation for v2.

## Glossary

**Causal transformer.** A neural network built from attention layers where each position can only attend to positions before it in the sequence. Same architecture as GPT.

**Token.** A single unit the model reads or predicts. In language models, a word-piece. Here, a compressed market-state vector as input; a discrete bucket ID as output.

**Multi-modal market-state token.** A single input token per timestep that combines features from many data channels — target instrument, correlated markets, liquidity, macro, event — projected and summed into one vector.

**Vol-normalized return.** The next-bar return divided by an estimate of current volatility. Scale-invariant across regimes.

**Bucket / return bucket.** One of 32 discrete labels the model predicts. Each label covers a range of vol-normalized returns. Predicting a bucket ID is the equivalent of predicting a word ID in a language model.

**Expected Calibration Error (ECE).** How well a model's predicted probabilities match observed frequencies. If the model says "80% chance up" on 100 occasions, the up-move should happen ~80 times. ECE measures the gap.

**Purged embargo.** A gap of `H` bars left at every train/validation or train/test boundary, where `H` is the prediction horizon. Prevents overlapping labels from bleeding across splits.

**Capacity.** The largest position size at which the strategy's Sharpe stays positive. Approximates how much money the edge can absorb before market impact eats it.

**Cost-aware decision layer.** The function that turns the model's predicted distribution into a trade decision. Compares expected edge against expected cost, decides direction and size.

**Ablation.** A training run with one component removed or changed, to test whether that component was doing useful work.
