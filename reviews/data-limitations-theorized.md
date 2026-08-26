# Data limitations — a theory of why the sweep barely beats linear

> **RETRACTION HEADER (2026-08-25, Sprint 113 close).** The trigger numbers below assume the transformer trained on the correct artifact. It did not. Every Sprint 110-112 run trained on an un-normalized `.pt` — Sprint 084's guard was mixer-only and sum fusion silently drowned non-target channels because raw dollar_volume dominated per-channel Linear projections. Sprint 113 fixed the guard, regenerated the canonical artifact normalized, and retrained md at same 20K steps on normalized data: **pooled val_nll 3.1976 vs linear@800's 3.289 = transformer +2.8% BETTER**, first arc win. Wins low, mid, high, pooled, top-1. See `reviews/post-mortem-normalization-bug.md`. The stethoscope-at-door metaphor still holds for the 10% pre-registered gate (still 7.5% away under normalized data), but "the amplifier is already fine" was false — the amplifier was mis-wired for 71 days. Predictions in §3 that survive the retraction stay valid; the "multi-channel edge is real but small" prediction actually understated the edge under proper normalization.

**Author:** Claude Code (Opus 4.7), acting in Agent role.
**Date:** 2026-08-24.
**Trigger:** `artifacts/sprint110-sweep-report.md` — best transformer (lg, 25.3M params) reports pooled val_nll 3.3993 against a 64-token bucket-ID linear baseline at 3.3331. The transformer is *worse* than the linear model. All learning is concentrated in the low-vol regime; the high-vol regime (58.7% of val by weight) tops out at chance NLL and sub-chance top-1.
**Frame:** what in the *data*, not the *model*, produces this pattern.

---

## The one-line thesis

The pipeline is trying to hear a whispered conversation from behind a closed door with a stethoscope. The transformer is a better amplifier than the linear model's bare ear. Neither can hear what is on the other side of the door because the door only lets certain frequencies through. Opening the door — higher-frequency data, order flow, text — is the fix. Building a better amplifier is not.

Everything below explains why the door filters the way it does.

---

## Six data limitations that produce exactly this pattern

### 1. 15-minute bars are the wrong resolution for the alpha that exists

Financial signal lives on distinct time scales:

- **Sub-second:** order book state, quote updates, market-maker uncertainty, order flow imbalance. This is where informed-trading alpha lives.
- **Seconds around releases:** Fed announcements, CPI prints, earnings surprises. The move happens in the first 30 seconds.
- **Minutes to hours:** volatility clustering, mean reversion, cross-asset factor rotation. This is where linear autocorrelation lives.
- **Days to weeks:** macro regime shifts, earnings cycles, calendar effects.

15-minute bars aggregate over sub-second microstructure and blur the exact seconds of macro releases. The signal that *survives* the 15-minute aggregation is autocorrelation and volatility clustering — which is exactly what a linear model on past 64 bucket-IDs captures. The transformer sees the same aggregated signal plus 18 more channels that repeat the same information at different lags.

**The transformer's edge is real only where the linear model's simple window shape breaks down** — the low-vol regime, where cross-asset correlation and macro conditioning add small marginal information. In high-vol, where the informative sub-second events dominate, both models are equally blind because both are reading 15-minute-averaged residue.

### 2. Macro channels are constant across ~4000 bars between releases

CPI releases once a month. FEDFUNDS changes ~8 times a year. NFP monthly, UNRATE monthly, DGS10 daily. Between releases the value is unchanged for hundreds to thousands of 15-minute bars.

Of 54,262 training rows, only ~400 carry fresh macro information (once per release × 5 macro series × 8 years). That is 0.7% of the training corpus with new macro signal. The other 99.3% see a constant column.

The frozen-normalizer drift diagnostic (Sprint 055) confirmed this cleanly: `macro__CPI` KS=0.9987, `macro__NFP/UNRATE/FEDFUNDS` all KS≈0.997 between training and test partitions. The macro columns are step functions that decorate the aligned parquet with impressive-looking numbers and contribute almost no bits per bar.

### 3. Event channels are similarly sparse

FOMC: 8 scheduled dates/year + 7 emergency dates in 2020. CPI_RELEASE: 12/year. OPTIONS_EXPIRY: 12/year. EARNINGS_DENSITY_SPX: daily aggregate. Total informative event-days per year: ~55. Over eight years: ~440 rows out of 54,262 = 0.8%.

The event features (`release_flag`, `mins_to_next_release`) carry real information *on those days*. On the other 99.2% of days they are flat step functions or monotone countdowns.

### 4. Options data at hand is stale and aggregated

`HISTORICAL_PUT_CALL_RATIO` returns one number per day per symbol. `HISTORICAL_OPTIONS` gives per-contract detail but aggregated to daily volume in the current pipeline. Real intraday options flow — sweeps, unusual activity, at-the-money-vs-out-of-the-money volume shifts, block trades — is where informed-trading alpha shows up first, and none of it is at 15-min resolution on the current data source. Options got fed into the pipeline as another slowly-varying step function like the macros.

### 5. Cross-asset channels re-express information the target already carries

QQQ, IWM, GLD, TLT, UUP, VXX, USO co-move with SPY at high frequencies. Regressing SPY's next 15-min return on 64 past QQQ log_returns adds almost nothing beyond what the same regression on 64 past SPY log_returns already captures — cross-asset correlation over short windows is dominated by the market factor everything shares.

The transformer over-parameterizes on cross-asset regressions that look predictive in-sample and do not generalize. The drift diagnostic surfaced this too: dollar_volume KS=1.00 between training and test.

### 6. No order-flow data at all

The tech-arch names LOB tokens as v3+ and explicitly says they "cross an architectural boundary" — 234,000 timestamps per trading day at 100ms resolution. Not in v1. Also not in v1: intraday tick data, quote updates per second, level-2 depth, trade size distribution, VWAP execution prices. These are the raw materials of intraday alpha. Everything currently in the pipeline is coarse-grained aggregates of what happened.

---

## What this predicts about the results (and what actually happens)

The theory predicts:

- **Signal concentrated in low-vol.** ✓ Report finding 3.
- **High-vol regime unlearnable at 15-min bars.** ✓ All sizes at chance NLL on high-vol.
- **Transformer barely (or fails to) beat linear on pooled val NLL.** ✓ lg -1.99%.
- **Bigger models plateau.** ✓ md → lg gain of 0.007 nats vs md at 14.3M → lg at 25.3M.
- **The multi-channel information advantage is real but small.** Untestable in this sweep because the correct target-only ablation (Sprint 061's `zero_non_target_features` used in `run_training_feats`) was not run. Predicted delta if it *were* run: transformer beats zeroed-channel version by a few percent, both lose to linear on pooled val NLL, both beat linear on low-vol.

Every prediction the theory makes is either confirmed or predicted-but-untested. That is what a *data-limitations* theory looks like: the model is doing its job; the data is the limit.

---

## What data would move the ceiling

Ranked by expected marginal information per dollar of engineering:

**Tier 1 — highest ROI, still fits v1 architecture:**

- **Longer training window (2007-2014 backfill).** Adds the 2008 financial crisis, QE1-3, the 2011 US downgrade, and the pre-Fed-QE regime. Extends 8 years to 16 years of training. Doubles regime-shift training examples from ~10-16 to ~20-30, which is the sample size that actually matters for predicting regime-conditional behavior. Alpha-Vantage carries the data. Cost: ~$0 additional (already-purchased tier).
- **Multi-instrument training targets (product-spec v2).** Same architecture, six targets (SPY + QQQ + IWM + TLT + GLD + USO) sharing the same 19-channel context. Pool 6× the training gradient on the same feature set. Product-spec explicitly says this is a config change, not a rewrite.
- **Sector-rotation features.** Add sector ETFs (XLK, XLF, XLE, XLI, XLV, XLY, XLU, XLB, XLC, XLRE) as extra market_context channels. Intraday sector rotation is where most 15-min alpha lives in low-vol regimes. Adds ~10 channels; free ingest cost.
- **Better macro release timing.** Currently macro known_at is stamped at a per-channel daily lag (`known_at_lag_days`). Real releases hit at 8:30 ET (CPI, NFP, jobless) or 2:00 ET (FOMC). Adding a per-second timestamp (or at least a per-minute) would let the model condition on pre-release vs at-release vs post-release. Costs: hand-curated release-schedule table.

**Tier 2 — architectural boundary crossed, real information gain:**

- **Sub-minute equity bars (1-min or tick-level).** Order flow imbalance becomes computable from bar volume + close vs open + high vs low. VWAP available. Effective sample size grows 15×. Doesn't include level-2 depth but captures the second-tier microstructure. Alpha-Vantage carries 1-min bars; Polygon.io carries tick.
- **Intraday options flow.** CBOE-adjacent feeds. Real put/call ratio streaming, unusual-activity signal, ATM vs OTM volume shifts. Not on Alpha-Vantage; requires Databento or similar. Cost: ~$1,500-3,000/month.
- **Real intraday VIX via VIX futures.** Front-month VX futures tick data proxies the intraday VIX better than VXX ETN. Databento or CBOE direct. Cost: ~$500/month.

**Tier 3 — v3+ scope per the tech-arch:**

- **Level-2 order book snapshots.** 100ms resolution, 234k timestamps/day. Direct order flow imbalance. Requires hierarchical temporal aggregation (a separate encoder over the LOB stream emits per-15-min-bar summaries). Databento's Plus tier ~$1,750/month.
- **News/text conditioning.** Reuters/Bloomberg feeds through a small encoder. Real informed-trading alpha in headline reactions. Requires a new modality module.
- **Alternative data.** Credit card spend, satellite imagery, web traffic. Product-spec v3+ item.

---

## What resolutions would help

The current 15-min resolution sits in a valley — too coarse for microstructure, too fine for macro regime. Two clean answers:

- **Down** (1-min or tick): captures order flow, matches the timescale where the market makes decisions. Direct route to the alpha the current pipeline is blind to.
- **Up** (daily): matches the timescale where cross-asset correlations and factor rotation carry real signal. Loses microstructure but the model is not capturing microstructure anyway.

The 15-min horizon exists in the product-spec because it is the natural aggregate for a swing-trading strategy — one that a human might hold positions across a few hours or a day. If v1 shipped as a daily-bar model, the transformer would probably beat linear cleanly (autocorrelation weakens; cross-asset factor rotation strengthens). If v1 shipped as a 1-min-bar model, the transformer would eat the linear model alive on order-flow features but the training corpus would need to shrink to a smaller wall-clock window.

15-min is the wrong middle. Not fatally wrong — the low-vol regime does show real learning — but the pooled gate is anchored to a horizon at which the multi-channel signal is thinnest.

---

## The metaphor that clicks

Three tries, in order of what actually explains the result:

**The stethoscope at the door.** The pipeline stands in a hallway with a stethoscope pressed against a closed door. Behind the door is the actual market — quote updates every millisecond, order book depth shifting, block trades printing, informed traders positioning. The stethoscope (transformer + 19 channels) is a better amplifier than the linear model's naked ear. But most of the conversation happens in the room. Only the loudest words leak through the door at 15-minute intervals. Both models hear the loudest words — those are the words that actually leaked. The transformer's amplifier does not change what is on the other side of the door.

**The 15-min photograph of a football game.** The model sees the field at bar close: score, player positions, crowd posture. It can tell which team is winning (low-vol autocorrelation). It cannot tell you the next play, because plays are called in the huddle at sub-frame resolution.

**Predicting Brownian motion from 15-min position samples.** There is a theoretical variance bound on how well any model can predict a random walk from coarse position samples. Better models do not close that bound. Better sampling does. The transformer is a better predictor than linear in the low-vol regime because the process there has more autocorrelation than pure Brownian; in the high-vol regime the process is closer to pure Brownian and no model beats the variance bound.

Pick whichever metaphor is most useful. The mechanism is the same: the *data available* at 15-min resolution has a signal-to-noise ratio that both models approximately saturate. The transformer's marginal edge over linear is roughly the marginal edge of "18 extra channels of low-information side data" over "past 64 bucket-IDs of the same target." That marginal edge is small because the extra channels are mostly step-function macros, day-lagged options aggregates, and cross-asset correlations the target already contains.

---

## What Sprint 111+ should do

Given the theory, the sensible next moves rank as:

1. **Run the correct target-only ablation** (Sprint 061's `zero_non_target_features`). Costs one training pass per size. Answers the direct question: does the multi-channel data add anything at all, even at 15-min? If the multi-channel transformer beats the zeroed-channel transformer, the data has some information; if not, the door is fully closed to what leaks through at this resolution.
2. **Extend the training window to 2007-2014.** Costs API budget + one alignment re-run. Doubles the regime-transition sample size. This is the cheapest thing that could change the result.
3. **Add sector rotation channels** (XLK/XLF/XLE/XLI/XLV/XLY/XLU/XLB/XLRE). Costs ingest + one alignment re-run. If low-vol edge grows, the sector-rotation hypothesis holds; if not, it does not.
4. **Re-tune LR on md** per Sprint 110 review §3 — v2's lr=3e-4 hit 3.18 val_nll before divergence, 4.5% better than linear. Cheap experiment, potentially closes the gate on the *current* data.
5. **Multi-instrument training** (product-spec v2). Pool six targets' gradient on the same context. Config change, no code rewrite.

Only after all five are exhausted do the tier-2 data moves (1-min bars, intraday options flow, real VIX) become the honest next step. Attempting a v1.5 with better architecture but the same data (which the current sweep-planning implies) will produce a bigger, slower transformer that also barely beats linear.

The door has to open. The amplifier is already fine.

---

## Addendum — first principles + design + discipline (2026-08-25, Sprint 113 post-mortem context)

The original piece asked what the *data* explains. Sprint 113 changed the frame: the amplifier was broken for 71 days, the bug fix produced a +2.8% pooled val_nll win over linear (vs the pre-bug -1.99% loss), and the pre-registered ≥10% gate is now 7.2 points away instead of 12. This addendum revisits the question through five lenses the arc now needs to argue from — LLM first principles, transformer design at the research frontier, SDD discipline as Sprint 113 practiced it, code architecture's role in the bug, and experiment design's role in missing it for 71 days.

### 1. First principles — what a transformer actually does with a 15-min market signal

An attention layer is a soft dictionary lookup. Query `q_t` at position `t` weighs value vectors `v_1..v_T` by similarity to the keys `k_1..k_T`; the output is a convex combination of values. The linear operations before and after (`W_q, W_k, W_v, W_o` per head, then the feedforward `W_1, W_2`) parameterize what to look up and what to return. Nothing about the attention math is market-specific. The transformer is a general soft-lookup function approximator.

That has three consequences that the Sprint 110-113 arc surfaces:

**The transformer's job is to interpolate similar past contexts.** For a 15-min market state, "similar" is defined by the learned query and key projections. Under `MarketStateEmbedder`'s sum fusion with un-normalized dollar_volume, "similar" collapsed to "similar in the dominant channel's raw magnitude" — effectively target-only. Under proper normalization, "similar" opens up to include cross-asset + macro + event features. The bug did not corrupt the attention math; it corrupted what the embedder handed to attention. The lesson: the fusion layer is where the model's inductive bias about "what makes contexts similar" lives, and the fusion layer is where scale conditioning bites.

**Cross-entropy on 32 buckets caps the achievable information gain.** Chance NLL under uniform prediction is `log(32) = 3.4657` nats. A perfect predictor's NLL is 0. Every real NLL sits between. The normalized md hits 3.1976 nats, which is `(3.4657 - 3.1976) / log(2) = 0.386 bits per bar` of information about the next return's bucket. The linear baseline captures `(3.4657 - 3.2886) / log(2) = 0.256 bits`. The transformer's edge is `0.130 bits per bar`. At ~26 bars per RTH day, that is ~3.4 bits per trading day — enough to skew a probability distribution but not to name the next bucket with confidence. Whatever the model does, `log₂(32) = 5` bits of information about the exact bucket is the ceiling, and the empirical entropy of the vol-normalized-return distribution (real-world randomness, not model failing) probably caps the achievable near 1-2 bits. The model may be close to its information-theoretic ceiling at this discretization; adding capacity does not help past the ceiling.

**The bucket-classification objective is not the same as the trading objective.** Cross-entropy optimizes for probability mass on the correct bucket. A calibrated distribution can still lose money if the decision layer's `E[return] × p_up - costs` is negative in expectation. Product-spec's Sharpe gate consumes the distribution; NLL is a proxy metric. This means the "transformer beats linear on NLL" claim does not automatically translate to "transformer beats linear on held-out Sharpe" — the two metrics test different properties. The held-out sim (Sprint 088+) is where the actual thesis is tested.

### 2. The idea space — what the research frontier says about time-series transformers

The last four years produced a specific sequence of findings on transformer-based time-series forecasting worth naming:

**Informer (2020), Autoformer (2021), FEDformer (2022)** — early attempts at long-sequence time-series transformers. Each proposed clever attention approximations. Each was superseded within 18 months.

**Are Transformers Effective for Time Series Forecasting? (Zeng et al., 2022)** — showed a simple linear model beat every proposed time-series transformer on benchmark long-horizon forecasting. The finding matches Sprint 110's pre-fix result exactly. The paper's mechanism was that transformer attention over time steps for regular time series over-parameterizes the local autocorrelation structure that linear captures cheaply.

**PatchTST (Nie et al., 2023)** — patched the time axis into contiguous windows, treating each patch as a token. The result: transformer beats linear on the same benchmarks, once the tokenization aggregates over the timescale the noise operates at. The lesson maps directly: 15-min bars may already be a patch of sub-min ticks, and the mixer/patch=4 ablations in Sprint 087-090 are re-visiting this question at a higher level.

**iTransformer (Liu et al., 2024)** — inverted the tokenization: treat each variate (channel) as a token, treat time as the feature dimension. Attention runs across channels, not across time. The finding: on multi-variate time series with heterogeneous channel dynamics, iTransformer beats channel-mixed alternatives. The Sprint 083 channel-mixer ablation gestures at this — the mixer treats channels as a set to attend over per-timestep — but the full iTransformer swap is a design one axis over.

**Chronos / TimeGPT / Moirai (2024)** — foundation models pre-trained on billions of time-series tokens across domains, then fine-tuned. Strong on generic forecasting; mixed on financial data specifically, where the efficient-market constraint means published edges decay.

**Mamba / RWKV / other SSM variants (2024)** — state-space models compete with transformers on long-context. Mixed evidence on time series. Not obviously worth the architectural complexity for a 64-token context window.

The research consensus for a project at v1's stage: **plain transformer + proper tokenization + proper normalization beats linear at 2-5% NLL improvement on well-designed benchmarks.** Sprint 113's +2.8% is inside that band. That the arc is at the middle of the published-empirical band and not the top or bottom suggests the current architecture is neither miscalibrated nor state-of-the-art — it is competent. The path to +5-10% probably runs through iTransformer-style channel-as-token attention (Sprint 083 mixer at scale), or through hierarchical tokenization (Sprint 087 patch pattern extended), or through a foundation-model pretrain-then-fine-tune (unfamiliar to this codebase but a real 2026 option).

Two constraints specific to financial data no forecasting benchmark carries: **the efficient-market hypothesis** (any published edge is arbed toward zero) and **regime nonstationarity** (2015-2022 is not distributed like 2024-2025). The frozen-normalizer drift diagnostic already surfaced the second. Any architecture that assumes stationarity will underperform on out-of-sample macro rows.

### 3. SDD — what Sprint 113's post-mortem teaches

The Sprint 113 close is the strongest single argument for the SDD discipline this arc has produced. Six things happened inside one sprint:

- Discovery (target-only ablation matching to 4 decimals — the pre-registered ablation surfaced the bug).
- Fix (guard broadened from mixer-only to every fusion).
- Canonical-artifact swap (normalized becomes `tokens.latest.pt`; un-normalized preserved under a named archival path per hard rule 12).
- Test rewrite (`test_run_training_feats_permits_sum_on_unnormalized_artifact` inverted to `refuses`, docstring records the retraction).
- Fixture updates (four synthetic-artifact fixtures stamp `normalized: True`).
- Audit-trail update (retraction headers on the prior reviews, ledger correction from 3.3331 to 3.2886, KIT_DIARY lessons filed, `run_id` hyperparameter fingerprint landed).

That is the full retraction shape, executed in one sprint close with `[x]` on every action item. Cite as canon: **when a bug required immediate fix + retraction, its infrastructure fix belongs in the same closing gesture, not queued for later.** Sprint 105's CLAUDE.md-quoting deletion discipline applied to a bug fix.

Two SDD moves specifically worth naming:

**The vocabulary was unaffected by the bug.** Every trace file from Sprint 110-112 has honest emits: correct `WINDOW_SAMPLED.start_position` (Sprint 041 fix), correct `TRAINING_STEP_COMPLETED.train_loss` (Sprint 100's un-lie), correct `CHECKPOINT_WRITTEN` val metrics, correct `METRIC_COMPUTED` per regime. What was wrong was not the *reporting* but the *system being reported on*. The reports drew wrong conclusions from correctly-emitted signals. That is the value of "vocabulary is the contract" — the audit trail survives even when the code has a silent quality bug, because the signals do not lie about what they observe.

**The KIT_DIARY lessons are on-record and quotable.** Four rules, each with concrete evidence: silent quality collapse is worse than a crash; an untested assumption in a comment is a load-bearing lie (Sprint 084's *"sum tolerates un-normalized"* comment shaped 71 days of reader expectation); ablations that give suspiciously similar numbers are diagnostics not confirmations (target-only bit-identical to 4 decimals was the tell); the correct question, asked once, finds the bug in one hour (the artifact meta carried `normalized: False` for 71 days). These are new rules with real evidence, not restatements of prior rules. Sprint 113 added four novel discipline items to the kit. That is how the kit compounds.

### 4. Code architecture — the scale-conditioning pathology and its structural fixes

The bug's mechanism was mundane and instructive. `MarketStateEmbedder.forward` computes `Σ_c W_c x_c` where each `W_c` is `nn.Linear(F_c, d_model)` with Xavier init weights ~O(0.05). Under normalized input, `x_c` sits in [-3, 3] (approximately); the projections are order-comparable across channels; the sum is a balanced fusion. Under un-normalized input with `target__SPY__dollar_volume` mean ~61M std ~264M, the target projection dominates by ~7 orders of magnitude. The other channels contribute noise at effective weight ~10^-7. Adam converges to weights that project non-target channels to near-zero — the mathematically optimal thing to do given the loss surface. The model becomes target-only.

Three architectural moves would prevent recurrence:

**Fusion refuses un-normalized input at construction.** Not at load, at construction. `MarketStateEmbedder.__init__` inspects the artifact's `meta['normalized']` field (threaded through as a required kwarg or as a `FrozenNormalizer` reference) and raises if false. The `UnnormalizedArtifactRefused` guard is currently in `run_training_feats` — one layer up from the actual arithmetic that breaks. Pushing the guard into the fusion class itself makes the invariant local to the code that requires it. Fewer places to forget the check.

**Input LayerNorm per channel before the linear projection.** `nn.LayerNorm` on each channel's input before `nn.Linear(F_c, d_model)` self-heals against scale mismatch by re-centering + re-scaling each channel to zero-mean unit-var per bar. The cost is a small parameter count (two `d_model`-vectors per channel). The benefit is that a callback with un-normalized input would produce a well-conditioned sum by construction. Tech-arch §7.2 does not name this; worth an amendment.

**Per-channel gradient monitoring.** Every `TRAINING_STEP_COMPLETED` emit could include per-channel gradient norms. A channel whose gradient collapses to zero within the first 100 steps is a red flag — the model has already decided to ignore it. Current emit has `grad_norm` as a scalar. A `grad_norm_by_channel` list would let a Reviewer detect target-only-equivalence at step 100 rather than 71 days later. Small vocab change (v0.8 candidate).

Two related architectural observations from the broader post-113 picture:

**The `TokenizedArtifact.meta['normalized']` field was passive metadata for 71 days.** Any field marked as part of the contract must be checked at every read boundary or removed from the contract. The Sprint 077 `LegacyMaskSemanticRefused` pattern applied to `mask_semantics` shows the shape: refusing to read without an explicit acknowledgment of the field's value forces the check to happen. Applying that pattern to `normalized` at the `load_tokens_pt` boundary would have caught the bug at load time on Sprint 110.

**The Sprint 113b `run_id` hyperparameter fingerprint** is a structural correctness win. Sprint 112's checkpoint collision was possible because two runs with different hyperparameters could produce the same `run_id`. A `-hp{8char}` sha256 of every training hyperparameter (lr, wd, warmup, lr_min_frac, bf16, embargo, keep_top_k, target_only, fusion, mixer_dim, mixer_n_heads, patch_size, head_type, batch_size, deterministic) fingerprints the run at path-write time. Any distinct hyperparameter combo now writes to a distinct checkpoint path. Belongs in the KIT_DIARY as a general pattern for artifact naming.

### 5. Experiment design — the target-only ablation should have been first

The Sprint 110 sweep report reads as a competent experimental result. Four sizes, two LR settings, per-size training curves, per-regime breakdown, baseline comparisons. Every table has real numbers. Every interpretation is internally consistent. And every interpretation was wrong on the causal claim because the sweep never ran the one experiment that would have exposed the bug.

The lesson is not "Sprint 110 was sloppy." Sprint 110 followed the pre-registered ordering: sweep sizes first, then diagnostics. The pre-registered ordering was wrong. **The pre-registered target-only ablation is a diagnostic that belongs before the sweep, not after.** If Sprint 110 had run one xs pass with `zero_non_target_features` alongside one xs pass with full channels, the bit-identical result would have surfaced the bug in the first hour of training. Instead the sweep ran, three interpretation sprints wrote reports, and the diagnostic landed at Sprint 113.

Two related experiment-design moves the arc should adopt:

**Every training-related sprint runs a paired sanity check.** For a fusion sprint: a target-only run alongside a full-channel run; if they match to more than 3 decimals in val_nll, raise a flag. For a size sweep: a smallest-size run at each LR alongside a med-size run; if val_nll is monotone in size, size scaling is real; if not, something is off. These are cheap runs (usually one xs sweep-point per additional check) that pay back massively when the flagged output is a bug rather than a null result.

**Ablations belong in the pre-registration.** Product-spec §Baselines lists the baseline ladder but does not order it. Sprint 110's "sweep first, ablate later" was a workflow choice, not a pre-registered ordering. A revised pre-registration should read: *"target-only ablation runs at the smallest sweep point BEFORE the full sweep; if target-only ≈ full-channel in val_nll, halt the sweep and investigate the fusion path."* The pre-registration becomes not just what to measure but in what order.

**Sanity emits at training close.** Every training run's `EPOCH_COMPLETED` (or a new `SANITY_CHECK_COMPLETED` tag) could carry: per-channel gradient norm sum, target-only-equivalent val_nll delta (compute one target-only forward pass on a small val subset at close), input scale distribution per channel. A Reviewer scanning the trace file sees a target-only-equivalent delta of `< 0.001` and knows immediately something is wrong. This is Addendum D1's "signals drive but cannot grade" principle: the sanity check is a grader that the training run itself carries, not a separate script that has to be remembered.

Three specific experiment-design errors the arc's audit trail now names:

- **Interpretation before the diagnostic ran** (Sprints 110-112 wrote three reports before the target-only ablation).
- **Confidence in an untested comment** (Sprint 084's *"sum tolerates un-normalized"* shaped Sprint 110's setup without evidence).
- **Trust in a metadata field with no read-side enforcement** (`meta['normalized']=False` was visible for 71 days).

None of the three is unique to this arc. All three are patterns that show up in ML research groups broadly. The KIT_DIARY has them now as concrete evidence.

---

## Revised bottom line (post-Sprint-113)

The pre-Sprint-113 review's central claim — *the amplifier is already fine* — was false. The amplifier was mis-wired for 71 days. Under proper normalization the multi-channel signal is measurable at +2.8% pooled val_nll over linear, up from -1.99% under the bug. The transformer wins across low + mid + high regimes and top-1 accuracy, not just low-vol.

The pre-registered ≥10% gate is still 7.2 points away. The five tier-1 next moves from the original piece (target-only ablation on normalized data, longer training window, sector rotation, LR retuning, multi-instrument training) are all still ROI-positive and none have been tried under the fixed artifact. Sprint 114+ runs them against normalized data before any amendment to the pre-registration proceeds.

The three metaphors — stethoscope at the door, 15-min football photograph, Brownian motion from coarse samples — all still hold for the last 7.2 points of the gate. The revision: the door was more open than the original piece thought (because the amplifier was mis-reporting how much came through), but it is still not open enough for the pre-registered claim to be met without opening the door further.

The five-lens frame this addendum introduces gives Sprint 114+ a wider argument surface than the data-limitations frame alone. First principles set the information-theoretic ceiling (~1-2 bits per bar seems likely at this bucketization). The research frontier says 2-5% NLL improvement over linear is the well-designed-transformer band; the arc sits at 2.8%, competent. SDD discipline turned a silent 71-day bug into a one-hour fix + full retraction + four KIT_DIARY lessons — the discipline works when applied. Code architecture identifies three structural fixes (fusion refuses at construction, per-channel input LayerNorm, per-channel gradient monitoring) that prevent recurrence. Experiment design names three general errors the arc's audit trail now records.

The path to the 10% gate probably needs all of: proper normalization (landed), longer training (Sprint 112 partially explored, needs re-run on normalized data), longer training window (2007-2014 backfill), an iTransformer-style channel-as-token architecture (Sprint 083 mixer at scale, plus the input-LayerNorm fix), and possibly multi-instrument training. Whether that combination clears 10% or lands at 5-6% is the unknown Sprint 114+ has to measure.

The door is more open than the original piece thought. The amplifier is now fine. The remaining 7.2 points either close with the tier-1 moves or force an honest amendment to the pre-registration through the Architect's Decision channel.
