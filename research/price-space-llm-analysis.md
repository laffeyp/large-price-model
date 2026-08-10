# Market-Native Causal Transformer for Next-Price Prediction
## Prior-Art Map and Research Position

**Date:** 2026-05-17

---

## 1. The proposal, restated

A causal decoder-only transformer trained on tokenized market state.

- **Input:** a sequence of multi-modal market-state tokens, each combining (a) target instrument behavior, (b) market context (correlated assets, indices, rates, vol), (c) liquidity and execution context (volume, spread, order-flow imbalance, time-of-day), and (d) event/time/risk context.
- **Target:** the next price-move token, defined as a volatility-normalized return bucket.
- **Output:** a probability distribution over next-move tokens.
- **Downstream:** a cost-aware decision layer turns the predicted distribution into long/short/no-trade/size.

The model is a sequence model of *price space*, where the vocabulary is what prices do, the prompt is the market history, and the next token is what happens next.

---

## 2. Prior-art map

What exists in the adjacent literature, organized by what each system *tokenizes*, what it *predicts*, and what it *doesn't do*. This is descriptive — what's been built, not what should be done.

### 2.1 Generic time-series foundation models

These establish that tokenizing continuous values and training a causal transformer on them is a working recipe outside of finance.

**Chronos** (Amazon, 2024, [arXiv:2403.07815](https://arxiv.org/abs/2403.07815)). Scalar quantization into a 4,096-token vocabulary. T5 encoder-decoder, 20M–710M params. Trained with cross-entropy next-token loss on public time-series corpora. Output is a categorical distribution over bins, decoded back to quantiles. Demonstrates that the LLM-style discrete-token + cross-entropy recipe works on time series.

**TimesFM** (Google, 2024, [arXiv:2310.10688](https://arxiv.org/abs/2310.10688)). Decoder-only, ~200M params. Instead of quantizing scalars, it patches contiguous time points into vector tokens. Outputs multi-quantile forecasts. Demonstrates the patch-based alternative.

**Moirai / Moirai 2.0** (Salesforce, [arXiv:2402.02592](https://arxiv.org/abs/2402.02592), [arXiv:2511.11698](https://arxiv.org/abs/2511.11698)). Masked encoder with multi-patch-size projections and "any-variate attention" that flattens multivariate inputs. Demonstrates that multivariate time series can be ingested by a single attention stack.

**Lag-Llama** (ServiceNow / Mila, [arXiv:2310.08278](https://arxiv.org/abs/2310.08278)). Causal Llama-style decoder. Tokens are the value plus engineered lag and calendar features. Outputs a Student-t distribution per step. Demonstrates that auxiliary features can be embedded into the token stream of a causal AR model.

**TimeGPT-1** (Nixtla, [arXiv:2310.03589](https://arxiv.org/abs/2310.03589)). Commercial; details thin. Marketed for zero-shot transfer.

**Toto / Toto 2.0** (Datadog, [arXiv:2407.07874](https://arxiv.org/abs/2407.07874), [Apr 2026 launch](https://www.datadoghq.com/blog/ai/toto-2/)). Decoder transformer optimized for observability metrics; ~1T points of training data including 750B internal metrics. Demonstrates the scale ceiling for AR transformers on continuous time series.

**MOMENT** (CMU, [arXiv:2402.03885](https://arxiv.org/abs/2402.03885)). Masked encoder over patches, designed as a general backbone for forecasting, classification, anomaly, imputation. Non-causal — contrast to the proposal's causal architecture.

### 2.2 Market-specific transformers, autoregressive

These are the systems closest in structure to the proposal. All three use a causal decoder and tokenize market data into a discrete vocabulary.

**Kronos** (Tsinghua, August 2025, [arXiv:2508.02739](https://arxiv.org/abs/2508.02739), [code](https://github.com/shiyu-coder/Kronos)). Decoder-only, autoregressive, pretrained on 12B K-lines from 45 exchanges. A hierarchical tokenizer discretizes multi-dimensional OHLCV bars into discrete tokens. Trained with cross-entropy on next-token. Reports RankIC and volatility-MAE improvements over generic TSFMs.

What Kronos tokenizes: OHLCV bars only — one stream per instrument.
What Kronos predicts: the next K-line (candle reconstruction).
What Kronos does not tokenize: correlated instruments, indices, rates, FX, vol surfaces, LOB state, order-flow imbalance, time-of-day, event flags, news flags, liquidity regime, risk-on/off context.
What Kronos does not target: volatility-normalized returns, edge-in-risk-units, traders' decision variable.

**MarketGPT** (Wheeler & Varner, November 2024, [arXiv:2411.16585](https://arxiv.org/abs/2411.16585), [code](https://github.com/aaron-wheeler/MarketGPT)). Decoder-only GPT. Tokenizes the *fields of order-book messages* (price level, size, type, deltas) into a discrete vocabulary. Autoregressively generates LOB message streams. Used as a market simulator.

What MarketGPT tokenizes: single-venue order-message fields.
What MarketGPT predicts: the next message in a single instrument's order stream.
What MarketGPT does not tokenize: anything outside that single LOB.
What MarketGPT does not target: a tradeable signal — it is a simulator, not a forecaster.

**LOBS5** (Nagy et al., [arXiv:2309.00638](https://arxiv.org/abs/2309.00638)) and **LOBERT** ([arXiv:2511.12563](https://arxiv.org/pdf/2511.12563)). Same message-tokenization vocabulary as MarketGPT, but built on S5 state-space layers and BERT-style masked encoder respectively. Demonstrates the message-token vocabulary is being reused across backbones.

**FinCast** (CIKM 2025, [arXiv:2508.19609](https://arxiv.org/abs/2508.19609)). Sparse-MoE decoder, ~1B params, trained on 20B financial points across stocks, FX, crypto, futures. Uses continuous patches and a point-quantile loss head — no discrete vocabulary. Demonstrates that finance-specific large-scale pretraining is feasible, separately from any tokenization choice.

### 2.3 Market-specific transformers, supervised classification

Older line — pre-dates the AR-transformer-on-markets idea. Treats market state as numeric tensors and predicts a small set of discrete labels.

**DeepLOB** (Zhang, Zohren, Roberts, 2019, [arXiv:1808.03668](https://arxiv.org/abs/1808.03668)). CNN + Inception + LSTM over 10-level LOB snapshots, three-class direction output.

**TransLOB** (Wallbridge, 2020), **TLOB** (Berti et al., 2025, [arXiv:2502.15757](https://arxiv.org/abs/2502.15757)), **LiT** (2025, [Frontiers in AI](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2025.1616485/full)). Transformer-based successors, same supervised 3-class direction target on LOB snapshots.

These systems don't tokenize price into a vocabulary, don't train autoregressively, and don't model multi-modal market context. They're a different research line, included here for completeness.

### 2.4 Side reference

**BloombergGPT** ([arXiv:2303.17564](https://arxiv.org/abs/2303.17564)) and **FinGPT** are text LLMs over financial text. They don't tokenize price; orthogonal to this proposal. Included only to note that a literature search for "transformers + finance" will surface these — they are not prior art for next-price prediction.

---

## 3. Where this proposal sits in that map

Three design choices in the proposal are not present in combination in any published system.

**Choice 1: Multi-modal market-state tokens.** Every published causal market transformer tokenizes a single stream — Kronos: OHLCV bars; MarketGPT: order messages; LOBS5/LOBERT: order messages. None tokenizes a joint market state spanning target + correlated markets + liquidity + event/time. The information available to the attention layer is therefore fundamentally narrower in published work than in the proposal. A correlated-market lead-lag relationship, a liquidity regime shift, or an event-day context that a multi-modal token exposes is invisible to a bar-only or message-only model.

**Choice 2: Volatility-normalized return-bucket vocabulary.** Chronos quantizes raw scalars. Kronos reconstructs candles. Neither targets returns scaled by current volatility. Vol-normalized buckets have two structural properties the others don't: scale-invariance across regimes (a 1-sigma move in 2017 and a 1-sigma move in 2020 occupy the same token), and direct alignment with the trader-relevant decision variable (edge per unit risk).

**Choice 3: Cost-aware decision integration.** Published systems train the predictor and the trading rule separately, or skip the trading rule entirely (Kronos, MarketGPT). A decision layer that consumes the full predicted distribution — not just the point forecast — and compares predicted-edge-after-cost against a threshold is consistent with the proposal but not implemented in the prior-art line.

The combination of these three choices defines a design space that is not occupied by any cited system. That doesn't say anything about whether the system will produce tradable edge — that's empirical — but the *position* in the prior-art map is unambiguous: it is adjacent to Kronos and MarketGPT, not a re-implementation of either.

---

## 4. Open research questions specific to this design

These are the questions the work itself answers — phrased as research questions, not as obstacles.

**On multi-modal tokenization.** How should target, market-context, liquidity, and event/time channels be combined into a token stream? Options span from concatenating per-channel embeddings at each timestep, to interleaving channel-typed tokens (target_token, context_token, liquidity_token, time_token, ...), to a hierarchical scheme (a coarse market-state token at each timestep, with per-channel detail attended via cross-attention). The tradeoff is sequence length vs. information density. Lag-Llama's lag/calendar feature embedding is the closest existing template; the multi-modal extension is new.

**On the vol-normalization estimator.** Vol-normalized return buckets require an estimator of current volatility at decision time. Options include: rolling realized vol, EWMA, GARCH, implied vol from the option chain, or a learned vol head. The choice affects tokenization quality. Implied vol is the most forward-looking but introduces data dependencies; learned vol is the most principled but introduces another head to train.

**On bucket granularity.** Chronos uses 4,096 bins. DeepLOB uses 3 classes. The right granularity depends on the horizon: very short-horizon prediction benefits from fine bins; longer horizons benefit from coarser bins where each bin has enough mass to train against. Bucket boundaries can be fixed (e.g., percentiles of historical vol-normalized returns) or learned.

**On context length.** Kronos uses up to a few hundred bars. MarketGPT uses message-level context windows. The right context length for a multi-modal token stream depends on how much information each token already aggregates — denser tokens need shorter context.

**On the decision objective.** Several reasonable formulations: (a) train predictor on cross-entropy alone, decision layer post-hoc; (b) weight cross-entropy by the magnitude of the move so the model is rewarded more for being right about large moves; (c) train a separate head that directly predicts expected-edge-after-cost; (d) RL with the trading return as reward (out of scope for MVP per the proposal). Option (b) is the cleanest non-RL way to align the prediction loss with the trader-relevant variable.

**On scale.** Gu, Kelly & Xiu (RFS 2020) is sometimes cited as evidence that small NNs beat large ones in finance, but their setting was monthly cross-sectional asset pricing, not autoregressive tokenized sequence modeling — different regime, different conclusions. Kronos at 12B K-lines and FinCast at ~1B params suggest scale is at least viable. The MVP scale (10–50M params) is a reasonable starting point; the right scale is an empirical question.

**On evaluation.** The work needs a held-out chronological out-of-sample period that the model has never seen, and a comparison set: a single-channel Kronos-style baseline, a DLinear baseline, a small MLP baseline. These tell you whether multi-modal tokenization is adding information, whether the transformer is doing more than a linear model, and whether the model is doing more than a shallow alternative.

**On regime robustness.** A meaningful test is whether the model trained on data ending at time T continues to perform on data after T+N for plausible N. This is the empirical content of regime stability. It's not a verdict, it's a measurement.

---

## 5. Open code and implementations to study

For each line, the open-source repos worth reading before building:

- Chronos: [github.com/amazon-science/chronos-forecasting](https://github.com/amazon-science/chronos-forecasting) — for scalar quantization tokenization.
- Kronos: [github.com/shiyu-coder/Kronos](https://github.com/shiyu-coder/Kronos) — for the hierarchical OHLCV tokenizer and AR training loop.
- MarketGPT: [github.com/aaron-wheeler/MarketGPT](https://github.com/aaron-wheeler/MarketGPT) — for vocabulary construction over structured market events.
- LOBS5: [github.com/peernagy/LOBS5](https://github.com/peernagy/LOBS5) — for the message-token vocabulary.
- TimesFM: [github.com/google-research/timesfm](https://github.com/google-research/timesfm) — for patch-based tokenization as an alternative.

Reading these tells you, concretely, what the closest existing implementations have done so you can decide where to diverge.

---

## Sources

- [Chronos: Learning the Language of Time Series — Ansari et al., 2024 (arXiv:2403.07815)](https://arxiv.org/abs/2403.07815)
- [TimesFM: A decoder-only foundation model for time-series — Das et al., 2024 (arXiv:2310.10688)](https://arxiv.org/abs/2310.10688)
- [Moirai: Unified Training of Universal Time Series Forecasting Transformers — Woo et al. (arXiv:2402.02592)](https://arxiv.org/abs/2402.02592)
- [Moirai 2.0 — Salesforce, 2025 (arXiv:2511.11698)](https://arxiv.org/abs/2511.11698)
- [Lag-Llama — Rasul et al. (arXiv:2310.08278)](https://arxiv.org/abs/2310.08278)
- [TimeGPT-1 — Garza et al. (arXiv:2310.03589)](https://arxiv.org/abs/2310.03589)
- [Toto — Cohen et al., 2024 (arXiv:2407.07874)](https://arxiv.org/abs/2407.07874)
- [Toto 2.0 launch — Datadog, April 2026](https://www.datadoghq.com/blog/ai/toto-2/)
- [MOMENT — Goswami et al., 2024 (arXiv:2402.03885)](https://arxiv.org/abs/2402.03885)
- [Kronos: A Foundation Model for the Language of Financial Markets — Shi et al., 2025 (arXiv:2508.02739)](https://arxiv.org/abs/2508.02739)
- [MarketGPT — Wheeler & Varner, 2024 (arXiv:2411.16585)](https://arxiv.org/abs/2411.16585)
- [LOBS5 — Nagy et al., 2023 (arXiv:2309.00638)](https://arxiv.org/abs/2309.00638)
- [LOBERT — 2025 (arXiv:2511.12563)](https://arxiv.org/pdf/2511.12563)
- [FinCast — Zhu et al., CIKM 2025 (arXiv:2508.19609)](https://arxiv.org/abs/2508.19609)
- [DeepLOB — Zhang, Zohren, Roberts, 2019 (arXiv:1808.03668)](https://arxiv.org/abs/1808.03668)
- [TLOB — Berti et al., 2025 (arXiv:2502.15757)](https://arxiv.org/abs/2502.15757)
- [LiT — Frontiers in AI, 2025](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2025.1616485/full)
- [BloombergGPT — Wu et al., 2023 (arXiv:2303.17564)](https://arxiv.org/abs/2303.17564)
