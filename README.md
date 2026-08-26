# large-price-model

*Python package: `price_space_llm` — the historical name. Kept for import stability.*

Research on whether a language-model architecture — a causal decoder transformer with attention over past tokens — learns anything useful when applied to price sequences. This repository is the record of the experiment.

## The question

The decoder-only transformer moved from text into vision, audio, and code. Each move produced something: images that read like images, code that runs, speech that transcribes. The move into price data is the natural next question. Does the same architecture, given prices instead of words, learn structure that a simpler model does not?

## The build

- Input: 20 channels of 15-minute state — SPY OHLCV features, cross-asset returns, macro releases, options metrics, event flags, session flags — aligned on a shared grid.
- Target: the next bar's return, discretized into 32 vol-normalized buckets.
- Model: a MarketStateTransformer with three interchangeable embedder variants (per-channel linear sum, cross-channel attention mixer, patch), a categorical or quantile head, four sizes from 0.8M to 25M parameters.
- Baselines: linear regression on past bucket ids, an MLP, a GRU, and a target-only auto-regression.
- Diagnostics: a bar walker that turns per-bar predictions into a decision stream, a position and trade ledger, mark-to-market equity, block-bootstrap Sharpe with standard error. Used as an instrument, not as a strategy.

The training corpus runs 2015-01 through 2022-12. A held-out slice from 2024-01 through 2025-06 was set aside at the start and read exactly twice, per a 3-look budget enforced by a filesystem guard and a commit-message hook.

## What the experiment found

Two things.

**The model learns something.** On the training-window validation split, the best transformer (mixer fusion, learning rate 3e-5, five-seed mean) reaches pooled log-loss 3.180 against a linear baseline at 3.333 — an improvement of 3.29%. Every seed beats linear. The improvement is small; the pre-registered target of 10% below linear was missed by a factor of three. But the direction is real and reproduces across seeds. A language-model architecture over price sequences does learn structure that a linear regression on past returns does not.

**The learned edge lives in the shape of the output distribution, not the mean.** The best model's mean forecast is essentially zero (expected return ~1e-6 in log-return units, p_up 0.4973). A downstream reader that decodes the distribution into a directional signal — "go long if expected value is positive" — captures none of the log-loss edge. The improvement over linear is a sharper distribution, not a shifted one. This holds on both the training-window validation split and the held-out window.

Full breakdown in [`reviews/phase-h-close.md`](reviews/phase-h-close.md).

## What is interesting about the result

The gap between "distribution improved" and "mean unchanged" is the finding. The transformer knows more than the linear baseline about which bucket is likely; it has learned nothing more about which side of zero the next return will land on. That is a shape-vs-location distinction language models rarely surface, because in text the shape and the mean of "what comes next" are the same object — the next word.

Prices decompose. A conditional distribution can grow more concentrated, or fatter-tailed, or bi-modal, without its mean moving at all. The 3% log-loss improvement can be entirely a variance or tail-shape effect and produce zero improvement in any decoder that reads a single scalar off the distribution.

That opens the next set of research questions: which components of the distribution the model actually improves, whether those components carry any signal a non-scalar decoder could use, and what the encoder is building in the high-dimensional representation space that produces the shape improvement without the mean improvement.

## What the project proves

A language-model architecture over 15-minute price bars trains end-to-end and produces a small but real improvement over a linear regression on past returns. That matches what the theory predicts.

A model that improves log-loss over linear does not automatically improve every downstream reading of the distribution. The improvement can live in one component (the shape) and be invisible to a decoder that only reads another (the mean).

Both results are the intended outputs. The successor project starts from them.

## Repository layout

```
src/price_space_llm/     the library
scripts/                 CLIs — ingest, align, features, bucketize, train, evaluate, simulate
tests/                   629 tests, `uv run pytest`
sprints/                 117 sprint cards, one per unit of work
signals/                 the locked signal vocabulary (v0.7)
reviews/                 code reviews, post-mortems, phase-close reports
specs/                   product spec v4, technical architecture v4
sdd-kit-2/               the methodology this project uses (Signal-Driven Development)
BLACKBOARD.md            the live coordination log
KIT_DIARY.md             per-sprint lessons and hypothesis tracking
WORKING_AGREEMENT.md     project overrides on the SDD kit
plans/                   the roadmap
```

## Reproducing a training run

```bash
uv sync --dev
uv run pytest                # 629 pass, 2 skipped

# Rebuild the tokenized artifact from raw:
#   scripts/ingest.py → scripts/align.py → scripts/features.py → scripts/bucketize.py
# (Cached data, checkpoints, and traces are gitignored.)

uv run python scripts/train.py \
  --tokens-pt data/tokenized/tokens.latest.pt \
  --model-size md \
  --fusion mixer \
  --lr 3e-5 \
  --n-steps 20000 \
  --device mps
```

The `--device` flag accepts `cpu`, `mps`, or `cuda`. The 116-sprint arc ran on an Apple M5 Max via MPS. AWS scaffolding lives in `scripts/aws/` as a scale-up option, not the primary environment.

## Methodology

The project runs under [Signal-Driven Development](sdd-kit-2/README.md). Every unit of work is a sprint card in `sprints/`. Every code path emits typed signals against a locked vocabulary (`signals/0.7.json`) that a `StrictSignalEmitter` validates at the call site. Every sprint closes with a Rubber Duck Pass on the emitted signal trace. Cross-sprint lessons land in `KIT_DIARY.md`.

For a first read: `BLACKBOARD.md` is the current-state summary. `reviews/phase-h-close.md` is the final result. `sprints/` is the audit trail.

## Successor

Working name: Large Price Model. Two workstreams named at phase close:

- A database at the highest resolution available. The structure of the data is part of the design, not a downstream constraint.
- Two research tracks — what the encoder builds in the representation space, and which cross-domain metaphors from language and vision carry into price data.

Written up separately when it exists.

## License

Apache 2.0. See [LICENSE](LICENSE).
