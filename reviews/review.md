# Price-Space LLM — Full Review

**Scope.** The five documents in the project folder (`proposal.md`, `price-space-llm-analysis.md`, `product-spec.md`, `technical-architecture.md`, `build-guide.md`), read as a single package. Judged on principles, logical consistency, and whether the design gets it right the right way. Timeline is not a criterion.

---

## Verdict

The design is sound. The first-principles argument is correctly stated and correctly bounded. The implementation discipline is unusually strong for a solo project — six named invariants, eight pre-registered binary gates, three internal baselines, a purged embargo, and calibration-based checkpoint selection. The prior-art positioning is defensible on the cited papers.

Three parts of the package are not yet strong enough for the standard the rest of it sets. The simulator's cost model rests on a slippage coefficient the docs treat as a starting number, not a measurement; the same simulator uses a Corwin-Schultz bar-range spread proxy on an instrument whose true spread is close to zero most of the day. The eight success gates report point statistics with no attached confidence interval, on a holdout that produces something like 200–500 trades. The channel-summed embedder is defensible on parameter budget but the docs never state the assumption it forces on the model — that gradient descent will discover non-overlapping subspaces for each channel — and never propose a diagnostic for whether that assumption held.

Fix those three, and the package is right the right way.

---

## 1. First-principles argument: correct, and correctly bounded

The proposal makes one substantive claim and refuses to make several others. The substantive claim: the next price move is a well-defined random variable conditional on prior market state, the training signal is dense, and a causal decoder transformer is the right shape for estimating that conditional distribution. This is correct. It is the same argument that makes language modeling work, applied to a different measurable space.

The proposal declines to claim that markets are easy, that the model will be profitable, or that this design will beat any specific competitor. Those are the right refusals. What survives is a well-formed empirical question: does *this specific combination* of tokenization, target, and decision layer produce information that clears realistic costs on a chronological holdout. That question is falsifiable and the design answers it.

The choice of a decoder-only transformer, not something exotic, is right. Attention is the correct tool for "which prior states matter" without pre-specification. The docs correctly locate the novelty upstream (tokens) and downstream (decision layer), not in the attention mechanism. This is the same move Chronos and Kronos made and it is the right move for a small team.

The volatility-normalized return target is the strongest single design decision. It buys two things: scale invariance across regimes, and denomination in the units the downstream trading rule already needs. A model whose output is a distribution over risk-normalized moves does not need a separate "how do I turn this into a trade" translation layer with its own free parameters. The proposal's argument for this target is correct and load-bearing.

The multi-modal token is the second strongest decision but a weaker argument. See §5.

---

## 2. Implementation discipline: strong

The technical architecture names six invariants and treats them as bugs when violated. Five of the six are correct and load-bearing.

- **Causal by construction**, with a unit test that shuffles rows after `t*` and asserts feature values at `t ≤ t*` are byte-identical. This kills the entire class of leakage bugs at the level of the test. Correct.
- **Time-based splits with embargo of `H` bars.** Standard practice, done properly. Correct.
- **No magic numbers in code.** Hydra + Pydantic v2 with typed configs. Correct. The Pydantic wrapping catches misspellings and out-of-range values at load time rather than 40 minutes into a training run.
- **Reproducible training** with seeded `torch`/`numpy`/`random`/CUDA, `torch.use_deterministic_algorithms(True)`, and `CUBLAS_WORKSPACE_CONFIG=:4096:8`. The ~15% throughput cost is worth it. Correct.
- **Artifacts and configs ship together.** Tokenizer boundaries, normalizer stats, config, git SHA, data hash all live in `artifacts/{run_id}/`. Correct — the checkpoint alone is not the deliverable.
- **One source of truth per channel.** Correct in intent. The implementation risk is that any code path that recomputes a raw value silently violates the invariant; the docs do not describe a test for this. A hash-of-materialized-features check at feature-pipeline output would enforce it.

The checkpoint-by-ECE decision is the single most important architectural call in the training loop and it is right. Argmax accuracy is not what the trading rule reads; the full distribution is. Selecting on ECE selects for the shape the downstream cares about.

The ablation ladder is correctly structured. Linear on the same tokens tests whether depth is doing anything. MLP tests whether attention buys anything past a shallow nonlinearity. Target-only tests whether the multi-modal tokenization is doing anything. The third of these is the critical experiment; the whole thesis rides on it.

---

## 3. Cross-document consistency

The five documents agree on the important commitments and drift on a small number of details. Drift worth fixing before code lands:

- **Bucket indexing off-by-one.** `product-spec.md` numbers buckets 1–32 with 1 and 32 as tails. `technical-architecture.md` §7.1 numbers buckets 0–31 with 0 and 31 as tails. Same design, different indexing. Pick one and normalize.
- **Vocabulary size floated then committed.** `proposal.md` names "seven coarse or 128 buckets" as examples of the target vocabulary. Product-spec, tech-arch, and build-guide all commit to 32. Read the proposal as pre-commitment framing; that is not a contradiction but it will read as one to a careful reviewer.
- **Model size floated then committed.** Proposal says "tens of millions." All downstream docs commit to ~30M. Fine.
- **Context length floated then committed.** Proposal says "several hundred to a few thousand." Downstream commits to 512. Fine.
- **Realized-vol window.** `technical-architecture.md` §6 argues for 30-bar realized vol over EWMA for v1, giving a concrete reason (unambiguous semantics, matches DeepLOB baselines). `product-spec.md` §"Open questions" lists this as still open. The architecture doc is downstream; treat the choice as settled and update the spec to match, or explicitly note that the architecture picks and the spec keeps alternates.
- **Alpha-Vantage MCP vs. Polygon.** All docs list the MCP as primary and Polygon as fallback. `build-guide.md` week 1 leads with Polygon. The build guide reads earlier in the project's history — before the MCP was known to be available. Update the build guide.

These are edits, not design changes.

---

## 4. Prior-art positioning: accurate, and used correctly

`price-space-llm-analysis.md` is the strongest document in the set. It names 15 specific systems with arXiv IDs, describes what each tokenizes, what each predicts, and — crucially — what each does not do. That last move is what turns a lit review into a positioning argument. The claim that no cited system tokenizes joint multi-modal market state, targets vol-normalized return buckets, and integrates a cost-aware decision layer is defensible on the cited work. Kronos tokenizes one OHLCV stream. MarketGPT tokenizes one venue's order messages. LOBS5 and LOBERT reuse MarketGPT's vocabulary on different backbones. DeepLOB and its transformer successors supervise a three-class direction target on LOB snapshots. Chronos quantizes raw scalars. None of them is doing what this design proposes.

The doc correctly refuses to make the stronger claim that this novelty implies edge. That is what the experiment answers. The doc's discipline about the difference between "unoccupied" and "profitable" is right.

One thing worth adding: the small-NN-beats-large-NN result from Gu, Kelly & Xiu (RFS 2020) is mentioned in the open-questions section and correctly framed as a different regime (monthly cross-sectional pricing, not autoregressive sequence modeling). A reader who does not already know this will read the reference as a hedge; the doc should either drop the citation or say directly what it does and does not apply to. Currently it does the latter — well enough — but the point could be sharper.

---

## 5. Where the design's reasoning needs to go further

**The multi-modal token argument is thinner than the vol-normalized target argument.**

The proposal and product-spec both assert that a token compressing target + market context + liquidity + event/time gives attention more to work with than a single-stream token. This is true in the trivial sense — more information cannot be less information — but the interesting claim is that the architecture can *use* that information given the specific embedding scheme chosen.

The scheme (technical-architecture §7.2) is: each channel gets its own `nn.Linear(F_c, 512)` projection; the projections are summed; a learned channel-type embedding is added. The architecture doc defends summation over concatenation on parameter-budget grounds — concatenation makes `d_model` scale with channel count, summation holds `d_model` fixed. That defense is correct on parameter budget. It is not sufficient on information geometry.

Summation asks the model to discover, via gradient descent, non-overlapping subspaces in the 512-dim space for each channel. Without an explicit orthogonality prior, cross-channel projections can interfere; the channel-type embedding gives the model a route to disentangle them but does not force it. The BERT-segment analogy the doc invokes is real but weak: BERT has two segment types and only ever needs to route a global "is this A or B" signal. Here there are five channels, each contributing a full feature bundle at every position.

Two concrete things would strengthen this section:

1. **State the assumption explicitly.** "Summation assumes gradient descent will discover per-channel subspaces. If channels interfere, the target-only ablation will not lose much accuracy against the full model even when the extra channels carry real information." This turns the ablation gate into a test of the assumption, not just of the extra channels.
2. **Add a diagnostic.** At the end of training, project each channel's contribution at a held-out set of bars and measure the cosine similarity between channel means. If they cluster near orthogonal, summation worked. If they collapse, the model routed everything through one subspace and the multi-modal claim is architecturally undermined regardless of the ablation result. This is one plot in the eval doc.

Neither of these changes the design. Both make the design *defensible* rather than merely *stated*.

**The bucket-boundary decision has one gap.**

Bucket boundaries are percentile-uniform on training-set vol-normalized returns, frozen. Vol-normalization mitigates scale drift across regimes. It does not mitigate shape drift: skew, kurtosis, and tail-mass shifts in the return distribution are exactly what happens across regimes and are exactly what makes the frozen bucket boundaries less informative. The ECE gate at 0.05 will catch gross miscalibration, but not necessarily bucket-level shape drift.

One diagnostic worth adding: on the validation split, report the realized bucket-frequency histogram. If validation buckets 0 and 31 hold materially more or less than the training 0.5% each, that is direct evidence of tail-shape drift and it belongs in the run's summary. If 2024 validation shows drift, 2024–2025 test likely will too.

---

## 6. Statistical honesty: the gates need confidence

The eight success gates in `product-spec.md` are pre-registered, binary, and well-formed at the level of construction. The gap is that they are point statistics with no attached uncertainty.

Consider the Sharpe gate: "Held-out Sharpe ratio at least 0.5 after realistic costs." The held-out window is 18 months of 5-min SPY bars — roughly 18,720 bars. At any plausible trade rate (say, one trade per 30–100 bars) that is 200–600 trades. The standard error on an annualized Sharpe from N trades at trade-level is approximately `sqrt((1 + 0.5*S²)/N) * sqrt(bars_per_year / bars_per_trade)`. For S ≈ 0.5 and 300 trades on 5-min bars, the standard error is roughly 0.15–0.25 annualized. A reported Sharpe of 0.5 has a 68% confidence interval that grazes 0.25 on the low end.

This does not mean the gate is wrong. It means the gate as written invites overclaiming. Two fixes make the gate honest without weakening it:

1. **Report the gate as `Sharpe − 1 × SE > 0` or `Sharpe > 0.5 ± 0.2`**, not as `Sharpe > 0.5`. Under-report the point estimate; over-report the uncertainty.
2. **Report the block-bootstrap distribution of Sharpe across, say, monthly blocks of the holdout.** If 90% of block-bootstrap Sharpes are positive, the number is not a single lucky window. If half of them are negative, the point estimate is a coincidence.

Same treatment applies to the "three seeds within 0.3 Sharpe" gate. Three seeds is not enough seeds to distinguish training-procedure stability from noise at that tolerance. Either raise the seed count or widen the tolerance and say why.

**The 3-look budget is honor-system.** `register_run.py` asks for a boolean; nothing prevents "no" when the answer is "yes." The correct fix is structural, not procedural: add a filesystem guard that fails any script attempting to read files under `data/aligned/{run_id}.parquet` whose timestamps overlap the held-out range unless a `--i-know-this-is-a-test-look` flag is present, and log every use of the flag with a wall-clock timestamp to an append-only file that no code path can rewrite. This is not paranoia; it is what the "three looks" number is worth if it is not enforced.

---

## 7. The simulator: the biggest single lever, and the softest

Every backtest that has ever lied has lied at the simulator. This one is more careful than most: bar-by-bar walker, no vectorization tricks that risk peeking, fills at the *next bar's open* so the decision variable never touches the fill. Those choices are right.

The cost model is where the honesty is not yet earned.

**The spread proxy is Corwin-Schultz on bar range.** For SPY at 5-minute bars, the true bid-ask spread is one cent most of the day and widens only around the open, the close, and known event bars. Bar range at 5 minutes is dominated by the actual move, not by the spread. Corwin-Schultz on 5-min bars will systematically overestimate the spread by an order of magnitude in normal conditions and underestimate it near events. This is the kind of miscalibration that flatters some strategies and punishes others in ways not related to their edge.

Fix: on the days when the true SPY spread is knowable (any tick-level dataset for the training window will resolve this in an afternoon of work), calibrate the proxy against the truth and either replace it or scale it. If SPY tick data is not available, use SPY BBO snapshots from any free source and calibrate against those. Do not ship the run with an uncalibrated Corwin-Schultz on an instrument that has near-zero spread.

**The slippage coefficient `kappa` is the number that determines whether the Sharpe number is real.** The doc says it will be "calibrated by regressing observed short-horizon return against traded size proxy on the training window" and offers `0.5 bps per 1% of median 5-min volume` as a starting value. That regression is the load-bearing measurement in the whole simulator. It deserves its own section in the technical architecture, not a parenthetical. The section should specify: what is the observed short-horizon return (immediately-next-bar return? five-bar return?), what is the size proxy (traded volume as a fraction of ADV? traded volume as a fraction of concurrent 5-min volume?), what confidence interval attaches to the estimated `kappa`, and what happens to Sharpe as `kappa` moves inside its own confidence interval. A sensitivity plot — reported Sharpe as a function of `kappa` from 0.5x to 2x its point estimate — belongs in the results.

For SPY at $1M capacity (the gate) linear slippage is probably right; SPY absorbs $1M without measurable impact except in the fastest bars. That defensible claim is not in the docs. State it, and cite one number.

**Two smaller simulator points.**

Positions are single-instrument and single-position (technical-architecture §11). Overlapping signals are dropped. This is a scoping choice, not an error, but the doc should say what happens to an entry signal that fires while the previous position is still open: dropped, overrides, or extends. Whichever is chosen, name it.

The `risk_penalty = lambda * variance(p)` term appears in the decision rule with `lambda` unspecified. A hyperparameter that lives only in code and not in config is the exact thing invariant #3 forbids. Move it to the simulation config.

---

## 8. Smaller things

Some are small; none is nothing.

- **Macro channels at 5-min resolution carry very little bar-level information.** CPI is monthly, Fed funds moves at meetings, unemployment is monthly. Between releases they are constant. The `mins_to_next_release` and `days_since_release` features do most of the actual conditioning work. The target-only ablation is the right test of whether the macro slot earns its place, but the docs should predict what the ablation will find. If the macro channel is contributing mostly through the countdown features rather than the values, that is worth saying up front — because if true, the "multi-modal" claim is really "multi-instrument + event-clock," which is a slightly less bold claim honestly stated.

- **Expanding-window normalization freezes to a stable mean after warmup and misses regime shifts.** Rolling would leak. Expanding is defensible for the training window, but for inference on the holdout, the frozen normalizer is doing more work than the doc admits. If 2024–2025 realized vol shifts materially from the 2015–2022 mean, the vol-normalized returns going into the bucketizer are miscalibrated at the input side. This is not a bug; it is a specific failure mode to watch for. Add a diagnostic that plots the normalized-feature distribution on the holdout against training.

- **The optional magnitude-weighted loss** (`w_t = 1 + alpha * |center[target_t]|`) is a good idea and worth running as an ablation, not held for v2. It costs one extra training run and directly tests whether prediction quality on large moves — which is what pays the trading strategy — is being sacrificed to prediction quality on the fat middle.

- **RoPE is the right choice for future context growth.** The specific extension to LOB tokens (v3) implies context lengths past 2k. RoPE extrapolates cleanly. Learned absolute positions would need retuning. Good call, correct reason.

- **Polars over pandas is the right call and the doc says why with a number** (4s vs 90s on the aligned dataset). This is the tone the rest of the doc should adopt for every decision that has an alternative — name the alternative, name the cost, name the choice.

- **Weekly-aggregated targets and longer horizons are absent.** That is a scoping choice, not an error, but v1 as written is a next-bar-only predictor. Whether the same tokens carry information at different horizons is a separate test the design does not yet run. Worth flagging in `product-spec.md` §"What v1 explicitly is not" for symmetry with the other absences.

- **The build-guide describes a `nanoGPT`-style structure with learned positional embeddings**; the tech-arch commits to RoPE. Learned embeddings are what nanoGPT ships with; RoPE is a deliberate change. The build-guide should say "start from nanoGPT's structure, replace the position embedding table with RoPE."

- **The docs never state what happens if calibration passes but Sharpe fails.** If ECE is < 0.05 and the distribution is honest but the decision layer's threshold + cost model produces Sharpe 0.2, is the project a failure or a partial success? Name it. My read: the model is doing the work the model is supposed to do, and the decision layer needs a rethink. Say so.

---

## 9. The one architectural change worth pushing for

Add a **regime-conditional evaluation split**. Not a new training split — a slice on the existing holdout. Tag each 2024–2025 bar with a coarse regime label (VIX terciles, or trending vs. mean-reverting SPY realized vol, or three-state HMM on the training window fit only on training data), and report every held-out metric per regime. Cross-entropy, ECE, directional accuracy, Sharpe.

This does not add a training gate. It adds an evaluation gate. If the aggregate Sharpe is 0.5 and one regime contributes 2.0 while another contributes -0.5, the aggregate is a lie of averages and the honest answer is that the strategy works in one regime and does not work in the other. That is a useful answer. It tells you what v2 has to fix.

Everything else in the package is fine as it is or fixable in-line. The regime split is the one thing the package does not currently do that would materially improve what the package produces.

---

## What I am not worried about

The overall shape of the project. The plain-language proposal. The prior-art positioning. The gate structure. The invariants. The interface discipline. The ablation ladder. The choice of causal decoder over encoder or diffusion. The choice of 32 buckets over 4,096 or 3. The RoPE choice. The Polars choice. The Hydra + Pydantic config layering. The checkpoint-by-ECE decision. The single-GPU compute envelope. The refusal of RL, news, LOB, and multi-instrument for v1. The v2/v3 extensions all sit against clean module boundaries.

The design is right. The right way to finish the job is: patch the simulator's cost model until it is measured rather than starting-valued, attach confidence intervals to the gates, add the regime split to evaluation, add the channel-orthogonality diagnostic to prove the summed embedder worked, and reconcile the small drift across documents.

Do those, and the eventual result — whichever way it lands — will be worth trusting.
