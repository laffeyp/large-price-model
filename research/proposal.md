# Market-Native Causal Transformer for Next-Price Prediction
## A Research Proposal

---

## 1. The idea

Build a causal decoder transformer whose vocabulary is price movement, whose prompt is market history, and whose next token is what the market does next. The model learns the conditional structure of price space from sequence data. A cost-aware decision layer turns the predicted distribution into a trade.

The analogy to a language model is not metaphorical hand-waving. Both systems learn distributions over next tokens conditional on prior context. The difference is what the tokens represent. In a language model, tokens are pieces of natural language. Here, tokens are pieces of market behavior.

---

## 2. The first-principles argument

Markets are sequences. At every moment, the market has a state — prices, volumes, spreads, volatility, related-market behavior, time of day, event context. The next moment's price is produced out of that state, by participants reacting to it. That makes the next price *conditionally dependent* on prior market state, even though the future has not happened yet.

A model that learns this conditional dependence is doing exactly what a sequence model is designed to do. It is not predicting the unpredictable. It is estimating

```
P(next price movement | market history)
```

This is a well-defined probability distribution. The market history is observable. The next price movement is observable after the fact. The training signal is dense — every historical decision point produces a target. The model is therefore in the same epistemic category as any other sequence model that learns conditional distributions from data.

The reason a transformer specifically is natural here: attention learns *which prior states matter* for the current prediction, without being told in advance. The relevant context might be the last few bars, or the overnight session, or a correlated market move, or a liquidity event from earlier. The model is not constrained to a fixed lookback window with hand-chosen features. It learns the relevance structure itself.

---

## 3. The target: what gets predicted

The model does not predict raw price. Raw price is scale-dependent and nonstationary, so a model trained on it spends most of its capacity learning that price levels drift, rather than learning structure that matters for the next move.

Instead, the target is a **volatility-normalized return**: the change in price over the prediction horizon, divided by a current estimate of volatility. This is then **discretized into buckets** — for example, seven coarse buckets (large-down, medium-down, small-down, flat, small-up, medium-up, large-up) or a finer 128-bucket vocabulary.

Two properties make this target well-suited to the task.

**Scale invariance.** A one-sigma move in a calm year and a one-sigma move in a volatile year occupy the same token. The model is not forced to relearn what "a typical move" means for every regime. The vocabulary stays meaningful across time.

**Alignment with the trading decision.** A trader does not care about absolute price levels. A trader cares about edge measured in units of risk. The token vocabulary already speaks that language. When the model outputs a probability distribution over next-move tokens, that distribution is directly the input the trading decision needs.

The output of the model at each step is a probability distribution over the next token. From that distribution we can derive expected move, probability of an up move, probability of a tail move, the variance of the predicted distribution, and the model's confidence. The trading layer uses these.

---

## 4. The input: market state as a token sequence

At each timestep, the input is not a single number. It is a compressed **market-state token** that combines four channels of information.

**Target instrument behavior.** The price, volume, return, realized volatility, and microstructure features of the instrument we are trading.

**Market context.** Correlated markets — indices, sector ETFs, rates, FX, commodities, volatility indices. The next move of the target is often a function of what other markets are doing. Bar-only models that look at a single instrument are structurally blind to this.

**Liquidity and execution context.** Spread, depth, volume profile, order-flow imbalance, time-of-day, session boundaries, recent execution quality. These shape whether a predicted edge is tradeable and how the next price will be produced.

**Time, event, and risk context.** Calendar features, distance to known events (earnings, macro releases, options expiry), risk-regime indicators (risk-on / risk-off). These condition the rest of the state.

The four channels are combined into a single token at each timestep — by concatenation of per-channel embeddings, or by interleaving channel-typed tokens, or by a hierarchical scheme where a coarse market-state token at each step is refined by attention over per-channel detail. The exact embedding scheme is a design parameter the work answers, not a fixed choice.

The crucial property: the model sees the *joint* market state, not just one stream. The conditioning information available to attention is fundamentally richer than what any single-channel model can see.

---

## 5. The model

A causal decoder-only transformer. Standard architecture, deliberately. The novelty is in the data representation and the target, not in the attention mechanism.

The model reads a sequence of market-state tokens

```
state_{t-N}, state_{t-N+1}, ..., state_{t-1}, state_t
```

and produces a probability distribution over the next price-move token

```
P(token_{t+1} | state_{t-N}, ..., state_t)
```

It is causal — at any prediction point, the model only sees information that was available at that moment. It is autoregressive at the level of price-move tokens. The training objective is cross-entropy on next-token prediction, exactly as in a language model.

The model size for an initial version is in the range of tens of millions of parameters. This is small enough to train on a single GPU instance, and large enough to capture nontrivial structure. The right size is an empirical question, decided by whether bigger models keep improving out-of-sample performance.

Context length is another design parameter. Denser market-state tokens (a single token compressing target + context + liquidity + time information) can afford a shorter context window than thinner tokens. A starting point is several hundred to a few thousand tokens of context, which at minute or hour granularity covers days to weeks of market history.

---

## 6. The trading layer

The model's output is a probability distribution over next price-move tokens. This is converted into a trading decision by an explicit, cost-aware policy.

For each prediction, the trading layer derives:

- **Expected return**, weighted across the predicted bucket distribution.
- **Directional probabilities**, summed across up- and down-buckets.
- **Tail probabilities**, the mass on large adverse moves.
- **Confidence**, measured by the sharpness of the predicted distribution.

The decision rule compares the expected return against an estimate of the cost of trading, where cost includes spread, slippage, and a size-aware impact term. The rule looks like:

```
edge_after_cost = expected_return - cost(size) - risk_penalty
```

If `edge_after_cost` is strongly positive, long. If strongly negative, short. If neither, no trade. Size scales with the magnitude of the edge and inversely with predictive uncertainty.

A more aggressive variant: train the prediction loss with weights proportional to the magnitude of the price move, so the model is rewarded more for correctly predicting large moves than small ones. This aligns the optimization target with the trader's actual objective without requiring reinforcement learning.

The trading layer is not a black box on top of a prediction. It is a transparent function of a distribution the model produces, and every component can be inspected.

---

## 7. The MVP

The first version of this system is not a giant model. It is a deliberate test of whether the design choices work.

**What the MVP must do:**

- Tokenize multi-modal market state for a single chosen asset class and horizon.
- Train a small causal transformer (tens of millions of params) on a substantial chronological history.
- Produce calibrated probability distributions over next-token moves on out-of-sample data the model has never seen.
- Compare against three internal baselines: a one-layer linear model on the same features, a small MLP on the same features, and a single-channel version of itself (target-only, no market-context tokens). These tell us whether the architecture is doing work, whether the multi-modal tokenization is doing work, and whether the model is doing more than the simplest possible thing.
- Convert predictions to trades through the cost-aware decision layer, and report return, Sharpe, hit rate, and capacity-vs-impact behavior on the held-out period.

**What the MVP does not need to do:**

- Cover every asset class.
- Use reinforcement learning.
- Ingest natural-language news.
- Model a full order book or run at HFT speeds.
- Beat institutional desks in absolute return.

**What the MVP is testing:**

1. Whether the tokenization is learnable — does the loss decrease meaningfully across training.
2. Whether the multi-modal tokenization adds information beyond a single-channel model.
3. Whether the transformer adds information beyond a linear baseline on the same tokens.
4. Whether the predicted distributions are calibrated on out-of-sample data.
5. Whether the calibrated distributions, run through the cost-aware decision layer, produce a positive after-cost result on a chronological holdout.

Each of these is a separate, falsifiable question. The MVP either answers them clearly or it points to which assumption needs revising.

---

## 8. The design choices summarized

The system is defined by five specific commitments:

1. **Causal decoder transformer.** Standard architecture; no innovation here.
2. **Discrete next-token target over volatility-normalized return buckets.** The vocabulary is scale-invariant and trader-aligned.
3. **Multi-modal market-state tokens at each timestep.** The model sees target + correlated markets + liquidity + time/event context jointly.
4. **Cross-entropy training**, optionally weighted by move magnitude so the optimization target is aligned with what a trader cares about.
5. **Cost-aware decision layer** that consumes the full predicted distribution, not just a point estimate, and accounts for size-dependent impact.

None of these is exotic individually. The combination defines a specific shape of model that does not exist in any published implementation. The work tests whether that combination, designed deliberately, produces something the published prior art does not.

---

## 9. What this proposal is, and is not

This is a proposal to build a model and run a clean empirical test of whether a specific design choice — multi-modal market-state tokens predicting volatility-normalized return buckets through a small causal transformer — produces information that survives out-of-sample evaluation with realistic costs.

It is not a prediction about whether the model will be profitable. That is what the experiment answers.

It is not a claim that markets are easy. It is a claim that a specific corner of model design has not been seriously explored, and that the corner has structural reasons to be worth exploring: the input is richer than what any published causal market transformer has tokenized, and the target is closer to the variable a trader actually cares about than what any published model has predicted.

The work is run end-to-end before any judgments about whether the approach works. The empirical answer comes out of the held-out period, not out of priors.
