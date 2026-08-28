# large-price-model — text-market experiments

This document catalogs eight research programs the text-market architecture (see `text-integration-v1.md`) enables. Each is self-contained: a hypothesis, a methodology, and a theoretical contribution independent of any trading application. Where a program does not need the full text-integration stack, that is named in the program's methodology.

These are not sprints. Each is a program that would span many sprints. The purpose of the catalog is to keep the ideas on file so the operator can pick which program to open when the earlier work in the main spec (`large-price-model-v1.md`) and the text-integration architecture (`text-integration-v1.md`) reach a point where the program becomes actionable.

Each program shares a common thread. None asks "does this make money?" Each asks: what does the relationship between text and markets reveal about information processing, causality, or the structure of the economy?

## Program 1 — Information diffusion latency as the target

Instead of predicting returns, predict the time lag between the appearance of a textual concept and its incorporation into market prices. Different information diffuses at different rates. A tweet about a CEO resignation may affect prices in minutes. A demographic trend in a UN report may take months. A scientific breakthrough in battery technology may take years.

**Methodology.** For each text document, compute its embedding. Compute the cross-correlation between the embedding (or specific concept dimensions within it) and subsequent market movements across a range of time horizons — one hour, one day, one week, one month, one year. Train the model to output a diffusion distribution over these lags for each incoming text. The ground truth is the lag at which the text's predictive power for returns peaks.

**Theoretical contribution.** A direct empirical measure of information friction. Tests whether markets incorporate all information instantly (peak at zero lag) or whether significant lags exist across different textual domains. The model becomes an instrument for studying the speed of information assimilation, not a predictor of price direction. No existing work predicts the temporal structure of information integration; most feeds text in and looks for immediate price impact.

## Program 2 — Counterfactual price formation

Treat textual events as treatments in a causal inference framework. Estimate the conditional average treatment effect of a specific text on subsequent price distributions.

**Methodology.** Given the market state at time t and a text document that appears at t, ask what the price distribution would have been at t+1 if that text had not appeared. Train a conditional generative model — a diffusion model, a normalizing flow, or a mixture density network — that outputs the distribution of future returns conditioned on both the numerical market state and the text embedding. Train a second model conditioned on the market state alone. The difference between the two conditional distributions is the causal effect of the text. For real-time inference, use a causal transformer that explicitly separates confounders (market history) from treatments (text).

**Theoretical contribution.** Moves the analysis from correlation to causation. Identifies which textual concepts are causally related to market outcomes, not merely correlated with them. A direct test of the information content of text, not its predictive value. Causal ML in finance is nascent and mostly limited to macro variables (interest rates, GDP). Applying it to arbitrary text is unexplored.

## Program 3 — Semantic state inversion

Reverse the direction. Given a sequence of market price movements, generate the textual narrative that best explains that movement.

**Methodology.** Train a conditional generative model — an autoregressive language model, or a diffusion model over text embeddings — that takes a sequence of numerical market states and outputs a textual summary. The training objective reconstructs the text that was actually present in the corpus during the corresponding time period. Use a contrastive loss to ensure the generated text is distinct from the actual text but captures the same latent state.

**Theoretical contribution.** If the model accurately generates the narrative that explains a price move, it demonstrates that the numerical encoder's latent representation captures the same semantic structure as natural language — a test of representational alignment between the financial and linguistic domains. It also provides a diagnostic: if the generated narrative is nonsensical, the numerical encoder is not capturing meaningful structure. Analysts could use the model to read what the market is thinking from price action alone.

## Program 4 — Topological regime discovery via textual embeddings

Use the textual corpus to discover macro-regimes standard economic indicators do not capture. Regimes (risk-on, inflation scare, AI bubble) are usually defined heuristically. Text contains rich conceptual clusters that may correspond to latent economic states.

**Methodology.** For each time window, compute an aggregate text embedding — mean-pooled, max-pooled, or attention-weighted across the documents in the window. Apply unsupervised clustering (HDBSCAN) to these window embeddings. Map the clusters to market characteristics (realized volatility, correlation structure, factor returns) and test whether the clusters are statistically distinct on those characteristics. Use persistent homology from topological data analysis to identify stable clusters over time and detect phase transitions between them.

**Theoretical contribution.** A data-driven typology of market regimes that is not constrained by economic theory. Uncovers regimes economists have not named, or reveals that certain regimes are artifacts of textual noise. Combining textual semantics with topological persistence is novel — topological methods have been applied to price data alone, but not to multi-modal text-price alignment.

## Program 5 — Information entropy divergence as a volatility leading indicator

When a large volume of diverse text arrives (high textual entropy) but the market remains stable (low predictive entropy for prices), latent information has built up that is not yet priced. When the divergence resolves, volatility should spike.

**Methodology.** Textual entropy: compute the Shannon entropy or the perplexity of the text embedding distribution over a rolling window. Predictive entropy: compute the entropy of the model's output distribution over returns. Compute the rolling difference or ratio between the two. Test whether extreme values of this divergence predict subsequent realized volatility, benchmarked against a GARCH or realized-volatility baseline.

**Theoretical contribution.** An information-theoretic measure of latent market pressure. Not a directional signal — a volatility predictor independent of option prices. If it works, textual information flow precedes price adjustment. Entropy comparison across modalities is rare in finance; most work focuses on sentiment polarity rather than information volume or diversity.

## Program 6 — Learnable temporal granularity

Allow the model to dynamically select the temporal resolution at which it processes both text and prices. Different information operates at different scales; instead of fixing a 15-minute window, let the model learn which aggregation level is most predictive for a given context.

**Methodology.** Use a multi-scale Transformer or a pyramid network that processes the same data at multiple resolutions (5-minute, 15-minute, hourly, daily). Use a learnable gating mechanism — attention over scales — to select the relevant resolution for each prediction. For text, maintain separate embedding histories at the same resolutions. The model outputs predictions at all resolutions; a secondary network learns which resolution to trust for each query.

**Theoretical contribution.** Tests whether market dynamics are fundamentally multi-scale and whether the model can identify scale-dependent structure. Moves away from the arbitrary choice of a fixed window size. Adaptive multi-scale architectures exist in computer vision but are rarely applied to financial time-series, and almost never to cross-modal text-price data. This program does not require the full text-integration architecture — the same idea applies to price-only models.

## Program 7 — Systematic ablation as a discovery engine

Instead of asking what works, ask under what conditions the model completely fails. A systematic mapping of failure modes reveals the boundary conditions of predictability.

**Methodology.** Systematically ablate subsets of the input — text categories (social media, books, scientific papers), instrument subsets (single-name vs cross-asset), horizon subsets (only long-term, only short-term features). Measure the drop in performance (log-loss, CRPS, direction-specific metrics). Input categories whose removal causes the largest drop are the most informationally relevant. Categories expected to be relevant that produce no drop are redundant.

**Theoretical contribution.** A direct empirical test of information redundancy and source relevance. Quantifies the marginal value of each input category. Ablation studies are standard practice, but systematic ablation across broad textual categories has not been done for financial prediction. The pattern of what matters and what does not is the finding, independent of any absolute performance number.

## Program 8 — Self-supervised alignment as a foundation objective

Do not train on any supervised target initially. Train the model purely on alignment tasks between text and prices. Create a foundation model that learns a joint embedding space where semantically related text and market states are close, without any explicit prediction objective.

**Methodology.** Use a contrastive loss such as InfoNCE. Positive pairs are text and price windows that are contemporaneous within a defined tolerance. Negative pairs are randomly mismatched windows across time. The model learns to map both modalities into the same embedding space. After pre-training, freeze or fine-tune the model for downstream tasks — direction prediction, volatility, regime classification, any of the other seven programs listed here.

**Theoretical contribution.** Tests whether there is a fundamental semantic alignment between language and markets. If the model reliably pairs text with concurrent price movements, the textual corpus and the price dynamics share a common latent structure. If it cannot, the two modalities are fundamentally disconnected. Contrastive pretraining has been successful for vision-language (CLIP) and audio-text; it is almost unexplored for financial text-price alignment. This program deepens the existing Q3 "contrastive pretraining" bullet in the main spec and, if it succeeds, becomes the pretraining objective the text-integration architecture is built on top of.

## Position relative to the other specs

- **`large-price-model-v1.md`** — three co-equal open research questions. Programs 6 (multi-scale), 7 (systematic ablation), and 8 (self-supervised alignment) have direct homes in that spec's Q3 candidate transfers or Q2 retraining experiments. The main spec references them from those homes.
- **`text-integration-v1.md`** — the architectural instrument for text-price modeling. Programs 1 through 5 require the full text-integration stack (embeddings, retrieval, cross-attention, latent regime). Program 8 is a candidate pretraining objective for that architecture.
- **This document** — a research-program catalog at the experiment altitude, sitting alongside `text-integration-v1.md`. It becomes active when the operator picks a program to open. Each program lands as its own multi-sprint arc under its own sprint cards; the catalog just holds the design brief.
