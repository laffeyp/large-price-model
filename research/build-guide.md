# How to Actually Build This

A practical walkthrough. About nine weeks of focused work to get a defensible v1 running end-to-end. Solo, single GPU.

## Week 1–2: Pick the target and pull the data

Pick the asset class and horizon first. Everything else is downstream of this choice. For a first build, two defensible options: liquid US equity ETFs at 1- or 5-minute bars (clean data, well-understood microstructure, free or cheap sources), or crypto perpetual futures (BTCUSDT, ETHUSDT — 24/7 data, exchange-provided history). Crypto removes session-boundary headaches but adds different ones.

Concrete data sources: Polygon.io for US equity minute bars (~$200/month); Binance Vision archives for free historical crypto; IBKR or Alpaca for a paper-trading endpoint later. Pull at least 5–10 years for the target *and* every context instrument (index, sector ETF, vol, rates).

Store as Parquet keyed by timestamp. UTC throughout. Build one timezone-aware loader and never touch raw timestamps again. The first non-trivial work is alignment: every context instrument has different trading hours, gaps, and missing bars. Write an alignment function that produces a single tensor `[time, channel, feature]` on a common time index, with explicit missing-data flags — not zeros, not forward-fills.

## Week 2–3: Features and tokens

Define the per-timestep feature vector for each channel.

- **Target:** log return, realized vol over 30 bars, volume z-scored over 100 bars, bar shape (`(close-open)/range`), spread proxy.
- **Market context:** the same set computed on SPY, QQQ, VIX, TLT, or whatever is correlated to your target.
- **Liquidity:** rolling average volume, spread, dollar volume, minutes since session open.
- **Time/event:** minute-of-day (sin/cos encoded), day-of-week, distance to next earnings/CPI/FOMC.

Normalize every feature with a **causal z-score** — at time `t`, use only statistics from before `t`. Never normalize with future data. This single discipline prevents 80% of the leakage failure modes.

For the target: compute realized volatility over a trailing window (30 bars is a reasonable start) and define the next-bar return divided by that vol. Learn fixed bucket boundaries from a training-only sample — say, 32 buckets from the 0.5th to 99.5th percentile of vol-normalized returns, with two outer buckets for tails. Save the boundaries; reuse them at inference.

## Week 4–5: The model

PyTorch, single file, structured like `nanoGPT`. Start at ~30M parameters: 8 layers, 512 hidden, 8 heads, context length 512.

At each timestep, the market-state token is a learned linear projection of the concatenated per-channel feature vector into the hidden dimension. Add learned positional embeddings. The output head is a linear map from the final hidden state to vocabulary size (32 logits). Loss is cross-entropy.

Defaults that aren't worth tuning yet: AdamW with weight decay 0.1, learning rate 3e-4 with cosine schedule, batch size as large as GPU memory allows (32–128 sequences), gradient clipping at 1.0, dropout 0.1.

## Week 5–6: Training

Rent a single A10 or A100 on AWS, GCP, or Lambda Labs — $1–3/hour. A 30M model on 10 years of minute bars across five channels trains in hours, not days.

Two non-negotiable training disciplines.

**Split by time, never randomly.** Train on years 0–7, validate on year 8, hold out years 9–10 as untouchable test. The held-out years exist to be looked at exactly once, at the end.

**Embargo overlapping windows.** If your prediction horizon is 5 bars, leave at least 5 bars between adjacent training windows so labels don't bleed across the train/val boundary.

Log training loss, validation loss, validation accuracy, and validation calibration (does predicted `P(up)` match the realized frequency of up moves) every epoch. The loss curve tells you the tokenization is learnable. The calibration curve tells you the predictions are usable downstream. Save checkpoints by validation calibration, not by accuracy — calibration is what the trading layer actually needs.

## Week 7: Baselines and ablations

Before claiming the transformer is doing useful work, run three internal comparisons on identical data and splits.

1. **One-layer linear model** from the same input tokens to the same bucket targets. If your transformer doesn't beat this, the transformer isn't doing work.
2. **Small MLP** (3 layers, 128/64/32) on the same tokens. Same test.
3. **Target-only ablation** — your own transformer, same architecture, with the market-context, liquidity, and event channels zeroed. If the full model matches this, your multi-modal tokens aren't adding information and the four-channel design isn't yet paying off.

Each baseline takes hours. The ablations are where you learn whether your specific design choices justify themselves.

## Week 8: The trading layer

Write a bar-by-bar simulator over the held-out period. At each bar:

1. Compute the market-state token from data available up to that bar.
2. Forward-pass the model to get the predicted distribution over next-move buckets.
3. Convert to expected vol-normalized return, directional probability, and confidence (sharpness of the distribution).
4. Apply the decision rule: trade if expected return exceeds the cost estimate by a margin scaled by uncertainty.
5. Apply costs: half-spread on entry and exit, plus a slippage term that grows with position size (linear is fine to start; non-linear when you care about capacity).

Track per-trade P&L, hit rate, Sharpe, max drawdown, and the largest size at which Sharpe stays positive. That last number is your capacity. It tells you whether the edge is real or just a zero-impact artifact.

## Week 9+: Iteration discipline

Now the real work starts. Every change — new feature, new tokenization, new horizon, new asset, new bucket scheme, new model size — is a separate experiment. The thing that kills these projects is not running out of ideas; it's losing track of how many ideas have been tried.

Keep a logbook. One line per experiment: date, what changed, train loss, val loss, val calibration, held-out Sharpe if applicable. Tag which experiments touched the held-out set (those count more against your effective multiple-testing budget). When the logbook gets long, you have data on what kinds of changes consistently help, what's noise, and what's regressing.

The system you'll have at the end of nine weeks isn't the final system. It's a working end-to-end pipeline you can iterate against — tokenizer in, transformer in the middle, decision layer out, evaluation honest. From there, every change you make produces a concrete answer instead of a vibe.

## Tools you'll touch

- **Data:** Polygon.io / Binance Vision / yfinance for prototyping; Parquet files; pandas or polars.
- **Modeling:** PyTorch, `nanoGPT`-style structure, AdamW, cosine LR.
- **Compute:** Lambda Labs / AWS EC2 / GCP — single A10 or A100.
- **Tracking:** Weights & Biases or a plain CSV logbook; both work.
- **Simulation:** Custom bar-walker, or `vectorbt` / `backtrader` if you want a framework.
- **Versioning:** Git for code; DVC or plain timestamps for data and model artifacts.

That's the whole pipeline. The hard part isn't the code — the code is a long weekend. The hard part is the discipline around data alignment, causal normalization, time splits, embargo, calibration tracking, and the experiment logbook. Nothing in that list is hard individually. Skipping any of them lets you fool yourself.
