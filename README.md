# large-price-model

*Python package: `price_space_llm` — the historical name. Kept for import stability.*

A causal decoder transformer trained on fifteen-minute SPY bars. The tokens are quantile bins of the next-bar return. The point was research, not trading: what happens in this specific narrow shape — decoder-only, thirty-two vol-normalized return bins as the vocabulary, twenty channels of state as input — and what does the log-loss gain over a linear baseline actually contain.

Transformers on price series are not new. Informer, TimesNet, PatchTST, and years of applied work came first. This repository is not a claim on the architecture family. It is a specific configuration, run end to end with a full downstream reader (a simulator) used as a diagnostic.

## What it does

The model reads twenty channels of state on a fifteen-minute grid: SPY features, other assets, macro releases, options metrics, event flags. It writes a probability distribution over thirty-two bins of the next bar's return. A frozen normalizer holds the training-window scale. A linear regression on past returns is the baseline.

Alongside the model sits a simulator: a bar walker, a position machine, a trade ledger, a Sharpe number with a standard error and a block-bootstrap distribution. The simulator was built to test the model, not to trade. It answers one question: does the log-loss improvement over linear survive being read as a directional signal?

## What it found

Two things.

The model learns something. Across five seeds, the best configuration reaches validation log-loss 3.180 against a linear baseline at 3.333 — an improvement of 3.29 percent. Every seed beats linear. The pre-registered target was ten percent; the margin fell short by roughly a factor of three. The direction is real, the magnitude is small, and it reproduces.

The improvement lives in the shape of the distribution, not the mean. The best model's mean prediction is essentially zero. Its p_up sits at 0.4973, a coin flip. A simulator that decodes the distribution into "which side of zero" captures none of the log-loss gain. The transformer knows more than the linear baseline about which bin is likely; it has learned nothing more about which half of the number line the next return will land on.

This is the interesting finding. In text, "what comes next" has one mean and one shape at once; the next word is the sentence. In prices they separate. A conditional distribution can grow sharper without shifting. Three percent of log-loss can hide entirely inside variance and tail shape, invisible to any reader that only looks at the mean.

That opens the successor's questions. Which parts of the distribution the model actually improved. Whether those parts carry a signal a non-scalar reader could use. What the encoder is putting into its representation space that shows up as shape and not location.

Full breakdown in [`reviews/phase-h-close.md`](reviews/phase-h-close.md).

## Repository layout

```
src/price_space_llm/     the library
scripts/                 CLIs — ingest, align, features, bucketize, train, evaluate, simulate
tests/                   629 tests, `uv run pytest`
sprints/                 117 sprint cards, one per unit of work
signals/                 the locked signal vocabulary (v0.7)
reviews/                 code reviews, post-mortems, phase-close reports
specs/                   product spec v4, technical architecture v4
sdd-kit-2/               the methodology this project uses
BLACKBOARD.md            the coordination log
KIT_DIARY.md             per-sprint lessons
WORKING_AGREEMENT.md     project overrides on the kit
plans/                   the roadmap
```

## Reproducing a training run

```bash
uv sync --dev
uv run pytest                # 629 pass, 2 skipped

uv run python scripts/train.py \
  --tokens-pt data/tokenized/tokens.latest.pt \
  --model-size md \
  --fusion mixer \
  --lr 3e-5 \
  --n-steps 20000 \
  --device mps
```

`--device` accepts `cpu`, `mps`, or `cuda`. The full arc ran on an Apple M5 Max via MPS. AWS scaffolding lives in `scripts/aws/` as a scale-up option. Raw data, features, checkpoints, and traces are gitignored; rebuild them from `scripts/ingest.py` onward.

## Methodology

The project runs under Signal-Driven Development. Every unit of work is a sprint card in `sprints/`. Every code path emits typed signals against a locked vocabulary at `signals/0.7.json`; a strict emitter validates each call at the source. Every sprint closes with a walk over its emitted trace. Cross-sprint lessons land in `KIT_DIARY.md`. See [`sdd-kit-2/README.md`](sdd-kit-2/README.md).

For a first read: `BLACKBOARD.md` is the current-state summary. `reviews/phase-h-close.md` is the final result. `sprints/` is the audit trail.

## Successor

Working name: Large Price Model. Two workstreams. First, a database at the highest resolution available — the structure of the data is part of the model, not a downstream constraint. Second, two research tracks: what the encoder builds in the representation space, and which cross-domain metaphors from language and vision carry into price data.

Written up separately when it exists.

## License

Apache 2.0. See [LICENSE](LICENSE).
