# large-price-model

A transformer predicts the next fifteen-minute SPY return. A simulator opens and closes positions based on those predictions and keeps a ledger.

The model reads eight years of fifteen-minute bars across twenty channels. One channel is SPY. The rest carry other stocks, currencies, macro releases, options, and calendar events. For each bar the model produces a probability distribution across thirty-two bins of the next return. A normalizer fit on the training window standardizes each channel. A linear regression on past bins is the baseline.

At each bar the simulator reads the model's distribution, decides whether to open, hold, or close a position, and records the trade. At the end it reports Sharpe with a bootstrapped error bar.

## What it found

The model beats the linear baseline on log-loss. Across five seeds the best configuration reaches 3.180 against a linear at 3.333. Every seed beats linear. The pre-registered target was ten percent below linear; the result is three percent below. The direction is real. The size is small.

The gain does not appear in the mean. The best model's mean prediction is near zero — about one part in a million. The probability the return is positive comes out to 0.4973: a coin flip. A rule that trades on the sign of the mean captures none of the log-loss gain. The transformer has learned more about which bin is likely. It has learned no more about which side of zero.

A distribution can grow sharper without shifting. Three percent of log-loss can hide inside its variance and its tails, invisible to any decoder that reads only the mean.

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

`--device` accepts `cpu`, `mps`, or `cuda`. The training ran on an Apple M5 Max via MPS. AWS setup scripts live under `scripts/aws/` if the training outgrows a laptop. Raw data, features, checkpoints, and traces are gitignored; rebuild them from `scripts/ingest.py` onward.

## Methodology

The project runs under Signal-Driven Development. Each task is a sprint card in `sprints/`. Every code path emits typed signals against the locked vocabulary at `signals/0.7.json`. A strict emitter checks each call as it is made. Each sprint closes with a review of the signals it emitted. Lessons that span sprints go into `KIT_DIARY.md`. See [`sdd-kit-2/README.md`](sdd-kit-2/README.md).

`BLACKBOARD.md` holds the current-state summary. `reviews/phase-h-close.md` holds the final result. `sprints/` holds the audit trail.

## Next

A database at the highest resolution available. The shape of the data is part of the model.

Two research tracks: what the encoder builds internally, and which ideas from language and vision transfer to price data.

Written up separately.

## License

Apache 2.0. See [LICENSE](LICENSE).
