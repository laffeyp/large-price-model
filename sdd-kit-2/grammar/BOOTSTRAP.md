# BOOTSTRAP.md — the Vocabulary Session procedure

*The Vocabulary Session is Sprint 0 of any new SDD project. The human Architect + an LLM agent walk through the steps below together, producing `signals/0.1.json` (the locked vocabulary) and `signals/0.1-rationale.md` (the rationale doc). After this session, no implementation sprint dispatches until both files exist and the Architect has signed off.*

*Read `grammar/PRINCIPLES.md` before running this procedure. For deeper per-layer guidance, worked examples, and the empirical lessons from prior projects, see the predecessor kit's expanded grammar folder at `sdd-kit/grammar/` (the audit-trail-preserving original): `PER_LAYER.md`, `EXAMPLES.md`, `EMPIRICAL.md`. The two-file grammar in `sdd-kit-2/` is the minimal version that supports running the procedure; the expanded versions are reference when needed.*

---

## Inputs

Before starting the session, the Architect should have:

- **A product spec.** What the system is, who it's for, why it exists. Operational language, not marketing.
- **A technical spec** (if applicable). Architecture, components, data flows, runtime decisions, operator boundaries.
- **A design canon** (if the project has UI). Component descriptions, voice canon, design tokens, copy.
- **Prior-project postmortems** (if applicable). Make The Models Talk's Round-2 postmortem is canonical; if the new project's domain overlaps with a prior project, that prior project's vocabulary is reference material.

If any of these are missing or thin, the session will produce a thin vocabulary. The agent should NOT compensate for thin docs by inventing entities or events; instead, the session halts and the Architect improves the docs.

---

## Outputs

At session close, two artifacts exist on disk:

- **`signals/0.1.json`** — the locked vocabulary. Eleven layers populated to the extent the docs support; gaps surfaced as typed proposals in `signals/proposals.json` for future versions.
- **`signals/0.1-rationale.md`** — the rationale document. Per-layer section recording: what was considered, what was rejected, what failure modes were named, which prior-project postmortems informed which choice. The dual-contract audit table appears here.

The Architect signs off on both. v0.1 is locked.

---

## The session structure

Eleven steps walking the layers in dependency order. Plus a sign-off step at the end.

The agent drives each step by reading the relevant docs, populating the relevant layer, surfacing questions and proposals. The Architect answers questions, ratifies proposals, signs off. The session is collaborative; this is the one time natural language is strictly required.

---

## Step 0 — Preflight

**Agent:**

1. Read `sdd-kit-2/foundations/01-signal-driven-development.md`, `sdd-kit-2/foundations/04-sdd-claude-design.md`, and `sdd-kit-2/grammar/PRINCIPLES.md`. (If not already loaded.)
2. Optional reference (if the project's vocabulary is non-trivial): `sdd-kit/grammar/PER_LAYER.md` and `sdd-kit/grammar/EXAMPLES.md` in the predecessor kit. Skim during Steps 1–10 as appropriate.
3. Read the Architect-provided product spec, technical spec, design canon, prior-project postmortems.
4. Write a one-paragraph orientation entry to `BLACKBOARD.md ## Surfaced for review`: "I have read the foundations, the principles, the per-layer guidance, and the examples. I have read the project's inputs at the following paths: [list]. Ready to begin the Vocabulary Session."
5. Wait for Architect "go" before proceeding.

**Architect:**

1. Verify the agent's orientation entry actually names the docs the agent read.
2. Confirm or correct.
3. Say "go" when ready.

---

## Step 1 — Layer 0 (Ontology) — extract entities from the docs

**Agent:**

1. Walk through the docs. For each kind of thing the system tracks state for, propose an entity. Examples: from a checkout spec, propose `Cart`, `Order`, `Payment`, `Inventory`, `User`. From a game spec, propose `Player`, `Region`, `Item`, `Beat`.
2. For each entity: name (PascalCase), one-sentence definition drawn from the docs, source citation (which document, which section, which sentence).
3. Halt the per-entity work if any of:
   - The docs don't name the entity at all but you're tempted to surface it from inference. Halt with `ENTITY_IMPLIED_BUT_UNNAMED`; let the Architect decide.
   - Cross-document polysemy: the same entity appears under different surface forms across docs. Surface as `ENTITY_MERGE_PROPOSED`.
4. Write the entity list to `signals/0.1.json` under a Layer-0 / `ontology` section.

**Architect:**

1. Review the entity list. Add any the agent missed (the agent will under-extract more often than over-extract).
2. Remove any the agent over-extracted.
3. Resolve cross-document polysemy: are these the same entity or different?
4. Say "Layer 0 ready" when satisfied.

---

## Step 2 — Layer 1 (Lexical) — name the tags per entity

**Agent:**

1. For each entity from Layer 0, walk through the docs again. For each observable event involving that entity (each verb the system can do or that can happen to the entity), propose a tag.
2. Tag form: `{ENTITY_SNAKE_UPPER}_{VERB_PAST_PARTICIPLE_UPPER}`. Past tense. Irregular forms handled explicitly (see `BIRD_FLIT` example in EXAMPLES.md).
3. Recognize chain decomposition (see Audio Object's `REC_QUEUED → REC_FIRE → REC_START_NOW` in EXAMPLES). When a domain interaction produces multiple lifecycle events at different observability points, propose multiple tags.
4. For each tag: category (architectural boundary), stratum (event / ambient / summary / incident), one-sentence note describing what the tag means and when it fires.
5. Halt:
   - If a Layer-0 entity classified as load-bearing produces zero tags. The entity may be passive (no observable lifecycle); confirm with the Architect.
   - If a single entity-verb pair decomposes into more than five tags. Over-decomposition likely.
6. Write tags to `signals/0.1.json` under `tags[]`.

**Architect:**

1. Review tag list. Audit for past-tense convention; rename if needed.
2. Audit chains: did the agent over-decompose or under-decompose?
3. Resolve stratum disagreements (the agent might call something `event` when it's actually `summary`).
4. Say "Layer 1 ready" when satisfied.

---

## Step 3 — Layer 2 (Payload) — type the fields per tag

**Agent:**

1. For each tag from Layer 1, walk the docs again. What data does the program need at this emission point? List candidate fields.
2. Per field: name (snake_case), type (string / int / float / bool / enum-with-values / entity-reference), required vs optional. Enum-typed fields list their values explicitly.
3. Apply the universal view-payload convention: every tag with `category: view` automatically gets `payload: [frame, visible, scene_id, layer]`. Add project-specific structural fields per-view-tag as the dual-contract pairings require (see `SCENE_RENDERED.visible_paths` example).
4. Foreign-key resolution: for each `_id` field, identify the Layer-0 entity it references. If no match: either propose a new Layer-0 entity (back-propagate via `ENTITY_IMPLIED_BUT_UNNAMED`) or rename the field.
5. Halt:
   - If a tag's payload is entirely ambiguous (every field surfaces with `requiredness: ambiguous`). The docs don't describe what the tag carries clearly enough.
   - If foreign-key resolution rate is below 70%.
6. Write payloads to `signals/0.1.json` per tag.

**Architect:**

1. Review payloads. Tighten anything ambiguous. Distinguish required from optional. Confirm enum value sets.
2. Decide the validator-extras posture (default: strict; opt-in to Trading System's documentation-only-extras pattern if appropriate). Document in the rationale doc.
3. Say "Layer 2 ready" when satisfied.

---

## Step 4 — Layer 3 (Session) — frame the event streams

**Agent:**

1. Walk the existing tags. Identify boundary candidates (tags whose verb roots are in `{start, init, begin, open, end, close, stop, resume, reset}`). For each, ask: does this open or close a stream of other tags?
2. Per session stratum: name, boundary-open tag, boundary-close tag (or "inferred from timeout / app-exit"), re-entry tag (if applicable), list of framed tags, persistent attributes (from the boundary-open tag's payload).
3. Recognize nesting: a `game_session` may contain many `gameplay_sessions`. Declare the parent-child relationship explicitly.
4. If the docs do not name "session" as a concept and you must construct the abstraction from boundary tags, surface `framing_inferred` in the rationale doc.
5. Halt:
   - No boundary-open candidates. The docs don't describe any session-shaped abstraction. (Rare; usually means single-shot CLI tool.)
   - A boundary-open candidate frames no tags.
6. Write session strata to `signals/0.1.json` under a `sessions[]` array.

**Architect:**

1. Review session strata. Confirm boundary tags. Confirm nesting (if any). Confirm persistent attributes.
2. Say "Layer 3 ready" when satisfied.

---

## Step 5 — Layer 4 (Temporal) — name timing invariants

**Agent:**

1. Walk the docs. Find sentences containing temporal keywords: `within`, `after`, `before`, `every`, `Hz`, `cooldown`, `timeout`, `eventually`, `never`, `at most`, `at least`.
2. For each candidate: kind (window / cadence / cooldown / pairing / forbidden_after / eventually_must), tag(s) involved, duration (if any), payload constraint (if any), source citation.
3. Cross-check ambient-stratum tags from Layer 1: every ambient tag MUST have a cadence invariant. If missing, halt.
4. Halt: cadence missing for any ambient tag. Conflicting invariants.
5. Write invariants to `signals/0.1.json` under a `temporal_invariants[]` array.

**Architect:**

1. Review invariants. Confirm durations (the docs may say "within a few seconds" — the Architect specifies "5s").
2. Catch any invariants the agent missed (the docs may declare timing in prose the keyword filter didn't catch).
3. Say "Layer 4 ready" when satisfied.

---

## Step 6 — Layer 5 (State-Transition) — graph the allowed orderings

**Agent:**

1. Walk the docs for ordering language: `after`, `before`, `precedes`, `follows`, `requires`, `terminal`, `cannot follow`, `must precede`, `next`.
2. For each candidate: kind (allowed_set / forbidden_after / forced_next / terminal / pairing_ordering), from_tag, to_tags_allowed (or to_tags_forbidden), payload_match (if any).
3. Build the transition graph. Check: cycles outside named loop constructs (usually a bug), unreachable tags (one or both endpoints not appearing in any allowed edge), sessions with no reachable terminal.
4. Cross-check with Layer 3 (session boundaries) and Layer 4 (window invariants imply ordered transitions).
5. Halt: unexpected cycles, unreachable tags, sessions with no reachable terminal, rule conflicts.
6. Write transition rules to `signals/0.1.json` under a `state_transitions[]` array.

**Architect:**

1. Review the graph. Confirm terminals are correct. Confirm allowed-sets aren't over-restrictive.
2. Sparseness is OK: not every tag pair needs a rule. Most Layer-5 rules cover the critical paths (pairing, terminal, forbidden_after); the rest is implicit.
3. Say "Layer 5 ready" when satisfied.

---

## Step 7 — Layer 6 (Runtime / Operator) — name the operators

**Agent:**

1. Read the technical spec. Identify named subsystems via section headings, code-block class/struct/type definitions, architecture tables.
2. Per operator: name, responsibilities (one paragraph), which tags it emits (cross-reference to Layer 1), which tags it consumes, model route (if LLM-based), fallback chain (if applicable), performance constraints.
3. Recognize dual classification: an entity at Layer 0 may also be an operator at Layer 6 (Katybird's `Bird` is both). Declare both classifications.
4. Halt: operator count exceeds tag count (over-decomposition); tags with no emitting operator.
5. Write operators to `signals/0.1.json` under an `operators[]` array.

**Architect:**

1. Review operators. Confirm boundaries align with the technical spec's architecture.
2. Resolve dual-classification cases. Document in the rationale doc.
3. Say "Layer 6 ready" when satisfied.

---

## Step 8 — Layer 7 (Evidence) — declare payload constraints

**Agent:**

1. Read the design canon's voice/copy guides (if applicable). Extract `TonalRule` records — what tonal constraints apply to player-facing strings? Bind them to relevant payload fields (those of type `string` likely to contain user-visible content).
2. Walk the product and technical specs for numeric ranges and cross-reference assertions. Per constraint: kind, target tag, target field, constraint spec, source citation, enforceability (`mechanical | llm_check | manual_review`).
3. Apply stratum-specific evidence requirements: incident-stratum tags need diagnostic-required Evidence; summary-stratum tags need outcome-required Evidence; view-category tags need structural Evidence (covered by Layer 2's universal view payload).
4. Halt: incident tag with no diagnostic constraint; tonal rule with no bound fields; cross-reference constraint pointing at an unresolved foreign key.
5. Write constraints to `signals/0.1.json` under an `evidence_constraints[]` array.

**Architect:**

1. Review constraints. Resolve enforceability (which can the grader auto-check; which need LLM checks; which need human review).
2. Say "Layer 7 ready" when satisfied.

---

## Step 9 — Dual-Contract Audit

**Agent:**

1. Walk every behavior-category tag from Layer 1. For each, pair it with one of:
   - A view-category tag (e.g., `WORLD_PATH_UNLOCKED` ↔ `SCENE_RENDERED.visible_paths`).
   - A structural payload field on an existing view tag (e.g., `APOLOGY_LAYER_ADDED` ↔ `HUD_RENDERED.apology_layers_present`).
   - A typed gap-proposal naming what the artifact-side substrate should be (e.g., `DUAL_CONTRACT_PAIRING_GAP: KATY_GLIMPSED needs dedicated view tag because narrative weight is high`).
2. Write the audit table to the rationale doc as a section with three columns: behavior tag, view-side counterpart (tag or field), notes.
3. For each gap-proposal: surface to BLACKBOARD `## Surfaced for review` for the Architect to ratify.

**Architect:**

1. Review the audit table. For each gap, decide: add a dedicated view tag, add a structural payload field to an existing view tag, or accept the gap (declare the behavior tag has no view-side counterpart — rare; document why).
2. Ratify or revise. The agent re-runs the audit if the Architect ratifies new view tags or fields.
3. Say "Dual-contract audit closed" when satisfied.

---

## Step 10 — Synthesize Layers 8–10

These layers are mostly inherited; the agent emits them deterministically.

**Agent:**

1. Layer 8 (Report): bind the project's tag set into the Signal Report template per `templates/SIGNAL_REPORT.md`. Behavior tags → OBSERVED/EXPECTED; view tags → RENDERED; incident tags → NOTES; proposals → GRAMMAR_DRIFT. Write the binding to `signals/0.1.json` under a `report_binding` object.
2. Layer 9 (Version): emit lock metadata. `{version_id: "0.1", locked_at: $NOW, locked_by: "Architect via Vocabulary Session, $DATE", prior_version: null, migration_proposals: []}`.
3. Layer 10 (Grammar-Growth): reference the proposal taxonomy version and declare any project-specific overrides (e.g., validator-extras posture). Default: `{grammar_growth_taxonomy_version: "0.1", project_overrides: []}`.

**Architect:**

1. Review version metadata. Confirm.
2. Say "Layers 8-10 ready" when satisfied.

---

## Step 11 — Write the rationale doc

**Agent:**

1. Compose `signals/0.1-rationale.md`. Sections, in order:
   - **Intent and scope.** What this vocabulary is for; what project it belongs to; what its bounds are.
   - **Per-layer decisions.** One section per Layer 0–7. For each layer: what was populated, what was considered and rejected, what gaps were left as proposals, which source documents informed which choices, which prior-project postmortems were consulted.
   - **Dual-contract audit table.** The table produced in Step 9, with rationale for each gap-resolution choice.
   - **Project-specific overrides.** Validator-extras posture, view-payload convention overrides (if any), category-set deviations from common patterns.
   - **Open proposals for v0.2.** Typed proposals (per the eight evolution kinds) that the docs forced but v0.1 did not adopt. The Architect will ratify or reject these during the project's lifetime.
   - **Signatures.** The Architect's name + date.

**Architect:**

1. Read the rationale doc. Confirm it's defensible — if someone six months from now asks "why is `BIRD_FLIT` separate from `BIRD_HOPPED`?" the rationale should answer.
2. Sign at the bottom.
3. Lock `signals/0.1.json` (file becomes read-only by convention until ratified version bump).

---

## Step 12 — Sign-off

**Agent + Architect together:**

1. Verify both files exist on disk.
2. Verify `signals/0.1.json` parses as JSON.
3. Verify the rationale doc has a signature.
4. Write the close entry to BLACKBOARD `## Built`: "Sprint 0 (Vocabulary Session) closed. signals/0.1.json + signals/0.1-rationale.md authored. v0.1 locked. Ready for Sprint 1."
5. The next sprint is Sprint 1 of regular implementation work.

---

## Anti-patterns to watch for

The empirical baseline and the soundfield experience surface these patterns. The agent and Architect both watch for them throughout the session.

- **Fabricating to avoid halting.** When the docs underspecify a layer, the temptation is to invent rather than halt. Don't. Halt with the typed reason; the Architect improves the docs; the session resumes.
- **Skipping the rationale doc.** Without it, the vocabulary is undefendable six months later. Audio Object proves the methodology can work without one only because the project IS where the methodology emerged; every other project must produce one.
- **Compressing the session for speed.** The Vocabulary Session is the founding act. A two-hour session producing a defendable v0.1 saves dozens of sprints of downstream rework. A 30-minute session producing a vague v0.1 costs them.
- **Architect ratifying without reading.** The rationale doc is for the Architect's defense in the future. The Architect ratifies what they can defend, not what the agent emits.
- **Treating v0.1 as a draft.** v0.1 is locked. Changes go through the proposal taxonomy and bump the version (v0.2). "Just edit the JSON" is the silent-drift failure mode that breaks every project's vocabulary stability.
- **Vocabulary materialized after implementation starts.** The soundfield project did this; the 60 sprints prior to vocabulary materialization carried Logger-instead-of-signal drift that took 6 cleanup sprints to repair. Vocabulary is Sprint 0; no implementation sprint dispatches until the lock is signed.

---

## Estimated time

For a project with moderate-complexity specs (~50-100 pages total across product + technical + design):

- Steps 0-2 (Preflight + Layers 0-1): 30-45 minutes.
- Steps 3-5 (Layers 2-4): 45-60 minutes.
- Steps 6-7 (Layers 5-6): 30-45 minutes.
- Step 8 (Layer 7): 15-30 minutes.
- Step 9 (Dual-contract audit): 15-30 minutes.
- Steps 10-12 (Layers 8-10 + rationale + sign-off): 20-30 minutes.

Total: 2.5 – 4 hours of Architect-and-agent collaborative work. Producing `signals/0.1.json` (50-100 tags, 9-15 categories, 4 strata, 5-15 temporal invariants, 10-30 state-transition rules, 5-12 operators, 10-25 evidence constraints) + a 2,000-5,000-word rationale doc.

The session is one of the most leveraged work blocks in the project's lifetime. Treat it accordingly.

---

*BOOTSTRAP.md. The 12-step Vocabulary Session procedure. Sprint 0 of any new SDD project. Outputs: signals/0.1.json + signals/0.1-rationale.md. No implementation sprint dispatches until the lock is signed.*
