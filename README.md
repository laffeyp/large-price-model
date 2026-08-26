# large-price-model

A transformer predicts the next fifteen-minute SPY return. A simulator walks the bars, trades on those predictions, and keeps a ledger. This repository holds both, and the record of what they produced.

The model reads eight years of fifteen-minute bars across twenty channels: SPY on one, and on the other nineteen other stocks, currencies, macro releases, options figures, and calendar events. It outputs a probability across thirty-two bins of the next return. A normalizer fit on the training window holds the scale. A linear regression on past bins is the baseline.

The simulator walks the bars, opens and closes positions on the model's predictions, keeps a trade ledger, and reports Sharpe with a bootstrapped error bar.

## What it found

The model beats the linear baseline on log-loss. Across five seeds the best configuration reaches 3.180 against a linear at 3.333. Every seed beats linear. The pre-registered target was ten percent below linear; the result is three percent below. The direction is real. The size is small.

The gain does not appear in the mean. The best model's mean prediction is near zero — expected return around one millionth of a log-return unit, p_up 0.4973. A rule that trades on the sign of the mean captures none of the log-loss gain. The transformer has learned more about which bin is likely. It has learned no more about which side of zero.

That gap between shape and side is the finding. A distribution can grow sharper without shifting. Three percent of log-loss can hide inside variance and tail shape, invisible to any decoder that reads only the mean.

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

`--device` accepts `cpu`, `mps`, or `cuda`. The arc ran on an Apple M5 Max via MPS. AWS scaffolding under `scripts/aws/` is a scale-up option. Raw data, features, checkpoints, and traces are gitignored; rebuild from `scripts/ingest.py` onward.

## Methodology

The project runs under Signal-Driven Development. Every unit of work is a sprint card in `sprints/`. Every code path emits typed signals against the locked vocabulary at `signals/0.7.json`. A strict emitter validates each call at the source. Every sprint closes with a walk over its trace. Cross-sprint lessons land in `KIT_DIARY.md`. See [`sdd-kit-2/README.md`](sdd-kit-2/README.md).

For a first read: `BLACKBOARD.md` is the current-state summary. `reviews/phase-h-close.md` is the final result. `sprints/` is the audit trail.

## Next

Two workstreams named at the close of this phase.

A database at the highest resolution available. The structure of the data is part of the model, not a downstream constraint.

Two research tracks: what the encoder builds in its representation, and which ideas from language and vision transfer to price data.

Written up separately.

## License

Apache 2.0. See [LICENSE](LICENSE).
