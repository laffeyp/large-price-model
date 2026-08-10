# TECHNIQUES.md — comprehensive catalog of named development techniques

*A reference. Consult when authoring something whose discipline you don't already have in mind. The point is: don't reinvent the wheel. Across the four originals + soundfield + every kit revision since, these are the named practices that have earned their place. The catalog lives here so a Tier-1 LLM agent and a human Architect, working from this kit, have access to the accreted know-how instead of re-deriving it sprint by sprint.*

*Not gated. Not required reading per sprint. Skim once early in a project to form a mental map; then dip into the relevant section when relevant. The originals applied many of these techniques without a catalog — by inheritance from earlier projects, in the heads of the human Architect. The catalog makes the inheritance explicit so the kit's discipline doesn't depend on having practiced the predecessors.*

---

## How to use this file

- **At project start.** Skim Section 1 (universal). Skim the Section 2 subsection(s) matching your project's class(es). The point is to know what's here so you can find it later.
- **When composing a sprint.** If the sprint touches a discipline you're not sure how to handle, look here first. If the technique exists, follow it. If it doesn't and you've found a real gap, write a KIT_DIARY entry — that's how this catalog grows.
- **When the kit is being maintained.** New techniques surfaced by projects go to KIT_DIARY first; back-propagated upstream into this catalog when they stabilize across projects.

---

## Section 1 — Universal techniques

Apply across greenfield projects regardless of class. Grouped by problem domain.

### The kit as process, not prompt — the mechanism behind everything below

**0. Process not prompt — the four mechanisms behind why the kit's structure works.** The kit's value isn't in any one artifact; it's in the sustained, structured sequence — read working agreement → write comprehension affirmation → lock vocabulary → execute sprint → emit Signal Report → run Rubber Duck Pass → merge to BLACKBOARD → repeat. The mechanism is not that the model "learns" or "internalizes" — LLMs are stateless across sessions, weights don't update, there's no commitment-style consistency (the persona-consistency literature shows models drift from stated commitments without active reinforcement). The mechanism is four compounding effects, in descending order of evidence strength:

1. **Serial compute.** Multi-step structures literally extend the computational depth available to a fixed-depth transformer. Constant-depth transformers without intermediate tokens are bounded to TC⁰; with T intermediate tokens, the same transformer can express any function computable by a circuit of size T (Merrill & Sabharwal 2024, *The Expressive Power of Transformers with Chain of Thought*; Li et al. 2024, *Chain of Thought Empowers Transformers to Solve Inherently Serial Problems*). Sprint structure, intermediate signal emissions, and rubber-duck narration all add serial tokens the model computes over. This is the load-bearing theoretical result.

2. **Attendable intermediate state in-window.** Articulated content (the vocabulary file, the working agreement, the comprehension affirmation, the Signal Report) sits in the context window where attention reads it. Subsequent generation is conditioned on it. The "in your own words" requirement for the COMPREHENSION_AFFIRMATION is doing real work via this mechanism — articulation forces tokens into the window that wouldn't otherwise be there (Olsson et al. 2022, *In-context Learning and Induction Heads*; persona-vector work from Chen et al. 2025). Caveat: this is a property of the current context window, not a persistent property of the model.

3. **Externalized artifacts that survive context-window degradation.** The BLACKBOARD, the KIT_DIARY, the locked vocabulary, the Signal Reports — these persist across sessions. The next session reconstructs the relevant slice cheaply via selective retrieval, placing it at high-attention positions (early or late in the context). This addresses lost-in-the-middle degradation (Liu et al. 2024, *Lost in the Middle*) and context rot, both well-established empirically. Externalization beats long-context conversation because long context degrades; selective retrieval into a fresh window doesn't.

4. **Task-recognition priming via in-context learning.** Worked examples (like `example/`), vocabulary locks, and tone canons don't teach the model anything new — they tell the model *which already-learned capability to activate* (Brown et al. 2020, GPT-3 paper; Xie et al. 2021, *An Explanation of In-context Learning as Implicit Bayesian Inference*). The kit's vocabulary lock and the example project are doing ICL task-selection work.

**What this means in practice.** Each kit artifact maps onto one or more of these mechanisms. The comprehension affirmation does (1) and (2). The locked vocabulary does (3) and (4). The Rubber Duck Pass does (1) and depends on (5) below. The BLACKBOARD and KIT_DIARY do (3). The TECHNIQUES catalog and the worked example do (4).

**5. Self-grading needs external check surface; pure intrinsic critique is contested.** Huang et al. (2023, ICLR'24, *Large Language Models Cannot Self-Correct Reasoning Yet*) and Tyen et al. (2023, *LLMs cannot find reasoning errors, but can correct them given the error location*) show that without external feedback, models often *degrade* on reasoning after self-correction; the bottleneck is error *detection*, not error *fixing*. The kit's Rubber Duck Pass is defensible because it has external check surfaces: the locked vocabulary (parity check), the dual contract (artifact + signal assertions), the observation contract (post-grade behavior verification). A Rubber Duck Pass without these grounding surfaces would be pure intrinsic self-critique — much weaker, and possibly degrading.

**6. Faithfulness caveat.** CoT and Signal Reports are not faithful traces of the model's "actual reasoning" (Lanham et al. 2023, Anthropic — perturbing CoT often doesn't change the answer). They're useful as compute-on-paper (mechanism #1), as audit surface (mechanism #3), and as priming for downstream generation (mechanism #2). They should NOT be read as "what the model thought." This matters for the Rubber Duck Pass: it's a structured externalization that does useful work via the four mechanisms; it's not a window into the model's mind.

**What this technique explicitly drops.** The kit does NOT depend on: the model "internalizing" anything (it doesn't — weights are static); a Cialdini-style commitment effect (persona-consistency literature suggests models drift from stated positions, not commit to them); a "substrate thickening over time" (there is no substrate; only artifacts accumulating); or a "different relationship between session 30 LLM and session 1 LLM" (same model, different conditioning). Phrasings that import human-cognition mechanism are evocative metaphors at best, mistaken at worst. The four-mechanism framing replaces them.

**Sources.** See `process-not-prompt-research.md` (sibling to this file) for full citations and verdict-by-phrase table. Open empirical questions worth investigating are listed there in §6.

---

### Vocabulary and contracts

**1. The vocabulary is the contract.** A signal vocabulary is a typed list of the events the system admits it knows about, the categories those events belong to, and the payload each one carries. Designed before the code. Reviewed like a schema migration. Refactored like a public API. Changes rarely; when it changes, old names retired explicitly. Lives in `foundations/01-signal-driven-development.md` + `grammar/PRINCIPLES.md`.

**2. Schema enforced at the speaker's mouth (poka-yoke).** When the program emits a signal, the emit call validates the payload against the locked schema. Out-of-vocabulary tags raise. Malformed payloads raise. The receiver does not negotiate. Lives in `grammar/PRINCIPLES.md` commitment 2; `lib/sdd.py` implements it for Python.

**3. Workers cannot invent vocabulary.** When the Agent encounters a need for a new tag, payload field, ordering rule, or invariant, return a typed proposal via the supervised-grammar-evolution taxonomy (eight types listed in `grammar/PRINCIPLES.md`). The Architect ratifies; vocabulary version bumps.

**4. Tags as stable identifiers.** Uppercase. Specific. Refactored like a public API. `RECORD_ARM_REJECTED` is better than `"recorder: couldn't arm because [...]"`. A tag the program emitted last week means the same thing today.

**5. Categories as architectural decomposition.** Categories are coarse-grained subsystem groupings. They align with architectural boundaries, NOT class names or file paths. Trading System's 15 categories align with pipeline stages, not modules.

**6. Payloads minimal but complete.** Required fields are exactly enough to reconstruct the decision. Not everything — what reconstructs the choice. Over-payloading bloats the trace; under-payloading makes the trace un-replayable.

**7. Stratified emission with no querying.** Tags belong to event / ambient / summary / incident strata. Each layer reads down only; no layer queries up. Drill-down is a bounded tool, not a query.

**8. Stability contract.** Vocabulary changes via the eight proposal types; never silent. Old names retired explicitly with a deprecation entry.

**9. SESSION_INIT pattern.** First signal in any capture declares starting state — mode, fixture, vocabulary version, seed. Every subsequent signal interpretable relative to this baseline.

**10. View-payload-universal convention.** Every view-category tag's payload includes `frame`, `visible`, `scene_id`, `layer` (or domain equivalents). Lets a Monitoring Agent reconstruct visual state without per-tag parsers.

**11. Validator-extras posture is explicit.** Whether payload extras (fields not in the schema) are documentation-only (Trading System pattern) or strict (Katybird pattern) is a per-project choice declared at the founding act and documented in the rationale doc.

### Sprint shape and dispatch

**12. Sprint sweet spot ≤2 files / one concept.** Empirically (across soundfield's 130 sprints), the Agent's effective sprint scope tops out at ~2 files / one concept. Cross-cutting refactors split into a chain. Bigger sprints fail unpredictably. AGENTS.md hard rule 6.

**13. Plan-mode-per-sprint vs auto-within-phase.** Architecture-band sprints (establishing contracts, types, module boundaries) run plan-mode (Architect reviews before dispatch). Functional-band sprints (filling logic against established contracts) often run auto-band.

**14. Pass-kind drives sprint shape.** Sprint card frontmatter declares `pass_kind: architecture | functional | docs | bridge | observation`. Each kind has different review depth, context-file defaults, success criteria.

**15. Wave 0 carry / pre-filled contract files.** Sprints touching shared contract files (type definitions consumed by many subsystems) open with a Wave 0 sprint that pre-fills canonical shapes; subsequent parallel sprints merge against it. Trading System ADR-019 origin.

**16. N.INT integration sprints at wave boundaries.** Every wave (group of related sprints) ends with `N.INT` asserting everything in the wave is mounted, wired, visible end-to-end. Integration sprint is the wave's proof-point. MMT Round-3 origin: AgentPaneView in MMT Round-2 was nobody's mounting deliverable.

**17. Chain-of-small-sprints over one-big-sprint.** When a refactor spans 5+ files, split into 3-5 chained sprints, each ≤2 files. Each sprint closes clean before the next dispatches. Halt at each boundary to surface anomalies.

### Coordination and shared state

**18. Single-writer-per-section BLACKBOARD.** Seven sections, single-writer per section. Architect-only: `## Decisions`. Agent-only: `## Built`. Agent-maintains: `## Drift watchlist`, `## Sprint tail`. Anyone may append: `## Deferred`, `## Open questions`. Both write `## Surfaced for review`. Discipline, not code-enforced.

**19. Architect Decisions ground subsequent sprints.** The Agent reads `BLACKBOARD.md ## Decisions` at every session start. Decisions written there become the ground truth shaping every subsequent sprint card's scope. When the Architect's intent shifts, they write a new Decision; the Agent re-reads.

**20. Compaction via Sprint tail rollups.** `## Sprint tail` holds the last 10 sprint closes; older entries roll forward into `## Built` as compressed paragraphs. Prevents BLACKBOARD growth from blowing past the agent's session-context budget.

**21. Integration-manager workflow.** The Agent doesn't auto-commit to git. The Architect reviews diffs and commits. (Some projects deviate with per-sprint silent commits via a wrapper script; that's an exception for solo-Architect cadence.)

**22. Canonical home registry.** `WORKING_AGREEMENT.md` declares which file owns which public type. The Agent consults before authoring. Without this registry, multi-sprint sequences thrash by silently re-declaring types across files. Soundfield BLACKBOARD Decision 138 origin.

### Grading

**23. Dual contract.** Every sprint has signal AND artifact contracts. Both must pass for the sprint to close. Folded into AGENTS.md.

**24. Observation contract for behavior-touching sprints.** When a sprint changes product behavior (UI, audio, model loading, replay), the sprint card MUST include `## observation contract` enumerating: UI driving steps, expected log substrings, expected runtime signals, expected screenshot regions. Content assertions don't cover product behavior. Soundfield round-23 origin.

**25. Dual-contract audit table at Vocabulary Session close.** During the Vocabulary Session, walk every behavior-category tag and pair it with either a view-category tag, a structural payload field on an existing view tag, or a typed gap-proposal. Make pairings explicit in the rationale doc. Lives in `grammar/BOOTSTRAP.md`.

**26. Rubber Duck Pass at every sprint close.** Three steps: sequence narration (mechanical) → six-category taxonomic observation → four-state bounded disposition. State-over-Tokens externalization. Catches what the dual contract misses. Folded into AGENTS.md.

**27. Content assertions over command exit codes when the verifier is faster than the build.** A `grep -q 'def encode_price_state' src/...` runs in milliseconds; a full `pytest` takes seconds-to-minutes. For sprints where the artifact's shape matters more than its runtime behavior, prefer cheap content assertions to expensive build runs.

### Error handling

**28. Halt-and-articulate.** When uncertain, surface to `BLACKBOARD.md ## Surfaced for review` with typed reason; do not silently decide. BLACKBOARD entries are cheap; bad assumptions are expensive. AGENTS.md hard rule 4.

**29. Reverse cascade for typed errors.** The Agent returns typed status from sprint work: `complete | needs-review | blocked | failed | vocabulary-change-required`. Every error has a typed upward path; nothing fails silently.

**30. Hand-author requires explicit human authorization.** If iteration repeatedly fails (or the sprint's shape is too uncertain for any candidate to land), the Agent does NOT silently switch into hand-author-bypass mode. Surface to the Architect: what was attempted, why each failed, what would unblock. Only on explicit "hand author" does the Agent proceed. AGENTS.md hard rule 10.

**31. Comprehension-as-prerequisite.** First session in a project, write a COMPREHENSION_AFFIRMATION to `BLACKBOARD.md ## Surfaced for review`. The Architect ratifies before the first sprint dispatches. AGENTS.md hard rule 5.

**32. Bridge mapping before bridge sprint.** Sprints with `pass_kind: bridge` (integrate an external SDK) require a bridge-mapping entry in `WORKING_AGREEMENT.md` first. Halt with `bridge_mapping_required` if missing.

### Memory and compaction

**33. Originals over summaries.** When transmitting context to a new session, transmit the originals (foundations, AGENTS.md, this file, project's locked vocabulary, BLACKBOARD's Decisions) — not summaries. Summary-based pattern-matching is the dominant transmission-failure mode. AGENTS.md hard rule 11.

**34. Diary discipline.** Per sprint or per phase, write a `KIT_DIARY.md` entry: what worked, what got in the way, what this says about the next kit version. The diary is the project's accumulating memory about how the kit serves the work. Soundfield's ~130 numbered v2-kit findings are the canonical example.

**35. Hypothesis tracking in the diary.** Per project, maintain a hypothesis table. Each hypothesis gets `confirmed | falsified | partially` markers as evidence accumulates.

**36. Round-N versioning for documents.** Never edit originals. New thinking lands in `<docname>/round-N.<ext>` or `<thing>-2/`. The audit trail is the work. (User-corrected rule, applies to all artifacts in the user's projects.)

**37. No deletions.** Restructures land in new files / folders / round-N versions. Even ceremony files that look dead stay in place. The audit trail is what makes lessons compoundable.

### Testing and validation

**38. Test fixtures from confirmed-good captures.** A confirmed-good signal capture becomes a regression fixture. `assert_signal(tag, **partial_payload)` and `assert_no_signal(tag)` (per the test-primitive pattern from foundation 02) make the test suite a library of actual captures, not hand-written mocks of imagined behavior.

**39. Empirical-testing dimensions reported separately.** Quality, speed, cost, reliability, recovery, handoff, concurrency. Reporting them jointly hides tradeoffs. Use SWE-bench Verified or a similar industry benchmark as carrier when comparing approaches.

**40. Fidelity test pattern.** Same model, same task. Arm A: prose-only context. Arm B: signal-capture-based context. Measure resolution-rate lift. The cleanest way to show the discipline's value.

**41. Cautions when running empirical tests.** Cherry-picking (pre-register the task set). Vocabulary tax (vocab-authoring time is part of the cost). Strawman control (compare against realistic prose practice, not deliberately weak prose). Operator skill (same agent run by different humans → different results). Training-data contamination (model may have seen the task). Vocabulary leak (don't include the tag list in the prose arm by mistake).

**42. Three judgment layers.** Deterministic (convergence, sequence match, tests pass). Signal-coverage (a Monitoring Agent reads DELTA between expected and observed signals). LLM-as-judge (pairwise comparison, randomized order, length-normalized, judge-family disjoint from generator-family, Bradley-Terry scoring).

### Refactoring and revision

**43. Refactor as chain of behavior-preserving sprints.** A refactor's contract: same dual-contract outcomes before and after. Each sprint in the chain closes with the project's existing observation contract passing unchanged.

**44. SEARCH/REPLACE edits preserve accreted detail.** Use the Edit tool's SEARCH/REPLACE semantics rather than full-file rewrites. Workers given "rewrite this file" scope drop accreted detail prior sprints had earned. AGENTS.md hard rule 7.

**45. Deprecation entries instead of removals.** When a tag, function, or type is retired, the vocabulary or canonical home registry gets a deprecation entry naming the replacement, not a removal. Old code that emits the deprecated tag still parses; new code uses the replacement.

### LLM-and-AI-tool integration

**46. External SDK bridge mapping.** When the project authors code importing an external SDK (LLM library, audio framework, HTTP client), the Architect reverse-engineers the SDK's actual public API surface and documents it in `WORKING_AGREEMENT.md` BEFORE any sprint authoring against it. Workers given only spec prose consistently invent symbols that don't exist. Soundfield rounds 13 + 20-26 origin.

**47. Substrate-gap-honest events.** When an external substrate (e.g., MLX-Swift's high-level API) doesn't provide the data the spec describes (per-token top-K, entropy, logits), set the corresponding `supports*` flag to false and skip emitting the unobtainable events. Truth ("we don't have this") IS information. Don't fake-emit.

**48. Mock backends gated by environment.** When a project supports both mock and real backends, the backend selection MUST be gated by build environment (e.g., `#if targetEnvironment(simulator)`) so it's structurally impossible to silently ship the mock to production. Soundfield rounds 110b/110c origin: bare `.mock` ran for 67 sprints because no gate prevented it.

**49. Conversation history must be built from a Chat structure.** When an SDK provides a `[Chat.Message]` API (or equivalent), use it from the start — don't pass the raw prompt string. Conversation memory loss is the dominant LLM bug pattern when the API is mis-used. Soundfield sprint-110 origin.

**50. Per-sprint context budget awareness.** The Agent's session-context budget is finite. Sprint cards declaring 12+ context files for a small sprint are an antipattern; either split the sprint or factor context into smaller reference files.

### Observability beyond signals

**51. Always-emit summary + paired incident.** Validation / loading / initialization paths use a summary-stratum always-emit tag with a structural outcome field (`schema_pass, errors`) plus a paired incident tag that fires only on failure. Summary answers "did the operation occur"; incident answers "do I need to do something."

**52. Operator-chain category alignment.** For long pipelines, align category names with the pipeline stages (Trading System: `ingest, encode, compose, propose, constrain, execute, assimilate, compress, explain`). Use payload foreign keys to reconstruct the chain in the Signal Report.

**53. The spec ENUMERATES state transitions.** When authoring the project's technical spec, enumerate ALL state transitions the system will undergo — including boring ones (engine_started, model_loaded) — so they get vocabulary entries from spec → vocab JSON → Worker context. The implicit-state-transition trap (soundfield round 18 finding 47) closes only if the spec is explicit.

---

## Section 2 — Project-class-specific techniques

Each project declares its class(es) in `WORKING_AGREEMENT.md`. Consult the relevant subsection during sprint composition.

### Visual / UI class

**Design bundle context inclusion.** Per AGENTS.md hard rule 8. When a sprint's `## artifact contract → Files created or modified` includes paths matching UI-file patterns (`App/**/*View*.swift`, `app/**/*.tsx`, `**/views/*`, etc.), the sprint card's `## context_files` MUST include the project's design canon. Soundfield rounds 25-26 origin.

**View-tag duality.** Every behavior-category tag whose effect should be visible in the UI pairs with a view-category tag (or structural payload field on an existing view-category tag). Surfaced during the Vocabulary Session's dual-contract audit. MMT Round-2 → Round-3 origin: 24 view tags added in Round-3 after Round-2 closed `pass: true` on broken UI.

**Component-tree-aligned view vocabulary.** View-category tags derived from the design canon's component tree, not arbitrary view-state. Every component with observable state gets a view tag with structural payload (typically including `frame`, `visible`, `scene_id`, `layer`).

**Accessibility identifier on every interactive UI element.** Every interactive UI element gets a stable `accessibilityIdentifier`. Observation contracts use these identifiers as the canonical handle for UI driving (`ui_tap("chat-input")`, `ui_find_element("master-gain-toggle")`).

**Accessibility identifier propagation hazard.** Stating an `accessibilityIdentifier` on a parent container view propagates it to all child elements, overriding the children's own identifiers. Apply identifiers only to leaf interactive elements; if a wrapper needs an identifier (rare), use `.accessibilityElement(children: .contain)`. Soundfield sprints 082/083 origin.

**Deterministic pixel anchors for visual state decoding.** Visualizations include deterministic pixel colors at known coordinates. Screenshots can be decoded for state without manual visual inspection.

**Voice/tone canon consulted at content authoring.** Player-facing strings honor the project's voice canon (in `WORKING_AGREEMENT.md` Tone canon section). Tonal drift is a Rubber Duck Pass `tone trace` observation.

**Two-track visual grading.** Separate the structural assertion (component is mounted, layout boundaries correct) from the perceptual assertion (color, contrast, polish). Structural gradable mechanically; perceptual requires the human or a vision-model judge.

### Audio class

**Sample-accurate timing primitives.** Use the platform's sample-accurate time API (e.g., `AVAudioTime` on Apple platforms; equivalent on others). Don't approximate audio timing in wall-clock seconds.

**Render-thread sacred.** Audio render blocks: MUST NOT capture an actor; MUST NOT allocate memory; MUST NOT call `await`; MUST NOT acquire blocking locks. Share state via a separate `@unchecked Sendable` class behind a lock.

**Audio session config per platform.** iOS: `AVAudioSession.sharedInstance().setCategory(.playback, mode: .default, options: [.mixWithOthers])` then `setActive(true, options: [])`. Guard with `#if os(iOS) || os(tvOS) || os(watchOS)`.

**Subsystem signal categories.** Audio Object's pattern: tag categories align with audio subsystems (`engine`, `transport`, `click`, `loop`, `recorder`, `mixer`). Each subsystem has its own vocabulary section.

**Audio renders / waveform captures as observation evidence.** When grading audio behavior, the artifact is the audio output (a buffer, a waveform image with time markers, a short recording). "Looks correct" is not gradable; the rendered output is.

**Audio rendering is human-on-device verified.** Simulator audio is unreliable. Behavior-touching sprints that change audio render output halt with `awaiting_human_audio_verification`; the human runs on real device, listens, captures OSLog output, pastes back to BLACKBOARD as `## Decisions`.

### iOS class (mobile native)

**ios-simulator-mcp + xcrun simctl integration.** The simulator workflow uses `mcp__ios-simulator__screenshot`, `ui_describe_all`, `ui_find_element`, `ui_tap`, `ui_swipe`, `ui_type` for headless UI driving; `xcrun simctl install booted`, `launch`, `io booted screenshot`, `spawn booted log stream` for build/install/launch/observe.

**Visual gate at N.INT integration sprints.** Every wave ends with `N.INT` that boots the simulator, builds, installs, launches, screenshots the home, runs the wave's observation contract, asserts behavior end-to-end. MMT Round-3 origin.

**Xcode + Metal compilation requirements.** Some packages (mlx-swift's Metal kernels) require Xcode's `xcrun metal` compilation. `swift build` from CLI doesn't compile Metal shaders. Sprints depending on Metal-compiled artifacts validate via `xcodebuild` against the App's Xcode project, not against the SPM target. Soundfield round 17 audit D origin.

**Swift 6 strict-concurrency invariants.** When authoring Swift 6 code: prefer `AsyncStream.makeStream()` over closure-init; `T: Sendable` constraint on generic helpers using `withThrowingTaskGroup`; explicit `[continuation]` capture lists on Task closures; `nonisolated` on actor methods matching non-async protocol requirements; `@unknown default` on non-`@frozen` enums. Soundfield rounds 14-15 origin.

### Backend / data-pipeline class

**Wave 0 carry / pre-filled contract files.** (Also listed in Section 1.) Sprints touching shared contract files open with a Wave 0 sprint that pre-fills canonical shapes.

**N.INT integration sprints at wave boundaries.** (Also listed in Section 1.) Wave-end sprint asserts everything mounted end-to-end.

**Test fixtures from confirmed-good captures.** (Section 1 #38.) `assert_signal(tag, **partial_payload)` and `assert_no_signal(tag)` make the test suite a library of actual captures.

**Operator-chain category alignment.** (Section 1 #52.) For long pipelines, align category names with pipeline stages.

**Always-emit summary + paired incident.** (Section 1 #51.) Validation / loading / initialization use a summary always-emit + paired incident-on-failure pattern.

**Idempotency at every external write boundary.** Database writes, file writes, network POSTs are idempotent (composite-key upsert, content-hashed filenames, idempotency keys). Sprints that violate this need explicit observation contracts proving the retry behavior.

**Backpressure as a signal, not a flag.** When a queue fills or a downstream stage slows, emit a backpressure signal (with payload: which stage, current depth, capacity) — don't just throttle silently.

### LLM-integration class

**External SDK reverse-engineer-first.** Before authoring any code importing an LLM SDK (MLX-Swift, llama.cpp, OpenAI client, Anthropic client, Ollama client), the Architect (or a sub-agent) fetches the actual upstream source / docs, identifies the real API surface, documents the bridge mapping in `WORKING_AGREEMENT.md`. Workers given only spec prose consistently invent symbols that don't exist.

**Substrate gap acknowledgment.** When the SDK provides less than the spec describes, declare the gap explicitly. Set `supportsX = false`; don't fake-emit.

**Mock backend gated by environment.** Backend selection gated by build environment so mock can't silently ship.

**Conversation history must be built from a Chat structure.** Use the SDK's `[Chat.Message]` API from the start; don't pass raw prompt strings. Conversation memory loss is the dominant bug pattern.

**Streaming token boundaries as signals.** When the model streams, emit per-token (or per-chunk) signals with the cumulative state. Lets the observation contract verify both presence and ordering.

**Per-role model routing.** Different models for different sprint roles (drafter, coder, reviewer). Cheaper model for tighter loops; more capable model for high-stakes architecture. Declare per-role routing in `WORKING_AGREEMENT.md`.

### CLI / command-line class

**Exit codes as the contract.** Every CLI command has a documented exit-code contract: 0 for success, distinct non-zero codes for distinct failure modes. The artifact contract's `Command exit codes` section depends on this.

**Subcommand category alignment.** Tag categories align with subcommands (`init`, `validate`, `report`, `migrate`). Drill into a subcommand's signal stream by category-filter.

**Stdout for data, stderr for narration.** The pipeable output (JSON, CSV, structured) goes to stdout; human-readable progress, warnings, signal narration go to stderr. Lets the CLI compose into Unix pipelines without polluting downstream readers.

**Flag-driven instrumentation.** `--trace`, `--signals-out=path.jsonl`, `--verbose` are first-class. The signal sink should be optional and side-effect-only (the CLI's main path doesn't depend on its presence).

### Web / frontend class

**Component-tree-aligned view vocabulary.** (Same as Visual/UI.) View tags derive from component tree.

**Route boundaries as session boundaries.** Each navigation emits a `ROUTE_CHANGED` signal (or equivalent) with from/to. SESSION_INIT fires once per page-load; route changes are within-session.

**Hydration vs render distinction in signals.** Server-rendered output and client-rehydration are distinct events. Emit `RENDER_COMPLETE` server-side; `HYDRATE_COMPLETE` client-side. Lets the observation contract verify both halves of the SSR contract.

**Browser-as-runtime requires out-of-process signal capture.** Signals fire in the browser; the agent doesn't run the browser. Either ship a `window.__signals` collector that the Architect pastes back, or wire a remote logging endpoint that the project captures.

### Data science / ML training class

**Dataset version as part of SESSION_INIT.** Vocabulary version, model version, and dataset version (or fingerprint) all fire in SESSION_INIT. Replays must match all three.

**Training loop emits per-step + per-epoch + per-run signals.** Three strata: per-step (frequent, lightweight), per-epoch (summary), per-run (terminal). Sprint cards for training work declare which stratum the assertion sits at.

**Metric snapshot as artifact.** Training run produces a `metrics.json` artifact whose content assertions name expected key presence + value ranges. Cheaper than running the training again.

**Determinism budget.** Sprint declares whether the artifact is bit-deterministic (same seed → same weights) or statistically deterministic (same seed → metrics within tolerance). The observation contract grades accordingly.

### Game development class

**Scene boundaries as session boundaries.** Scene transition emits `SCENE_CHANGED`; SESSION_INIT fires once at game launch; scene changes are within-session.

**Frame-budget as a signal stratum.** Per-frame summary signals (frame time, draw call count) at ambient stratum; per-frame anomaly signals (dropped frame, GC pause) at incident stratum. Don't emit a signal every frame at event stratum.

**Determinism via seeded RNG + replay.** Game state changes go through a seeded RNG. Replays use the same seed; signal traces from a replay match the original.

**Input replay as observation contract.** UI-driving for games is input replay (recorded keypress/touch sequences, played back at controlled timing). The observation contract names the replay file + expected end state.

### Documentation class

**The spec ENUMERATES state transitions.** (Section 1 #53.) Spec lists all state transitions including boring ones, so vocabulary inherits the enumeration.

**Originals over summaries when referencing canonical material.** (Section 1 #33.) Spec cites the original (`sdd-kit/foundations/01-...§n`), not summaries.

**Versioned docs use round-N naming.** Spec revisions land as `<doc>-round-N.md` alongside the original; never overwrite. (User-corrected rule.)

**Cross-reference index over flat prose.** Long specs include a cross-reference table mapping concept → canonical home. Lets readers jump rather than re-read.

### Embedded / IoT class

**Memory-bounded signal buffer.** `lib/sdd.py`'s deque has `max_buffer=500`; embedded targets may run with `max_buffer=64`. Sprint cards for embedded work declare the buffer ceiling.

**Wall-clock NOT available; use monotonic + uptime.** SESSION_INIT includes `uptime_seconds` rather than `wall_time`; replays anchor relative to session start.

**OTA-update boundaries as session boundaries.** Firmware update emits `OTA_INSTALLED` with from/to versions; SESSION_INIT fires post-reboot with new version in payload.

---

## Section 3 — Techniques deliberately NOT in this kit

These exist (or did exist in earlier kits) but require orchestration the simplest kit doesn't ship. Listed so projects don't think they're missing something accidentally.

**Best-of-N parallel dispatch with build-validation scoring + halt-on-all-fail.** Dispatching the same prompt to multiple LLMs in parallel, running build validation per candidate, refusing to land a broken winner. Requires an orchestrator. Soundfield's best-of-N became reliable after sprint-029's halt-on-all-fail discipline landed. Not shipped here. Compose with Aider, Cline, Cursor, Continue, LangGraph, or a custom orchestrator if needed.

**Correction loop with build-error feedback.** Single worker dispatches; on build failure, the error tail feeds back into the next attempt; loop K times before halting. Requires an orchestrator. Aider and most modern coding agents implement this; compose them with this kit's discipline rather than reimplementing.

**Preflight codebase signature verification.** Before dispatching a sprint, grep the codebase for every type/init referenced in the sprint card; surface unknowns + signature mismatches + ripple-affected files. Requires kit-side code. Soundfield's preflight (`orchestrate/preflight.py`, 674 LOC) is the reference.

**Drafter public-surface fetching.** Before dispatch, glob project source for every type the sprint mentions; inline the actual public API as a `## verified surfaces` block in the worker's prompt. Soundfield's drafter (281 LOC) is the reference.

**Aider-style SEARCH/REPLACE patch applier.** Workers emit unified diffs or SEARCH/REPLACE blocks; kit parses and applies via literal substring matching with ambiguous-match rejection. Aider's open-source patch applier is the canonical implementation; use it directly.

**Multi-foreman parallel sprint dispatch.** Two+ foreman processes running concurrently on file-disjoint sprints, with per-section BLACKBOARD locks. Requires per-section locking infrastructure.

**Auto-execute observation contract via MCP tooling.** Kit-side enhancement that auto-runs the sprint card's `## observation contract` post-grade (boot sim, build, install, launch, drive UI, grep OSLog, take screenshots, fold into dual-contract grade). Requires MCP tooling + dispatch infrastructure. Soundfield round-26 finding 82 named this as the highest-leverage v2 addition.

**Per-role model routing with build_adapters() config.** Different LLMs for different sprint roles via a config.toml + adapter abstraction. Soundfield's `cli.py` + `adapters/` is the reference.

**Signal-trace JSONL sink + cross-session replay.** A persistent signal sink that survives the Python process; the next session's Rubber Duck Pass reads from it. Not shipped; if a project needs it, wire `lib/sdd.py` to dump to JSONL at session end and read on next start.

**Vocabulary parity validator beyond Python.** `lib/sdd.py` validates Python emit calls at the speaker's mouth. For other languages (Swift, TypeScript, Rust), parity validation requires a language-specific checker (regex over emit call sites + cross-check against `signals/0.1.json`). Projects ship their own; the kit doesn't.

**Artifact content-assertion runner.** A `tools/check-artifact.py` that takes a sprint card and runs the content assertions (grep / JSON validate / size check). The Architect runs assertions manually in this kit; if the project wants automation, write the runner project-side.

These are real engineering accomplishments. They belong in an orchestration framework, not in a methodology kit. The kit's discipline (this file + foundations + grammar/ + templates/ + AGENTS.md) composes cleanly with any orchestrator that wants to apply it.

---

*TECHNIQUES.md — comprehensive catalog. Section 1 covers universal techniques (53 entries, grouped by problem domain). Section 2 covers project-class techniques (visual, audio, iOS, backend, LLM-integration, CLI, web, data-science, game-dev, documentation, embedded). Section 3 names what's deliberately deferred to orchestration. Consult when relevant; don't reinvent.*
