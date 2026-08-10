# Round-3 review — signals/proposals.json + signals/0.1.json

**Reviewer:** Claude Code (Opus 4.7), acting in Agent role.
**Date:** 2026-08-09.
**Scope:** The round-3 recast: four canonical proposals in `signals/proposals.json`, 25 entities plus 10 flags in `signals/0.1.json`, seven inline removals, and the BLACKBOARD round-3 close entry.
**Frame:** `grammar/PRINCIPLES.md § "The supervised-grammar-evolution proposal taxonomy"` (eight canonical types), `grammar/BOOTSTRAP.md` (Step 1 halt conditions plus 0 → 7 dependency order), `WORKING_AGREEMENT.md § "Canonical home registry"`.
**Recommendation:** Ratify P-001, P-002, P-003. Move P-004 and the four Layer-6-forward flags to `BLACKBOARD.md § Deferred` where P-015 already sits. Stamp the remaining six Layer-0 flags inline. Tighten `Bar`. Note Session's Layer 0 + Layer 3 duality now, before Step 4.

---

## 1. The meta-vocabulary violation is fixed

All four proposals in `proposals.json` use canonical types: three `ENTITY_MERGE_PROPOSED` (P-001, P-002, P-003) and one `NEW_TAG_PROPOSED` (P-004). No `POLYSEMY_VERDICT_PROPOSED`, no `NEW_ENTITY_PROPOSED`, no `KIT_PATTERN_ADOPTION_PROPOSED`. The round-2 pattern of inventing meta-vocabulary in response to a review about inventing vocabulary is closed. The `_recast_log` block records every round-2 entry's disposition, so a future reader can trace how the queue arrived at four from fifteen.

## 2. `_recast_log` and `removed_from_layer_0_inline` are the right audit trail

The kit's "no deletions" hard rule (AGENTS.md rule 12) says restructures land additively. `_recast_log` in `proposals.json` and `removed_from_layer_0_inline` in `0.1.json` both hold what the prior round wrote, with the disposition and the citation to the review that forced the change. Nothing was silently dropped; everything moved has a paper trail. This is exactly what BOOTSTRAP means by "the discipline is what compounds."

## 3. The three canonical merges ratify cleanly

- **P-001** (`Baseline + Ablation → Model`). Rationale names all nine variants; the reworded `Model` entry in `0.1.json` line 82 already spells them out (LinearBaseline, MLPBaseline, GRUBaseline, ChannelMixerVariant, PatchNVariant, QuantileHeadVariant, TargetOnlyVariant, MagnitudeWeightedVariant). `run_kind` is forward-declared as a Layer-2 payload attribute, which will need its own `PAYLOAD_FIELD_PROPOSED` when Step 3 opens.
- **P-002** (`Distribution → Prediction`). Clean.
- **P-003** (`SpreadCalibration + KappaCalibration → CostCalibration`). Reflected in `0.1.json` line 111 as one entity with two component fits; matches the simulator's "one precondition" reading of the two files.

Ratify all three. The version bump from 0.1 to 0.2 waits for lock, per PRINCIPLES.md Layer 9.

## 4. P-004 is a premature Layer-1 proposal

`NEW_TAG_PROPOSED` belongs to Step 2 (BOOTSTRAP: "Step 2 — Layer 1 (Lexical) — name the tags per entity"). Step 1 has not closed. Filing a Layer-1 tag before the Layer-0 stamp that motivates it — `ExperimentConfig` is still in `flags[]` — inverts the dependency order that PRINCIPLES.md §"Dependency structure" makes non-negotiable ("Lower layers are populated first because upper layers consume them").

The `"state": "shell — pending Step-2 population"` field is honest about what P-004 is (a placeholder), but honesty does not legitimize the layer skip. The right home for a Step-2 commitment recorded during Step 1 is the same home the Step-7 commitment took: `BLACKBOARD.md § Deferred` with a revisit trigger. That is the P-015 pattern, and P-015 works because BLACKBOARD explicitly holds forward-commitments across sprint boundaries.

The Layer-7 half of the commitment — the evidence constraint that `lambda_risk MUST be present` in a resolved config — is named in P-004's rationale but has no queue entry at all. Same fix: BLACKBOARD Deferred, revisit trigger "sprint that opens Step 8 (Layer 7)."

## 5. Four Layer-6-forward flags are mis-filed

`IngestionClient`, `AlignmentJoin`, `TrainingLoop`, and `Simulator` sit in `entity_implied_but_unnamed.flags[]` with `layer_target: 6`. BOOTSTRAP Step 1's halt condition is specific to Layer 0: "the docs don't name the entity at all but you're tempted to surface it from inference." Step 7 (Layer 6) has its own halt conditions (operator count exceeds tag count, tags with no emitting operator). A Layer-6 candidate does not fit Step 1's halt bucket.

The `layer_target: 6` annotation is again honest about the misplacement without fixing it. The mechanism that already exists in this project for cross-layer forward-commitments is BLACKBOARD Deferred — where P-015's domain-vs-runtime commitment for Step 7 was correctly filed on this same date (BLACKBOARD line 49). Move all four flags to BLACKBOARD Deferred, either as extensions of the existing P-015 entry or as a fresh entry naming each operator with its source citation and revisit trigger.

The intent — transmit runtime-grammar entities across the layer boundary so Step 7 arrives with the anchors in place — is right. The mechanism should be uniform: BLACKBOARD Deferred for forward-commitments, `flags[]` for Step-1 halts on Layer-0 candidates.

## 6. Six Layer-0 flags ratify inline

`Bucket`, `MetricSnapshot`, `Split`, `Session`, `ExperimentConfig`, `Source` all belong at Layer 0 by the docs the citations name. Each carries the reasoning BOOTSTRAP Step 1 requires. Stamp each in place — the promotion moves the flag into `entities[]` and a rationale-doc entry lands at Step 11.

Two of the six deserve a note attached at stamp time:

- **`Session` is dually classed at Layer 0 and Layer 3.** PRINCIPLES.md Layer 3: "What is a 'session' in this system? What is its boundary, its persistent attributes?" The trading session is exactly that — an event stream framed by open and close, with persistent attributes (`session_date`, `is_rth`, `regime_label`). Stamp as Layer-0 entity; note in the flag itself that Step 4 (Layer 3) will re-encounter it and should treat it as a session-stratum, not re-propose it as a new entity.
- **`ExperimentConfig` may still fold into `TrainingRun`'s payload at Layer 2.** The current TrainingRun definition (line 87) says "carries ExperimentConfig, git SHA, data hash, seed, `run_kind`" — treating ExperimentConfig as a payload field. If one config seeds many runs is the design intent, ExperimentConfig stands alone. If the one-to-many pattern is not committed in the specs, folding is simpler. The Architect should say which at stamp time, so the Layer-2 payload work at Step 3 does not have to relitigate.

## 7. `Bar`'s definition is still ambiguous

The Layer-0 entry (line 17) reads: "One 15-minute OHLCV observation on the canonical UTC grid for a target instrument." But tech-arch §4.2's channel table lists QQQ, IWM, VIX, TLT, DXY, GLD, USO all fetched at 15-minute (downsampled), each producing a row that the docs would call a "bar." Two options:

- Broaden `Bar` to "one 15-minute OHLCV observation on the canonical UTC grid for any Symbol," and let context distinguish target bars from context bars.
- Keep `Bar` as target-only and add `ContextBar` for the cross-asset case.

The first is closer to how the docs actually use the word. Tighten during Step-1 stamp.

## 8. Two removals to double-check

`removed_from_layer_0_inline` lists `IngestionCall`, `Sprint`, `Embedder`, `Bucketizer`, `Normalizer`, `SpreadCalibration`, `KappaCalibration`. Six of the seven are unambiguous. The seventh — `Embedder` — is worth a second look.

The removal reason (line 235) is: "Its state lives inside Checkpoint, not a separate Layer-0 file. Moves to Layer 6 only; no Layer-0 replacement seat needed." That is correct as far as it goes. But the Embedder's *output* — `MarketStateToken` — is already at Layer 0 (line 71). So the Embedder-to-Layer-0 relationship is preserved through its output vector rather than through frozen fit-state. Note this parallel explicitly in the rationale doc when Step 11 arrives: for Bucketizer and Normalizer, the Layer-0 seat is fit-state (`BucketStats`, `NormalizerState`); for Embedder, the Layer-0 seat is runtime output (`MarketStateToken`). The pattern is consistent; the mechanism differs.

## 9. WORKING_AGREEMENT canonical home registry is stale on two rows

WORKING_AGREEMENT.md `§ Canonical home registry` (line 33 onward) predates the Layer-0 reclassification. Rows for the Bucketizer (line 45) and MarketStateEmbedder (line 46) name the operator with no separate row for the frozen-file artifact. Post-stamp, add two rows:

- `BucketStats` (artifact) → `artifacts/tokenizer/bucket_stats.json`, produced by `ReturnBucketizer`, read by evaluator/simulator/notebooks.
- `NormalizerState` (artifact) → `artifacts/{run_id}/normalizers.pt`, produced by `src/features/normalize.py`, read by validation and test paths.

Not blocking. But the registry is what future sprints grep to answer "where does this type live," and the two artifacts are now first-class Layer-0 entities that need a home.

## 10. What round 3 addresses from prior reviews

Every finding from `vocab-0.1-layer-0-review.md` (round 1) is addressed, ten of ten. Every finding from `vocab-0.1-proposals-review.md` (round 2) is addressed, seven of seven, except that forward-commitment mechanism-choice remains inconsistent — P-015 → Deferred is correct, P-004 → proposals is not, four Layer-6 flags → `flags[]` is not.

The trajectory is honest and narrowing. Round 1 broke commitment #3 (workers-cannot-invent) at the vocabulary level. Round 2 broke it at the meta-vocabulary level. Round 3 breaks a smaller thing — the dependency order between layers, and only for two forward-commitments, both of which have a correct home already in use in this same project on this same date. One more pass closes it.

## 11. Ratification recommendation

Ratify: **P-001**, **P-002**, **P-003**.

Move: **P-004** to BLACKBOARD Deferred (revisit trigger: "sprint that opens Step 2 for CONFIG_RESOLVED"; a second Deferred entry for the Layer-7 `lambda_risk` evidence constraint, revisit trigger: "sprint that opens Step 8"). Move **IngestionClient, AlignmentJoin, TrainingLoop, Simulator** from `entity_implied_but_unnamed.flags[]` to BLACKBOARD Deferred (revisit trigger: "sprint that opens Step 7," folding into the existing P-015 entry).

Stamp inline: **Bucket, MetricSnapshot, Split, Session** (with Layer 0 + Layer 3 dual-class note), **ExperimentConfig** (with a stamp-time decision on whether it stands alone or folds into TrainingRun's payload), **Source**.

Tighten: **Bar**'s definition to cover any Symbol on the 15-minute grid, or introduce **ContextBar** for cross-asset bars.

Update: WORKING_AGREEMENT.md canonical home registry with two rows for `BucketStats` and `NormalizerState` after ratification.

After these edits, `signals/proposals.json` holds three ratified merges. `signals/0.1.json` holds 31 entities (25 already in `entities[]` plus the six stamped flags), zero pending flags, seven inline removals with citations, and a comment naming the Layer-3 duality on Session. BLACKBOARD Deferred holds the two Step-2/Step-8 commitments plus the four Step-7 runtime operators. Step 1 closes cleanly. Step 2 opens.

The founding act is real work. This draft is close.
