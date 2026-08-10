# PRINCIPLES.md — the 11-layer grammar stack and the non-negotiable commitments

*Read this file before populating any vocabulary. The principles below are not configurable; they're what makes the vocabulary compounding across sessions, agents, and project lifecycle. They derive from `foundations/01-signal-driven-development.md`, the manifesto in the SDD canon, and the SDD theory branch that extended the original four foundations with the eleven-layer formulation.*

---

## What a grammar is

In Signal-Driven Development, "grammar" means more than the list of signal tags. The full grammar is an eleven-layer typed schema. Each layer answers a distinct question about the system's signals; together they define what the system can say and what it means.

The vocabulary as casually used — `signals/0.1.json` with its list of tag names and payloads — is Layer 1 (Lexical) plus Layer 2 (Payload) of the eleven. The other nine layers are usually implicit in the project's prose documents (the spec, the ADRs, the working agreement). The simplest kit asks you to make them explicit because the empirical work shows that projects which leave them implicit drift across sessions, while projects which make them explicit hold their grammar stable across many sprints and many architectural rewrites (Trading System being the strongest empirical case).

---

## The 11 layers

In dependency order. Upper layers consume lower; you cannot meaningfully populate Layer 5 before Layer 0.

**Layer 0 — Ontology.** What kinds of things exist in this system? Entities, not events. The nouns the signals operate on. *Katybird examples:* Bird, Katy, Region, Path, Clue, Memory, Premonition, Beat, ApologyLayer, Perch. *Trading System examples:* Episode, Run, Operator, Setup, PriceState, Bar, Sector.

**Layer 1 — Lexical.** What signal tags do those entities admit? The tag names themselves. Uppercase, specific, refactored like a public API. Form: `{ENTITY}_{VERB_PAST_PARTICIPLE}`. *Examples:* `BIRD_HOPPED`, `CLUE_INSPECTED`, `PACKAGE_VALIDATED`, `REC_QUEUED`, `AGENT_HEARD`.

**Layer 2 — Payload.** Per-tag typed fields. What data accompanies each tag at emission? Required vs optional; type per field; foreign-key references to Layer-0 entities. *Examples:* `BIRD_HOPPED.payload = [from, to, ground]`; `CLUE_INSPECTED.payload = [clue_id]`.

**Layer 3 — Session.** Situated event streams. What is a "session" in this system? What is its boundary (start tag, end tag)? What persistent attributes does the session carry that aren't repeated in every tag's payload? *Examples:* Katybird's `SESSION_INIT` → `SESSION_END` with `package_id`, `vocab_version`, `save_slot`; Trading System's `SESSION_STARTED` per market day.

**Layer 4 — Temporal.** Ordering rules with timing. *When* tags fire relative to each other. *Examples:* "every `CLUE_INSPECTED` is followed within 5s by a `CLUE_TEXT_DELIVERED` with matching `clue_id`" (window invariant); "`FRAME_RENDERED` sampled at 4Hz" (cadence invariant).

**Layer 5 — State-Transition.** Which tags can follow which. A directed graph of allowed transitions over Layer 1's tag set. *Examples:* "after `KATY_FOUND`, no further `KATY_GLIMPSED` can fire" (forbidden-after); "`BEAT_REACHED` must precede `BEAT_COMPLETED` for the same beat_id" (pairing-ordering).

**Layer 6 — Runtime / Operator.** *How* the program computed each event — model routes, fallbacks, operator boundaries. Distinct from Layer 0 (what exists) and Layer 1 (what events). *Examples:* Trading System's named operator chain (PriceStateEncoder → SetupKeyComposer → EpisodeRecorder); Audio Object's AudioEngine + MetronomeScheduler; Katybird's BeatScheduler + PathPlanner.

**Layer 7 — Evidence.** What evidence each tag must carry beyond its type signature. Constraints on payload content: tonal constraints on player-facing strings, range constraints on numeric fields, cross-reference constraints (foreign keys must resolve), diagnostic-required for incident-stratum tags.

**Layer 8 — Report.** The Signal Report format the project uses for agent-to-agent (or agent-to-self) handoff. Inherited from `foundations/03-sdd-team-model.md`: Observed / Expected / Delta / Hypothesis with the operational AAR subsections nested. Layer 8 binds the project's tag set into the report template.

**Layer 9 — Version.** Vocabulary versioning. `0.1` lock at the founding act; subsequent versions emerge through the supervised-grammar-evolution proposal taxonomy (Layer 10). Each version carries `version_id`, `locked_at`, `locked_by`, and `prior_version` for migration audit.

**Layer 10 — Grammar-Growth.** Meta-rules for how the grammar may evolve. The supervised-grammar-evolution proposal taxonomy lives here (see below). Most projects inherit the default; some declare project-specific overrides (e.g., "payload extras are documentation-only, not version-bumping" — the Trading System validator-extras pattern).

---

## Dependency structure

Lower layers are populated first because upper layers consume them. The Vocabulary Session walks layers in dependency order: 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7. Layers 8–10 are metadata produced at the end from the project's lock decision plus the methodology-level defaults.

When an upper layer reveals an underspecification in a lower one (e.g., Layer 5 wants to enforce an ordering that references an entity Layer 0 didn't surface), the discipline loops back to the lower layer and proposes the missing element via the appropriate evolution type rather than silently inferring it.

Empirically (across the four projects + the soundfield experience), the upper layers saturate first — that is, Layers 5–7 underspecify more often than Layers 0–2. This is a known pattern from adjacent-literature ontology learning (Cimiano's "layer cake"). Plan for it: Layer 5/6/7 entries in `signals/0.1.json` may be sparser than Layer 1/2 entries; that's fine if the gaps are surfaced as proposals for later evolution.

---

## The non-negotiable commitments

These follow from SDD's first principles (`foundations/05-sdd-manifesto.md` if shipped, otherwise restated here from the four originals). They are what makes the grammar compounding.

**1. The vocabulary is the contract.** Designed before the code. Reviewed like a schema migration. Refactored like a public API. The tag the program emitted last week means the same thing today. Changes are intentional and old names are retired explicitly, never silently. *Why this matters: stability is what makes prior reading (by the agent, by a future session, by a human reviewer) still valid. Without stability, the methodology collapses back into prose-and-inference.*

**2. Schema enforced at the speaker's mouth.** When the program emits a signal, the emit call validates the payload against the locked schema. Out-of-vocabulary tags raise. Malformed payloads raise. The receiver does not negotiate — speaker-side validation is the contract. *Why this matters: validation at ingest is a filter; validation at the mouth is a contract. The kit ships `lib/sdd.py` (foundation 02's 120-line reference) which implements this; projects may implement their own in the project's language using the same discipline.*

**3. Workers cannot invent vocabulary.** When a Worker (or you, the LLM agent, in your Worker role) encounters a need for a new tag, new payload field, new ordering rule, or new invariant, you do not write it into the vocabulary unilaterally. You return a typed proposal via one of the seven (now eight, with v2's ENTITY_MERGE_PROPOSED) evolution types. The Architect ratifies; the vocabulary version bumps. *Why this matters: unilateral invention is the dominant failure mode in adjacent fields (ontology learning, KG construction, schema-from-text). Without supervised evolution, the vocabulary drifts and the grader can't tell silent additions from intentional ones.*

**4. The dual contract.** Every interactive state the program admits gets two contracts: a signal contract (the typed event sequence the runtime emits) and an artifact contract (the structural shape the rendered output must take — files exist with expected content, build commands return expected exit codes, optionally view assertions for UI-touching work). Both must pass for the sprint to close. *Why this matters: the Make The Models Talk Round-2 postmortem documented that components passing isolated tests can ship a mounted system that doesn't render. The dual contract closes that gap. This commitment makes view-state legible to agents the same way signal-state is.*

**5. Stratified emission, no querying.** Tags belong to four strata (event / ambient / summary / incident). Each layer reads down only; no layer queries up. When a layer needs more detail than its summary stratum provides, it calls a bounded drill-down tool, not a query. *Why this matters: querying is description by another name (the lossy step relocated from human prose to model SQL). Stratification keeps the stream legible and the cost bounded.*

**6. Originals over summaries when transmitting between sessions.** When a new session inherits a project, transmit the originals (this kit's foundations, the project's `signals/0.1.json`, the project's `BLACKBOARD.md ## Decisions`) — not your synthesis. Summary-based pattern-matching is the dominant transmission-failure mode. *Why this matters: the v1 → v1.2 prompt-factory trajectory documented this across three versions; each version's failure was a transmission failure that the prior had compressed past.*

**7. The founding act is real work, not setup.** The Vocabulary Session (Sprint 0) produces `signals/0.1.json` and `signals/0.1-rationale.md`. The rationale doc is the load-bearing artifact — without it, the vocabulary cannot be argued back against six months later when a downstream session inherits the project and asks "why is `BIRD_FLIT` separate from `BIRD_HOPPED`?" *Why this matters: Audio Object's grammar was authored without a Vocabulary Session (the methodology didn't exist yet) and has no rationale doc; it works because the methodology emerged from that project. Every subsequent project has had a Vocabulary Session and a rationale doc, and those grammars have held across sprints. The discipline is what compounds.*

---

## The supervised-grammar-evolution proposal taxonomy

When you (the agent in Worker role) encounter a need for vocabulary change, you propose via one of these typed kinds. The Architect ratifies; the vocabulary version bumps; the new version becomes the contract going forward.

- **`NEW_TAG_PROPOSED`** — a candidate tag the locked vocabulary does not contain. Most common.
- **`PAYLOAD_FIELD_PROPOSED`** — a new field for an existing or proposed tag's payload.
- **`SEQUENCE_RULE_PROPOSED`** — a temporal ordering invariant the docs declare but the vocabulary's Layer 4 doesn't yet name.
- **`INVARIANT_PROPOSED`** — a state-transition or value-range invariant for Layer 5 or Layer 7.
- **`TAG_SPLIT_PROPOSED`** — when the same surface term denotes different events in different contexts; the DDD bounded-context move. ("`PAYMENT_DECLINED` in retail-checkout vs `PAYMENT_DECLINED` in subscription-renewal are different events — propose split.")
- **`TAG_MERGE_PROPOSED`** — when two existing tags appear to denote the same event under the current framing. The opposite of split.
- **`TAG_DEPRECATION_PROPOSED`** — when an existing tag has no support in the documents anymore; the system no longer admits the event the tag named.
- **`ENTITY_MERGE_PROPOSED`** — when the same conceptual entity appears under different surface forms across documents (e.g., `the conversation` in PRODUCT.md vs `ConversationSession` in ENGINEERING.md vs `ChatThread` in DESIGN.md). Surfaced for explicit Architect reconciliation rather than silent collapsing.

Every proposal carries:

- The candidate element.
- The source citations that motivated it (which document, which sentence).
- The layer it belongs to.
- A one-sentence rationale derived from the source citation's prose.
- The Architect's ratification stamp (which the Architect adds when they accept).

The proposal goes into the project's `signals/proposals.json` (or a similar file) until the Architect ratifies. Ratification bumps the vocabulary version and the rationale doc gains the new entry.

---

## What "domain grammar" and "runtime grammar" mean

The SDD theory branch distinguishes two grammars that coexist in every project:

- **Domain grammar.** What the system MEANS. Player-facing concepts. The nouns and verbs the product designer or the customer would recognize. Lives mostly in Layers 0–5.
- **Runtime grammar.** What the system COMPUTED. How the program decided each thing — model routes, fallbacks, operator boundaries, latency budgets, error classifications. Lives in Layer 6 (Runtime) and informs Layer 7 (Evidence) and Layer 9 (Version).

Both are typed; both are graded; both share the same dual-contract discipline. The distinction matters because a vocabulary that only describes domain grammar leaves the runtime invisible (and the soundfield project's diary documents what happens then — the mock backend ran for sprints because no runtime signal said "I'm a mock"). The Vocabulary Session asks you to populate both.

---

## What's deliberately NOT in this principles file

- **The full theoretical defense of why signals beat prose.** That's `foundations/01-signal-driven-development.md` and `foundations/05-sdd-manifesto.md` (if shipped). Read them.
- **The implementation of `emit_signal()` at the speaker's mouth.** That's `lib/sdd.py` (foundation 02's reference library) for Python projects; the discipline is independent of language.
- **The dispatch architecture (Workers, Foreman, parallel candidates).** Out of scope; the simplest kit doesn't ship orchestration.
- **How to convert prose specs into the 11-layer grammar automatically.** That's the doc-to-grammar tier specified in `factory-v0/sdd-grammar-from-docs/`; out of the simplest kit's scope. The BOOTSTRAP procedure walks the Architect + agent through it manually.

---

*PRINCIPLES.md. The 11-layer stack. Seven non-negotiable commitments. Eight proposal types. The grammar is the contract; the vocabulary's stability is what makes the methodology compounding.*
