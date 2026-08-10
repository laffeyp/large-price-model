# Proposals review — signals/proposals.json (15 entries)

**Reviewer:** Claude Code (Opus 4.7), acting in Agent role.
**Date:** 2026-08-09.
**Scope:** `signals/proposals.json` — the fifteen typed proposals filed in response to `reviews/vocab-0.1-layer-0-review.md`.
**Frame:** `grammar/PRINCIPLES.md § "The supervised-grammar-evolution proposal taxonomy"` (eight canonical types) and `grammar/BOOTSTRAP.md` Step 1 (halt conditions and Architect-inline ratification).
**Recommendation:** Ratify the three canonical merges, recast the twelve non-canonical entries, and reconcile `proposals.json` with the entity list in `signals/0.1.json` before Step-2 dispatch.

---

## 1. Seven proposal types are invented

PRINCIPLES.md lists eight canonical proposal types: `NEW_TAG_PROPOSED`, `PAYLOAD_FIELD_PROPOSED`, `SEQUENCE_RULE_PROPOSED`, `INVARIANT_PROPOSED`, `TAG_SPLIT_PROPOSED`, `TAG_MERGE_PROPOSED`, `TAG_DEPRECATION_PROPOSED`, `ENTITY_MERGE_PROPOSED`. The queue introduces seven new types beyond that list:

- `POLYSEMY_VERDICT_PROPOSED` — P-004, P-005
- `NEW_ENTITY_PROPOSED` — P-006, P-007, P-008, P-009
- `OPERATOR_RECLASSIFICATION_PROPOSED` — P-011
- `ENTITY_REJECTED` — P-012
- `KIT_PATTERN_ADOPTION_PROPOSED` — P-013
- `RATIONALE_COMMITMENT` — P-015

The pattern is the same failure the prior review named, at one level up. The prior review said the Worker cannot invent vocabulary (commitment #3). The response invents proposal types. The eight-type taxonomy is itself a Layer-10 grammar element; extending it is a Grammar-Growth change stamped by the Architect at the vocabulary-methodology level, not a move the Worker makes inside `proposals.json` by writing a new value in the `kind` field.

Two paths close this. Either the Architect files one Layer-10 grammar-growth proposal that extends the taxonomy from eight types to whichever new set the project actually needs — and the extension itself is ratified before P-004 through P-015 stand — or the twelve non-canonical proposals get recast in canonical shape. The recast, per proposal, is straightforward and appears in §4.

## 2. The three canonical merges are clean

P-001 (`Baseline + Ablation → Model`), P-002 (`Prediction + Distribution → Prediction`), and P-003 (`SpreadCalibration + KappaCalibration → CostCalibration`) all use `ENTITY_MERGE_PROPOSED` as defined. Rationales cite source. P-001 flags `run_kind` as a Layer-2 payload attribute needing its own proposal at Step 3, which is correct forward-declaration. Ratify.

## 3. P-010 uses `TAG_SPLIT_PROPOSED` for something that is not a split

`TAG_SPLIT_PROPOSED` in PRINCIPLES.md is the DDD bounded-context move: an existing tag denotes different events in different contexts and needs to become two. P-010 uses it for `IngestionCall → INGESTION_CALL_ISSUED + INGESTION_CALL_CACHED`. But there is no `INGESTION_CALL_HAPPENED` tag to split — `IngestionCall` is a Layer-0 entity in the current draft, not a Layer-1 tag.

The correct shape is two proposals: a Layer-0 removal of `IngestionCall` (Step-1 inline Architect action, not a `proposals.json` entry) and two `NEW_TAG_PROPOSED` entries at Layer 1 once Step 2 opens. Filing this under `TAG_SPLIT_PROPOSED` will cause the Step-2 Worker to look for a tag that never existed and produce a null result.

## 4. Recast, per non-canonical proposal

- **P-004, P-005 (POLYSEMY_VERDICT_PROPOSED — distinct).** Distinctness is the default. The taxonomy has no "distinct" verdict type because no verdict is needed to keep two things separate. Move the reasoning to the rationale doc's per-layer decisions section as "considered and kept distinct." Remove from `proposals.json`.

- **P-006 (Split), P-007 (Session), P-008 (ExperimentConfig), P-009 (Source).** During a Vocabulary Session, entities added at Step 1 are ratified inline by the Architect after review — no `proposals.json` entry needed, because `proposals.json` governs changes to a *locked* vocabulary and `signals/0.1.json` is not locked yet. Move these four to the `entity_implied_but_unnamed.flags[]` section of `signals/0.1.json` for Architect ratification, then promote into `entities[]` on stamp. The current `flags[]` section already holds Bucket and MetricSnapshot; that is the correct shape.

- **P-011 (Embedder / Bucketizer / Normalizer reclassification).** PRINCIPLES.md's dual-classification clause is the mechanism. Two ways to satisfy it: declare `Embedder`, `Bucketizer`, `Normalizer` as dually classified at Layer 0 (state) and Layer 6 (operator), with the dual noted in the rationale doc; or split the entities as this proposal does, keeping `BucketStats` and `NormalizerState` at Layer 0 and moving the operators to Layer 6 with `MarketStateToken` covering the Embedder's output. The split is a defensible choice; the type name is not. Record the decision as an entity-list revision in `signals/0.1.json`, not as a proposal.

- **P-012 (Sprint rejection).** Pre-lock, entities the Architect rejects during Step 1 are simply removed. No proposal type. Delete `Sprint` from `signals/0.1.json § entities[]` and note the rejection in the rationale doc's per-layer decisions section.

- **P-013 (MetricSnapshot kit-pattern adoption).** Duplicates the existing `entity_implied_but_unnamed` flag in `signals/0.1.json`. The rationale — "adopting a kit pattern requires explicit Architect stamp" — is right; that stamp is the Architect's inline Step-1 ratification of the existing flag, not a new proposal. Remove from `proposals.json`.

- **P-014 (Bucket ENTITY_IMPLIED_BUT_UNNAMED).** Also duplicates the existing flag in `signals/0.1.json`. `ENTITY_IMPLIED_BUT_UNNAMED` is BOOTSTRAP Step 1's halt condition, not a taxonomy proposal type. Remove from `proposals.json`; leave the flag in place in `0.1.json` for Architect stamp.

- **P-015 (domain-vs-runtime commitment for Step 7).** Not a proposal shape at all. It is a Step-7 commitment. The right home is BLACKBOARD `## Deferred` with a revisit trigger of "Sprint that opens Step 7," or the rationale doc's forward-looking section once written. Remove from `proposals.json`.

## 5. `proposals.json` and `signals/0.1.json` disagree in isolation

`signals/0.1.json § cross_document_polysemy_review.resolved_as_distinct` still contains the old wrong-bucket `Baseline vs Ablation vs Model` entry. P-001 correctly reclassifies it. Nothing in the two files points at the other. A future reader who opens `0.1.json` alone will see the resolution as distinct; a reader who opens `proposals.json` alone will see it as pending merge. The two must agree, and the agreement should be enforced by cross-reference: either the `resolved_as_distinct` entry gets a "superseded by P-001" note, or it gets deleted with a rationale-doc entry explaining the supersession.

Same problem for `Prediction vs Distribution` (P-002) and any other entry that appears in both files with different resolutions.

## 6. One review finding was not translated into a proposal

The prior review's finding 6 named three under-extractions — `Split`, `Session`, `ExperimentConfig` — and finding 3 named runtime-grammar absence. `ExperimentConfig` (P-008) came with a specific commitment: "will need a `CONFIG_RESOLVED` tag with typed payload in Layer 1 and an evidence constraint in Layer 7 for the `lambda_risk`-must-be-present rule." No entry in `proposals.json` carries that forward. When Step 2 opens, the Worker will need to remember it; a `NEW_TAG_PROPOSED` shell keyed to `CONFIG_RESOLVED` opened now (empty, pending Step 2 population) is the discipline that transmits.

The runtime grammar absence is partly addressed by P-009 (`Source`) and by P-011's move of operators to Layer 6. It is not addressed for `IngestionClient` (façade), `AlignmentJoin` (the as-of operator itself, distinct from `AlignedRow` the row it emits), `TrainingLoop`, or `Simulator`. P-015's intent covers this but P-015 is not a proposal. The correct shape is four additional Layer-6-forward `ENTITY_IMPLIED_BUT_UNNAMED` flags on `signals/0.1.json`, each with a Layer 6 note.

## 7. Ratification recommendation

Ratify P-001, P-002, P-003 as filed.

Reject P-004, P-005, P-013, P-014 as duplicative of existing `signals/0.1.json` content or as non-events (distinctness is the default).

Reject P-010's type; refile as one Layer-0 removal (inline) plus two `NEW_TAG_PROPOSED` shells for Layer 1.

Reject P-011's type; refile as an entity-list revision in `signals/0.1.json` (with dual-classification note in the rationale doc).

Reject P-012 as a proposal shape; delete `Sprint` inline in `signals/0.1.json` and note in rationale.

Reject P-015 as a proposal shape; file in BLACKBOARD `## Deferred` and rationale-doc forward section.

Move P-006, P-007, P-008, P-009 from `proposals.json` into `signals/0.1.json § entity_implied_but_unnamed.flags[]` for Step-1 Architect stamp.

Open one Layer-10 grammar-growth proposal — the eighth-to-Nth extension of the proposal-type taxonomy — if the project decides it wants a real `NEW_ENTITY_PROPOSED`, `OPERATOR_RECLASSIFICATION_PROPOSED`, or `POLYSEMY_VERDICT_PROPOSED` type as a first-class kit-level addition. That is the mechanism that promotes what is currently invention into what is discipline.

Reconcile `signals/0.1.json` with the accepted set before Step-2 dispatch, so the two files agree without a reader needing to cross-check them.

The pattern the queue exposes is honest and worth stating plainly: the response to "you invented vocabulary" was to invent meta-vocabulary. The fix is the same at both levels — canonical types, or a stamped extension of the type list, but never both silently.
