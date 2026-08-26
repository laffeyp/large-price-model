# Post-mortem: the normalization bug (Sprint 054 → Sprint 113)

**Date filed:** 2026-08-25
**Written:** immediately after Sprint 113 close
**Severity:** silent quality collapse across every training run of Sprints 110-112. Zero training crashes. Zero test failures. Zero visible symptoms. The bug produced honest-looking numbers that misled every conclusion Sprints 110-112 drew.
**Blast radius (contained by):** the bug was scientifically invalidating, not procedurally destructive. Every affected artifact is preserved. Every conclusion the arc reached is retractable and re-testable. No production wall-clock and no held-out looks were spent under the bug's shadow.

## timeline

- **Sprint 054** (2026-08-14): frozen normalizer landed. `scripts/bucketize.py --fit-normalizer` flag introduced. Bit-tight artifact contract: features are z-scored on the training partition and the normalizer is persisted for reuse on val/test.
- **Sprint 083** (2026-08-16): `ChannelMixerEmbedder` landed. Live smoke on real corpus showed the mixer's random-init attention diverging (grad_norm ~33M) on un-normalized input.
- **Sprint 084** (2026-08-17): `UnnormalizedArtifactRefused` guard added to `run_training_feats`, scoped to `fusion == 'mixer'` only. Comment on the exception class explicitly says: *"sum fusion tolerates un-normalized input via internal LayerNorms and is unaffected."* That claim was based on the observation that sum fusion did not diverge under un-normalized input. Not tested against validation performance.
- **Sprint 110** (2026-08-24): model-size sweep. Every run trained on `data/tokenized/tokens.latest.pt`, which was generated without `--fit-normalizer`. Sum fusion. No divergence. Every run reported val_nll ~3.30-3.42. All four sizes concluded to lose to a linear baseline. Report authored: "monotonic scaling with plateau, transformer loses to linear."
- **Sprint 111** (2026-08-25): per-regime diagnostic. Same un-normalized artifact. Report authored: "linear beats transformer on every regime — high-vol especially. The transformer isn't extracting even the auto-regressive signal linear captures."
- **Sprint 112** (2026-08-25): H1 (longer training) vs H2 (regularization) probes. Same un-normalized artifact. md-longtrain hit pooled val_nll 3.315 at step 30000 (best-in-arc up to that point). Report authored: "H1 partially confirmed — training helps."
- **Sprint 113** (2026-08-25): target-only + fusion probes. Sprint 113-A ran target-only on the un-normalized artifact — matched Sprint 110 v3 md to four decimals in every regime. Sprint 113-D tried mixer on the un-normalized artifact and was refused by the Sprint 084 guard. Regenerated the artifact with `--fit-normalizer`. Sprint 113-C (sum + normalized) hit pooled val_nll **3.1976 at step 2000** — beat linear on every regime, first arc win. Root cause identified.

**Total elapsed under the bug's shadow: 71 days (Sprint 054 close to Sprint 113 discovery).** No wall-clock production runs were spent, because Phase H didn't start until Sprint 108. Actual under-bug production training: Sprint 110 through Sprint 113-A. ~5 hours of real GPU-equivalent time.

## root cause

Two failures composed:

1. **The artifact contract carried a `normalized` field in `meta` but wasn't enforced on the read path.** `tokens.latest.pt` was written without `--fit-normalizer` at some point before Sprint 110 (predates the audit trail; the `run_id` in meta doesn't record whether normalization was requested). The `.pt` reader in `load_tokens_pt` returned the artifact without inspecting the `normalized` field. Every downstream consumer either checked it explicitly (`run_training_feats` for mixer) or ignored it (`run_training_feats` for sum, `run_evaluation_feats`, every analysis script).
2. **The Sprint 084 guard was scoped to the symptom, not the cause.** Mixer diverged loudly on un-normalized input. Sum fusion did not diverge — it silently produced a target-only-equivalent output because the raw `dollar_volume` scale (mean ~61M, std ~264M) dominated every non-target channel's `nn.Linear(F_c, d_model)` projection inside `MarketStateEmbedder`. The projection weights would need to be ~1e-8 for any non-target channel to contribute at target-comparable magnitude. Random init produces weights ~O(1/sqrt(d_model)) = ~0.05. The projected non-target vectors were ~10-million times the projected target vectors, so the sum was ~all-non-target-noise, and Adam converged to weights that projected non-target to near-zero — effectively giving the target-only path.

Neither failure alone would have caused the silent quality collapse. Failure 1 without 2: the mixer guard would have blocked every mixer run correctly (and it did — Sprint 113-D). Failure 2 without 1: an inspected normalized field would have caught the un-normalized artifact at load time.

## how it stayed hidden

Six things kept the bug invisible until Sprint 113:

1. **Sum fusion never diverged.** Every training run completed cleanly. No `TRAINING_DIVERGED` emit. No exception. Trace files complete, checkpoints saved, val_nll values in reasonable range (3.30-3.42 vs chance 3.47).
2. **Target-only ablation was never run under sum fusion.** The `zero_non_target_features` function existed since Sprint 061 but wasn't wired into `scripts/train.py` as a CLI flag. Landing it at Sprint 113-A is what surfaced the target-only ≈ full-channel result to 4 decimals.
3. **Baselines seemed defensible.** Linear at 3.33 vs transformer at 3.40 read as "transformer is 2% worse than linear at this budget." A plausible finding that fit the data-limitations-review's central thesis. Never looked wrong enough to demand investigation of the input.
4. **Per-regime story was internally consistent.** The transformer wins on low-vol vs chance, loses on high-vol vs chance. The multi-channel-features-drown-in-noise hypothesis explained this cleanly. Every finding fit the frame; no finding contradicted it.
5. **Sprint 084's comment stated the wrong invariant confidently.** *"Sum fusion tolerates un-normalized input via internal LayerNorms."* This was an untested assumption from the Sprint 083 divergence observation. Anyone reading that comment before adding a symmetric guard would have concluded no guard was needed.
6. **`meta['normalized']=False` looked like a warning, not a diagnostic.** The field was there. It just wasn't checked.

## the moment of visibility

Sprint 113 was scoped to probe *why* the transformer lost to linear. Two probes: A (target-only) and B (mixer). Probe A completed and matched Sprint 110 v3 md to 4 decimals in every regime. That was the first datum incompatible with the "multi-channel features add small signal" narrative — if features added signal, target-only should lose. Probe B was refused by the Sprint 084 guard, which surfaced `normalized: False` in the artifact meta. Regenerated with `--fit-normalizer`, retried, hit val_nll 3.1976 at step 2000. The 0.21-nat gap between un-normalized-sum-md and normalized-sum-md was the bug's magnitude.

The bug was visible in one hour once the right question was asked. The right question — *does the artifact respect its own contract* — had gone unasked for 71 days.

## what the false conclusions were

Every "the transformer can't beat linear" finding Sprints 110-112 drew was **wrong on the causal claim** and **correct on the surface number given the wrong artifact**. Specifically retracted:

- **Sprint 110 sweep report finding**: "monotonic scaling with plateau, transformer loses to linear." Correct against un-normalized data; wrong as a claim about the transformer architecture at this training budget.
- **Sprint 111 diagnostic finding**: "linear beats the transformer on every regime." Correct on un-normalized; wrong as a claim about the multi-channel features carrying no usable signal.
- **Sprint 112 H1 finding**: "training helps; longer training closes the gap to -0.8%." Correct on un-normalized; the actual normalized+short-training already beats linear by +2.8%, so the "training closes the gap" story is incomplete — training and normalization together cross the gate; either alone doesn't.
- **The Sprint 111 data-limitations review's central thesis** ("the amplifier is fine, the door has to open"): partially retracted. The amplifier was mis-wired for 71 days. The door metaphor still holds for the 10% pre-registered gate — we're 7.5% below it even under normalized data — but "the amplifier is already fine" was false.

## what stays true

The Sprint 111 review's specific predictions all hold under the normalized regime too:

- Signal concentrated in low-vol ✓ (normalized: low nll 2.92 vs high 3.23; still low-vol dominates the edge)
- Multi-channel edge is measurable but bounded ✓ (normalized: +2.8% pooled, not +10%)
- 15-min horizon has a signal ceiling that no architecture crosses without data expansion ✓ (10% gate still 7.5% away)
- Bigger training window + higher resolution data are the ROI-ordered next moves ✓ (Sprint 114+ ordering unchanged)

The direction of the arc's next work — regularization sweep, then data expansion — is unchanged. The **magnitude** of the linear gap and the **interpretation** of which experiments told us what are both revised.

## fixes landed now (Sprint 113, immediately)

1. **`UnnormalizedArtifactRefused` broadened to every fusion.** Trainer now refuses to run on any un-normalized `.pt` under any fusion setting, sum included. Error message specifically names the Sprint 113 finding so a future reader knows what silent failure the guard prevents. Docstring on the exception class rewritten to record the retraction of Sprint 084's incorrect "sum tolerates un-normalized" claim.
2. **Canonical artifact swapped.** `data/tokenized/tokens.latest.pt` now points at the normalized version (`data/tokenized/normalized/tokens.tokenize-features-align-2015-01-2022-12-....pt`). The pre-Sprint-113 un-normalized artifact preserved under `tokens.unnormalized.tokenize-features-align-2015-01-2022-12-....pt` for archival — any future reproduction of Sprints 110-112 numbers must reach into that named file, not the canonical path.
3. **Test that asserted the old behavior replaced.** `test_run_training_feats_permits_sum_on_unnormalized_artifact` became `test_run_training_feats_refuses_sum_on_unnormalized_artifact`. Body inverts to assert the guard fires. Docstring records the Sprint 113 retraction.
4. **Every existing `run_training_feats` fixture stamped `normalized: True`.** Four tests were building synthetic un-normalized artifacts and feeding them to `run_training_feats`; each now marks the artifact as normalized so tests exercise the new happy path. No fixture legitimately needs to be un-normalized; the guard-test is the sole exception.

Verified: **628 tests green** (up from 628 after the sweep, no net change — one test replaced, four fixtures updated). Guard demonstrably fires on the archival un-normalized artifact (verified via manual CLI probe).

## post-fix stance on tech debt

Every item is landed. No open tech debt from this bug remains. This is the correct default: if a bug required immediate fix + retraction, its infrastructure fix belongs in the same closing gesture, not queued for later.

- **Trainer refuses unnormalized under every fusion** — landed. Guard broadened from mixer-only.
- **Canonical `tokens.latest.pt` normalized** — landed. Unnormalized archived.
- **Tests updated for the new guard** — landed. Fixtures stamp `normalized: True`; the "permits sum on unnormalized" test replaced with "refuses sum on unnormalized".
- **Ledger and data-limitations review updated with retraction** — landed.
- **`run_id` hyperparameter fingerprint** — landed. Sprint 112's checkpoint collision was a workaround-away from correctness under `--run-id-tag`; the sprint-113b auto-fingerprint (`-hp{8char}` sha256 of every training hyperparameter) makes it structurally impossible. Sprint 112 md-regularized and Sprint 110 v3 md would have gotten distinct suffixes `-hp5a54265a` vs `-hp1ede6816`. Any distinct hyperparameter combo now writes to a distinct checkpoint path.

## lessons filed to KIT_DIARY (in style of past entries)

- **"Silent quality collapse is worse than a crash."** A training script that runs to completion, emits every expected tag, saves valid checkpoints, and reports plausible val_nll numbers can still be silently producing a target-only-equivalent output because a single meta field went unchecked. Fail-loud guards should cover the failure *class* (any output quality drop), not the failure *symptom* (visible divergence). Sprint 084's guard caught the symptom on mixer; sum's silent failure went 71 days.
- **"An untested assumption in a comment is a load-bearing lie."** Sprint 084's comment *"sum fusion tolerates un-normalized input via internal LayerNorms and is unaffected"* was based on observing no divergence, not on measuring val performance. It read as authoritative and shaped every subsequent reader's expectation. Documented untested claims should be either verified inline or rewritten as hypotheses.
- **"Ablations that give suspiciously similar numbers are diagnostics, not confirmations."** Sprint 113-A's target-only matching Sprint 110 v3 to 4 decimals in every regime *should* have been the immediate red flag. The Sprint 111 review's prediction was "target-only < full by a few percent." Bit-identical results were the tell. The next-most-informative move after a null result is asking why it's *bit-identical* rather than approximately equal.
- **"The correct question, asked once, finds the bug in one hour."** Sprint 113's target-only probe was a scoped one-flag training run. The bug had been visible in the artifact meta for 71 days. Nobody looked because nobody had the target-only comparison to force the question.

## action items (all landed; recording for the log)

- [x] Broaden `UnnormalizedArtifactRefused` guard to every fusion.
- [x] Swap canonical `tokens.latest.pt` to normalized; archive un-normalized.
- [x] Replace test that asserted the old wrong behavior.
- [x] Stamp `normalized: True` on every existing test fixture.
- [x] Update `artifacts/experiment-ledger.md` with the corrected linear baseline number (3.2886, not 3.333) and Sprint 113 results.
- [x] Update the Sprint 111 data-limitations review to note the Sprint 113 retraction.
- [x] `run_id` hyperparameter fingerprint: `-hp{8char}` sha256 of every training hyperparameter (lr, wd, warmup, lr_min_frac, bf16, embargo, keep_top_k, target_only, fusion, mixer_dim, mixer_n_heads, patch_size, head_type, batch_size, deterministic). Sprint 112's checkpoint collision structurally impossible from Sprint 113b onward.

No open items.
