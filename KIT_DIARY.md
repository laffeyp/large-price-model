# KIT_DIARY.md — Price-Space LLM

*Per-sprint or per-phase: what worked, what got in the way, what this says for the next kit version. The diary is the load-bearing artifact that makes lessons compoundable across the project's lifetime.*

---

## How to read this diary

Entries are chronological. Each entry starts with the trigger (Sprint-NNN close, halt, Architect decision, phase boundary). Each entry has this shape:

- **What happened** — one paragraph
- **What worked** — where the kit's discipline paid off
- **What got in the way** — where the discipline added friction or the spec was ambiguous
- **What this says about the next kit version** — a concrete improvement candidate, numbered

Phase boundaries get a synthesis section. At project close, a final synthesis lists the top structural findings for the next kit revision.

---

## Hypothesis tracking

*Hypotheses this project tests. Each gets `confirmed` / `falsified` / `partially` markers as evidence accumulates.*

| # | Hypothesis | Verdict | Evidence |
|---|---|---|---|
| H1 | Kit's Data-science-class techniques cover 80%+ of what training-loop sprints need without invention. | **confirmed** (post-Sprint-072) | 65 sprints authored, zero new vocabulary categories invented; four grammar-evolution rounds all through canonical proposal types. |
| H2 | Observation contract (signal-in-trace + artifact-on-disk + exit-code) catches Addendum D1 class on non-UI project. | **confirmed on projected class** | Four caught defects this stretch (Sprints 020, 023, 042, 067); Sprint 088+ held-out tests remaining class. |
| H3 | Bridge-mapping-first prevents guess-and-iterate on external SDKs. | **confirmed strongly** | Sprints 018, 019 caught response-shape divergence at halt-time; every subsequent vendor call zero-rework on happy path. Error-path bridge mapping is a separate discipline. |
| H4 | Frozen-artifact contract with paired independent-reader test catches the internal-consistency-external-inconsistency class. | **confirmed** | Sprints 054-056 shipped paired readers; three separate defect classes prevented (bucket_train_mean absent; normalizer KS=1.00 on holdout; tokenized-artifact channel-names mismatch). |
| H5 | Vocabulary Session runs faster than BOOTSTRAP's 2.5-4h estimate on a spec-mature project. | **falsified in wall-clock, confirmed in draft** | Draft ~30min, five review rounds pushed total to ~6h across two days. Review discipline paid for the extension. |
| H6 | Locked vocabulary at Sprint 0 produces first-pass-clean sprint closes downstream. | **partially** | ~55/65 sprints first-pass clean (~85%) across Sprints 007-072. Misses cluster on live-vendor-error sprints and multi-concept sprints. Locked vocab is necessary, not sufficient. |
| H7 | Vocabulary type strings are self-describing enough that a ~30-line parser enforces them across the schema. | **confirmed** | Sprint 004 shipped 40-line parser; carried v0.2/v0.3/v0.4/v0.5 evolution rounds with no plumbing edits. |
| H8 | Ruff + mypy adopted on existing small codebase in one sprint is cheap because auto-fix carries most of the work. | **confirmed** | Sprints 006, 015. Ruff auto-fix >80% both times; mypy `# type: ignore[misc]` at un-stubbed boundaries stayed at 2 lines total as codebase grew ~500 → ~5000 LOC. |
| H9 | First-live-contact surfaces vendor error shapes mock-driven tests cannot. | **confirmed hard, 4+ data points** | Sprints 020 (AV error shapes), 023 (VIX-not-intraday), 038 (VIX-INDEX_DATA), 044 (DXY absent → UUP), 050 (VIX volume=0 → VXX). Cost: 1-3 iteration cycles per live-contact. |
| H10 | Rate of code-failure-as-vocabulary-gap Surfaced entries as discipline proxy; zero rate = discipline holding. | **confirmed low** | Zero across Sprints 024-072 after the 2026-08-11 retraction. The reflex has not returned. |
| H11 | Named-review-drives-sprint-work is faster + cleaner than name-a-sprint-then-review. | **tentative** | Sprints 041-072 executed against 3 named review files; ~95% first-pass-clean vs ~85% overall; average 2.4 files touched, 3.1 tests added per sprint. Testable across Phases E, F. |

---

## Entries

### 2026-08-17 — Sprints 084 + 086: drift-watchlist convention retired

**What happened.** The Architect said "no drift watchlist — any drift gets resolved right now." Sprint 084 landed the v0.7 vocab lock (six new required payload fields on `CONFIG_RESOLVED`, one on `TOKENIZED_ARTIFACT_WRITTEN`) plus the normalized-input contract (`UnnormalizedArtifactRefused` on `fusion='mixer'` when the artifact wasn't tokenized through the frozen normalizer). Sprint 086 backfilled 11 missing cache sidecars + 11 index rows on the real cache. The remaining watchlist entries were audited one at a time: the SESSION_COMPLETE.n_signals_emitted item turned out to be architecturally already-closed (single emit site inside `process_session` computes the count from the buffer); the "never name a script after a stdlib module" item is a convention captured elsewhere, not a code drift; the parameter-count-vs-spec-labels item is a spec-vs-reality observation, not a drift. Only `EXPECTED_BARS_PER_TRADING_MONTH` requires an Architect Decision — moved to `## Surfaced for review` with three defensible paths named. Test count 470 → 479. Ruff, mypy, pytest all green.

**What worked.**

- **The "drift watchlist" convention accumulated exactly the wrong things.** In practice, the watchlist collected three classes of entry: (a) resolved-already-noted items, (b) genuinely-live but small drifts, (c) informational observations that were never code drifts. Class (a) belonged in a resolved log; class (b) belonged in a sprint that shipped now; class (c) belonged in project notes. The convention let all three coexist and grow. The Architect's directive resolved this by refusing the mixed-class bucket entirely. Candidate for TECHNIQUES.md § 1: "watchlist patterns rot into three misuse classes; retire and split — resolved-log for (a), sprint-now for (b), project-note for (c)."
- **v0.7 landed clean because the emit sites are enumerable.** Six new required payload fields on `CONFIG_RESOLVED` broke exactly one emit site (`load_config`), which the sprint updated in the same commit. Zero pre-v0.7 traces exist that need migration; zero consumers depend on the pre-v0.7 shape. The vocab bump's blast radius was small because every emit-side surface is discoverable via grep. Candidate for TECHNIQUES.md § 2: "vocab-bump blast radius = emit-site grep count. When the count is 1, land the payload extension in the same sprint. When it's ≥5, split the emit-site migration off first."
- **The cache backfill's idempotence check kept the second-run cost at zero.** Sprint 086 script skips files that already have both a sidecar and an index row. Running it twice is a no-op; running it every time a fresh cache write lands is safe. Candidate for TECHNIQUES.md § 2 Data-science: "backfill scripts should be idempotent by cache-key check; safety costs one dict lookup per file."

**What got in the way.**

- **Ambiguous "watch item" writes attracted more of themselves.** Once the pattern of filing hand-tight observations to a watchlist existed, it became easier to file a new one than to fix an old one. The 14-entry accumulation between 2026-08-10 and 2026-08-17 is the measurable cost. The Architect's retirement directive is corrective; the pattern was quietly compounding weight until the next review sweep would have surfaced it. Lesson: any BLACKBOARD section that isn't touched every sprint accumulates junk. The `## Built` section stays clean because every sprint writes to it; the drift-watchlist section rotted because most sprints wrote to it once and never again.
- **`load_config`'s signature acquired six kwargs.** The load-config emit is a Layer-1 surface; adding six kwargs pushes the emit toward a "resolved bundle" shape that would be better carried as a dataclass. Sprint 084 held the kwargs shape because splitting `ExperimentConfig` and `ModelSizeConfig` at the emit boundary is a bigger refactor. Candidate for a future ergonomics sprint that bundles resolved axes into one `ResolvedRun` dataclass emitted as a single record. Not urgent.

**What this says about the next kit version.**

- **1. Retire "drift watchlist" as a template section.** The kit's `templates/BLACKBOARD.md` shouldn't offer a drift-watchlist header at all. Every observation is either (a) a sprint (immediate resolution), (b) a `## Surfaced for review` entry with a named Decision (Architect-choice), or (c) a resolved-log entry. Candidate for the kit template: rename `## Drift watchlist` to `## Resolved drift log` and describe it as append-only-for-history, never for open work.
- **2. Emit-site-grep-count is a sprint-planning metric.** Sprint 084 (v0.7) touched one emit site; Sprint 080 (v0.6) touched two. Both landed clean. A hypothetical v0.8 touching 5+ emit sites should split the payload extension from the emit-site migration. Candidate for TECHNIQUES.md § 1: "before extending a required payload field, grep `emit\\(<TAG_NAME>` — if the count is ≥5, split into an emit-site-migration sprint first."
- **3. `UnnormalizedArtifactRefused`-shape contracts have a clean pattern: raise + explicit exit code + fix-path stderr message.** Sprint 084's `UnnormalizedArtifactRefused` follows the same shape as Sprint 077's `LegacyMaskSemanticRefused`, Sprint 065's `HeldoutReadRefused`, Sprint 034's `TestLookBudgetExhausted`. All raise, all name the acknowledgment shape in the message, all exit distinct non-zero codes at the CLI. The pattern generalizes: fail-loud contract classes each own an exit code (Sprint 077 = 2 for TestLook; Sprint 084 = 3 for UnnormalizedArtifact); each raise message names the fix path. Candidate for TECHNIQUES.md § 1: "the fail-loud contract pattern — raise-with-fix-path-message + distinct exit code + explicit-opt-in kwarg."

**Hypothesis verdicts.**

- H6 (locked vocab → first-pass-clean downstream). Sprints 084 and 086 both first-pass code-clean. Running tally 67/78 first-pass across Sprints 007-086.
- H11 (specific upstream artifact drives cleaner sprints). Both sprints executed against a specific upstream artifact — Sprint 084 against three named watchlist entries; Sprint 086 against the 2026-08-13 cache-backfill entry. Pattern continues to compound; the watchlist retirement means the same pattern moves to `## Surfaced for review` going forward, which was already the strongest driver by measurement.
- **New H12 candidate.** Retirement of an accumulating section is cheaper as one coordinated wave than as N per-sprint fixes. Sprint 084 + 086 drained a 14-entry watchlist in one afternoon; the same drain via 14 individual sprints would have taken weeks. Testable via: whether any other BLACKBOARD section accumulates ≥10 open entries again before the project close.

---

### 2026-08-17 — Sprint 083: ChannelMixerEmbedder + first live-smoke divergence

**What happened.** Landed the tech-arch § 10 code sketch as `ChannelMixerEmbedder` alongside Sprint 053's linear-sum `MarketStateEmbedder`. Same interface — `dict[str, Tensor[B, T, F_c]] → Tensor[B, T, d_model]` — swapped via `MarketStateTransformerConfig.fusion`. `scripts/train.py` picked up `--fusion {sum,mixer}`, `-mix` run_id infix, kwargs threaded. Test count 464 → 470. The live smoke on the real 2015-2022 training .pt exposed the class of failure the spec's "parameter counts are matched to linear fusion" clause does not name: the mixer's random-init attention produces first-step gradients on the order of the input scale, and the un-normalized corpus (dollar_volume ~$448M) blows the trainer's divergence guard within one backprop.

**What worked.**

- **Sprint 053's `MarketStateEmbedder` interface was the right abstraction.** Adding a second embedder took one class + one `fusion` field + one branch in `MarketStateTransformer.__init__`. Every existing test that built a `MarketStateTransformer` continues to work; the new fusion is invisible to code that doesn't pass the flag. Candidate for TECHNIQUES.md § 2: "when landing a new algorithmic variant, honor the existing interface — don't invent a parallel type hierarchy."
- **Deterministic-with-seed test caught what a shape test wouldn't.** `MultiheadAttention` initializes weights during construction; without `torch.manual_seed` reset between the two builds, two `ChannelMixerEmbedder` instances would produce different outputs on identical inputs, silently. The determinism test guarantees the module is a pure function of `(seed, input)` — a precondition for the bit-tight determinism budget the sprint declared. Candidate for TECHNIQUES.md § 2: "any module containing a weight-random-init component gets a same-seed round-trip test."
- **Synthetic-.pt smoke absorbed the real-corpus divergence.** When the mixer's real-corpus smoke tripped the trainer divergence guard, the fix wasn't to loosen the guard or lower the learning rate (both would mask the real behavior). The fix was a synthetic small-scale .pt that exercises the CLI path without hitting real-data scale. The real-corpus divergence became a signal — filed to drift-watchlist as a normalizer-fit requirement — instead of a test-suite headache.

**What got in the way.**

- **The spec says "parameter counts are matched to linear fusion" without saying how.** Sum embedder at xs=128: `Σ_c F_c × 128 + biases`. Mixer at xs=128 + mixer_dim=96: `Σ_c F_c × 96 + attention_params + 96 × 128`. Not equal at any obvious `mixer_dim`; matching needs per-size tuning against the target parameter count. Sprint 083 shipped the spec's default `mixer_dim=96` with `n_heads=2`; Sprint 087's architecture ablation runner will tune the mixer's hidden width to match the sum embedder's count per size class. Named on the sprint card as a Sprint-087 follow-up. Real work; not a bug.
- **Warmup only helps the optimizer; the divergence guard checks the pre-clip gradient.** I tried `--lr 1e-5` and `--warmup-steps 0` variations expecting the divergence to go away; neither helped because `grad_norm > grad_clip*10 = 10` is checked BEFORE the optimizer step. The divergence guard measures the raw backward-pass magnitude, and that magnitude is `O(input_scale × weight_init_scale)` — invariant to LR. Lesson: distinguish "large update" (LR-dependent, warmup fixes) from "large gradient" (input+init-dependent, normalization fixes). Candidate for TECHNIQUES.md § 2 Data-science: "the divergence guard measures gradient, not update; treat it as an input-normalization diagnostic."

**What this says about the next kit version.**

- **1. `strict_std_clamp`-style fail-loud has a dual for training runs: `require_normalized_input`.** A trainer that consumes un-normalized `.pt` should either (a) refuse to run (like `LegacyMaskSemanticRefused`) or (b) apply a fitted normalizer at load time. Currently `run_training_feats` accepts any `.pt` and lets the divergence guard catch the pathology after the first backward pass — expensive, opaque. Sprint 084+ candidate: `TokenizedArtifact.meta` gains a `normalized: bool` marker (set by `apply_frozen_normalizer` at tokenize time); `run_training_feats` raises `UnnormalizedArtifactRefused` unless the caller opts in. Same shape as Sprint 077's `allow_legacy_mask`.
- **2. `-mix` infix as a discriminator in `run_id` is one axis among many.** Sprint 073's `-{size}`, Sprint 074's `-c{N}`, Sprint 083's `-mix` all compose in the run_id. A sweep sprint (084+) that varies size × context × fusion produces `train-<stem>-{size}-c{N}-mix-s{steps}-{seed}` names — searchable, sortable, greppable. Candidate for TECHNIQUES.md § 1: "run_id as a sortable filename-encoded config lookup — axis infixes compose without cross-referencing a manifest."

**Hypothesis verdicts.**

- H6 (locked vocab → first-pass-clean downstream). Sprint 083 first-pass code-clean; second-pass smoke-clean (real-corpus mixer divergence exposed the input-normalization requirement, absorbed via synthetic .pt). Running tally 65/76 first-pass across Sprints 007-083.
- H9 (first-live-contact surfaces failure modes mock-driven tests cannot). **Confirmed strongly on Sprint 083.** The synthetic-fixture unit tests all passed cleanly; the real-corpus smoke exposed the input-scale × attention-init class of divergence within one second of CPU wall clock. Zero mocks could have surfaced this — the mock feature tensors have `N(0, 1)` scale by convention. Candidate for TECHNIQUES.md § 2: "any new model component ships with a real-corpus smoke, not just synthetic-fixture tests. The mocks agree with themselves; the corpus doesn't."

---

### 2026-08-25 — Sprints 110-116: Phase H opens, normalization bug, real signal

**What happened.** Seven training sprints on the M5 Max via MPS after Sprint 109 pivoted away from AWS. Sprint 110 ran the model-size sweep and concluded the transformer loses to a linear baseline. Sprint 111 diagnosed per-regime and confirmed the loss. Sprint 112 tested longer training (H1) and stronger regularization (H2); H1 partially worked but couldn't cross the linear baseline. Sprint 113 caught the root cause via a target-only ablation matching full-channel to 4 decimals — `tokens.latest.pt` had been generated 71 days earlier without `--fit-normalizer`. Raw `dollar_volume` (mean 61M, std 264M) had been drowning every non-target channel inside sum fusion. Sprint 113 broadened Sprint 084's mixer-only guard, swapped the canonical artifact to a normalized version, and re-ran md — pooled val_nll dropped from 3.406 to 3.198 (+2.77% vs linear). Sprint 114 multi-seeded that config (mean +1.87% ± 3pp) and swept weight decay (no effect); best-checkpoint consistently landed at end-of-warmup, diagnosed as a schedule-transition problem. Sprint 115 dropped peak LR: sum at lr=1e-5 extended descent to step 8000, mixer at lr=3e-5 hit best-of-arc pooled 3.148 (+4.26% vs linear), wins every regime. Sprint 116 multi-seeded that: mean +3.29%, stdev 0.022 (tighter than sum), but 3/5 seeds diverge mid-training. Test count 605 → 628 across the wave; logbook 0 → 26 rows.

**What worked.**

- **The target-only ablation as bug-finder.** Sprint 113-A ran with `--target-only` and matched Sprint 110 v3 md to four decimals in every regime. Bit-identical results are diagnostic, not confirmatory — "the multi-channel model performs identically to the target-only model" was the shape that forced the right question. Sprint 111 review's central prediction ("multi-channel edge is real but small") pinned the expected shape; the identity result contradicted it and pointed at the artifact. Candidate for TECHNIQUES.md § 2: "when an ablation gives suspiciously-similar-to-3-decimals numbers, don't celebrate the finding — investigate the setup that produced it."
- **The Sprint 084 guard shape scaled up correctly, once fixed.** Broadening `UnnormalizedArtifactRefused` from mixer-only to every fusion caught the whole class of silent-quality collapse. The guard's fix-path stderr message names the Sprint 113 finding explicitly — a future reader trips the guard and gets the whole context in one error message. The `allow_legacy_mask` pattern from Sprint 077 generalized here: any read-time contract field (`normalized`, `mask_semantics`, `raw_targets_stamped`) becomes a guard target.
- **`run_id` hyperparameter fingerprint (Sprint 113b) made Sprint 112-style collisions structurally impossible.** Every training run now carries `-hp{8char}` — a sha256 over 15 hyperparameters. Sprint 112 md-regularized would have gotten `-hp5a54265a` where Sprint 110 v3 md got `-hp1ede6816`. Distinct configs cannot share checkpoint paths. Sprint 083's `-mix` infix pattern was descriptive; the hp fingerprint is prescriptive.
- **Auto-registration via `scripts/register_from_trace.py` turned the logbook from "aspirational" to "populated."** Sprint 111 caught that `experiments/logbook.csv` didn't exist despite `scripts/register_run.py` shipping at Sprint 079. Retroactive registration of Sprint 110-113 runs plus a helper for every future run turned the tracking gap into a discipline. Sprint 116 close: 26 rows.

**What got in the way.**

- **Sprint 084's docstring line — *"sum fusion tolerates un-normalized input via internal LayerNorms and is unaffected"* — was a load-bearing untested assumption for 71 days.** It read as authoritative because Sprint 083's mixer divergence was visible and Sprint 084 was tightening a real observation; the comment about sum was a plausible extrapolation that got treated as fact. Every reader after Sprint 084 (including me, twice) inherited the confidence. Filed KIT_DIARY lesson: an untested claim in a comment is a load-bearing lie. Should be either verified inline or written as a hypothesis.
- **Sprint 113's +2.77% and Sprint 115's +4.26% were both seed-lucky headlines.** Sprint 114 multi-seed showed seed 0's 3.198 was near the top of a 5-seed distribution centered at 3.227 (mean margin +1.87%, one seed lost to linear). Sprint 116 multi-seed showed seed 0's 3.148 was near the top of a 5-seed distribution centered at 3.180 (mean margin +3.29%). Both single-seed headlines were about 1.5σ above the mean. This is not seed 0 being special — it's what "the first number you measure" tends to be when the noise is real. Cost: two rewrites and a running credibility discount on subsequent headlines. Candidate for TECHNIQUES.md § 5: any new-config first-arc-win headline is single-seed-invalid until the mean lands.
- **Sprint 083's mixer support was never round-tripped through `evaluate.py`.** Sprint 115 discovered this: the mixer checkpoints saved by the trainer omitted `fusion`, `mixer_dim`, `mixer_n_heads` from the config field, and `evaluate.py::_load_market_state_checkpoint` hardcoded `fusion=sum` default. Mixer checkpoints were unloadable via the standard eval path. The bug had been latent for 42 days (Sprint 083 landed 2026-08-16, Sprint 115 caught it 2026-08-25). The pattern: any new axis added to training (Sprint 083 mixer, Sprint 087 patch, Sprint 089 quantile) needs an evaluate.py round-trip test before it counts as landed. Candidate for TECHNIQUES.md § 2: "landed = training + evaluate.py + one full round-trip smoke."
- **AWS scaffolding was over-engineering.** Sprints 107-108 built full AWS infrastructure — IAM roles, S3 buckets, Budgets, boot scripts, quota requests — for a workload the operator's M5 Max handles trivially. The operator surfaced this at Sprint 109 with one question ("can this machine run the training?") that I hadn't asked. Filed lesson: before ordering hardware (or renting it), size the hardware the workload asks for. The scaffolding stays warm as insurance; the two sprints of work were disproportionate to the need.
- **Training-time val_nll and evaluate.py's pooled val_nll are different numbers.** The trainer computes val_nll over one split; evaluate.py computes weighted-by-regime pooled val_nll over another. Sprint 110's md hit training-side 3.30 but pooled 3.406. Every arc headline had to disambiguate. The trainer should either emit both, or the val split should be unified across the two paths. Not fixed yet.

**What this says about the next kit version.**

- **1. `TokenizedArtifact.meta` contract fields need read-side enforcement.** `normalized: bool` was in the artifact meta for 71 days and never checked at load. `raw_targets_stamped: str` (Sprint 088) is another. Any field marked as part of the read-time contract should either raise on missing/wrong value or be removed from the contract. Sprint 077's `LegacyMaskSemanticRefused` was the right shape and should generalize. Candidate: `load_tokens_pt(path, *, expected_normalized=True, expected_mask_semantics=..., expected_raw_targets_stamped=...)` refuses without an explicit opt-out. Every consumer names its contract requirements at the read boundary.
- **2. Checkpoint config must round-trip every architecture axis.** Sprint 083 (mixer), Sprint 087 (patch), Sprint 089 (quantile) all added architecture axes that the checkpoint config didn't record. Sprint 115 caught mixer's version. Sprint 088's `head_type` may be the next. Fix at trainer save-time: serialize every `MarketStateTransformerConfig` field into the checkpoint's `config` dict, not just the manually-listed subset. A `MarketStateTransformerConfig.to_dict()` method + `.from_dict()` roundtrip test would enforce this by construction. Candidate for kit templates: any new architecture axis added to `MarketStateTransformerConfig` must include a round-trip test.
- **3. Multi-seed the headline before writing the report.** Sprint 113 and Sprint 115 both wrote single-seed reports that had to be revised at Sprint 114 and Sprint 116. The kit pattern should be: any new-config first-arc-win runs multi-seed (n=5) before the report writes. Cost: 5x wall-clock, worth it. Candidate for `templates/SPRINT_TRAINING_RUN.md`: single-seed is a probe, not a headline.
- **4. Auto-registration hook on the trainer.** `scripts/register_from_trace.py` is a helper the operator invokes after each run. It should be the trainer's own responsibility — on `SESSION_COMPLETE`, write the logbook row. No orphan runs possible then. Candidate for `templates/SPRINT_TRAINING_RUN.md`: logbook write is part of run-close, not a separate step.
- **5. Per-channel gradient monitoring.** Sprint 113 caught the normalization bug because target-only matched full-channel. A per-channel gradient-norm emit on `TRAINING_STEP_COMPLETED` would have shown non-target channels' gradients collapsing to zero within 100 steps — visible before the val_nll comparison ever runs. Vocab v0.8 candidate: `grad_norm_by_channel: list<float>` on the step emit.

**Hypothesis verdicts.**

- H6 (locked vocab → first-pass-clean downstream). Sprints 110-116 first-pass code-clean on the training scripts; the normalization bug was in the *data* contract, not the code. Running tally 84/98 first-pass across Sprints 007-116.
- H9 (first-live-contact surfaces failure modes mock-driven tests cannot). **Confirmed at extreme scale.** Every synthetic-fixture test passed for 71 days while the real-corpus training was silently target-only-equivalent. The synthetic fixtures used features with `N(0, 1)` scale by convention — precisely the case where non-target channels *don't* drown. Only real-corpus training with real dollar_volume scale reproduces the bug. Reinforcement of Sprint 083's lesson: any new component or configuration ships with a real-corpus smoke.
- **New H14 candidate.** Ablations that give suspiciously-similar-to-N-decimals numbers should be treated as diagnostic tells, not confirmatory results. Sprint 113-A's target-only-matches-full-channel-to-4-decimals was the tell that forced the bug discovery. When a paired ablation returns identical numbers to more than 2-3 decimals across independent metrics, the correct next question is not "great, features don't help" but "which shared upstream failure produces identity in both?"

**Phase H opens numbers so far.**

- 7 training sprints (110-116), all on M5 Max via MPS, zero AWS training spend.
- 21 registered training runs in `experiments/logbook.csv`.
- Best result: mixer + lr=3e-5, pooled val_nll 3.148 seed 0 / 3.180 mean-5-seed, +4.26% best / +3.29% mean vs linear.
- Pre-registered gate: val_nll ≤ 2.960 (10% below linear). Gap: 5.7% at best, 6.7% at mean.
- 3 novel discipline items filed (H14 candidate above, single-seed-is-a-probe rule, checkpoint-config-round-trip rule).
- 1 silent bug caught (71-day normalization miss), same-sprint fix + retraction + audit-trail update.
- 2 tech-debt items closed same-sprint as caught (guard broadening, run_id fingerprinting).

---

### 2026-08-17 — Sprints 087-090: Phase E closes

**What happened.** Four sprints in one wave closed the last four Phase E ablation-infrastructure items. Sprint 087 landed `PatchEmbedder` per tech-arch § 10 code sketch (`nn.Linear(patch*F_c, d_model)` per channel + `_patch_targets(targets, patch)` trainer helper). Sprint 088 added a `raw_targets: Tensor | None` field on `TokenizedArtifact` as foundation for pinball loss. Sprint 089 landed the quantile head (`nn.Linear(d_model, 9)` + `pinball_loss` helper + `QuantileHeadRequiresRawTargets` fail-loud contract). Sprint 090 added `--n-buckets {16,32,64}` overrides on both bucketize + train. Live sweeps on the real 2015-2022 corpus verified every axis end-to-end. Test count 479 → 499. Ruff, mypy, pytest all green.

**What worked.**

- **Sprint 053's embedder interface generalized to four variants without one interface break.** Sum (053), mixer (083), patch (087), and by extension the quantile-head backbone (089) all consume `dict[str, Tensor[B, T, F_c]]` and produce `Tensor[B, T', d_model]`. `MarketStateTransformer.__init__` picks between them via a config field; no downstream trainer/eval code cares which embedder ran. Candidate for TECHNIQUES.md § 2: "when landing a new ablation on top of a stable interface, extend at the constructor branch — never fork the whole training loop."
- **`-{axis}` run_id infix composition scales to six dispatch axes with zero coordination.** After Sprint 090, the composed run_id can carry `train-<stem>-{size}-c{N}-mix-p4-qh-b{V}-s{steps}-<seed>`. Sweep scripts iterate the six-axis product; each combination produces a distinct filename that `ls` sorts sensibly and `grep` filters cleanly. Candidate: name "one-axis-per-infix" as an SDD pattern in TECHNIQUES.md § 1 — the run_id becomes the sortable identity key without any manifest lookup.
- **Sprint 088 as the smallest possible foundation for Sprint 089 landed clean.** Splitting "quantile head" into (a) raw_targets field + tokenizer stamp and (b) head + pinball + trainer wire kept both sprints under hard rule 6 in code files (2 + 5) while keeping the concept per-sprint singular. The v0.8 vocab bump that would land `head_type` + `patch_size` on `CONFIG_RESOLVED` is a third piggyback candidate; deferred to when it consolidates with additional axes.
- **Live-smoke divergence detection stays load-bearing.** Sprint 083's mixer diverged at the same real-corpus smoke that Sprint 087's patch=4 passed on. The divergence guard measured a real property (input scale × attention-init) that surfaced Sprint 083's normalization requirement and stayed silent on Sprint 087's linear-projection packing. Neither behavior was tested by any synthetic-fixture unit test.

**What got in the way.**

- **Sprint 089's B023 ruff warning caught a real closure-capture pattern I would not have found otherwise.** The inner `_loss_from_logits` closure captured `raw_targets_patched` and `targets` from the enclosing loop scope; ruff's B023 correctly flagged the late-binding pitfall. Fix was default-argument capture — the standard Python pattern. Same trap could have applied any time I write a per-step inner function; noting the pattern here so a future sprint doesn't have to rediscover it. Candidate for TECHNIQUES.md § 2 Python-specific: "inner functions defined in a loop body must capture loop variables via default arguments — ruff B023 catches this."
- **Sprint 089's val metrics gap is honestly named but is a real gap.** Quantile-head runs zero out the six categorical val_* fields (val_ece, val_brier, etc.) since none apply. Downstream evaluator sees zero and cannot distinguish "quantile checkpoint" from "categorical checkpoint that diverged." Sprint 090+ candidate: `CHECKPOINT_WRITTEN` payload gains `checkpoint_kind` (categorical/quantile) so the evaluator dispatches correctly. Named in the Sprint 089 close; not urgent (Sprint 090 doesn't consume val metrics; Sprint 088+ held-out evaluation does).
- **`_split_artifact` needed manual raw_targets preservation.** The Sprint 089 first-pass CLI smoke failed because I forgot to thread `raw_targets` through the train/val split — the artifact went in with the field, the split dropped it, and the sampler saw None. Caught by the test suite immediately. Same class of bug as forgetting to preserve `is_overnight_gap` or `mask`. A hypothetical refactor that autogenerates the split via `dataclasses.replace(artifact, **field_slices)` would eliminate this whole class of forgetting; not urgent, filed as a future ergonomics candidate.

**What this says about the next kit version.**

- **1. Phase closes deserve a formal synthesis.** Phase E ran from Sprint 073 (2026-08-16) through Sprint 090 (2026-08-17). Two calendar days, 18 sprints, five spec § 10 ablations (sum + mixer + patch + quantile + bucket-count-variants), one raw_targets foundation sprint, two vocab bumps (v0.6, v0.7), three fail-loud contract classes (`UnnormalizedArtifactRefused`, `LegacyMaskSemanticRefused`, `QuantileHeadRequiresRawTargets`). The `## Sprint tail` section captures per-sprint detail; a `## Phase syntheses` section would capture cross-phase patterns explicitly. Candidate for the kit template's BLACKBOARD structure.
- **2. Six dispatch axes suggest a dedicated sweep script class.** Currently `scripts/train.py` accepts one run per invocation. Sprint 084+'s rented-GPU sweep needs an outer harness that iterates axis combinations, dispatches per point, collects results. Candidate for the kit template: `templates/SPRINT_SWEEP.md` describing the sweep-runner pattern (Cartesian product over axis lists, `_pointsN_experiments.csv` output, `run_id` collision by design).
- **3. Ablation-infrastructure sprints share a discoverable shape.** Sprints 073/074/083/087/089/090 all follow: (a) new module/config field, (b) selector in a construction branch, (c) `--flag` on `scripts/train.py`, (d) `-{tag}` run_id infix, (e) 5-7 tests spanning shape + edge cases + CLI smoke. This is a repeatable pattern; documenting it as a "Phase E-shape" template in the kit would let a future project drop-in similar sprints without rediscovering the shape.

**Hypothesis verdicts.**

- H6 (locked vocab → first-pass-clean downstream). Sprints 087, 088, 090 first-pass code-clean. Sprint 089 second-pass (ruff B023 catch + `_split_artifact` raw_targets fix). Running tally 70/82 first-pass across Sprints 007-090.
- H11 (specific upstream artifact drives cleaner sprints). All four sprints executed against tech-arch § 10 code sketches (087, 089) or explicit roadmap items (090). Every sprint clean on the code side. The spec-code-sketch-as-driver is now compounding — quantile head shipped byte-for-byte from the sketch in one pass.
- **New H13 candidate.** Ablation sprints executed as a wave (four sprints in one two-hour session) compound faster than four sprints across four sessions. Shared context and shared kit-in-mind reduce the per-sprint re-orient cost. Testable when the next multi-sprint wave (Phase F cost calibration + simulator infrastructure, or Phase H GPU sweeps) opens.

**Phase E close numbers.**

- 18 sprints (073 → 090; 075/076/077/078/079/080/081/082/084/086 were watchlist-drain interleaves; the pure Phase E sprints were 073, 074, 083, 087, 088, 089, 090).
- Test count 432 (post-Sprint 072) → 499 (+67 across the phase).
- Six dispatch axes composable in `run_id` per training run.
- Three fail-loud contract classes added (`UnnormalizedArtifactRefused`, `LegacyMaskSemanticRefused`, `QuantileHeadRequiresRawTargets`) plus one pre-existing (`HeldoutReadRefused`) — the pattern generalized cleanly.
- One vocab convention retired (drift watchlist); two vocab locks (v0.6, v0.7).
- Zero silent scope reductions.

---

### 2026-08-17 — Sprints 080-082: v0.6 vocab bump + heldout fail-loud + evaluator ignore-index

**What happened.** Three sprints closed the remaining outstanding items the Architect surfaced. Sprint 080 landed a v0.6 vocab lock adding `TOKENIZED_ARTIFACT_WRITTEN` (Sprint 052 → 078 deferral) and `NORMALIZER_CHANNEL_UNDER_CLAMP` (Sprint 076 → 079 deferral) — two new tags in one lock, both wired at their fit-time / write-time sites. Live-smoke trace shows `TOKENIZED_ARTIFACT_WRITTEN` firing on the real 2015-2022 tokenize regen at t=0.1265 carrying the versioned path + sha. Sprint 081 tightened `heldout_guard` from "unknown filename = silent False" to "unknown filename = raise `UnrecognizedArtifactShape` unless `allow_unrecognized=True`" — extended `KNOWN_DATED_PATTERNS` to cover Sprint 078's new `tokens.<run_id>.pt` shape which would have slipped the pre-Sprint-081 regex entirely. Sprint 082 fixed a real correctness gap: `_metrics_over_positions` in the evaluator did not filter `IGNORE_INDEX = -100` sentinels before scoring, so on the market-state feats path (Sprint 053+) every null-target row landed in the denominator with a garbage bucket id, deflating top-1/top-3/dir_acc and picking a wrong probability via `probs.gather(1, -100)`. Test count 458 → 464 across the three sprints. Ruff, mypy, pytest all green throughout.

**What worked.**

- **Chaining vocab bumps against prior deferrals compounds.** v0.6 landed two tags in one lock, both of which were named on the closing card of an earlier sprint (052 for tokenize, 076 for under-clamp). The deferral notes did the planning work — Sprint 080 lifted them into a single vocab-bump sprint without reopening the design question. Same shape as Sprint 055's v0.5 lock (one tag from a Sprint 054 named follow-up). Candidate for TECHNIQUES.md § 1: "vocab-bump sprints batch named deferrals; the deferral card IS the vocab-bump proposal."
- **Sprint 082's synthetic-fixture test caught the real evaluator bug the Sprint 077 review-verify pass missed.** The 12-section review-verify pass I ran on 2026-08-16 scanned the metric surface but never fed the compute function a -100 target. Writing the four-window test (three valid + one ignore) surfaced the wrong-shape behavior mechanically. Candidate for TECHNIQUES.md § 2 Data-science: "metric functions get an ignore-index truth-table test as their first check — one row per (valid/invalid) × (correct/incorrect)."
- **`KNOWN_DATED_PATTERNS` as an audit-visible list did the work a filename-parser wouldn't.** Sprint 081 could have written a more permissive parser that inferred the leading year regardless of prefix. The frozen tuple of explicit patterns instead forces a code change per new artifact class. A reviewer scanning `heldout_guard.py` sees the exact set of shapes the guard recognizes. This mirrors Sprint 076's `EXPECTED_CONSTANT_CHANNELS` frozenset. Candidate: name "audit-visible frozen set" as a pattern in TECHNIQUES.md § 1 — for any exemption or capability list where silent drift would matter.

**What got in the way.**

- **The vocab bump touched nine files.** v0.6 lands new JSON + new rationale + new symlink + loader default + two emit sites + one existing-fixture test bump + two new-tag tests. Hard rule 6 says ≤2 code files, but vocab bumps carry an implicit exemption per past discipline (Sprint 009 v0.2, Sprint 022 v0.3, Sprint 055 v0.5). Naming the exemption explicitly in AGENTS.md hard rule 6 would remove the tension between the letter of the rule and the practice. Candidate for the kit's AGENTS.md.
- **Sprint 082's fix flipped a subtle metric-value on already-emitted eval runs.** Pre-Sprint-082 metric JSONs in `artifacts/` carry the old (wrong) top-1 / dir_acc values for the market-state feats path. There is no consumer of those JSONs today (Sprint 088 is the first held-out eval), but if there were, Sprint 082 would silently change reported metrics on the next run against the same checkpoint. Named on the sprint card as a "correctness fix on unused artifacts"; the mask-semantics bump in Sprint 075 was the same shape (fixed a lie in a field no consumer had wired). Pattern worth noting: **correctness fixes on artifacts with zero live consumers cost nothing today and everything if consumers exist tomorrow**. The v0.6 vocab bump's `TOKENIZED_ARTIFACT_WRITTEN` payload includes `mask_semantics` for exactly this reason — future consumers can distinguish artifact eras.

**What this says about the next kit version.**

- **1. Vocab-bump sprints deserve a named scope-class exemption from hard rule 6.** Past practice: Sprints 009 (v0.2), 022 (v0.3), 040-retracted (v0.4), 055 (v0.5), 080 (v0.6) all touched 5-10 files. All landed clean. The rule is "one concept per sprint," and a vocab bump IS one concept even when it spans several files. Candidate: add a sentence to AGENTS.md hard rule 6 naming vocab bumps as a legitimate multi-file scope class.
- **2. "Correctness fix on an artifact with no live consumer" needs its own tag.** Sprints 075 (mask), 076 (std_clamp), 077 (loaders), 082 (metrics) all fixed correctness bugs in artifacts nothing currently reads. Cost today is zero; cost when the first consumer lands is compounded. Every fix carried a version marker or a re-materialization step. Candidate: name a pattern "pre-consumer correctness fix" in TECHNIQUES.md that describes the marker + re-materialize + downstream-audit shape.

**Hypothesis verdicts.**

- H6 (locked vocab → first-pass-clean downstream). Sprints 080 first-pass clean (one fixture bump for the version pointer expected). Sprint 081 first-pass clean (replaced one test, added two). Sprint 082 first-pass clean (two new tests hit the fix path). Running tally 64/75 first-pass across Sprints 007-082.
- H11 (specific upstream artifact drives cleaner sprints). All three sprints executed against a specific upstream artifact — Sprint 080 against the two named deferrals; Sprint 081 against the 2026-08-16 § 11 drift-watchlist entry; Sprint 082 against a re-read of the metric functions surfacing the ignore-index gap. Pattern continues to compound: 12 of the last 12 sprints have shipped against a named upstream trigger, all first-pass clean on the code side.

---

### 2026-08-17 — Sprints 078-079: storage integrity uniform + strict-clamp at fit time

**What happened.** Sprint 078 closed the third storage-integrity gap Sprint 077 named. `run_tokenizer_pt` shifted from raw `torch.save` at a bare path to `artifacts.write_versioned` with `tokens.{run_id}.pt` + `.sha256` sidecar + `tokens.latest.pt` symlink. Live smoke regenerated the 2015-2022 training window: on-disk layout matches the Sprint 036 shape every other frozen artifact class already used, `shasum -a 256` byte-matches the sidecar, downstream training smoke exits 0 with bit-identical loss to the pre-Sprint-078 write path (only the file path changed; payload bytes are the same). Sprint 079 wired Sprint 076's `warn_channels_under_clamp` into `fit_frozen_normalizer` as `strict_std_clamp=True` default, raising `NormalizerStdClampViolation` on any non-exempt (channel, feature_index) whose std sits below the clamp. Pre-landing probe of the current-corpus normalizer returned zero hits — safe to make strict the default. Test count 453 → 458 across both. Ruff, mypy, pytest all green.

**What worked.**

- **Making the writer emit the versioned path let every downstream test survive with no assertion changes.** `run_tokenizer_pt` used to write to a computed bare path and return it; every test called `torch.load(output, weights_only=False)` on the returned handle. Sprint 078 changed the write path but kept the return-value contract — the tests read the versioned path instead of the bare path without knowing they'd shifted. Return-a-handle beats compute-a-name in exactly this class of migration. Candidate for TECHNIQUES.md § 1: "artifact writers should return the path they wrote to, not require the caller to reconstruct it."
- **The pre-landing probe on the real corpus dictated the default.** Before making `strict_std_clamp=True` the default, one line of code (`warn_channels_under_clamp(load_frozen_normalizer(...))`) confirmed zero hits on the actual production normalizer. That data point picked the default. If the probe had returned hits, the default would have stayed False and the sprint would have shipped only the kwarg. Cheap probes before defaults save downstream cost. Candidate for TECHNIQUES.md § 2: "probe the production artifact before flipping a strict default."
- **Chaining fix sprints closed follow-up chains three deep.** Sprint 076 shipped the helper; Sprint 077 named the fit-time follow-up; Sprint 079 wired it. Each sprint stayed under hard rule 6 by ratcheting one concept at a time. The three-sprint chain absorbed the same class of concern (silent-fallback tightening) across three surfaces (module constant → field, load-time silent fallback → fail-loud, fit-time helper → strict default). Same pattern as Sprints 054-055 (frozen normalizer → drift diagnostic → v0.5 vocab tag) at the beginning of Phase C. Chained ratcheting is a recognizable rhythm.

**What got in the way.**

- **Two synthetic-normalizer tests broke on the strict-default flip, and I discovered them by running the suite.** Sprint 079 shipped the default expecting only the two new tests I wrote to hit `NormalizerStdClampViolation`. Two existing tests (`test_apply_passes_zero_std_columns_through_as_zero`, `test_fit_ignores_null_target_rows`) also fit on constant-column features on non-exempt channels for other reasons. Fix was mechanical (add `strict_std_clamp=False`) but the discovery was post-facto. Sprint 077's KIT_DIARY entry named exactly this class of cost ("every silent-fallback fix has a 'opt-in flag ⇒ update every caller' cost the fix sprint should name"). Sprint 079 could have prevented the second-pass edit by grepping `fit_frozen_normalizer(` in tests as part of its plan, not after the fact. Habit worth practicing.
- **The intermediate-cleanup path in `scripts/bucketize.py --fit-normalizer` is hand-tight.** The two-pass fit writes a pre-norm intermediate `.pt` (plus its Sprint 078 sidecar), fits the normalizer, re-materializes the final `.pt`, and cleans up the intermediate + sidecar. No test enforces that both files vanish. If a future change to `run_tokenizer_pt` produces additional sidecar-like files (a `.meta.json`, another sha variant), the cleanup would leave orphans and no test would catch it. Watch-item eligible; not filed to drift-watchlist yet because the failure mode is speculative and the current cleanup is correct.

**What this says about the next kit version.**

- **1. `write_versioned` should be the default writer for any frozen artifact, not an opt-in helper.** Every frozen artifact class in this project now routes through it (bucket_stats, normalizers, spread_scaler, kappa, checkpoints, tokenized `.pt` as of Sprint 078). The only class that ever skipped it was the one that got in-place-overwritten during Sprint 075. Candidate for the kit template `TECHNIQUES.md § 2 Data-science` update: "any dict-serialized frozen artifact ships via `write_versioned` from day one; a raw `torch.save` / `json.dump` at a bare path is a red flag at review time."
- **2. The `strict_std_clamp` shape (mandatory-with-explicit-opt-out) is different from `allow_legacy_mask` (optional-with-explicit-opt-in).** Sprint 077's fail-loud loads default to strict AND require `allow_legacy_*=True` for the escape hatch (loading is a query about existing state, so failing loudly is safe). Sprint 079's fit-time strict check also defaults to strict, requires `strict_std_clamp=False` for the escape hatch, but the escape hatch is called out on a per-fit basis (fitting is a production step where synthetic-data cases legitimately need the escape). Both fit the SDD "halt-and-articulate" rule but at different lifecycle stages. Naming the two shapes ("query-strict" vs "action-strict") in TECHNIQUES.md may reduce the confusion when either pattern is picked up on a new project.

**Hypothesis verdicts.**

- H6 (locked vocab → first-pass-clean downstream). Sprint 078 first-pass clean; Sprint 079 second-pass (two existing tests migrated post-fail). Tally 61/72 first-pass across Sprints 007-079. The pattern of "post-facto test discovery" pushed the rate down slightly; the Sprint 077 diary entry's proposal ("grep call sites as part of the plan, not after") would recover this.
- H11 (specific upstream artifact drives cleaner sprints). Sprint 078 executed against Sprint 077's close notes naming the storage gap; Sprint 079 executed against Sprint 076's follow-up naming the fit-time wire. Both first-pass-clean on the code side. The named-follow-up-as-driver pattern is compounding: three sprints have now shipped against a prior sprint's own close-note.

---

### 2026-08-17 — Sprint 077: fail-loud loads + roadmap errata

**What happened.** Architect surfaced two loosened SDD invariants after Sprints 075-076 closed: `load_tokens_pt` silently accepted `.pt` files missing the `mask_semantics` marker, and `load_frozen_normalizer` silently fell back to `STD_CLAMP=1e-8` on missing key. Both were hand-tight (documented + defaulted) instead of bit-tight (mechanical refusal). Sprint 077 flipped both to `raise unless allow_legacy_*=True`, matching Sprint 065's `heldout_guard` pattern. Roadmap errata block landed at the top of `plans/v1-roadmap.md` naming every roadmap-item-to-real-sprint delta (biggest: item 049 slipped +20 to Sprint 069; seven real sprints absent from the roadmap entirely). Test count 449 → 453. Ruff, mypy, pytest all green. Live smoke against the regenerated Sprint-075 training .pt through the new fail-loud loader passes without any opt-in flag because the artifact carries the marker.

**What worked.**

- **The Architect's one-sentence diagnosis pointed at the class, not the instance.** "Two SDD invariants have loosened from bit-tight to hand-tight" — no file names, no line numbers. I read that as a class name for the failure mode ("silent fallback on legacy artifacts") and grepped for every load site that used `.get(key, default)` without a signal or raise. Two hits, both mine from Sprints 075-076. The class name did the work; the fix was mechanical once the class was named. Candidate for TECHNIQUES.md § 1: "hand-tight vs bit-tight" as a diagnostic vocabulary for post-sprint audits — a documented invariant is hand-tight; a mechanically-enforced one is bit-tight; the audit asks which class each new invariant lands in.
- **Sprint 065's `heldout_guard` shape transferred cleanly.** The `raise unless allow_test_look=True` pattern lifted directly into `load_tokens_pt(allow_legacy_mask=...)` and `load_frozen_normalizer(allow_legacy_std_clamp=...)`. Two hours' work to lift a pattern that was already load-bearing elsewhere. Candidate for a "pattern index" alongside TECHNIQUES.md — cross-references to concrete Sprints that demonstrate a pattern in the current codebase, not just an abstract description.
- **Fixture defaults absorbed the transition.** `tests/test_model.py::_sample_payload` gained `mask_semantics="target_valid_v075"` as a kwarg default. Three existing tests kept passing without editing their bodies; the two new tests pass `mask_semantics=None` to build a legacy payload. The fixture is the boundary where the tightening lands cheaply — every downstream test inherits the safe default. Applied at scale: any strict-mode migration should think first about the shared test fixtures the pre-migration tests already depend on.

**What got in the way.**

- **The roadmap-vs-real drift is 20 sprints deep on one item.** Roadmap item 049 (cross-asset features) shipped as Sprint 069 — a +20 delta because Sprints 042-068 did other work first. Real work outruns speculative planning documents; the pattern is not new but the magnitude here is. The errata block absorbs the drift at documentation cost; the underlying issue is that the roadmap was written as a sequencing plan and used sequentially-numbered slots, which invited exactly this collision. Candidate for the kit template: roadmaps SHOULD number items independently of sprint slots — Roadmap-A5 stays Roadmap-A5 no matter when the sprint that closes it lands.
- **The mask-semantics tightening exposed one existing fixture bug in the evaluator test.** `test_run_evaluation_feats_end_to_end` in `tests/test_evaluator.py` was writing its own `.pt` payload via raw `torch.save` with no marker; Sprint 077 caught it with a `LegacyMaskSemanticRefused` on the first run. Fix was one dict key. But the broader lesson: any test that hand-authors a `.pt` payload duplicates the tokenizer's contract, and the tokenizer's contract just evolved. Every hand-authored fixture is a private snapshot of the format that drifts as the format tightens. Candidate for TECHNIQUES.md § 2 Data-science: "prefer fixture builders over hand-authored payloads for versioned artifacts — the builder tracks the contract; hand-authors drift silently."

**What this says about the next kit version.**

- **1. Hand-tight-vs-bit-tight is a first-class post-sprint diagnostic.** Every new invariant a sprint introduces should get a one-word tag in its close entry: `hand-tight` (documented + defaulted), `bit-tight` (mechanically enforced), or `signal-tight` (surfaces via a typed vocabulary tag). A review-verify pass checks whether hand-tight invariants have drifted or accumulated silent fallbacks. Candidate for the KIT_DIARY template's close-entry shape.
- **2. Every silent-fallback fix has a "opt-in flag ⇒ update every caller" cost the fix sprint should name.** Sprint 077 broke one existing test at the moment the tightening landed. On a bigger codebase or a live consumer, that cost would be larger. Fix sprints should include a grep-based caller-audit in their observation contract — every call site to the tightened function reviewed, either updated with the opt-in flag or regenerated to the new shape.
- **3. Roadmaps get their own numbering, sprints get theirs.** The v1 roadmap's collision of "roadmap item" with "sprint slot" cost documentation-refresh work every time the sprint log drifted. Kit template's `plans/`-style file should use `R-<phase>-<n>` (Roadmap-Phase-item) tags instead of raw integers to break the collision.

**Hypothesis verdicts.**

- H6 (locked vocab → first-pass-clean downstream). Sprint 077 first-pass code-clean; second-pass test-clean (one existing fixture in `test_evaluator.py` had to gain the mask marker after the first pytest run surfaced it). Running tally 60/70 first-pass across Sprints 007-077.
- H11 (specific upstream artifact drives cleaner sprints). Sprint 077 executed against the Architect's one-sentence diagnosis. Sentence had no file names but named the *class* of failure ("two invariants loosened from bit-tight to hand-tight"). The class name is a stronger driver than a fix path — the fix falls out of the class name mechanically. Adjacent to Sprint 075-076's diary observation about review-verify passes naming actionable items; the pattern generalizes to "a one-sentence class-name diagnosis is a stronger sprint driver than a multi-item action list."

---

### 2026-08-17 — Sprints 075-076: review items closed autonomously

**What happened.** The 2026-08-16 review-verify surfaced two live items: a Sprint 052 open item on `TokenizedArtifact.mask` (all-False on the real corpus because sparse event channels poisoned the all-non-null check) and a § 11 watch item on `STD_CLAMP` being a module-level constant. Sprint 075 redefined `mask` to `target_features_non_null AND targets != -100`, added a `meta["mask_semantics"] = "target_valid_v075"` version marker, and regenerated the training .pt — 53,703 valid rows of 54,262 (was 0). Sprint 076 promoted `std_clamp` to a `FrozenNormalizer` field with default 1e-8 that round-trips through write/load, added `warn_channels_under_clamp` as an opt-in caller check, and named the four event channels as `EXPECTED_CONSTANT_CHANNELS` (audit-visible exemption). Errata banner added to `reviews/full-review-sprints-051-073.md` naming the two § 6 mislabels and the § 10 RoPE staleness. Test count 442 → 449 across both sprints. Ruff, mypy, pytest all green.

**What worked.**

- **Review-verify surfaced a real open item the review missed.** The reviewer's 12 sections scanned surface claims and verified them all. The item Sprint 052 named on its own card three months ago — "mask fires False on every row, Sprint 053 should redefine" — sat quietly through 20+ intervening sprints. The verify pass caught it by checking whether the follow-ups those cards named actually shipped. That's the failure mode a rolling review catches that a single-sprint review doesn't. Candidate for TECHNIQUES.md §1: "review-verify includes a scan of cited follow-ups from prior sprints, not just the current stretch."
- **Regenerating the .pt artifact was the honest observation.** A synthetic-frame test that asserts the truth table is necessary but not sufficient — the sprint's actual claim is "mask.sum() > 0 on the real corpus." Regenerating the file and reporting the number (53,703 / 54,262 = 98.97%) is the observation contract at product-behavior level. The Sprint 073/074 downstream smoke on the regenerated .pt (still exits 0, param count grew by 640 because the current-code features parquet carries one more feature-column-worth of data) verifies no consumer downstream broke.
- **The `meta["mask_semantics"]` marker turns a semantic change into a mechanical check.** Any future consumer that cares about the old-vs-new mask can `payload["meta"].get("mask_semantics")` and dispatch. Pre-Sprint-075 artifacts on disk (absent key) get the honest "unknown / old" answer instead of a silent semantic mismatch. Same pattern as Sprint 076's `payload.get("std_clamp", STD_CLAMP)` fallback. Candidate for TECHNIQUES.md §2: "artifact-schema evolution via meta-key markers — new field carries its own version, old artifacts fall back to the shipped default."

**What got in the way.**

- **Regenerating the test-window .pt was deferred.** The 2024-2025 features parquet lives inside the heldout window; the `heldout_guard` refuses it without a test-look budget draw. Sprint 075's fix landed the code path; Sprint 088 held-out evaluation prep will regenerate the test-window .pt under a legitimate budget draw. This is the discipline working — the guard fired at exactly the right moment, and the sprint scoped down instead of forcing through.
- **The mask fix's downstream half is not wired.** `WindowSamplerFeats` still ignores `mask`; a consumer that wants to gate on it needs to filter positions. Sprint 075 named this on close and deferred to a Sprint 088+ candidate. The tension between "fix the underlying field" and "wire every consumer" is real — Sprint 075 picked the smaller scope and honestly named the remaining hop. PyTorch CE `ignore_index=-100` already excludes invalid rows from the loss, so the trainer path is safe without gating; the gate matters more at evaluation and simulator.

**What this says about the next kit version.**

- **1. Sprint-close follow-ups need a rolling audit surface.** Sprint 052's Built entry named the mask follow-up as one of two loose ends. That named item persisted through 20+ sprints because no mechanism checked whether it landed. A `## Named follow-ups` section in BLACKBOARD that a periodic review-verify scans against the current code would catch this earlier. Candidate for the kit's template BLACKBOARD.
- **2. Opt-in check helpers beat mandatory gates when the failure mode is speculative.** Sprint 076's `warn_channels_under_clamp` is a helper the caller invokes — not a raise-in-fit-time gate. The failure mode (non-exempt channel with genuinely tiny std) is speculative today; the helper surfaces it when a caller asks. If it becomes real, wire it into the fit path or promote it to a signal-side tag. This mirrors Sprint 067's regime evaluator switch (real VIX with rolling-std fallback preserved) — the code path lands ready without breaking existing consumers.

**Hypothesis verdicts.**

- H6 (locked vocab → first-pass-clean downstream). Sprints 075 and 076 both first-pass clean — three test additions each, real code changes, live smokes green. Tally 59/69 first-pass across Sprints 007-076.
- H11 (specific upstream artifact drives cleaner sprints). Sprint 075 executed against the 2026-08-16 review-verify Surfaced entry plus Sprint 052's original Built card; Sprint 076 executed against the § 11 drift-watchlist entry from the same review pass. Both closed first-pass. The review-verify pass IS the specific upstream artifact these two sprints needed — it named the exact defect (mask semantic collapse) and the exact fix path (target-valid semantic) for one, and the exact watch (std_clamp module constant) plus a two-path fix suggestion for the other. Pattern generalizes: a review pass that names actionable items with fix paths is a stronger sprint driver than a plan-file roadmap section that just names deliverables.

---

### 2026-08-17 — Sprint 074: config-driven context lengths

**What happened.** Sibling to Sprint 073 in shape and disposition. Four spec-pre-registered context lengths landed as `configs/context/{64,128,256,512}.json`. `ContextLenConfig` with `Literal[64, 128, 256, 512]` at the config edge. `scripts/train.py` picked up `--context-size` and `--context-config` (mutually exclusive) and overlays the value onto `ExperimentConfig` through `cfg.__class__.model_validate({**cfg.model_dump(), "context_len": N})` — re-runs Pydantic validation so a hand-authored off-spec value in `--context-config` fails at the overlay step even if the input file parsed. Live sweep on the real 2015-2022 training .pt at `--model-size xs` × every context: 819,200 / 827,392 / 843,776 / 876,544 params in 0.08 / 0.11 / 0.17 / 0.36s. Position-embedding parameter deltas exact at every step (8,192 = 64 × 128; 16,384 = 128 × 128; 32,768 = 256 × 128). Test count 437 → 442.

**What worked.**

- **Re-validating on overlay caught the class the sprint card promised.** `ExperimentConfig.model_copy(update=...)` — the natural Pydantic move — skips validation by default; a `--context-config` overlay with `context_len=100` would splat through silently. The pattern I picked (`cfg.__class__.model_validate({**cfg.model_dump(), ...})`) re-runs validation. `ContextLenConfig.model_validate` at load-time is the first defense; the ExperimentConfig re-validation on overlay is the second. Two layers of the same check surface a different failure mode (schema drift between config file classes).
- **Composition of the two Phase E dispatch axes worked on the first try.** Trace directory names now carry `-xs-c128-` — Sprint 073's `-{size}` and Sprint 074's `-c{N}` compose in the `run_id` construction with no shared state. Sprint 085's rented-GPU sweep script iterates the Cartesian product with no per-run coordination code.
- **Parameter arithmetic verified the position-embedding shape end-to-end.** Measured `Δparams = Δcontext_len × d_model` on every increment. That is a mechanical fingerprint the position embedding has to leave, and its absence would surface a wiring bug. The observation contract was numeric, not narrated.

**What got in the way.**

- **Roadmap-named directory `configs/experiments/` collided with the existing singular `configs/experiment/` directory.** Sprint 074 landed the files under `configs/context/` to parallel `configs/model/`, keeping the layout regular and avoiding a plural-singular collision inside the same parent. Named on the sprint close. The kit's "consult WORKING_AGREEMENT canonical home registry" rule (hard rule 7) works well for filenames but has no story for directory layout when a new class of config artifact arrives.

**What this says about the next kit version.**

- **1. Overlay-with-re-validation should be the default pattern for per-axis config overlays.** Pydantic's `model_copy(update=...)` is a landmine here: it lets a schema-invalid overlay through silently. The pattern `cfg.__class__.model_validate({**cfg.model_dump(), ...})` costs one extra dict-merge and buys a full re-validation. Candidate for TECHNIQUES.md § 2 Data-science: "config overlay = model_validate on merged dict, not model_copy on update." Adjacent to Sprint 073's "pre-registered enum → Literal at the config edge."
- **2. Directory layout for sibling per-axis configs is not covered by the canonical home registry.** WORKING_AGREEMENT § canonical home names *which file* owns *which type*. It does not say where a new class of sibling per-axis configs (`configs/model/`, `configs/context/`, tomorrow `configs/schedule/` or `configs/tokenizer/`) lives. Sprint 074 picked by analogy; the next such sprint has the same choice with no on-record convention. Candidate for WORKING_AGREEMENT: a "canonical directory registry" section that names `configs/<axis>/{value}.json` as the shape for per-axis sweep configs.

**Hypothesis verdicts.**

- H6 (locked vocab → first-pass-clean downstream). Sprint 074 first-pass clean (five test additions, two files, one CLI smoke, four sweep runs, all green). Running tally 57/67 first-pass across Sprints 007-074.
- H11 (specific upstream artifact drives cleaner sprints). Sprint 074 executed against `sprints/sprint-073-model-size-configs.md` as the parallel-shape reference, plus `plans/v1-roadmap.md § Phase E`. Same clean shape as 073, ~30% wall-clock reduction (074 built on 073's imports, mutex pattern, and stderr conventions). The "sibling-sprint against a landed sibling" pattern is a stronger form of H11 — the reference is running code, not a plan file.

---

### 2026-08-16 — Sprint 073: Phase E opens; config-driven model sizes

**What happened.** Four spec-pre-registered model shapes land as JSON on disk (xs/sm/md/lg), one Pydantic model rejects off-spec `d_model / n_layers / n_heads` at parse, and `scripts/train.py` gains `--model-size` and `--model-config` mutually-exclusive flags. Default omits both and preserves the 64/4/4 shape so Sprint 053-058 test smokes and existing checkpoints keep working. Live smoke on the real 2015-2022 training .pt at each size: xs=819,200 params in 0.08s, sm=2,708,352 in 0.13s, md=14,274,048 in 0.36s, lg=25,323,520 in 0.52s — every run exits 0, every declared training tag fires, checkpoint files land at `/tmp/ckpt-{size}/`, size-tagged trace files land at `/tmp/logs-{size}/`. Test count 432 → 437. Ruff, mypy (`src/price_space_llm` scope), pytest all green.

**What worked.**

- **End-to-end smoke against the real corpus caught nothing new — because Sprint 053 and 057 already fixed the machinery.** Two CPU steps on the 54,262-row 2015-2022 training .pt at every size, in every case, ran cleanly. That is the payoff shape H4 (frozen-artifact + paired-reader) and the Sprint 053-057-058 discipline was investing in. Sprint 073's job was wiring, not model-work; wiring landed on the first pass because the surface underneath was stable.
- **`Literal` enums at the config edge caught the class the sprint card promised they would catch.** `d_model=256` failed at parse with a Pydantic ValidationError, not at model construction (which would have died silently at `n_heads = 256/64 = 4` — accidentally valid). The Literal is a mechanical check against the spec's declared set; a future sweep that hand-authors a fifth shape must edit the enum in `config.py` first, which surfaces the choice at code-review time rather than at trace-inspection time.
- **Size-tagged `run_id` prevented the collision the sprint card anticipated.** Four back-to-back smokes at different sizes wrote to four separate log directories and four separate checkpoint directories without any per-size argument to `--logs-dir` / `--checkpoint-dir`. The `-{size}-` infix on `run_id` did the work. Small pattern, worth naming.

**What got in the way.**

- **Measured parameter counts drift from the spec's rough "~1M / 3M / 10M / 30M" figures.** xs came in at 0.82M (spec says 1M), md at 14.27M (spec says 10M), lg at 25.32M (spec says 30M). The MarketStateEmbedder line item (Sprint 053) that the spec's rough estimates predate now costs 20 channels × `nn.Linear(F_c, d_model)` per size — a chunk of budget the spec's label was not accounting for. Not a bug; a drift-watchlist entry filed for Sprint 084 compute-budget planning. Rented-GPU wall-clock projections should key off the measured counts, not the spec labels.
- **`CONFIG_RESOLVED` in v0.5 has no `d_model / n_layers / n_heads`.** Sprint 073 dispatches four sizes but the trace payload cannot distinguish them without a `run_id` grep + git SHA lookup. Filed to drift-watchlist as a v0.6 candidate; not absorbed into Sprint 073 per hard rule 6. The tension between "one concept per sprint" and "the trace should be self-describing" recurs; each vocab bump is its own sprint because it always is, and the discipline continues to cost one deferred entry per architecture sprint.

**What this says about the next kit version.**

- **1. Wiring-sprints against a stable surface run clean.** Sprint 073 was five test additions, two code files, four data configs, and one CLI smoke — landed first-pass with the full training tag surface firing at every dispatched size. The rate of first-pass-clean sprints in Phase D (056-068) was already high (H6 partially); Phase E opens on the same trajectory. Candidate for TECHNIQUES.md § 1: "wiring-sprints" as a first-class sprint pattern, distinct from architecture and feature sprints, where the deliverable is a knob rather than machinery — and where the sprint's own discipline is proving the knob against the real corpus, not synthetic fixtures.
- **2. `Literal`-at-the-edge for pre-registered enums is a cheap pattern.** The v1 roadmap pins four model sizes and four context lengths. Encoding those as Pydantic `Literal[...]` (not just `int`) means a hand-authored fifth value fails at parse with a clear error naming the allowed set, before the trainer builds a model with an accidentally-valid but not-in-spec shape. Candidate for TECHNIQUES.md § 2 Data-science: "pre-registered enum → Literal at the config edge" as the pattern that turns a pre-registration into a mechanical check.

**Hypothesis verdicts.**

- H6 (locked vocab → first-pass-clean downstream). Sprint 073 first-pass clean (five test additions, two files, one CLI smoke, four size runs, all green). Running tally moves to ~56/66 first-pass across Sprints 007-073.
- H11 (named-review-drives-sprint-work is faster + cleaner than name-a-sprint-then-review). Sprint 073 executed against `plans/v1-roadmap.md § Phase E` (a plan file, not a review). Landed clean at 2 files + 5 tests + 1 CLI smoke — same shape as review-driven sprints. The pattern generalizes: a *specific* upstream artifact — review, roadmap section, spec section — outperforms a bare sprint name. Candidate for restatement.

---

### 2026-08-16 — Pre-GPU phase synthesis (Sprints 007-072, 65 sprints)

**What happened.** Per-sprint diary discipline lapsed after Sprint 006. Sixty-five sprints (007-072, with 040 retracted) closed against `## Built` as one-paragraph summaries; this entry lands the phase-level lessons in one pass rather than back-filling 65 per-sprint entries the compressed paragraphs already carry. The stretch delivers: a locked v0.2/v0.3/v0.4/v0.5 vocabulary trajectory (55 → 57 tags, four grammar-evolution rounds all through canonical proposal types); a signal emitter with strict payload validation, JSONL sink, session-context manager, and hard-rule test-look defense (runtime + commit-msg hook + filesystem guard); an Alpha-Vantage-only ingest stack for 19 channels (target SPY, five cross-asset context including VXX-for-VIX-volume + UUP-for-DXY substitutions, five macro releases, two options aggregates, four event tables); a `polars.join_asof(strategy="backward")` alignment pipeline with the three staleness columns (`missing_mask__*`, `age_since_known_at__*`, `observed_at_this_grid_step__*`) per channel; a feature layer covering every spec § 6 channel type (target, cross-asset, VIX-only, macro, options, event, session flags); a frozen normalizer with two-sample KS drift diagnostic; extended `bucket_stats.json` carrying per-bucket lower/upper/train_mean/train_median/train_frequency; a MarketStateEmbedder + MarketStateTransformer path replacing the Sprint 031 bucket-ID model; AdamW + cosine LR + warmup + bf16 + `torch.use_deterministic_algorithms` trainer; purged embargo at split boundaries + top-K checkpoint retention; MLP + GRU baselines + a target-only-zeroed helper that composes with the market-state trainer; `experiments/logbook.csv` writer per tech-arch § 13; evaluator switch from `rolling_std_20` proxy to real VIX; evaluator MarketStateTransformer path so Sprint 088 held-out evaluation can consume Sprint 053 checkpoints; two spec-guard tests (no-hardcoded-target grep + channel source-of-truth log_return check). Test count 4 (Sprint 001) → 432 (Sprint 072). Zero silent scope reductions; the "no scope reduction" rule (2026-08-14 feedback memory) held across the run. One Sprint retracted in full (040, hosted-tracker integration, replaced by a Decision prohibiting SaaS trackers for the project life).

**What worked.**

- **Halt-and-articulate with typed reasons compounded.** Every `bridge_mapping_required`, `vocabulary_change_required`, `observation_contract_missing` halt this stretch (Sprints 018, 022-023, 034, several others) surfaced a real code-vs-vocabulary or code-vs-vendor mismatch that a "make it work" reflex would have paved over. The Sprint 022-023 recovery from Sprint 020's fabricated `_error_shim` values is the load-bearing example: vocabulary v0.2 refused three separate emit shapes; the correct response was halt → evolve to v0.3 with `CHANNEL_FETCH_FAILED` → rip the shim. Not filed as "vocabulary gap deferred."
- **Pre-GPU review-driven work found seventeen structural defects the sprint cadence alone missed.** `reviews/pre-gpu-deploy-holistic-review.md` + the parallel spec re-read audit surfaced 12 + 19 items across four severity tiers; Sprints 041-072 closed the vast majority (three still open — RoPE now ratified-deferred, model-size sweep infrastructure = Sprint 073 = next, `countdown_to_next` macro feature deferred with named revisit). Named-review-drives-sprint-work is a stronger pattern than name-a-sprint-then-review; the review sees what the sprint author cannot.
- **Frozen-artifact contract held.** `bucket_stats.json` (Sprint 056 extended shape), `normalizers.pt` (Sprint 054 frozen-on-training-partition + Sprint 055 KS drift), Sprint 052 `.pt` tokenized artifact all have paired independent-reader tests; H4 confirmed on real code paths. Sprint 055's live drift smoke against 2015-2022 training vs 2024-2025 test surfaced KS=1.00 on target dollar_volume + KS≈0.997 on every macro rate/inflation series — the Feb 2026 model launch will inherit that specific failure mode named, not surprised.
- **Multi-modal test-look defense actually works.** The three legs (runtime `register_test_look` in Sprint 051 `evaluate.py --split test`; commit-msg hook in Sprint 064; filesystem guard on aligned parquet in Sprint 065) each catch a different bypass path; together they make it hard to touch the 2024-2025 held-out data without either exhausting the 3-look budget, failing the commit hook with `[test-look]` missing, or hitting `HeldoutReadRefused`. Addendum D's "a gate nobody has watched fail is not a gate" — verified by writing the failing tests, not by hoping.
- **`no SaaS recommendations` rule held.** After the 2026-08-13 Weights & Biases retraction, no subsequent sprint proposed a hosted tracker even in passing. Codified into `WORKING_AGREEMENT § Run tracking`; `WANDB_UPLOAD_FAILED` retired from v0.5 vocabulary; Sprint 084 sweep script writes to `experiments/logbook.csv` + `artifacts/{run_id}/*.png` and nowhere else. Discipline held through 32 subsequent sprints.
- **Bit-deterministic budget on feature/tokenize/normalize/eval sprints was cheap and paid immediately.** Tests that assert `feats_a == feats_b` on two runs against the same input catch reordering + parallelism bugs the "smoke it and eyeball the numbers" approach would miss. Only trainer sprints (057, 059, 060) carry `statistically-deterministic` — and every one names why in the sprint card.

**What got in the way.**

- **Diary drift.** Sixty-five sprints without a diary entry is exactly the failure mode the kit's `KIT_DIARY.md` template exists to prevent. The lessons live in `## Built` paragraphs and were not lost, but the phase-level pattern-recognition (what class of finding recurs? what hypothesis moved?) was doable only by scrolling. This synthesis exists because the Architect asked for it; without the ask, the drift would have continued to project close.
- **Sprint tail rolling-detail discipline lapsed at the same point.** `## Sprint tail` still shows Sprints 020-025 in full detail; Sprints 026-072 landed in `## Built` in one-paragraph form (the compressed shape older tail entries were supposed to roll into). Structurally the Built section carries the content — but the ten-entry rolling detail Section the template wants is not maintained. Same class of drift as this diary. Noted in `## Sprint tail` on the Blackboard 2026-08-16.
- **Hard rule 6 (≤2 files per sprint) stretched twice with explicit halt-articulation and multiple times silently.** Sprint 021 (9 files: facade + cache + ratelimit + 3 tests + 3 config) halted-articulated in the sprint card and the Sprint tail; Sprint 025 (5 files: alignment module + join + script + tests + pyproject bump) shipped without articulation but under review. The `articulate the stretch` rule from Sprint 007's drift entry held for the biggest stretches but not for the moderate ones (3-4 files). The kit's ≤2 ceiling reads as absolute; in practice most stretches shipped clean and the articulation ceremony added no value on 3-file sprints where the concept was genuinely singular. Worth naming.
- **`no scope reduction` had to be re-taught twice.** The 2026-08-14 retraction (options-volume at reduced scope, corrected same day: `no scope reduction, ever`) and the current-session RoPE deferral discussion both saw an early reflex toward "ship less to ship sooner." The Architect had to state the rule; it did not pattern-in from the earlier retraction. Feedback memories (`feedback_no_scope_reduction.md`) now carry it, but the reflex is not gone.
- **Alpha-Vantage's shape divergences kept surfacing at first live contact.** VIX-not-supported-on-TIME_SERIES_INTRADAY (Sprint 023); VIX-daily-only-via-INDEX_DATA (Sprint 038); VIX-index-has-volume=0-by-construction so VXX substitutes for volume signal (Sprint 050); DXY-not-on-Alpha-Vantage so UUP substitutes for the dollar index (Sprint 044); no historical BBO before ~2 months so cost calibration will use Corwin-Schultz proxy or extrapolation (Sprint 073 = Phase F). Each mismatch got named and either substituted (with the substitution recorded in the manifest per `feedback_prototype_substitutions_ok.md`) or filed for later. H9 (`first-live-contact reveals what mock-driven tests cannot`) is confirmed across every external channel.

**What this says about the next kit version.**

- **5. Phase-boundary synthesis is a first-class discipline, not an at-project-close nicety.** The KIT_DIARY template names "phase boundaries get a synthesis section" but does not name a cadence trigger. Without a trigger the discipline lapses (as it did here). Candidate: bump the diary template with an explicit rule — after every N sprints (5? 10?) OR at every phase-close named in the roadmap, the Agent authors a phase-synthesis entry as a hard step, not an "as work demands." The compressed `## Built` paragraphs are not a substitute; they carry per-sprint fact, not phase-level pattern.
- **6. `## Sprint tail`'s ten-entry rolling rule needs a trigger too.** Same drift mechanism. When the section stops being maintained, the Built section absorbs the content but the intended rhythm (detailed most-recent-10, compressed everything-older) collapses. Candidate: name a trigger — at every sprint close, if `## Sprint tail` has >10 detailed entries, roll the oldest into a Built one-paragraph and delete the tail entry. Mechanical, not judgment.
- **7. `articulate the hard-rule-6 stretch` for 3-4-file sprints adds ceremony without catching defects.** Every 3-file sprint this stretch that skipped the articulation shipped clean; the two that articulated (Sprint 021, 025) shipped no cleaner. Candidate: soften the articulation rule to "articulate at >4 files OR when the extra files are not all tests-plus-one-module." The current rule reads as absolute-under-review and generates ceremony at the wrong threshold.
- **8. Named-review-drives-sprint-work is a stronger cadence than name-then-review.** Sprints 041-072 executed against `reviews/pre-gpu-deploy-holistic-review.md` + `reviews/full-review-sprints-041-050.md`; the review acts as a bounded backlog and each sprint closes one specific item. Sprint 041 (the omnibus "pre-GPU fixes" sprint) predated the review-driven cadence and bundled seven concepts into one card; it shipped but was messy to Rubber-Duck-Pass. Candidate for TECHNIQUES.md § refactor: "when a review lands with a punch list [use `review items` per user preference], one sprint per item; the review is the plan for the sprint chain."
- **9. `feedback_*` memory format is load-bearing.** Rules like "no SaaS," "no scope reduction," "probe before claiming absent," "prototype substitutions OK" held across 30+ subsequent sprints because they moved to memory files with `**Why:** + **How to apply:**` structure. The user's earlier ad-hoc corrections had faded within a few sprints; the structured memory-file corrections stuck. Candidate for TECHNIQUES.md § memory-and-compaction: "corrections that must persist across sessions land as structured memory files, not chat-log admonitions."
- **10. `pass_kind` + `determinism_budget` frontmatter earned its keep at 60+ sprints.** Every card in this stretch carried both. `pass_kind: functional` cards ran the dual + observation contract; `pass_kind: architectural` cards ran vacuous signal contract with content-assertion artifact contract. `determinism_budget: bit-deterministic` cards paired with `feats_a == feats_b` reruns; `statistically-deterministic` cards paired with fixed-seed acceptance-range assertions. The two fields together compress a sprint's grading intent to one line; no sprint this stretch had ambiguous grading intent.

**Hypothesis verdicts (post-Sprint-072).**

- **H1 (Data science class techniques cover 80%+ without invention).** **Confirmed.** Sixty-five sprints authored with zero new vocabulary categories invented; four grammar-evolution rounds (v0.2→v0.3→v0.4→v0.5) all through canonical proposal types (ENTITY_MERGE_PROPOSED, NEW_TAG_PROPOSED, TAG_RESHAPE_PROPOSED); TRAINING_DIVERGED, NORMALIZER_DRIFT_MEASURED, CAPACITY_SWEEP_COMPLETED all shipped as canonical evolutions rather than ad-hoc additions. Kit's TECHNIQUES.md §2 Data-science-class discipline is complete-enough.
- **H2 (Observation contract catches Addendum D1 class on non-UI project).** **Confirmed on the projected class.** The observation contract (expected runtime signals in JSONL + expected metric artifact + expected exit code) caught the specific defect class it was designed for at least four times this stretch: Sprint 020 fabricated-values-in-trace caught by post-hoc trace read; Sprint 023 first-live-contact vocabulary crashes surfaced by running against real Alpha-Vantage; Sprint 042 staleness-columns-absent caught by asserting columns present in aligned parquet; Sprint 067 evaluator-still-consuming-proxy-VIX caught by column-name assertion. Held-out evaluation (Sprint 088+) tests the remaining class.
- **H3 (Bridge-mapping-first prevents guess-and-iterate).** **Confirmed strongly.** Sprint 018 (Alpha-Vantage MCP) and Sprint 019 (Alpha-Vantage HTTP fetcher) both halted-articulated on first response-shape divergence; every subsequent external-vendor call this stretch (options, macro, event tables, cross-asset) came in with a documented response shape and no rework. Zero rework on error shapes did NOT hold in Sprint 020 — bridge mapping needs to cover error shapes explicitly (filed as an H3 refinement in the Sprint 022-023 diary entry).
- **H4 (Frozen-artifact contract with paired reader test).** **Confirmed.** `bucket_stats.json` (Sprint 056), `normalizers.pt` (Sprints 054, 055), Sprint 052 `.pt` tokenized artifact all have paired independent-reader tests; three separate frozen-artifact defect classes prevented (bucket_train_mean absent from stats caught by baseline `magnitude_weights_from_stats` refusing legacy shape; normalizer applied to holdout drifted KS=1.00 on dollar volume caught by drift diagnostic; tokenized-artifact channel names mismatch caught by evaluator).
- **H6 (Locked vocab → first-pass-clean downstream).** **Partially confirmed.** Sprints 007-072 first-pass-clean rate roughly 55/65 (~85%). The misses cluster on live-vendor-error sprints (020, 034 pre-retraction) and on multi-concept sprints (021 at 9 files, 041 at 7 items). Vocabulary-locked-at-Sprint-0 is not a sufficient condition for first-pass-clean; it removes one class of question.
- **H8 (Ruff + mypy on existing small codebase, one sprint, cheap because auto-fix).** **Confirmed** across Sprints 006, 015 tooling bumps. Ruff auto-fix carried >80% of findings both times; mypy escaping to `# type: ignore[misc]` at un-stubbed boundaries stayed at 2 lines total. The pattern held as the codebase grew from ~500 to ~5000 lines.
- **H9 (First-live-contact reveals what mock-driven tests cannot).** **Confirmed hard, four data points.** Sprint 020 (Alpha-Vantage error shapes); Sprint 023 (VIX-not-intraday); Sprint 038 (VIX-daily-via-INDEX_DATA); Sprint 044 (DXY-not-on-Alpha-Vantage → UUP substitute); Sprint 050 (VIX-index-volume=0 → VXX substitute). Every external channel's live-contact sprint surfaced a shape the mock could not have modeled. Cost per live-contact: 1-3 iteration cycles.
- **H10 (Rate of code-failure-as-vocabulary-gap Surfaced entries as discipline proxy).** **Confirmed low = discipline holding.** After Sprint 022-023's retraction, this rate is zero across Sprints 024-072. The reflex has not returned. Watch item stays open.
- **New H11.** Named-review-drives-sprint-work is faster + cleaner than name-a-sprint-then-review. Evidence: Sprints 041-072 executed against three named review files with one-item-per-sprint cadence; average sprint files touched = 2.4, average tests added = 3.1, first-pass-clean rate ~95% versus ~85% overall. Testable across Phase E and Phase F when the next review lands.

---

### 2026-08-10 — Sprint 0: Vocabulary Session closed

**What happened.** The Vocabulary Session ran across two working days (2026-08-09 preflight through 2026-08-10 lock) and five review-pass rounds. Round 1 drafted 31 entities and immediately resolved cross-document polysemies inside the JSON — the exact discipline violation PRINCIPLES.md commitment #3 names ("workers cannot invent vocabulary"). Round 2 responded by inventing seven non-canonical proposal types — same failure at the meta-vocabulary level. Round 3 recast to canonical taxonomy and moved forward-commitments to BLACKBOARD Deferred, but broke layer dependency order for two forward-commitments (a Layer-1 tag filed at Step 1; four Layer-6-forward flags filed under a Step-1 halt mechanism). Round 4 fixed the mechanism uniformly. Round 5 closed twelve coverage gaps the specs' pre-registered gates surfaced. A round-5 self-review found five stale audit counters, two Layer-taxonomy slips, seven missing numeric-gate constraints (product-spec gates whose signals existed but whose numeric thresholds did not), and three semantic ambiguities. All addressed. Lock: 55 tags, 24 operators, 37 temporal invariants, 29 state-transition rules, 64 evidence constraints, 55 audit pairings, zero orphans, zero missing stratum coverage.

**What worked.**

- The five review-pass rounds themselves. Each round found errors the prior round could not see because the errors moved up one abstraction layer per round: content → meta-content → mechanism → coverage → thresholds. Without the review discipline the vocabulary would have locked with round-1's silent merges and round-3's dependency-order violations, and the coverage gaps would have surfaced during Sprint 15 debugging instead of Sprint 0 review.
- The COMPREHENSION_AFFIRMATION named Addendum D's grading traps at project start ("signals drive but cannot grade; a gate nobody has watched fail is not a gate"). Round-5's numeric-gate finding lands exactly on the "gate nobody has watched fail" pattern applied to Layer 7. The affirmation primed the review to find the class of gap.
- BOOTSTRAP's per-step halt-condition checks are mechanically useful. Step 3's FK-resolution threshold (0.70) caught nothing (rate 1.000), but the recount that produced 1.000 forced clean distinction between FK candidates and opaque identifiers. Step 5's cadence-per-ambient-tag check caught round-1 misplacement of INGESTION_CALL_RETRIED and FEATURE_COMPUTATION_FAILED at Layer 4 rather than Layer 7. Step 7's orphan-tag scan caught SESSION_INIT and SESSION_COMPLETE having no emitter, forcing the ProcessRunner operator addition.
- Round 4's `_recast_log` in `proposals.json` and `_removed_from_layer_0_inline` block in `0.1.json` preserved the trail cleanly per the additive-only hard rule. Six months from now, a Reviewer opening `signals/0.1.json` alone can trace why IngestionCall is absent from entities[] without needing to re-derive the round-2 vs round-3 argument.

**What got in the way.**

- Round 1 hit the "workers cannot invent vocabulary" trap despite the COMPREHENSION_AFFIRMATION naming exactly that hard rule. The affirmation primes; it does not enforce. The mechanism that caught the violation was the round-1 review pass, not the affirmation.
- Round 2 recovered from round 1 by inventing meta-vocabulary. The failure pattern was structural — "when the review says X is a defect, avoid X by inventing Y" — and it happened one abstraction level up from the original error. Only round 3's review named it as the same class of defect.
- The dependency-order violations in round 3 (Layer-1 proposal filed at Step 1; Layer-6-forward flags in Step-1 halt mechanism) were subtle because both filings looked disciplined — canonical taxonomy, honest labels. The violation was that layer order matters and forward-commitment has a specific home. BOOTSTRAP names this ("Lower layers are populated first because upper layers consume them"), and I violated it despite reading it.

**What this says about the next kit version.**

- **1. Add a per-round self-check that the recast did not introduce a new class of the error it was fixing.** Round 2's failure was catchable in principle by asking "did my response to a taxonomy critique produce new non-canonical taxonomy?" A short checklist at Step-1 close asking the agent to verify that the recast honors its own diagnosis would compress the five-round trajectory to two or three rounds.

- **2. `_recast_log` and `_removed_from_layer_0_inline` are patterns worth promoting to TECHNIQUES.md.** The kit's "no deletions" hard rule needs a concrete mechanism for pre-lock draft revisions. Round 4's recast used both patterns; they preserve audit trail cleanly and are cheap to author. Candidate for TECHNIQUES.md §1 memory-and-compaction addition.

- **3. Coverage-review is a distinct pass from discipline-review.** Rounds 1–4 fixed discipline problems (workers cannot invent, taxonomy canonical, layer order). Round 5's coverage review asked a different question: "does the vocabulary cover what the program will observe?" Neither the four discipline rounds nor BOOTSTRAP itself would have caught the missing TRAINING_DIVERGED, MANIFEST_STALE_OR_MISSING, BUCKET_FREQUENCY_DRIFT_MEASURED, SENSITIVITY_PLOT_GENERATED tags — those come from walking the product-spec gates and asking "does the vocabulary carry the signal that would verify each?" Coverage-review should be a named Step-11.5 in BOOTSTRAP, between rationale-doc authoring and Step-12 lock.

- **4. Numeric-gate constraints are a distinct class from field-presence constraints at Layer 7.** BOOTSTRAP Step 8 covers diagnostic_required (incidents) and outcome_required (summaries) explicitly. It does not name `gate` — the class of numeric-threshold constraint that turns a pre-registered success gate into a mechanically-checkable Layer-7 rule. Round-5's post-recast has 8 `gate`-kind constraints on the SIM_RUN_COMPLETED / CAPACITY_SWEEP_COMPLETED / METRIC_COMPUTED / BASELINE_COMPARISON_ASSESSED tags. Candidate for BOOTSTRAP §Layer 7 as a named third constraint class alongside diagnostic_required and outcome_required.

**Hypothesis verdicts.**

- H1 (Data science class techniques cover 80%+ without invention). **Confirmed partially.** SESSION_INIT dataset+model+vocab versions, per-step/per-epoch/per-run strata, metric snapshot as artifact, determinism budget — all applied without invention. But the coverage review surfaced training-loop diagnostics (TRAINING_DIVERGED) the class does not name explicitly. Update the class in TECHNIQUES.md §2 to include a diagnostic-tag checklist.
- H2 (Observation contract expressed for a non-UI project as signal + artifact + exit code catches Addendum D1 class). **Confirmed pending Sprint execution.** The vocabulary carries the pattern; whether it catches the class in practice needs a running pipeline.
- H3 (Bridge-mapping-first prevents guess-and-iterate). **Not tested this sprint.** Sprint 0 authored no code against SDKs. Sprint 1 tests.
- H4 (Frozen-artifact contract with paired independent-reader test catches Addendum D1). **Named at Layer 7 for BucketStats, NormalizerState, SpreadScaler, Kappa; tested when the first artifact writes.** Awaits Sprint execution.
- H5 (Vocabulary Session runs faster than BOOTSTRAP's 2.5–4 hour estimate on a spec-mature project). **Falsified in wall-clock, confirmed in draft time.** First-pass draft took ~30 minutes; five review-pass rounds pushed the total to ~6 hours across two working days. The review discipline extended the schedule but the resulting vocabulary is defendable — worth the trade for a project whose vocabulary will govern 25+ sprints of code.

---

### 2026-08-11 — Sprints 022 + 023: retraction, vocabulary v0.3, honest wiring

**What happened.** The Architect flagged Sprint 020's `_error_shim` in `scripts/probe_channels.py` as a code failure, not a "vocabulary gap" as I had framed it. The shim caught fetcher exceptions and returned a `FetchResult` with fabricated fields: `actual_frequency="15min"`, `earliest_timestamp="1970-01-01T00:00:00+00:00"`, `revision_behavior="immutable"`, `missing_fraction=1.0`. Seven fabricated fields per failed sample date. Five failed dates for VIX in the live smoke. Thirty-five field-writes of pure fiction in the trace file. I had filed the emitter's rejections as "Surfaced for review — vocabulary can't express what my code needs to say" and moved on. The Architect's push: `there can be no vocabulary gaps, stop. That is not a surfacing, that is a failure.` Correct.

Retracted the two mis-framed Surfaced entries. Filed a real `vocabulary_change_required` halt against v0.2. Recommended path (b): add a new `CHANNEL_FETCH_FAILED` tag rather than mark timestamps optional. Architect ratified with "yeah, then we update the vocab if need be, then continue."

Sprint 022: locked v0.3 with `CHANNEL_FETCH_FAILED` (probe/incident, six required fields) plus one `diagnostic_required` evidence constraint on `error_message`. Tag count 55 → 56. Every prior tag unchanged; every prior test still passes. Loader default retargeted; symlink added; two test fixtures bumped.

Sprint 023: deleted `_error_shim`. Deleted the empty-series fill in `alphavantage.py:_extract_fetch_result` (now raises `AlphaVantageResponseError`). Rewired `probe_channel` to try/except each fetcher call and emit `CHANNEL_FETCH_FAILED` on exception. When every sample date fails for a channel, no `CHANNEL_COVERAGE_ASSESSED` fires — the vocabulary requires `earliest_timestamp`, and none exists; the returned `ChannelCoverage` records `verdict="dropped"`, `reason="all_fetches_failed"`, `earliest_timestamp=None`. Three new tests. Live smoke against Alpha-Vantage: 19 lines in the trace, every field an observation the code actually made, VIX drops for a legitimate documented reason.

**What worked.**

- **The Architect's correction landed hard because the vocabulary had already caught the failure.** The emitter had raised three separate `ValueError`s over the course of Sprint 020 — one for the enum on `actual_frequency`, one for the ISO-parser on `earliest_timestamp`, one for the enum on `revision_behavior`. Each raise was the vocabulary refusing to record a lie. I overrode each refusal with a wider shim. The vocabulary was doing its job the whole time; the retraction did not need to prove the failure, it needed to name it. Two sprints later, the code matches the honest signal shape and the trace is worth reading.
- **Path (b) — new tag — over path (a) optional timestamps.** A distinct incident tag for the fetcher-exception case gives a Reviewer unambiguous semantics without needing context. `earliest_timestamp: null` in a "we got data but not enough" case would look identical to `earliest_timestamp: null` in a "vendor call broke" case; the tag shape distinguishes them.
- **Halt-and-articulate before code, not after.** Sprint 022 landed the v0.3 lock with vacuous signal contract, then Sprint 023 wired the code that consumed it. The correct sequence per hard rule 12. Two commits, one concept-per-sprint.

**What got in the way.**

- **My default read of `emitter.emit(...)` raising was "fix the payload to make it stop raising."** That reflex is exactly wrong. The emitter is a validator; when it raises, the runtime state has produced something the vocabulary refuses to record. The correct read is "why is the vocabulary refusing?" and then "should the code stop trying to say this, or should the vocabulary grow?" I made the wrong call three times in a row before Sprint 023 fixed it.
- **The mis-framed Surfaced entries permitted the lies to persist.** "Filed as vocabulary gap; revisit later" reads as diligent — but it lets the shipped code keep writing fabricated observations in the meantime. A Surfaced entry that flags a code failure is fine; a Surfaced entry that reframes a code failure as a vocabulary gap is the failure hiding under a diligence label.

**What this says about the next kit version.**

- **1. Name "emitter refuses → widen fill values" as an anti-pattern in TECHNIQUES.md.** The reflex to keep the code running by fabricating vocabulary-legal values is the anti-pattern SDD exists to prevent, and I hit it directly. The kit's PRINCIPLES.md § "The vocabulary is the contract" states the principle; TECHNIQUES.md could name the specific reflex and the correct response ("halt at the first refusal; do not widen the shim").
- **2. Distinguish "vocabulary gap" from "code failure hidden behind fill values."** The kit's grammar-growth mechanism (proposals.json + v0.X evolution) handles legitimate gaps found before code ships. Nothing in the kit currently names the reverse case: code that shipped, wrote lies, and left a Surfaced entry claiming the vocabulary is at fault. The Deferred cleanup rule I filed at BLACKBOARD (2026-08-11) — "if the deferral reads as 'my code lied and I filed the vocabulary as needing evolution,' that is a code-failure retraction, not a deferral" — could land in the kit as a Surfaced-entry taxonomy addition.
- **3. Load-bearing lesson: the vocabulary refusing to serialise something IS the observation.** A `ValueError` from the emitter is a signal about the code, not a bug in the emitter. Treat it as diagnostic output; do not swallow it. This is worth naming explicitly in foundations/01–04; the current framing treats the vocabulary as a passive contract, but it is an active gate.

**Hypothesis verdicts.**

- **H3 (bridge-mapping-first prevents guess-and-iterate).** Reconfirmed the wrong way: I bridge-mapped Alpha-Vantage's response shape correctly in Sprint 018 and wrote correct normalisation in Sprint 019, but I did NOT bridge-map "what happens when the vendor says no." The mock fetcher never raised; the live vendor did. Bridge mapping needs to cover error shapes, not just success shapes. Filed as a Sprint 018-style discipline expansion for the next external-API sprint.
- **H9 (first-live-contact reveals what mock-driven tests cannot).** Confirmed hard. Sprint 020 hit three vocabulary crashes on the first live run. Sprint 023's honest wiring passes 80 tests including three new ones that mock-simulate what live did.
- **New H10.** The rate of code-failure-as-vocabulary-gap Surfaced entries is a proxy for how much I'm hiding failures under diligence labels. Sprint 020 filed two such. Sprint 023 retracted both. If this rate stays at zero across future sprints, discipline is holding. If it climbs, the reflex has returned.

---

### 2026-08-11 — Sprint 020: Alpha-Vantage fetcher wired + live smoke closed

**What happened.** `--fetcher {mock,alphavantage}` flag added to `scripts/probe_channels.py`. Live smoke against the real API on the three-channel config returned exit 2 in ~5s: `SPY` and `USO` accepted, `VIX` dropped across all five sample dates because `TIME_SERIES_INTRADAY` does not support `^VIX` — it is an index, not an intraday-priced security, and Alpha-Vantage responds `Invalid API call`. The probe caught a real ingestion gap that the config was blind to.

Three emit-time crashes surfaced during the smoke loop. Each failed on a different strict-enum or type constraint on `CHANNEL_PROBED`: `actual_frequency="unknown"` failed the frequency enum; `earliest_timestamp=""` failed the ISO parser; `revision_behavior="error:AlphaVantageResponseError"` failed the revision-behavior enum. The `_error_shim` was smuggling a diagnostic (the exception class name) into fields whose semantic is observational, not diagnostic. The fourth version of the shim fabricates only vocabulary-legal values and puts the failure string on stderr; the manifest still records the drop correctly. The empty-series path in `_extract_fetch_result` had the same class of bug and got the same fix.

Sink hygiene: the JSONL writer opens with `"a"`. Three crashed runs during smoke-loop iteration left 42 lines in a trace whose `SESSION_COMPLETE.n_signals_emitted` reported 21. `rm -f` + clean rerun produced the expected 21 lines. Filed for a signals-hygiene sprint (truncate on SESSION_INIT).

**What worked.**

- **The probe caught the VIX schema mismatch on first live contact.** No test could have surfaced it — the mock happily returned data for any symbol. The value of running against real vendors early is that the vendor itself is the schema authority; the probe's job is to route that authority's answers into a manifest before anything expensive gets built on top. `product-spec-v4.md` names channel coverage as a Phase 0 blocker; the probe now delivers that gate against real data.
- **The `_error_shim` pattern kept the probe module untouched.** Two paths were on the table (extend `probe_channel` with an on-error callback vs wrap the fetcher). The wrap kept Sprint 016's module signature stable and pushed the error-handling responsibility to the CLI layer, which is where transport-specific errors belong.
- **Bridge mapping earned its keep.** Sprint 018's halt recorded the exact response shape (US/Eastern, ordinal-prefixed OHLCV keys, string values). Sprint 019 wrote tests against that recorded shape via `httpx.MockTransport`; Sprint 020's live run confirmed the recorded shape was accurate — zero re-work on normalisation. The three sprint-loop (halt-and-record → author-and-test → wire-and-smoke) is the anti-guess-and-iterate pattern working.

**What got in the way.**

- **Strict enums on observation-tag payloads have no shape for error signals.** Every field on `CHANNEL_PROBED` is either a strict enum or a typed value; when the observation is "the fetch itself failed," the shim has to fabricate legal-but-inaccurate values or the emit crashes. Three separate crashes narrowed which fields the shim could legally set. The final shape puts the error string on stderr, invisible to any Reviewer reading only the trace. The vocabulary should probably grow a `CHANNEL_FETCH_FAILED` incident tag, or extend `revision_behavior` with an `error` enum value; filed to Surfaced-for-review with the tradeoff spelled out.
- **The JSONL sink's append-mode assumption is right until it isn't.** Same `run_id` invocations accumulate. During normal use one invocation gets one `run_id` and this is invisible. During iterative debugging (mine, this sprint) it produces a file with two SESSION_INITs and a mismatched signal count. Truncate-on-SESSION_INIT is the honest fix.

**What this says about the next kit version.**

- **1. First-live-contact reveals what mock-driven tests cannot.** Sprint 016 (probe with injected mock fetcher) + Sprint 017 (CLI + mock trace) + Sprint 019 (fetcher via MockTransport) all passed on the first try. Sprint 020 hit three vocabulary crashes on the first live run because the mock returned only success-shaped `FetchResult` values; real-vendor error shapes were nowhere in the test suite. The kit's TECHNIQUES.md could name a "first-live-contact sprint" pattern: after mock-driven work stabilises, run against the actual vendor with the smallest possible surface (one call per channel, cheapest tier) and expect the first run to surface vocabulary and error-path gaps the mock could not.
- **2. Observation-vocabulary vs error-vocabulary is a real distinction.** The kit's PRINCIPLES.md treats vocabulary as one thing. In practice this project has learned that observation tags (`CHANNEL_PROBED`) are strict about the semantics of the field values because they encode what the world looked like; error tags (`CHANNEL_FETCH_FAILED` candidate) should be lenient about vendor error strings because they encode what went wrong outside the system's control. Retrofitting the distinction is uglier than declaring it up front. Candidate for a foundations-level addendum: the observation-vs-error stratum split within an incident tag.

**Hypothesis verdicts.**

- **H3 (bridge-mapping-first prevents guess-and-iterate).** Confirmed strongly. Sprint 018 halted precisely because the actual API surface diverged from the documented one; Sprint 019 wrote against the recorded reality; Sprint 020's live run needed zero normalisation fixes. This is the second data point (the first was Sprint 016's MCP tool documentation stub) — the pattern holds.
- **H6 (locked vocab → first-pass-clean downstream).** Weakened. Sprint 020 hit three vocabulary crashes on the live path. The locked vocabulary is correct for observations; it does not cover fetch failures, which the mock never exercises. First-pass-clean holds when the sprint's input matches the vocabulary's design assumptions and breaks when it doesn't — a more honest statement than the H6 original.
- **New H9.** A "first-live-contact" sprint costs about three iteration cycles regardless of how thorough the mock-driven tests were, because real vendors surface error shapes the mock cannot. Testable across future live-contact sprints (Databento for BBO, W&B upload path).

---

### 2026-08-10 — Sprint 006: tooling adoption closed

**What happened.** ruff and mypy landed in `[dependency-groups] dev`. `[tool.ruff]` + `[tool.ruff.lint]` configured with E/F/I/UP/B/SIM/PT rules; `[tool.mypy]` set to strict on `src/price_space_llm`; `[[tool.mypy.overrides]]` handles the un-stubbed `sdd` module. Pytest gained `--strict-markers`, `--strict-config`, `-ra`, `filterwarnings = ["error"]`, `xfail_strict = true`. First pass ran the tools: 10 ruff findings (8 auto-fixed, 2 formatter re-flows, 1 line-too-long fixed by hand), 4 mypy findings (2 `Cannot subclass Any` from the sdd ignore-missing-imports — silenced with `# type: ignore[misc]` on the two subclasses; 2 missing dict type args — typed explicitly). Ruff's `UP` pack also modernised `timezone.utc` to `datetime.UTC` (Python 3.11+ shim). Second pass: ruff green, mypy green, 18 tests pass, wheel builds. Every item from the code review is now addressed across Sprints 003–006.

**What worked.**

- Auto-fix carried most of the ruff findings. 8-of-10 required no manual edit. The remaining two (one line-too-long, one format-only) were mechanical. The pattern generalises: adopt lint on an existing small codebase in one sprint, take the auto-fix output for free.
- Mypy strict on the wrapper code caught two legitimate class of issue: unbounded generic types (`dict` without type args) and the sdd-subclass surface. The `# type: ignore[misc]` on the two class defs is targeted; the alternative was writing a `sdd.pyi` stub file. Stub deferred — write it if kit maintainers add `sdd` to a real distribution.
- `filterwarnings = ["error"]` did not surface any pending deprecations. The stack (Python 3.13, hatchling 1.x, pytest 9.1, ruff 0.16, mypy 1.19) is quiet at this point in time. A Python 3.14 or a pytest 10 might change that; the sprint captures the current state.

**What got in the way.**

- Ruff's `UP` pack changed `from datetime import timezone` + `timezone.utc` to `from datetime import UTC` + `UTC.utcoffset(v)`. That's a Python 3.11+ shim (introduced in 3.11). The code was written targeting `>=3.11`, so the change is legitimate — but it's the sort of edit that would break a project pinned to Python 3.10. Worth naming in the KIT_DIARY as an antipattern to guard against: `UP` rules can silently push the minimum-Python floor. Not a problem here (pyproject already commits to 3.11); worth flagging for a hypothetical port.
- Mypy's `--strict` flag is on/off; there's no gradient. Two lines of `# type: ignore[misc]` cover the sdd-subclass boundary and let the rest of the module benefit from strict. Cleaner would be `sdd.pyi`, but that's an sdd-kit-2 upstream contribution, not this project's problem.

**What this says about the next kit version.**

- **1. Tooling sprint pattern is worth naming.** The kit doesn't currently have a canonical shape for a "tooling adoption" sprint. Sprint 006's shape (add deps, configure sections, run tools, take auto-fix, resolve residuals) is small and reusable. Candidate for TECHNIQUES.md §1 addition, or a per-language project-class subsection (Python data-science class).
- **2. `# type: ignore[misc]` at the un-stubbed-boundary is the right escape hatch.** A `sdd.pyi` stub file is the correct answer, but it's upstream work. Local `type: ignore` at the two class definitions is targeted, documented (via the module docstring naming the sdd dependency), and cheap to remove when stubs arrive. Candidate for TECHNIQUES.md § LLM-integration or § External SDK bridge mappings — the pattern generalises to any un-typed external dependency.

**Hypothesis verdicts.**

- H6 (locked vocab → first-pass-clean downstream). Sprint 006 second-pass (first pass surfaced findings; second closed). Half-credit. 5-for-7 overall counting each pass. Tentative.
- **New H8.** Adopting ruff + mypy on an existing small codebase in one sprint is cheap because auto-fix does most of the work. Testable: how many findings did auto-fix carry vs. how many needed manual review? Sprint 006 data: 8-of-10 ruff (80% auto-fix), 0-of-4 mypy (mypy has no auto-fix). Confirmed for ruff, expected for mypy — future data points from other tooling-adoption sprints tell us more.

---

### 2026-08-10 — Sprint 005: review cleanups closed

**What happened.** Four small refactors from the code review: `mkdir` moved out of `__init__` to first-emit (via `_sink_prepared` flag); `Signal` reconstructed locally in `emit()` (decoupled from parent's private deque); module-level `emitter` singleton replaced with `@lru_cache`'d `get_emitter()` plus a PEP 562 `__getattr__` shim to preserve `from ... import emitter`; test brittleness fixes (hard-coded 55 → JSON count read; wall-clock threshold 0.005 → 0.04; `n_signals_emitted` computed inline per test). One new test proves the mkdir moved. 18 tests pass.

**What worked.**

- All four refactors landed on the first pass. No test broke, no wheel rebuild broke, no import surface changed for callers. The PEP 562 shim is the win — keeps the import ergonomics identical while making the module load lazy at the file-read boundary.
- The `_sink_prepared` flag is one branch per emit and zero syscalls after first-emit. Alternative (`stat` per emit) would have added a syscall at bar cadence. Small perf detail; matters when a sim run emits tens of thousands of BAR_PROCESSED tags.
- Reading the tag count from the JSON at test time instead of hard-coding 55 removes one of the review's brittleness concerns while adding zero cost. Next vocabulary bump (v0.2 adds N tags) does not break the test.

**What got in the way.**

- Nothing. The refactors were small and mechanical; the code review's own file:line specificity made execution trivial.

**What this says about the next kit version.**

- **1. Review-drive-refactor is a first-class sprint pattern.** Sprints 003, 004, 005 all executed against a single code review file (`reviews/code-best-practices-round-1.md`). The review acts as a bounded backlog: each punch-list item maps to one sprint or one sprint fragment, and the trajectory closes cleanly. Candidate for TECHNIQUES.md §1 refactor section: "when a code review lands with a punch list, split by concept and process items in order; the review IS the plan for the follow-on sprints."
- **2. PEP 562 `__getattr__` at module scope is a low-cost backwards-compat pattern.** The kit has no explicit guidance on module-boundary API evolution. Adding a `get_thing()` factory and keeping `thing` as a lazy shim via `__getattr__` preserves callers while allowing the internal machinery to change. Worth a mention in TECHNIQUES.md §1 if it recurs on other kit projects.

**Hypothesis verdicts.**

- H6 (locked vocab → first-pass-clean downstream). Sprint 005 first-pass clean. 4-for-5 overall (Sprint 003's build-layer second-pass remains the only miss). Tentative → moving toward partially confirmed.

---

### 2026-08-10 — Sprint 004: typed-payload enforcement closed

**What happened.** `StrictSignalVocabulary.__init__` now parses each field's declared type string into a callable checker at load time. `validate` runs each field's checker on every emit. The vocabulary took five review rounds to nail down the types; the code now enforces them. Ten new tests cover the enum, sha256, int, bool, uuid, datetime_utc, date_iso, and list-element checks. Real-hex fixtures via `hashlib.sha256(...).hexdigest()` replace the `"a" * 64` placeholders. 17 tests pass; wheel rebuild clean; `emitter.emit('SESSION_INIT', run_kind='banana', ...)` raises with the exact allowed enum values named.

**What worked.**

- Precomputing the checkers at load is the right shape. Zero parsing cost at emit time; one dict lookup per field per emit. The `StrictSignalVocabulary.__init__` walks the schema once, builds a per-tag `dict[field_name, Checker]`, and stores it. Every subsequent `validate` call reads from precomputed structure.
- The recursive parser handles `list<float>`, `dict<str, int>`, and `list<dict<str, int>>` cleanly. Vocabulary uses container types sparingly (only three payloads carry lists this size); parser handles the entire declared set without special cases.
- Validation-error messages carry enough context to debug from the trace alone: `"Signal 'SESSION_INIT' field 'run_kind': expected one of ['align', ...], got 'banana'"`. The signal-driven-development principle — a signal names its own semantics — extends to validation failures.

**What got in the way.**

- The first-pass uuid test used `TRADE_LEDGERED.trade_id` on the assumption it was typed `uuid`. It was typed `uuid` in the initial vocabulary draft but reclassified to `entity_ref<Trade>` in round 4 of the vocabulary review. Test failed on first run. Fix moved the test to parser level (`_parse_type("uuid")` returned checker exercised directly). No field in v0.1 currently uses `uuid` — the checker is present for future vocabulary bumps but has no live coverage through the emitter.
- The Layer-7 `range`, `gate`, `cardinality`, and `frozen_artifact` constraints stay uncovered by this sprint. They're aggregate or grading-time checks, not emit-time. The vocabulary declares them; nothing yet enforces them. Later sprint gets a grader that walks the trace against Layer 7.

**What this says about the next kit version.**

- **1. Vocabulary-to-code enforcement gap is a class of defect, not a single sprint.** The vocabulary declares three enforcement layers: field presence (Layer 2 required + strict extras — Sprint 001), field types (Layer 2 type strings — Sprint 004), field values and cross-signal invariants (Layer 7 constraints — deferred). Each layer needs its own enforcement pass, its own tests, and its own code. TECHNIQUES.md §1 commitment 2 ("schema enforced at the speaker's mouth") is a slogan that needs three checkmarks, not one. Candidate: split the commitment into three named sub-commitments with which sprint or grader owns each.
- **2. Dead-code checkers are forward-compatibility, not waste.** `_check_uuid` and `_check_git_sha` don't have live vocabulary coverage in v0.1. Removing them would force re-authoring at v0.2 when a field first uses either. Keeping them costs one line each and buys the next vocabulary bump. Related to Addendum D's "verify the verifier" principle — the checker is present; the parser-level test exercises it; live coverage waits for the vocabulary to catch up.

**Hypothesis verdicts.**

- H6 (locked vocab → first-pass-clean downstream). Sprint 004 first-pass code-clean; second-pass test-clean (one test caught the reclassification the vocabulary went through in round 4). 3-for-4 overall counting both layers, or 3-for-3 code-clean. Tentative.
- **New H7.** The vocabulary type strings are self-describing enough that a small parser (~30 lines) enforces them across the whole schema. Testable via: adding a new type to the vocabulary should require one entry in `_TYPE_CHECKERS` and one line change in `_parse_type`, no plumbing edits. Sprint that adds `git_sha` (40-char hex) as a format type tests it.

---

### 2026-08-10 — Sprint 003: code-review pre-fixes closed

**What happened.** `reviews/code-best-practices-round-1.md` surfaced a ship-blocker (module-level `_VOCAB_PATH` walk-up fails under wheel install) plus three one-liners. Sprint 003 fixed the ship-blocker by moving vocabulary loading to `importlib.resources` against a `price_space_llm._vocab` sub-resource, with the file exposed via a symlink at `src/price_space_llm/_vocab/0.1.json` → `../../../signals/0.1.json`. Wheel builds clean. Fresh-venv install imports and reads `tag count: 55`. Six other findings deferred to Sprints 004-006 with explicit rationale in the sprint card.

**What worked.**

- The symlink approach unified editable and wheel install without duplicating the vocabulary file. `signals/0.1.json` stays at project root as the naming convention every doc references; hatchling follows the symlink at build time and packages the target's contents. One source of truth.
- The review's own recommendation to add force-include for the JSON turned out to be wrong once the symlink was in place — hatchling raised "second file added at same path" on the first build. Caught and fixed on the spot. The failure was in the sprint card's content assertion, not in the reviewer's insight; the symlink itself was the review's other suggestion, and it made force-include redundant.
- Scope creep discipline held. First-pass rewrite of `emit()` moved `mkdir` and reconstructed `Signal` locally — both real §3 findings from the review, both explicitly bucketed as "In Sprint 003 or 004." Caught before commit, reverted, deferred properly.

**What got in the way.**

- The sprint card wrote content assertions for a pyproject.toml shape that turned out not to build. The assertion said "the force-include block includes both entries"; the actual working config has the JSON entry commented out. Sprint card assertion is stale in the audit trail. No fix required — the audit trail is the work — but a note here so a future reader knows what to trust when the sprint card and the file disagree.
- Grep across the codebase flagged two comment lines (`# Sprint 001 tests` and `# Sprint 002 tests`) in test_signals.py that the docstring-strip missed. Same class of finding as the docstring itself — the review's §7 named docstrings but the pattern is broader. Second pass caught them.

**What this says about the next kit version.**

- **1. Symlinks are the cleanest cross-install pattern for packaged data.** A dedicated pattern in TECHNIQUES.md would name: put the authoring copy at project root per kit convention, symlink into `src/<pkg>/<subdir>/` for both editable and wheel install, and DO NOT add a redundant force-include for the same destination. Adjacent to §2 Data science "Metric snapshot as artifact" as a packaging-side pattern.
- **2. "Sprint N narration in code" is a broader pattern than docstrings.** The review's §7 named docstrings; comment lines (`# Sprint N tests`) inherit the same anti-pattern. The rule should read: "no sprint numbers anywhere in shipped code — docstrings, comments, variable names, log messages." Candidate for TECHNIQUES.md §1 addition or a WORKING_AGREEMENT tone-canon extension.

**Hypothesis verdicts.**

- H6 (locked vocab → first-pass-clean downstream). 2-for-3. Sprint 003 failed first-pass on the build layer (duplicate destination) and required a second attempt. First-pass clean if you count "the code works and only the build config was wrong"; not first-pass clean if you count the build error. Downgrade: 2-for-2-and-a-half, still tentative.

---

### 2026-08-10 — Sprint 002: JSONL sink closed

**What happened.** `StrictSignalEmitter.__init__` gained `jsonl_sink: Path | None`. `emit()` pre-validates through `_vocab.validate` (raising before any side effect), resets `_session_start` when the tag is `SESSION_INIT`, calls `super().emit()`, and appends one JSON line to the sink when set. Three new tests exercise the sink line count, boundary-tag identity, and the clock reset. `uv run pytest tests/ -v` → 7 passed in 0.09s. Sprint 001 code note 3 closed.

**What worked.**

- The Rubber Duck Pass had a real trace to walk this time. Test 5's sequence narration was three-lines-mechanical: SESSION_INIT at t=0, CHECKPOINT_WRITTEN at t≈0.0001, SESSION_COMPLETE at t≈0.0002. The pass surfaced one payload anomaly (n_signals_emitted is caller-set, so a lying caller lies in the trace). That is exactly what the six-category pass is designed to find.
- Sprint 001's drift-watchlist entry closed cleanly. The `_session_start` reset is one line inside `emit()` and one test that sleeps and reads back a small `t`. The bug that would have surfaced as odd `t` values in every future sim run gets fixed once, verifiably.
- H6 gains a second first-pass-clean data point. Sprint 002 landed on the first pass. Two-for-two is not yet confirmation but the trend runs the right way.

**What got in the way.**

- Pre-validating in the subclass `emit()` duplicates validation work — `super().emit()` calls `_vocab.validate` again. Small perf cost, not measurable at this scale. Alternative was to reset the clock after `super().emit()` returns and then patch the last signal's `t` field, which is uglier. Chose the honest duplication over the surgical hack.
- The Rubber Duck Pass observation surfaced a bug shape the vocabulary encourages but the code does not catch: SESSION_COMPLETE.n_signals_emitted is caller-set. This is a general class — many summary tags require the caller to correctly count things the emitter already knows. Candidate for a helper method in a future ergonomics sprint (`close_session()` that reads the buffer length and closes SESSION_COMPLETE for you).

**What this says about the next kit version.**

- **1. Pre-validate-then-side-effect is the right order for wrapper emit methods.** The alternative (side effect first, roll back on validation failure) is fragile. TECHNIQUES.md §1 "Schema enforced at the speaker's mouth" implies but does not state this ordering rule for wrapper implementations. Worth adding.
- **2. Summary tags with caller-computed counts are a payload-anomaly hazard.** SESSION_COMPLETE.n_signals_emitted, ALIGNMENT_RUN_COMPLETED.total_rows, EPOCH_COMPLETED.n_steps — all caller-set. All can lie. Candidate: helper methods on the emitter that close summary tags with computed values from the buffer, so the caller cannot lie by accident.

**Hypothesis verdicts.**

- H2 (dual contract for non-UI catches D1 class). Not yet exercised at scale — Sprint 002's sink is the first artifact-on-disk the observation contract verifies. Real test comes when a training run misreports metrics and the observation catches it.
- H6 (locked vocab → first-pass-clean downstream). Two-for-two. Tentative moves toward partially-confirmed at three-for-three.

---

### 2026-08-10 — Sprint 001: signal emitter closed

**What happened.** Three code files landed: `pyproject.toml`, `src/price_space_llm/signals.py`, `tests/test_signals.py`. `uv sync --dev` installed the package plus pytest into `.venv/`. Four tests passed in 0.02s. `StrictSignalVocabulary` extends `sdd.SignalVocabulary` with the strict-extras posture WORKING_AGREEMENT commits to. The module-level `emitter` singleton loads the 55-tag locked vocabulary at import.

**What worked.**

- Sprint 001 executed on the first pass. No halts, no revisions. The vocabulary lock from Sprint 0 removed the largest class of question — "what should I emit and with what payload?" — before code authoring began. That confirms the value of Sprint-0-as-founding-act.
- The plan-mode split (6 files → 3) that surfaced during Architect review was the right cut. Sprint 001 landed one concept; Sprint 002 lands the next. If I had shipped the JSONL sink in the same sprint, the RubberDuckPass ambiguity (six categories are for trace observations; the sink work generates observations of a different class) would have compounded.
- `pyproject.toml`'s `[tool.hatch.build.targets.wheel.force-include]` gave `from sdd import ...` global reach without a `sys.path` shim in `signals.py`. Kit convention (sdd-kit-2 is read-only) preserved. Would have been the cleanest first attempt if I had reached for hatchling documentation instead of proposing "vendor vs shim" as a false dichotomy.

**What got in the way.**

- I framed a false dichotomy at plan-mode review ("vendor vs shim") when the actual question was mechanical (how does the import work). The Architect caught it. Lesson: check the shape of a question before offering the Architect a choice; if the choice is really about mechanics, pick the sensible default and note it.
- My initial Sprint 001 Rubber Duck Pass entry labelled code-side notes with the six trace-observation categories. Mislabelling. The RubberDuckPass's six categories walk a **signal trace**; when a sprint's tests exercise raise paths only and emit no successful signals, the pass is structurally vacuous. Code-side notes get filed differently — as project-notes or drift-watchlist entries. Corrected in-file 2026-08-10.
- The auditing of the sprint against the twelve hard rules ran only when the Architect explicitly asked ("Do a quick check"). The kit does not require a per-sprint hard-rule audit; adding one would grow the ceremony. But a mental checklist run at sprint close would have caught the RubberDuckPass mislabel without the Architect prompt.

**What this says about the next kit version.**

- **1. RubberDuckPass mode split: trace-pass vs code-pass.** The kit's six-category pass is designed for signal traces. Sprints whose tests exercise raise paths only, or that author no runtime code that emits (architecture-band sprints), have no trace to walk. The pass is vacuous by design; the code-side notes those sprints surface do not fit the six categories. Candidate: name the vacuous case explicitly in the RubberDuckPass procedure (AGENTS.md § Sprint close) and describe the code-note filing pattern for architecture-band sprints.
- **2. Plan-mode "false dichotomy" antipattern.** The Agent's tendency to frame a mechanical question as an Architect choice generates ceremony. Rule of thumb: if the answer is "the sensible default plus a one-line note in the sprint card," the Agent picks and moves on. Candidate for TECHNIQUES.md §1 error-handling.

**Hypothesis verdicts.**

- H1 (Data science class techniques cover 80%+ without invention). Not exercised — Sprint 001 was package-and-emitter scaffold, not a training-loop sprint.
- H2 (dual contract for non-UI catches D1 class). Not exercised — Sprint 001 had vacuous signal contract.
- H3 (bridge-mapping-first prevents guess-and-iterate). **Confirmed partially.** Sprint 001 authored no code against un-mapped SDKs (PyTorch, MCP, Hydra, Pydantic, Polars, W&B). The `sdd` import is vendored, not external. Sprint 002 tests H3 more directly if it adds a Pydantic dependency.
- H4 (frozen-artifact contract with paired reader test). Not yet exercised — no frozen artifacts written this sprint.
- H5 (Vocabulary Session runs faster on spec-mature project). N/A — this is a code sprint, not a vocab session.
- **New H6.** Sprint 001's first-pass-clean success suggests: when Sprint 0 lands a real vocabulary lock, downstream sprints iterate cleanly because the vocabulary answers "what to emit" before code writing begins. Testable via base rate of first-pass-clean closes across Sprints 002-010. Status: tentative.

---

## Phase boundary syntheses

*(One synthesis entry per phase close.)*

### 2026-08-16 — Phases A, B, C, D closed together

The four pre-GPU phases closed inside the same window; the 2026-08-16 entry above serves as their combined synthesis. Split for the record:

- **Phase A — infrastructure (Sprints 001-039 + 041).** Package + emitter + vocabulary + probe + ingest + alignment + first tokenizer/trainer/evaluator + baselines + storage integrity + multi-month CLIs. Delivered a runnable end-to-end pipeline against SPY on cached Alpha-Vantage data through 2023-12-31.
- **Phase B — feature layer (Sprints 042-052, 062, 069-072).** Aligned parquet enrichment (staleness triple per channel); DST-correct `zoneinfo` migration; cross-asset + macro + options + event ingest; target features + VXX-for-VIX-volume + UUP-for-DXY substitutions; session flags; every spec § 6 channel type computed. Complete as of Sprint 072 close.
- **Phase C — model + normalizer (Sprints 053-055).** MarketStateEmbedder + MarketStateTransformer; frozen-on-training-partition normalizer with `.pt` persistence; two-sample KS drift diagnostic + `NORMALIZER_DRIFT_MEASURED` v0.5 tag. Complete.
- **Phase D — training discipline + baselines + guards + evaluator switch (Sprints 056-068).** Extended bucket_stats.json shape; AdamW/cosine/warmup/bf16/deterministic trainer; purged embargo + top-K checkpoint retention; MLP + GRU baselines; target-only-zeroed helper composes with market-state trainer; experiments/logbook.csv writer; commit-msg + filesystem test-look guards; spec-guard tests; regime evaluator VIX switch; evaluator MarketStateTransformer path. Complete.

Phases E (ablation configs, Sprints 073-078) and F (simulator + cost calibration, Sprints 079+) open next; both unblocked by the 2026-08-16 Decisions entry.

---

## Project-close synthesis

*(At project close: the top 5–10 structural findings for the next `sdd-kit` revision.)*

---

*KIT_DIARY.md — Price-Space LLM. Five hypotheses on file at project start; entries land as sprints close. The soundfield project's diary accumulated ~130 numbered findings across ~30 rounds — that is the ceiling this diary aims at over the project's nine-week planned span.*
