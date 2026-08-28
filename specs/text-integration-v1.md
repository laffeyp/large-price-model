# large-price-model — text-integration proposal

This document proposes an architecture for a further phase of the project — beyond the immediate work laid out in `large-price-model-v1.md`. It ships as a companion spec because the ideas here are architecturally specific and further out on the horizon than the three co-equal questions in the main spec. It lands in the spec set so the design is on file for when the earlier work reaches the point where these questions become the next questions.

## Why text at all

The three-question spec's Q1 treats "data" as numeric time series — price, quote, trade, whatever resolution and instrument set the research picks. That is one shape of data. Text is another. Books, social media, political speech, scientific publication, government reports, cultural commentary, product releases: each is an artifact of some latent state of the world, and each state can influence prices at some lag through some mechanism.

Financial news is the narrow, obvious subset of text that touches markets. It is also the least useful subset for a research project. Financial news is written after market moves, not before — the causal direction is often reversed. It is already priced by the time a journalist writes it. It covers days, not decades. A novel published in 1974 may hold themes that foreshadow economic shifts a decade later; a Reuters headline holds none of that structure.

The research question the arbitrary-text architecture answers: **do asset prices reflect all publicly available information, including the broad cultural and scientific information present in arbitrary text, not just explicit market commentary?** That is a direct empirical test of the information frontier. The answer is scientifically valuable whether it is yes or no.

## First principles

Text as a data source has four properties price data does not.

- **Text is a proxy for latent states.** Political sentiment, scientific progress, cultural mood, public health, energy concerns. These states influence markets indirectly and with variable lag. The text is not the state; it is a snapshot of the state.
- **Relevance is learned, not prescribed.** No one knows in advance which corpus best predicts which market. The model has to identify which textual features correlate with market dynamics — that decision is not made in advance by a domain expert.
- **Temporal structure is heterogeneous.** A tweet affects prices in minutes. A regulatory filing affects them over months. A demographic study affects them over years. The lag is not one number.
- **Volume is a feature.** The frequency of text mentioning a topic — COVID, AI, tariffs — is signal on its own, independent of sentiment.

## Architecture

Four components. Each is designed for text's structural properties above.

### Universal text embedding

Use a general-purpose embedding model (E5, BGE, Llama-family embeddings) rather than a domain-specific one (FinBERT). A general model preserves information about concepts outside finance — themes, terminology, cultural references — that a financial model would discard as irrelevant. The downstream model learns which dimensions of the embedding correlate with market dynamics; that decision does not need to be made in advance by the embedding step.

Do not fine-tune the embedding model on financial text initially. Let the general representation stand. Fine-tuning happens later if the downstream signal points at specific dimensions the general model under-weights.

### Temporal aggregation with decay

Text arrives asynchronously. Each document has a timestamp; its relevance may peak at the timestamp and decay, or persist, or arrive with a delay.

For each prediction window, maintain a text history — the last N documents by timestamp. Weight each document's embedding by a time-decay function with a learnable half-life. Group documents by source (news, social, books, papers, government) and learn per-source decay rates: news decays fast, books slow.

Alternative or complement: compute rolling embeddings at daily, weekly, and monthly horizons. Feed all three as separate input channels. The model chooses which horizon carries signal for a given prediction.

### Sparse attention over retrieved text

The full text corpus is too large to feed directly into cross-attention with numerical data. A two-stage design handles the scale.

- **Retrieval.** For each prediction window, retrieve the top-K documents from the corpus that are most relevant to the current market state. Relevance is learned via a similarity metric — dot product between a market-state query embedding and each document's text embedding. The retrieval index is precomputed offline via a vector database (FAISS or similar). The similarity metric is fine-tuned during training so retrieval improves prediction.
- **Cross-attention fusion.** Only the top-K retrieved documents pass through cross-attention with the numerical stream. Text attends to numbers; numbers attend to text. K stays small (10-50 documents) so the cross-attention cost stays bounded. Efficient attention variants (Linformer, Performer) keep the cost linear in K.

Strict timestamp filtering prevents look-ahead: only documents whose timestamps precede the current prediction window are eligible for retrieval.

### Latent regime from text

Text can be used to classify the current regime (risk-on, risk-off, geopolitical stress, technological optimism). Reduce the text history to a small set of latent factors — via a variational autoencoder, clustering on embeddings, or a discrete regime classifier trained end-to-end. These factors are concatenated to the numerical input as auxiliary features. The Transformer processes the numerical data conditioned on the textual regime.

This step is a compression: it reduces the dimensionality of the text signal while preserving its high-level structure. Useful when the numerical model needs to know "we are in a risk-off regime" without also needing every document that established that fact.

## The pipeline

Inputs: a numerical tensor of past bars across assets, and a time-indexed text corpus of arbitrary content.

1. **Document embedding.** Encode each document to a vector using the frozen general-purpose embedding model. Store in a vector database with timestamp and source metadata.
2. **Query construction.** For each prediction window, build a query vector from the recent market state and optionally the current latent regime.
3. **Text retrieval.** Retrieve the top-K document embeddings from the vector database, filtered by timestamp to prevent look-ahead.
4. **Cross-attention fusion.** Pass the numerical sequence through a Transformer encoder. Pass the retrieved documents through a separate encoder or use their embeddings directly as tokens. Apply cross-attention between the two streams.
5. **Prediction head.** Output a distribution over returns — categorical, parametric, or whatever the current experiment specifies.
6. **Auxiliary tasks (optional).** Predict text source to force embeddings to preserve source structure. Reconstruct text embedding from the fused representation to maintain semantic content. Predict temporal distance to next text event to learn text arrival dynamics.

## Empirical questions this architecture answers

- Do arbitrary texts improve distributional accuracy beyond price and financial news?
- Which text sources are most predictive — books, social media, scientific publications, government reports, cultural commentary?
- What lag structure dominates — immediate reaction, days-later diffusion, years-later realization?
- Does text predict variance or direction? Does text primarily affect the variance (uncertainty) rather than the mean?
- Does the model identify non-obvious signals — for example, do science-fiction themes correlate with tech-stock volatility?
- Is text information already fully priced? If broadening the corpus adds no predictive power, the semi-strong efficient market hypothesis holds for the broadest possible information set — a substantive negative result.

## Implementation roadmap

Five phases. Each is a natural sprint boundary.

**Phase 1: build the corpus.** Assemble a time-indexed corpus of diverse text: Project Gutenberg with published dates; Wikipedia with edit timelines; timestamped social media; AP and Reuters across all categories; arXiv and PubMed abstracts with publication dates; government reports (Congressional records, Federal Reserve statements, agency filings). Every document must have a timestamp at daily or finer granularity. This is a substantial data-engineering effort and probably lands as its own multi-sprint arc.

**Phase 2: embed and index.** Choose a general-purpose embedding model. Embed every document. Store the vectors and metadata in a FAISS index.

**Phase 3: retrieval strategy.** Compare fixed-window retrieval (all documents from the last N days), relevance-based retrieval (highest cosine similarity to market state), and hybrid retrieval (weighted combination of recency and relevance). Measure how each affects downstream prediction.

**Phase 4: train and evaluate.** Add the textual inputs to the current architecture. Compare numerical-only, numerical-plus-financial-news, numerical-plus-all-text under each retrieval strategy. Evaluate on log-loss, CRPS, and conditional-mean bias. Analyze attention weights to identify which text features drive predictions.

**Phase 5: interpretability.** For each prediction, identify the top documents attended to. Manually inspect them: are they causally plausible? Use SHAP or a similar attribution method to identify which embedding dimensions are most predictive.

## Practical constraints

Corpus size runs into terabytes. Mitigation: precompute embeddings offline; use vector retrieval to avoid full-corpus scans at inference.

Temporal alignment is strict. Every document's timestamp must precede the prediction window it can inform. Look-ahead leakage is the single easiest way to invalidate a text-augmented result.

Most text is irrelevant to any given prediction. Retrieval plus attention is designed to filter noise; the risk is that the retrieval metric learns to ignore documents that do carry signal but are rare. Auxiliary reconstruction tasks help preserve information in the embedding that the retrieval might otherwise discard.

Cross-attention over even K=50 retrieved documents multiplies per-step compute. Efficient attention variants (Linformer, Performer) keep the growth linear in K.

Interpretability requires post-hoc analysis of sparse attention patterns and embedding dimensions. Any positive result has to survive that inspection — a model that improves prediction but attends to documents whose relevance no human can defend is a model with a hidden confound.

## Framing

This architecture is not a trading model. It is a generalized information-processing system. Its findings are theoretical contributions, independent of any subsequent trading use.

A positive result — arbitrary text improves distributional accuracy in ways price and financial news do not — identifies latent causal factors the current information framework misses.

A negative result — broadening the text corpus adds nothing — is equally valuable. It suggests markets are informationally efficient with respect to the broadest possible information set, a finding that would require significant revision of behavioral finance theories.

## Position relative to the main spec

This proposal is further out on the horizon than the three co-equal questions in `large-price-model-v1.md`. Q1's "how do we get the data we need" starts with numeric time series because that is the immediate next question. Text integration is the natural extension of Q1 once the numeric data question has answers. Q3's retrieval-augmentation candidate is the seed of the architecture proposed here. Q2's interpretability techniques apply directly to the retrieved-document attention weights.

This document sits in the spec set so the design is on file. It becomes active work when the earlier phase's findings point at it — or sooner, if the operator judges text is the more valuable question.

## Companion — research programs

`text-market-experiments-v1.md` catalogs eight research programs the architecture proposed here enables. Program 8 (self-supervised alignment) is the strongest candidate for the pretraining objective this architecture is built on top of — a CLIP-style contrastive loss on contemporaneous text-price pairs, trained before any supervised target. Programs 1 through 5 (diffusion latency, counterfactual price formation, semantic state inversion, topological regime discovery, entropy divergence) all require this architecture to run. Program 6 (multi-scale) and Program 7 (systematic ablation) apply beyond this architecture but fit naturally on top of it.
