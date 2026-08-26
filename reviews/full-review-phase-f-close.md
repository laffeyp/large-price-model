# Full review — Phase F close (sprints 095-099)

**Reviewer:** Claude Code (Opus 4.7), acting in Agent role.
**Date:** 2026-08-18.
**Scope:** the five sprints closing Phase F. Sprint 095 review-074-094 fixes; Sprint 096 position state machine + trades; Sprint 097 metrics + block bootstrap; Sprint 098 capacity sweep; Sprint 099 kappa sensitivity plot. New `src/price_space_llm/simulation/` package now at 8 files, 1,744 lines. Test count 543 → 585 (+42). Vocabulary version unchanged at v0.7.
**Verdict:** Phase F closes with every pre-registered signal wired. The walker family works. Three design-pattern-shaped items and four Python-basics performance items belong in a Phase G refactor before the Sprint 084 GPU sweep hits the block-bootstrap hot path. One correctness-of-reporting item (single-trade equity vs continuous mark-to-market) needs a rationale-doc note so Sprint 088 held-out numbers are read honestly.

---

## 1. What Phase F built

Eight files under `simulation/`:

| file | lines | responsibility |
|---|---|---|
| `skeleton.py` | 709 | four walker variants + position-transition helpers |
| `metrics.py` | 241 | Sharpe + drawdown + block bootstrap + equity curve |
| `policy.py` | 199 | edge + variance_vn + decide + PolicyConfig |
| `sensitivity.py` | 144 | kappa-multiplier sweep + zero-crossing flag |
| `capacity.py` | 147 | position-size sweep + capacity_usd derivation |
| `positions.py` | 118 | Position/Trade dataclasses + compute_pnl + prices-from-log-returns |
| `prediction.py` | 96 | PredictionScalars + derive_prediction_scalars |
| `__init__.py` | 90 | package surface |

Every one of the previously-deferred simulator vocabulary tags fires from live code: `SIM_RUN_STARTED`, `BAR_PROCESSED`, `SIM_RUN_COMPLETED`, `PREDICTION_EMITTED`, `DECISION_MADE`, `SIGNAL_DROPPED`, `POSITION_OPENED`, `POSITION_CLOSED`, `TRADE_LEDGERED`, `CAPACITY_SWEEP_COMPLETED`, `SENSITIVITY_PLOT_GENERATED`. Eleven tags. Zero unwired.

The seven `SIM_RUN_COMPLETED` payload fields all populate from live math: `sharpe_point`, `sharpe_se`, `block_bootstrap_positive_fraction`, `max_drawdown`, `time_to_recovery_bars`, `n_trades`, `implied_capacity_at_this_size_usd` — the last only meaningful under Sprint 098's capacity sweep, correctly zero for a single sim run.

---

## 2. Architecture: four walker variants share heavy duplication

`skeleton.py` contains four `run_simulation_*` functions built incrementally sprint-by-sprint:

- `run_simulation_skeleton` (Sprint 092) — no model.
- `run_simulation_with_predictions` (Sprint 093) — adds forward + PREDICTION_EMITTED.
- `run_simulation_with_policy` (Sprint 094) — adds decide + DECISION_MADE + SIGNAL_DROPPED.
- `run_simulation_with_trades` (Sprint 096) — adds position state machine + trades + P&L.

Each walker duplicates: the bar iteration `for t in range(context_len, n_rows)`; the feats-window slicing dictionary comprehension; `model.eval()` + `torch.no_grad()` context; softmax over last-position logits; `_timestamp_iso` (or inline equivalent); `SIM_RUN_STARTED`/`SIM_RUN_COMPLETED` bookending with placeholder `checkpoint_step=0` and `checkpoint_run_id="sprint-NNN-no-checkpoint-id"` defaults. Four copies of each. `run_simulation_with_predictions` and `run_simulation_with_policy` also each contain their own duplicated `train_means = torch.tensor([row.train_mean for row in per_bucket], dtype=torch.float32)` construction.

That is Template Method-shaped duplication in a language with first-class functions. Every extension of the walker means a fifth copy. When Sprint 100+ adds a fifth capability (e.g. mark-to-market equity), the choices become: (a) write a fifth walker with the whole loop duplicated again; (b) mutate the current four; (c) refactor to one walker with pluggable per-bar hooks. Option (c) is the Python-idiomatic path per Norvig — the Template Method dissolves into a list of hooks the walker composes.

Concrete shape:

```python
BarHook = Callable[[BarContext], None]

def run_walker(
    artifact: TokenizedArtifact,
    *,
    hooks: Sequence[BarHook],
    emitter: StrictSignalEmitter,
    ...
) -> SimResult:
    for t in range(context_len, n_rows):
        ctx = BarContext(t=t, artifact=artifact, ...)
        for hook in hooks:
            hook(ctx)
```

`PredictionHook`, `PolicyHook`, `PositionHook`, `MetricsHook` each own their state. `SimResult` becomes an aggregation of what each hook produced. Every existing walker becomes `run_walker(artifact, hooks=[PredictionHook(...), PolicyHook(...), PositionHook(...)])`. Test each hook in isolation. New capabilities add a hook, not a walker.

Named as a Phase G refactor candidate rather than a Phase F blocker. The four walkers work; the duplication does not corrupt output. It compounds maintenance cost per future extension.

**Additional structural notes:**

- `SimResult` carries twelve fields, most defaulting to zero because different walker variants populate different subsets. The `notes: str = "skeleton"` field discriminates "skeleton" / "predictions-only" / "predictions+policy" / "predictions+policy+trades" — a string field doing enum work. Better: `kind: Literal["skeleton", "predictions", "policy", "trades"]` for a checkable discriminator, or split into a discriminated union `SkeletonResult | PredictionsResult | PolicyResult | TradesResult` with a shared protocol.
- `skeleton.py` at 709 lines is the largest module in the project. Extracting the position-transition helpers (`_close_position_and_record`, `_emit_position_opened`, `_emit_position_closed`, `_emit_trade_ledgered`) into `positions.py` next to their dataclasses would drop it by ~130 lines and cluster the position machinery in one place.

---

## 3. Python-basics: four performance items on the GPU-run hot path

The Sprint 084 GPU sweep will run the walker + block bootstrap thousands of times across the six-axis dispatch space. Four constructs will dominate wall-clock; each has an idiomatic vectorized fix.

**3.1 `derive_prices_from_log_returns` iterates in Python** (`positions.py:105`):

```python
for i in range(n):
    r = float(raw_targets[i].item())
    if math.isfinite(r):
        running = running * math.exp(r)
    prices[i] = running
```

For 54,262 bars this is 54,262 Python-level tensor scalar-conversions, 54,262 `math.exp` calls, 54,262 tensor stores. Fully vectorizable:

```python
safe_returns = torch.where(torch.isfinite(raw_targets), raw_targets, torch.zeros_like(raw_targets))
log_prices = torch.cumsum(safe_returns, dim=0)
prices = torch.exp(log_prices).to(torch.float64)
```

Order-of-magnitude faster. Loses the "NaN holds last valid price" semantic literally — but the semantic result is identical because a NaN return means zero log-return means the price stays flat between bars, which is what the loop implements when it skips the multiply.

**3.2 `block_bootstrap_sharpe` runs a Python loop over 10,000 resamples** (`metrics.py:164`):

```python
for i in range(n_resamples):
    idx = rng.integers(0, n_available, size=n_blocks)
    resample = blocks[idx].reshape(-1)
    sharpes[i] = compute_sharpe(resample, bars_per_year)
```

Each iteration calls `compute_sharpe` which invokes `float(bar_pnl.mean())` and `float(bar_pnl.std(ddof=0))` in Python. 10,000 iterations × ~3 conversions × ~2 numpy reductions = ~60,000 numpy calls per sim run. Vectorizable in one pass:

```python
idx = rng.integers(0, n_available, size=(n_resamples, n_blocks))
resamples = blocks[idx].reshape(n_resamples, n_blocks * bars_per_block)
means = resamples.mean(axis=1)
stds = resamples.std(axis=1, ddof=0)
sharpes = np.where(stds > 0, np.sqrt(bars_per_year) * means / stds, 0.0)
```

One numpy call each for indexing, reshape, mean, std, and Sharpe. Bootstrap goes from ~0.5s to ~0.01s on a typical held-out run. Multiply by sweep size (six sizes × two ablations × four size configs × 3-look budget) and the win compounds.

**3.3 `build_equity_curve` uses `bisect_right` in a Python loop** (`metrics.py:73`):

```python
sorted_bar_ts = [ts.timestamp() for ts in bar_timestamps_utc]
for tr in trades:
    exit_epoch = tr.exit_ts_utc.timestamp()
    idx = bisect_right(sorted_bar_ts, exit_epoch)
```

Fine at hundreds of trades. When the Sprint 084 GPU-trained model produces thousands of trades per held-out run, `numpy.searchsorted` on a vectorized `exit_epochs` array closes it in one call.

**3.4 Repeated `train_means` construction across walker variants.** Every walker builds:

```python
train_means = torch.tensor([row.train_mean for row in per_bucket], dtype=torch.float32)
```

Rebuilt on each walker call. Move to a cached property on `BucketStats`:

```python
@cached_property
def train_means_tensor(self) -> torch.Tensor:
    return torch.tensor([row.train_mean for row in self.per_bucket], dtype=torch.float32)
```

Then every walker reads `bucket_stats.train_means_tensor`. Small per-call, non-trivial across the sweep.

---

## 4. Correctness observations

**4.1 Single-trade equity curve makes Sharpe under-report.** Sprint 097's `build_equity_curve` steps `equity[t]` at trade exits: continuous holds appear as flat plateaus followed by a single step at close. Sharpe on `bar_pnl = diff(equity)` becomes dominated by the single-bar jump at trade exit. For strategies that hold for hundreds of bars (Sprint 097's live smoke: one 334-bar hold), Sharpe collapses to near-zero regardless of the underlying return profile.

Tech-arch §11.5 prescribes bar-by-bar mark-to-market of open positions. Sprint 097's card names the approximation: *"first cut ignores mark-to-market of currently-open positions."* Honest. But the reported `sharpe_point` in a Sprint 088 held-out run will not match what a Reviewer expects from the continuous mark-to-market Sharpe the spec implies. Two consequences:

- Sprint 088 held-out results labeled "Sharpe" will read as much smaller than the same strategy under mark-to-market Sharpe. If the pre-registered gate `Sharpe > 0.5` fails on the step-function reading, the failure may be an artifact of the equity-curve approximation, not the underlying strategy.
- The three pre-registered gates that consume Sharpe — `Sharpe > 0.5`, `Sharpe − 1·SE > 0`, `block_bootstrap positive_fraction ≥ 0.70` — inherit the under-reporting bias.

Recommendation: either land the mark-to-market equity computation before Sprint 088 (adds one function to `metrics.py`, computes `unrealized_pnl_series[t]` from the current position + prices), or add a rationale-doc entry explicitly naming the step-function-Sharpe as the pre-registered metric so a future reader does not misread the number.

**4.2 Fill-price = close approximation cancels in expectation, not per trade.** `positions.py` module docstring: *"the approximation applies uniformly to entries and exits and cancels in the round-trip P&L."* True at the ensemble level; not true for any single trade. On a gap-up morning where SPY opens materially above the previous bar's close, a real fill at the open pays more than the close-price approximation reports. Per-trade P&L in the ledger will diverge from real fills by the gap distribution. Named honestly on the sprint card, but Sprint 088's per-trade P&L histogram (product-spec §11.5 required output) will carry the noise band the approximation induces. Worth naming in the rationale doc so a reader sees the histogram width in-context.

**4.3 `max_drawdown_from_equity` returns 0.0 on all-loss equity curves.** `metrics.py:117`:

```python
if peak_at_trough <= 0.0:
    return 0.0, trough
```

If cumulative P&L is monotonically negative from bar 0, `peaks` is at zero (starting equity), `drawdowns = peaks - equity` is positive throughout, but the guard returns zero because dividing by a zero peak is undefined. That reports zero drawdown when the strategy lost money throughout. Correct as division-by-zero handling; misleading as a reported drawdown. Consider: absolute-drawdown fallback when peak is zero, or emit the max absolute-loss with a `denominator_kind` payload field. Small.

**4.4 `sharpe_crosses_zero_in_range` uses strict `min < 0 AND max > 0`.** `sensitivity.py`. A flat-Sharpe-zero sweep returns False. Named honestly on the sprint card: *"a robust reported number requires positive Sharpe across the range; a flat-zero sweep is neither robust nor crossing, it is silent."* Reasonable, but the field name reads as "does it cross zero." A reader expecting "True iff Sharpe touches zero anywhere" gets False on a Sharpe-pinned-at-zero surface. Either rename to `sharpe_strictly_crosses_zero_in_range` or add a companion `sharpe_touches_zero_in_range`. Minor.

**4.5 `derive_prices_from_log_returns` NaN-holds-last-valid.** If a bar's raw_target is NaN (feature-failure), the price series holds. A walker that decides to close on that NaN bar would use the stale price, injecting phantom P&L into the ledger. The walker filters `vol <= 0` (line 550) but not `raw_targets[t].isnan()`. In practice `vol` is 30-bar rolling std of log_returns, so a run of NaN log_returns cascades into vol NaN — but a single NaN log_return does not necessarily produce vol NaN. Worth a defensive check: `if not math.isfinite(fill_price): skip`. Small.

---

## 5. SDD-technique observations across Phase F

**Every named approximation on the record.** `positions.py` module docstring lists three approximations with their rationales. Sprint 096 card + Sprint 097 card + Sprint 098 card + Sprint 099 card each name what is deferred and what is honest zero. This is the pattern established at Sprint 031 (placeholders named as placeholders) applied consistently across five sprints.

**Retracted marker discipline.** Sprint 095 documented Sprint 085's retraction via `sprints/sprint-085-retracted.md`. Hard rule 12 preserves the audit trail — a Reviewer walking the sprint sequence sees Sprint 085's slot occupied by a retraction record rather than an unexplained gap.

**Live-smoke observation contract on every sprint.** Every Phase F sprint executed a live smoke on the real 2015-2022 corpus with an untrained xs+10-step checkpoint, and reported the at-chance outcome honestly. Sprint 097: "1 trade in ledger... `pnl_net = -$12,684.26` on 334-bar hold. Numbers honestly at-chance (Sprint 093 warning applies) — mechanics green." Sprint 098: "Every per-size Sharpe = 0.0... `capacity_usd = $0`. Zero-Sharpe outcome is the honest tail of the same monotone-loss single-trade condition." Sprint 099: "Every per-multiplier Sharpe = 0.0; `sharpe_crosses_zero_in_range = False`. The False flag on an all-zero surface is honest." Five sprints, five honest-at-chance reports, five explicit deferrals to Sprint 084's GPU-trained model. Zero fabrication.

**Fail-loud contracts continued.** Sprint 096 `run_simulation_with_trades` refuses when `artifact.raw_targets is None` — Sprint 088's field is a hard requirement. Sprint 098 `run_capacity_sweep` raises on empty `sizes_usd`. Sprint 099 `run_kappa_sensitivity` raises on empty `kappa_multipliers`. Every fail-loud opt-in escape hatch pattern from Sprint 077 continues.

**Nested-run pattern established at Sprint 098, reused at Sprint 099.** Both sweeps use `dataclasses.replace(policy_template, ...)` to override one axis while preserving every other knob, then invoke `run_simulation_with_trades` per point. Both extract `metrics.sharpe_point` + `metrics.sharpe_se` from the nested SIM_RUN_COMPLETED. Nested SIM_RUN pairs count exactly per sweep dimension. Reader-friendly emit accounting.

**Vocab-side discipline.** Zero new tags this arc. Every emit consumes the v0.7 surface. The Sprint 096 card names a v0.8 candidate (`checkpoint_kind` + `patch_size` + `head_type` + `fusion` fields on `CONFIG_RESOLVED`); no vocab bump made, since the current sprints do not need it. Restraint on the version-bump axis when the code does not force it.

---

## 6. Small findings on this arc

**6.1 Sprint 093/094/096/097 walker `SIM_RUN_STARTED` emits placeholder `checkpoint_step=0` and `checkpoint_run_id="sprint-NNN-no-checkpoint-id"`.** Actual checkpoint metadata is available: the training checkpoint file's payload carries `step`, and the run_id can be threaded from the CLI. The placeholder defaults are lies-lite — legal string values that carry no meaning. Sprint 088 held-out simulation will call these walkers with a real checkpoint; the caller must remember to pass real `checkpoint_step` and `checkpoint_run_id` kwargs. Defensive fix: change the signature to require them (`checkpoint_step: int, checkpoint_run_id: str`) with no default. Fail-loud at the call site. Sprint 097 fix candidate.

**6.2 `sensitivity.py` and `capacity.py` share ~60% of code shape.** Both take an artifact + model + bucket_stats + `policy_template`, iterate a knob, `dataclasses.replace` one field, invoke `run_simulation_with_trades`, extract per-point metrics, emit one summary tag. Extracting a shared `_run_axis_sweep(axis_name, values, policy_field, ...)` helper deduplicates. Named as a Phase G refactor candidate.

**6.3 `metrics.py` `BARS_PER_YEAR_DEFAULT = 6552`.** `252 × 26 = 6552`. Correct for 15-min RTH bars. If a future sprint reduces to daily bars, this constant drifts silently. Consider making it a required argument or reading from ExperimentConfig.

**6.4 `variance_vn` handles NaN train_means but not NaN probs.** `policy.py:81`. `torch.isnan(bucket_train_means)` guards, but if `probs` carries NaN (softmax on NaN logits), the arithmetic silently propagates. Softmax on the NaN-loss branch would trigger this; the walker's model.eval() + torch.no_grad() context does not filter NaN outputs. Add `if torch.isnan(probs).any(): raise ValueError(...)` at the top of `variance_vn` and `derive_prediction_scalars`.

**6.5 `compute_pnl` raises on non-positive `entry_price` but not on non-positive `exit_price`.** `positions.py:78`. A NaN or zero exit price would compute `pnl_gross = size * (0/entry - 1) = -size` — a full-size loss reported without a signal. Add the symmetric guard.

**6.6 `block_bootstrap_sharpe` seed default is 42.** `metrics.py:156`. Reasonable, but the default should probably come from the TrainerConfig's seed (or a dedicated `SimulatorConfig.bootstrap_seed`) so the sim reproduces from a single knob. Small.

---

## 7. What remains

**Not addressed in this arc; carried forward from prior reviews:**

- **RoPE.** Deferred by 2026-08-16 Architect Decision.
- **`run_alignment` dispatch branch count** (nine branches; non-blocking readability question).
- **Quantile-head val_nll slot semantics** (Sprint 089's named gap; quantile-specific metrics candidate).

**New from Phase F:**

- **Walker refactor** (§2): four walkers → one walker + hooks list. Phase G candidate.
- **Bootstrap vectorization** (§3.2): 10,000-loop Python → single numpy call. Before Sprint 088.
- **Prices-vectorization + searchsorted + cached train_means** (§3.1, §3.3, §3.4): matter at sweep scale.
- **Mark-to-market equity** (§4.1): before Sprint 088 held-out sim, or explicit rationale-doc note.
- **`SimResult` discriminated-union or `Literal` kind field** (§2 end): cleanup.
- **`skeleton.py` split** (§2 end): position-transition helpers → `positions.py`.
- **Placeholder-default fail-loud on checkpoint kwargs** (§6.1): fail at the call site.
- **NaN-probs guard on `variance_vn` + non-positive `exit_price` guard on `compute_pnl`** (§6.4, §6.5): symmetry with existing fail-loud checks.

---

## 8. Bottom line

Phase F closes. Eleven previously-deferred simulator tags fire from live code. The pre-registered `SIM_RUN_COMPLETED` payload populates cleanly. Capacity sweep and kappa sensitivity report the shape a Reviewer expects.

The discipline continues at cadence: honest at-chance smokes on every sprint, named approximations in module docstrings + sprint cards + rationale positions, fail-loud contracts on artifact preconditions, retraction markers on abandoned sprint numbers.

The technical debt Phase F ships with is not correctness debt — the math is right. The debt is:
- **Duplication debt** in the four walker variants (§2).
- **Performance debt** in the four Python-loop-over-tensor constructs (§3).
- **Reporting-mismatch debt** in the step-function-vs-continuous Sharpe (§4.1).

Landing all three before Sprint 084's GPU sweep and Sprint 088's held-out evaluation would spend one Phase-G-shaped sprint arc and produce a simulator that the pre-registered gates read cleanly. Landing none of them would produce a Sprint 088 held-out report where the "Sharpe" field means something narrower than the spec's Sharpe, computed on a walker that took twenty times its necessary wall-clock, in four maintained-in-parallel copies of the same loop.

Recommendation: file the eight items in §7 to Deferred with revisit trigger "Phase G refactor sprint arc." Then Sprint 100 opens Phase G.
