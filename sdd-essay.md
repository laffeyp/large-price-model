# Signal-Driven Development, technique by technique

An essay on the load-bearing practices of `sdd-kit-2`.

---

## The problem the kit exists to fix

The standard loop for AI-assisted work has one lossy step in the middle. The human sees the fault, describes it in prose, the model reads the prose and codes against its guess. Description is a compression format with a high error rate for technical state. Prose loses timing, spatial arrangement, concurrent order, audio artefacts, and the exact contents of a buffer. Signal-Driven Development deletes the description step. The program describes itself in typed events; the human copies the events; the agent reads them without translation. The human's role shifts from narrator to operator: run the thing, trigger the behaviour, capture, paste.

Nothing in the kit is more load-bearing than this reframe. Every technique below serves it.

## The signal, and the vocabulary that types it

A signal is not a log line. A log tells a human what happened. A signal tells a machine what a designed event was called and what it carried, in a vocabulary the program and the reader share. The distinction matters because the vocabulary is a contract, and contracts survive across sessions. `PAYMENT_DECLINED` in a checkout service means the same thing next week that it means today; a log string does not.

The kit calls the vocabulary a grammar because it has eleven layers. Layer 0 names the entities the system tracks state for (Cart, Bird, PriceState). Layer 1 names the tags those entities admit, in a strict form: `{ENTITY}_{VERB_PAST_PARTICIPLE}`. Layer 2 types each tag's payload. Layer 3 frames the streams as sessions with boundary-open and boundary-close tags. Layer 4 records temporal invariants (`CLUE_INSPECTED is followed by CLUE_TEXT_DELIVERED within five seconds`). Layer 5 graphs the allowed transitions. Layer 6 names the runtime operators that emit each tag. Layer 7 declares payload evidence beyond type — tonal rules, numeric ranges, cross-reference constraints. Layers 8, 9 and 10 bind the tag set into a Signal Report format, stamp a version, and set the meta-rules for how the grammar may evolve. Most projects populate the first two layers and leave the rest implicit; the kit's empirical finding is that the projects which drift are the ones that leave them implicit.

The vocabulary is enforced at the speaker's mouth. When code calls `emit(tag, **payload)`, the emitter validates the tag against the locked schema and raises on any unknown tag or missing field. This is poka-yoke — the mistake cannot be made, because the emitter refuses to make it. Workers may not invent tags mid-sprint. A worker who needs a new tag halts with `vocabulary_change_required` and files a typed proposal under one of eight kinds (`NEW_TAG_PROPOSED`, `PAYLOAD_FIELD_PROPOSED`, `TAG_SPLIT_PROPOSED`, `ENTITY_MERGE_PROPOSED`, and four others). The Architect ratifies. The version bumps.

## The Vocabulary Session is Sprint 0

The kit's twelfth hard rule states it plainly: no implementation sprint dispatches until `signals/0.1.json` and its rationale document exist and the human has signed off. The soundfield project materialised its vocabulary at sprint sixty of sixty-seven; the prior fifty-nine sprints carried the gap, and six later sprints paid off the debt. The Vocabulary Session is a two-to-four hour whiteboard between the human and the agent. It walks the eleven layers in dependency order (Layer 0 first, Layer 7 last), producing the locked JSON and a rationale document that argues each choice from the docs. The rationale document is what makes the vocabulary defensible six months later, when a new session asks why `BIRD_FLIT` is a separate tag from `BIRD_HOPPED`. Skip the rationale and the vocabulary becomes undefendable.

## The dual contract, plus the observation contract as third leg

Every sprint has two contracts and, for behaviour-touching work, a third. The signal contract lists every tag the sprint's code will fire; the artifact contract lists every file it will author, every content assertion the reviewer can grep, and every command with its expected exit code. Both must pass to close.

The third contract exists because content assertions do not cover product behaviour. A file may contain the right function names and the app may still produce silence, mocked LLM output, or an unrendered pane. Soundfield's round twenty-three graded file contents while the running app produced silent audio; the observation contract closes that gap. Behaviour-touching sprints declare their UI driving steps, expected log substrings, expected runtime signals, and expected screenshot regions in the sprint card. A sprint that touches product behaviour without an observation contract halts with `observation_contract_missing`.

## Sprint sweet spot: at most two files, one concept

The empirical ceiling on effective sprint scope is two files and one idea. Bigger sprints fail unpredictably. Cross-cutting refactors split into chains of small sprints; each closes clean before the next dispatches. Wave-end sprints, labelled `N.INT`, boot the whole system and assert that everything in the wave is mounted end-to-end. Integration is a proof-point, not an assumption.

## Halt-and-articulate

Uncertainty is not silent-decision material. When the sprint's scope is unclear, when the vocabulary lacks a needed tag, when an external SDK's API is not documented in the working agreement, the agent writes a typed halt entry to `BLACKBOARD.md ## Surfaced for review` and stops. The typed reasons are named — `vocabulary_change_required`, `dual_contract_fail`, `comprehension_failed`, `bridge_mapping_required`, `observation_contract_missing`, `awaiting_architect_decision`. A BLACKBOARD entry is cheap; a bad assumption is expensive.

## Single-writer discipline on the BLACKBOARD

The project's shared scratchpad has seven sections and a single writer per section. `## Decisions` is Architect-only and append-only — the agent never writes there. `## Built` is agent-only and append-only, one paragraph per sprint close. `## Sprint tail` and `## Drift watchlist` the agent maintains. `## Surfaced for review` both write. This is discipline, not code enforcement; the merge conflicts humans use locks to avoid are prevented by refusing to write outside the section you own.

## Comprehension affirmation as the session-start step

At every first session the agent writes one paragraph to `## Surfaced for review` covering what the project is, what SDD is at root, what the kit's canonical loop is, and the halt-and-articulate rule. In the agent's own words. The kit is explicit about why: this is not a commitment ceremony. Large language models do not commit to stated positions; the persona-consistency literature shows they drift from them. The affirmation does two mechanical things. It adds intermediate tokens the model computes over — Merrill and Sabharwal proved in 2024 that intermediate tokens extend a fixed-depth transformer's computational depth beyond TC⁰. And it places the project's specifics in the context window at a position where attention will read them during subsequent generation. A hollow affirmation — boilerplate that names none of the project's specifics — gets neither effect and is rejected on that mechanical ground, not on ritual grounds.

## Four mechanisms, no metaphors

The kit refuses the language of internalisation, substrate thickening, and model-session relationships. Those phrases import human cognition that is not there. Four effects do the work, strongest evidence first. Serial compute: intermediate tokens extend the transformer's computational depth. In-window state: articulated content sits in the context window where attention reads it, so subsequent generation is conditioned on it. Externalised artefacts: the BLACKBOARD, KIT_DIARY, locked vocabulary, and Signal Reports survive across sessions; the next session retrieves the relevant slice into a fresh window instead of fighting lost-in-the-middle degradation of a long conversation. Task-recognition priming: a worked example and a locked vocabulary do not teach the model, they tell it which already-learned capability to activate. Every kit artefact maps to one or more. The comprehension affirmation is one and two. The Rubber Duck Pass is one, grounded by three and four. The BLACKBOARD is three. The `example/` folder and the vocabulary are four.

## The Rubber Duck Pass, and why it is not self-reflection

Pure intrinsic self-critique degrades LLM reasoning; Huang and colleagues showed this at ICLR 2024. The Rubber Duck Pass survives that finding because it is not self-reflection — it grounds itself in external check surfaces. The pass walks the signal trace in three steps. Sequence narration: read every signal in time order, one sentence per tag, mechanical English against the vocabulary's own notes and payloads. Observations: list anomalies in six closed categories — missing pair, order violation, vocabulary gap, payload anomaly, timing surprise, tone trace. Dispositions: commit each observation to one of four bounded states — `resolved-here`, `surfaced`, `halted`, `deferred`. The vocabulary is the check surface for missing pair, order violation, and vocabulary gap. The sprint card's signal contract is the check surface for payload anomaly. The tone canon is the check surface for tone trace. Without those surfaces the pass degrades into ceremony; with them it catches drift the dual contract misses.

## Signals drive; they cannot grade

Audio Object's grading round is the sharpest lesson in the kit. Every signal in the app was typed, ratified, and honest. A destructive audio crop shipped to a phone graded by nothing but `SAMPLER_CROPPED`, which emitted a clean line with sensible numbers. One outside gate — read the file back off disk with an independent reader and count the frames — found on its first run that `AVAudioFile.read(into:)` returns short. Every crop had been silently dropping sixteen milliseconds. Every internal check was consistent with every other internal check. The `Clip`'s frame count was computed from the same short read, so it agreed with the truncated file. The engine that produced the bytes could not judge them. The rule that fell out is simple. For any behaviour-touching claim, the grader must be something that did not produce the artifact: a foreign parser, an independent reader, a measurement, a device trace. Observation harnesses tell you what the program did. They cannot tell you whether it was right.

## Verify the verifier

A gate you have not watched fail is not a gate, including the gates that check the gates. The vocabulary audit that greps for tag emission sites can pass because the emitter wrapper contains the grep target; nothing outside the wrapper needs to exist. Plant the defect the gate exists to catch, run the gate, watch it go red, then restore. Do this for every gate, and do it especially for the gates that check the other gates.

## Canonical home registry, and originals over summaries

Two hard rules stop drift that would otherwise compound. The canonical home registry names which file owns which public type; the agent consults it before authoring. Without it, multi-sprint sequences thrash by silently declaring the same type in three files. Originals over summaries: when transmitting context to a new session, pass the originals — the foundations, the working agreement, the locked vocabulary, the BLACKBOARD's `## Decisions` — not the agent's synthesis of them. Summaries compress away the specifics that hold the argument up. The v1-to-v1.2 prompt-factory trajectory documented summary-induced drift across three versions. The cost of transmitting originals is paid once; the cost of summary drift is paid every sprint.

## No deletions, and hand-author requires authorisation

Restructures land in new files, new folders, round-N versions. The audit trail is the work. If a sprint's shape is uncertain and iteration fails, the agent does not silently slide into hand-authoring the artefact; it surfaces to the Architect with what was attempted, why each attempt failed, and asks the four questions — rescope, change models, hand-author, or pause? Only on an explicit "hand-author" does the agent proceed. Every hand-authorisation lands in the working agreement's log.

## What the kit deliberately does not do

The kit ships no orchestrator, no build runner, no HTTP adapter, no patch applier, no best-of-N dispatch, no cross-session signal-trace persistence. Text and convention. A hundred and fifty lines of Python for the reference emitter. Everything above rests on the human running the build by hand and the agent reading Markdown from disk. When a project outgrows this shape — multiple agents, CI dispatch, service-scale operation — the kit expects the team to wrap it in an orchestrator or to compose it with Aider, Cline, or Cursor. The methodology stays the same; the operations become a separate concern.

## Why the shape holds

The value is the sequence, not any one artefact. Read the working agreement, write the affirmation, lock the vocabulary, execute the sprint, emit the Signal Report, run the Rubber Duck Pass, merge to the BLACKBOARD, then do it again. Every pass leaves artefacts the next pass reads. Nothing depends on the model learning; the model does not learn. It depends on the human and the agent honouring the same discipline session after session, and on the audit trail nobody deletes. Soundfield's diary carries about a hundred and thirty numbered findings across thirty rounds. Katybird shipped. `wordcount` closed three sprints clean. The discipline compounds where it is kept.
