# large-price-model

A transformer predicts the next fifteen-minute return of the SPDR S&P 500 ETF (SPY). A simulator opens and closes positions based on those predictions and keeps a ledger.

## How it works

The model reads eight years of fifteen-minute bars — 2015 through 2022 — across twenty parallel time series. One is SPY itself. The rest carry other stocks, currencies, macro releases, options data, and calendar events. For each bar the model outputs a probability distribution over thirty-two buckets of the next return. The buckets are quantiles of the training-set return distribution, so each holds roughly the same number of training examples. This turns return prediction into bucket classification — the kind of task a language-model architecture (attention over past tokens) is built for.

Two safeguards keep the held-out data honest. A normalizer scales each channel using statistics computed only over 2015-2022, so the model never sees held-out data. A held-out window covering 2024-01 through 2025-06 was set aside before training and may be read at most three times over the project's lifetime, enforced by a filesystem guard and a commit-message hook.

The baseline is a linear regression on the sequence of past bucket labels — no attention, no channels other than the target's own history. It captures whatever structure lives in the returns themselves.

At each bar the simulator reads the model's distribution, decides whether to open, hold, or close a position, and records the trade. At the end it reports Sharpe — average return divided by return volatility, annualized — with an error bar from block-bootstrap resampling.

## What it found

The model beats the baseline on log-loss, the standard measure of how much probability a model puts on the correct next bucket. Across five seeds the best configuration reaches 3.180 against a linear baseline at 3.333. Every seed beats linear. The pre-registered target was ten percent below linear; the result is three percent below. The direction is real. The size is small.

The gain does not appear in the mean. Log-loss falls from 3.333 to 3.180 while the mean prediction stays within a millionth of zero. The probability of a positive return comes out to 0.4973: a coin flip. A rule that trades on the sign of the mean captures none of the log-loss gain. The transformer has narrowed its bet on which bucket the return will land in. It has not moved its bet on the direction.

Log-loss rewards a good probability on the right bucket. A model can improve it by moving probability mass around inside the distribution without moving the distribution's center. Bucket and direction are separate facts about a return; a directional strategy reads only the second.

Full breakdown in [`reports/phase-h-close.md`](reports/phase-h-close.md).

## Repository layout

```
src/price_space_llm/     the library
scripts/                 CLIs — ingest, align, features, bucketize, train, evaluate, simulate
tests/                   629 tests, `uv run pytest`
sprints/                 117 sprint cards, one per unit of work
signals/                 the locked signal vocabulary (v0.7)
reports/                 phase-close reports
postmortems/             bug post-mortems
reviews/                 code reviews and discipline checks
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

The project runs under Signal-Driven Development. Every code path emits a typed event against a locked vocabulary. Every task begins as a sprint card that declares what it will do and what events it will produce. Each task lives in `sprints/`. The vocabulary lives at `signals/0.7.json`. A strict emitter checks each call as it is made. Each sprint closes with a review of the signals it emitted. Lessons that span sprints go into `KIT_DIARY.md`. See [`sdd-kit-2/README.md`](sdd-kit-2/README.md).

`BLACKBOARD.md` holds the current-state summary. `reports/phase-h-close.md` holds the final result. `sprints/` holds the audit trail.

## Next

A database at the highest resolution available. The shape of the data is part of the model.

Two research tracks: what the encoder builds internally, and which ideas from language and vision transfer to price data.

Written up separately.

## License

Apache 2.0. See [LICENSE](LICENSE).
