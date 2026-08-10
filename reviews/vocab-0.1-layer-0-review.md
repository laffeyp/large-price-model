# Layer-0 review — signals/0.1.json (v0.1, in progress)

**Reviewer:** Claude Code (Opus 4.7), acting in Agent role.
**Date:** 2026-08-09.
**Scope:** `signals/0.1.json` Layer 0 (ontology) — the 31-entity extraction filed at BLACKBOARD entry `VOCABULARY_SESSION_STEP_1 close`.
**Frame:** `sdd-kit-2/grammar/PRINCIPLES.md` (11-layer stack, seven commitments, eight proposal types) and `sdd-kit-2/grammar/BOOTSTRAP.md` (12-step Vocabulary Session).
**Recommendation:** Do not sign "Layer 0 ready." Return the specific proposals in §11 to the Worker; re-run Step 1.

---

## 1. A silent merge is filed under `resolved_as_distinct`

The `cross_document_polysemy_review` lists `Baseline vs Ablation vs Model` and states the resolution as "distinct at Layer 6 but a single entity `Model` at Layer 0 — distinguished by an attribute (`run_kind`) on the TrainingRun." That is an `ENTITY_MERGE_PROPOSED` executed by the Worker and filed under the label that means "no merge happened." BOOTSTRAP Step 1 halts on ENTITY_MERGE candidates; this one did not halt, because the Worker put it in the wrong bucket. The Architect never gets the ratification prompt the discipline requires.

The pattern violates PRINCIPLES.md commitment #3 directly: workers cannot invent vocabulary. Merging two source terms under a third and inventing `run_kind` as the reconciler is invention. The resolution may well be right; the path to it violates the contract.

## 2. Fabricating-to-avoid-halting appears twice more

BOOTSTRAP's anti-patterns section names "fabricating to avoid halting" first. Two further instances live in this Layer 0.

`Prediction vs Distribution` is listed as "same entity, name `Prediction`" with no citation and no proposal type. `Distribution` in the docs is a noun the simulator consumes (`p[t] ∈ ℝ^V`, `variance(p)`, sharpness); `Prediction` is the model's output object. Whether they collapse is a real question. The Worker answered it in one sentence, in the JSON, without proposing.

`Symbol vs Channel` is resolved with a category assertion — "QQQ is a Symbol that lives in the market_context Channel" — that appears nowhere in either spec. That is the Worker's synthesis, plausible and probably correct, and again typed as a distinct resolution rather than proposed.

Both belong in `signals/proposals.json` awaiting Architect stamp. Neither is there.

## 3. Domain grammar covered; runtime grammar absent

Every one of the 31 entities is a domain noun — data objects, evaluation objects, frozen artifacts. Zero name the runtime: no fallback chain from `mcp_av` to `polygon`, no `IngestionClient` façade, no `TrainingLoop`, no `Simulator` operator, no `AlignmentJoin` — the operator that runs the as-of join whose failure mode is the primary invariant of the whole system.

PRINCIPLES.md names the failure mode directly in the domain-vs-runtime section: "a vocabulary that only describes domain grammar leaves the runtime invisible… the soundfield project's diary documents what happens then — the mock backend ran for sprints because no runtime signal said 'I'm a mock'." This project's Alpha-Vantage-vs-Polygon fallback, the cache-hit-vs-network paths in `IngestionClient`, the vendor-latency estimates that produce `known_at`, the bf16 autocast, the deterministic-CUBLAS flag — all runtime, all invisible in this Layer 0.

Step 7 (Layer 6) will discover the absence. It will discover it at a point when Layer 0 is locked and the operator entries have to reference nouns that do not exist.

## 4. Layer 6 operators are living in Layer 0

`Embedder`, `Bucketizer`, `Normalizer` are `nn.Module` subclasses that compute state. Their frozen output — `bucket_stats.json`, `normalizers.pt` — is the durable noun the pipeline downstream reads. PRINCIPLES.md permits dual classification with a Katybird `Bird` precedent, but requires the dual to be *declared* in the rationale. The rationale file does not exist yet; the JSON declares Layer-0 residency alone.

Two effects follow. The Architect's Step-1 review sees three "entities" that are really operators and cannot easily reject them without seeming to reject the pipeline stages they name. And Step 7 arrives with those slots pre-filled from Layer 0, which is exactly the shape that lets the runtime layer stay thin.

## 5. `Sprint` is a category error at Layer 0

PRINCIPLES.md: Layer 0 is "the nouns the signals operate on." The system's signals fire during ingestion, alignment, training, simulation. They do not fire *about* the process that authored the code. `Sprint` is a noun of `AGENTS.md`, not of the running program. Its inclusion is the Worker importing the kit's process vocabulary into the project's domain vocabulary — a violation of commitment #6 (originals over summaries) at the source-selection stage: the Worker treated `AGENTS.md` as an ontology source when the kit itself says it is a working agreement.

The soundfield-style test: delete `Sprint` from `signals/0.1.json`, and no tag in Layer 1 can lose its referent and no evidence constraint in Layer 7 can dangle. That is the test for whether an entity belongs at Layer 0.

## 6. The under-extractions Step 1 predicts the Architect must catch

BOOTSTRAP: "the agent will under-extract more often than over-extract." Three the Architect should surface:

- **`Split`.** Invariant #2 ("time-based splits with embargo") makes `Split` the load-bearing evaluation-side noun. `TestLook` names the guard; `Split` names the thing guarded. `build_split_mask` in §9.2 takes it as an argument. Not in Layer 0.
- **`Session`** (the RTH trading session). Step-0 preflight surfaced it; Step 1 dropped it. `SessionBoundary` is included; the thing being bounded is not. `is_overnight_gap`, the 26-bar count, and the FOMC/CPI diagnostic bars all reference it.
- **`ExperimentConfig`.** §11.3: "A run without an explicit `lambda_risk` in its resolved config fails registration." The resolved YAML is a first-class artifact with a Pydantic validator at the speaker's mouth (commitment #2). It is not `TrainingRun` — one config seeds many runs — and it will need a `CONFIG_RESOLVED` tag with typed payload in Layer 1.

## 7. `IngestionCall` is an event, not an entity

Per PRINCIPLES.md's Layer-0 definition — "Entities, not events" — "a cached vendor request" is activity. The output of the activity (`RawObservation`) is the noun. `IngestionCall` will resurface at Step 2 as `INGESTION_CALL_ISSUED` / `INGESTION_CALL_CACHED` — probably an ambient-stratum pair — and its Layer-0 seat needs to be given back.

## 8. The two implied-but-unnamed flags carry different weight

`Bucket` is implied by the schema of `bucket_stats.json` and by prose that names it ("bucket 0", "bucket 31"). Its motivation lives inside the project's specs. Ratify.

`MetricSnapshot` is imported from `TECHNIQUES.md §2`. That is a kit reference doc, not a project source. BOOTSTRAP Step 1 halts on `ENTITY_IMPLIED_BUT_UNNAMED` "when the docs don't name the entity at all but you're tempted to surface it from inference." The Worker was tempted by a kit pattern and surfaced it under project-source discipline. Reject, or accept explicitly on the ground that the kit pattern is being adopted — but do not accept implicitly through a flag.

## 9. Over-decomposition of the cost model

`SpreadCalibration` and `KappaCalibration` are two entities for one Layer-6 operator (the calibration scripts) writing to one directory (`artifacts/cost_calibration/`) that the simulator reads as one precondition ("required at simulator startup — hard fail"). One `CostCalibration` entity with two component fits matches the docs' lifecycle grouping and shortens the foreign-key graph Step 3 (Layer 2) will have to trace.

## 10. What this Layer 0 will do to Layers 1–7

- **Layer 1** will inherit the Baseline/Ablation collapse and lose the tag-level distinction between `BASELINE_TRAINED` and `MODEL_TRAINED`, which are different events on the simulator side.
- **Layer 4** will have no ambient-stratum home for the ingestion cadence tags that `IngestionCall` should have seeded.
- **Layer 5** has nothing to say about the `Split → TrainingRun → Checkpoint → TestLook` state-transition chain because `Split` is absent.
- **Layer 6** will be starved because its natural entries (`Embedder`, `Bucketizer`, `Normalizer`) have been consumed by Layer 0 and its ingestion operators were never proposed.
- **Layer 7** cannot bind a "no test-look reads on non-test data" invariant to a `Split` entity that does not exist.

The empirical pattern PRINCIPLES.md names — "upper layers saturate first" — will be amplified by this Layer 0's specific under-extractions rather than mitigated by them.

## 11. Ratification recommendation

Do not sign "Layer 0 ready." Return the following to the Worker as typed proposals, then re-run Step 1:

- One `ENTITY_MERGE_PROPOSED` for `Baseline / Ablation → Model`, with the `run_kind` discriminator named as a Layer-2 payload proposal awaiting Step 3.
- One `ENTITY_MERGE_PROPOSED` for `Prediction / Distribution → Prediction`.
- One `TAG_SPLIT_PROPOSED`-shaped note that `IngestionCall` is moving from Layer 0 to Layer 1 as two tags.
- Three `ENTITY_IMPLIED_BUT_UNNAMED` additions: `Split`, `Session`, `ExperimentConfig`.
- One `ENTITY_MERGE_PROPOSED` for `SpreadCalibration + KappaCalibration → CostCalibration`.
- One rejection of `Sprint` at Layer 0 on category grounds.
- One dual-classification declaration for `Embedder / Bucketizer / Normalizer` — Layer 0 (frozen state) plus Layer 6 (operator) — or a move to Layer 6 with Layer-0 slots for `BucketStats` and `NormalizerState`.
- One rationale-file entry explaining the domain-only shape of the current draft and committing Step 7 to populate the runtime grammar rather than paper over its absence.

The founding act is real work (commitment #7). This draft is a first pass with the discipline violations that a first pass produces. The next pass makes it a contract.
