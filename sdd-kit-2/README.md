# sdd-kit-2

*Slim refactor of `sdd-kit/`. Same methodology; fewer files; no application-gate ceremony. The simplest viable Signal-Driven Development kit, faithful to what the four originals (Audio Object, Trading System, Make The Models Talk, Katybird) actually practiced — structurally improved with the load-bearing lessons from the soundfield project. Text and convention. No orchestration. Human Architect + any Tier-1 LLM agent.*

---

## What changed from sdd-kit/

`sdd-kit-2/` is the slim refactor. The original `sdd-kit/` remains in place as the audit trail (per the project's never-delete-originals discipline).

Cuts:

- **Three grammar files folded back**: `EMPIRICAL.md`, `PER_LAYER.md`, `EXAMPLES.md` not carried forward. The originals built vocabularies without a formal treatise; the two remaining files (`PRINCIPLES.md` + `BOOTSTRAP.md`) are the minimal explicit version of what worked.
- **Three procedure files folded inline**: `COMPREHENSION_AFFIRMATION.md`, `DUAL_CONTRACT.md`, `RUBBER_DUCK_PASS.md` not carried forward as separate files. Their procedures live inside `AGENTS.md` directly — that's how the originals practiced them (inline in the working agreement) and that's what worked.
- **TECHNIQUES.md application-gate ceremony dropped**: AGENTS.md's hard rule 13 ("cite techniques in every sprint card"), the sprint card's `## techniques applied` section, and the Rubber Duck Pass's technique-citation drift check — all removed. The catalog itself stays, but as a reference, not a gate. The prompt-factory's earlier TECHNIQUES.md had gates and didn't transmit; the simplest kit closes the failure mode by removing the ceremony and trusting the catalog to be consulted when relevant.

Additions:

- **`example/` folder** with a small worked CLI project: vocabulary, three sprint cards, BLACKBOARD with real entries, KIT_DIARY with real entries, source files. The original four projects' biggest legibility advantage was concrete artifacts to pattern-match against; `sdd-kit/` shipped only abstract templates and lost that.
- **TECHNIQUES.md expanded**: 53 universal techniques (up from 32) + 11 project-class subsections (up from 6). Made comprehensive so projects don't reinvent.
- **Hard rule 12 in AGENTS.md (no deletions)** — restructures always land in new files / folders / round-N versions. The audit trail is the work.

Net: 24 files → 17 files (8 fewer); plus an 8-file example project. The kit's claim of "no orchestration" is honest. The methodology is unchanged; the ceremony is gone.

---

## What this is

A folder of markdown documents + one ~150-line Python reference library. No orchestrator. No HTTP adapters. No dispatch logic. No build runners. No CLI. The kit is what the agent reads; the agent + human run the loop.

The methodology comes from four projects (Audio Object, Trading System, Make The Models Talk, Katybird) that practiced SDD without any orchestration layer — one demonstrated ship (Katybird) plus three formative/exploratory projects whose lessons inform the discipline. The kit additionally absorbs structural lessons from the soundfield project (a more recent project that ran with a heavy orchestrator and demonstrated what was over-engineering versus what was load-bearing).

The kit ships:

- `AGENTS.md` — the working agreement, tool-agnostic. The load-bearing read at session start. Procedures (comprehension affirmation, dual contract, Rubber Duck Pass) folded inline.
- `CLAUDE.md` — thin shim for Claude Code sessions; points at AGENTS.md.
- `TECHNIQUES.md` — comprehensive catalog of named development techniques. Reference, not gate. Universal (Section 1, 53 entries) + project-class-specific (Section 2: visual, audio, iOS, backend, LLM-integration, CLI, web, data science, game dev, documentation, embedded) + what's deliberately not in the kit (Section 3, orchestration-deferred).
- `ADDENDUMS.md` — the staging ground between a project's `KIT_DIARY.md` and `TECHNIQUES.md`: dated, project-stamped technique captures that post-date the catalog and have surfaced on ONE project each (not yet stabilized across a second, so not yet promoted). Sits at kit root beside `TECHNIQUES.md` on purpose — the split is visible at a glance: `TECHNIQUES.md` is what's settled, `ADDENDUMS.md` is what's new and staged. Reference, not gate; weight each entry as real-on-one-project. On file: A (`substrate-ui`), B (`Cascade`), C (`Audio Object`).
- `foundations/` — the four originals of the SDD canon, untouched. Read once per project; informs everything else.
- `grammar/` — vocabulary authoring discipline (two files: `PRINCIPLES.md`, `BOOTSTRAP.md`).
- `templates/` — the artifacts a project instantiates (six files: VOCABULARY.json, BLACKBOARD.md, SPRINT_CARD.md, SIGNAL_REPORT.md, WORKING_AGREEMENT.md, KIT_DIARY.md).
- `lib/sdd.py` — the reference library from foundation 02 (~150 lines). Opt-in for projects that want typed `emit_signal()` in Python.
- `example/` — a worked mini-project (a tiny CLI) showing the discipline applied end-to-end.

---

## How a project uses this kit

1. Copy `sdd-kit-2/` into the project. Pick a name for the project's own version (e.g., `_sdd-kit/`).
2. Open a session with any LLM agent (Claude Code, Cowork, Cursor, Aider, Continue) and have it read `AGENTS.md` first.
3. Architect (human) + Agent run the **Vocabulary Session** following `grammar/BOOTSTRAP.md`. Output: the project's filled-in `VOCABULARY.json`.
4. Architect copies `templates/BLACKBOARD.md` to project root, opens it, writes the first Decision (project scope).
5. Architect (or Agent, reviewed by Architect) drafts the first sprint card using `templates/SPRINT_CARD.md`.
6. Agent reads AGENTS.md + the sprint card + the relevant foundations + the working agreement, writes a Comprehension Affirmation per the procedure in AGENTS.md, executes the sprint, returns a Signal Report per `templates/SIGNAL_REPORT.md`.
7. Architect runs the build/verification commands by hand (`swift build`, `pytest`, etc.) — the kit does not ship a runner.
8. Agent runs the Rubber Duck Pass per the procedure in AGENTS.md, writes observations + dispositions to BLACKBOARD per single-writer discipline.
9. Architect writes a KIT_DIARY entry per `templates/KIT_DIARY.md`: what worked, what got in the way, what this says for the next sprint.
10. Repeat from step 5.

For a worked example of all this end-to-end on a tiny CLI project, see `example/`.

No `python -m anything` runs. The kit is read; the agent acts; the human steers and verifies.

---

## What this kit does NOT do

Stated explicitly so the gaps are clear and project teams can fill them with their own tooling.

- **No orchestrator.** No process spawns workers, parses Signal Reports, writes artifacts to disk, or merges BLACKBOARD entries automatically. The agent does all of this through its own tool calls (Read, Write, Edit) inside the LLM session it runs in.
- **No build runner.** Dual contract requires running build commands (`swift build`, `pytest`, `cargo test`, `npm run build`). The human runs them. If the project wants automation, wrap the kit in a `make` target or a CI step — outside the kit's scope.
- **No HTTP adapters.** No Ollama, OpenAI, Anthropic, or Bedrock integration. The kit assumes the agent runs in whatever LLM session the human chose.
- **No vocabulary parity enforcement beyond Python.** `lib/sdd.py` validates at the speaker's mouth for Python projects. For Swift, TypeScript, Rust, anything else: discipline-enforced (the agent honors the vocabulary; the Rubber Duck Pass surfaces violations; the human catches what slips through). Projects that want hard parity ship a language-specific checker.
- **No artifact content-assertion runner.** Sprint cards declare assertions like "file contains X"; the Architect greps by hand or runs a project-side checker.
- **No best-of-N parallel dispatch.** No correction loops. No patch applier. If the agent's first output is wrong, the agent and human iterate; no Python loop manages it.
- **No comprehension-affirmation gate.** The procedure asks the agent to write the affirmation at session start as a ritual; the kit does not refuse to dispatch sprints if the affirmation is missing. The human refuses.
- **No sprint card parser.** Sprint cards are plain markdown files in `sprints/`. The agent reads the next one and works on it; the human reviews.
- **No signal trace persistence across sessions.** `lib/sdd.py` keeps signals in an in-memory deque; the process dies, the trace is gone. If the project wants cross-session traces, wire `lib/sdd.py` to dump JSONL at session end and read on next start.

The bet: discipline + procedures + clear failure modes documented in advance get a Tier-1 LLM agent (Claude Code, Cowork, Cursor) most of the way without any of these. The soundfield build's heavy orchestrator generated more bugs and more meta-work than it solved.

---

## Lessons the kit absorbs vs lessons it leaves behind

**Absorbed (structural):**

- Sprint sweet spot is ≤2 files / one concept. → `AGENTS.md` hard rule 6.
- Canonical home registry — name which file owns which type. → `templates/WORKING_AGREEMENT.md` has a section for this; `AGENTS.md` hard rule 7.
- The dual contract works and is required. → `AGENTS.md` "The dual contract" section.
- Observation contract beats content assertion for behavior-touching work. → `AGENTS.md` dual-contract section + hard rule 9.
- Diary discipline (what worked / what got in the way) is what makes lessons compoundable. → `templates/KIT_DIARY.md` is a first-class artifact.
- Comprehension affirmation as session-start ritual. → folded into `AGENTS.md`.
- Originals over summaries (the v1 → v1.2 transmission lesson). → `AGENTS.md` hard rule 11; `foundations/` kept verbatim.
- Hand-author requires explicit human authorization. → `AGENTS.md` hard rule 10.
- Sprint-0 vocabulary materialization (don't backfill at sprint-60). → `grammar/BOOTSTRAP.md` is the explicit founding act; `AGENTS.md` hard rule 12.
- External-package bridge mapping before any code authoring. → `grammar/BOOTSTRAP.md` + `templates/WORKING_AGREEMENT.md`.
- Design-bundle context inclusion for UI-touching sprints. → `templates/SPRINT_CARD.md` notes; `AGENTS.md` hard rule 8.
- The rubber-duck-pass-after-sprint-close discipline. → folded into `AGENTS.md`.
- No deletions — restructures land in new files / round-N versions. → `AGENTS.md` hard rule 12 (in the "should never do" list).

**Not absorbed (kit-operational):**

- Best-of-N tuning, build-validation scoring weights, halt-on-all-fail discipline. → No best-of-N here.
- `think: false` in the Ollama adapter, HTTPStatusError retry classification. → No adapter here.
- `_emit_log` locking under ThreadPoolExecutor concurrency. → No emitter loop here.
- patch_applier.py CRLF round-trip discipline, multi-divider SR-block rejection, atomic temp+rename. → No patch applier here.
- preflight ripple detection, drafter public-surface enumeration, codebase_grepper brace-walking. → If a project wants these, they're available in the soundfield build's `_factory/prompt-factory/orchestrate/` as reference; this kit doesn't ship them.
- Foreman lock POSIX vs Windows fallback. → No foreman here.
- TECHNIQUES.md application gates (re-skim before drafting, cite in every sprint card, plan-mode-checklist verification). → The catalog stays; the gates don't. The prompt-factory had these gates and they didn't transmit; trusting the catalog to be consulted when relevant is the simpler bet.

These are real engineering accomplishments; they belong in an orchestration framework, not in a methodology kit.

---

## When to outgrow this kit

This kit is for projects in the bottom 80% of operational complexity:

- Single human + single LLM agent
- Sprint cadence is loose (one sprint, then human review, then next)
- Build runs locally on the human's machine
- The project is one repo, one team, one product

When a project crosses into the top 20%:

- Multiple agents running in parallel
- CI dispatching sprints automatically
- Dispatch decisions need to be made without a human in the loop
- The project is being run as a service for other teams

… then the kit alone is no longer enough. Two paths from here:

- **Wrap the kit in a thin orchestrator.** A Python script that walks `sprints/`, dispatches Workers to an LLM, parses Signal Reports, writes artifacts. The discipline (this kit) stays the same; the orchestrator handles the operations.
- **Use a public orchestration framework.** Aider, Cline, Cursor agent, Continue, AutoGen, LangGraph all handle dispatch + tool use + patch application well. Bring this kit's discipline as the prompt + the working agreement + the templates. Let the framework handle orchestration.

The kit does not ship either path. The kit is the methodology. Orchestration is a separate concern.

---

## Reading order for a new agent on first session

1. `AGENTS.md` — load the working agreement into context.
2. `foundations/01-signal-driven-development.md` — the theory.
3. `foundations/04-sdd-claude-design.md` — the founding-act framing (sets up the Vocabulary Session).
4. `grammar/README.md` — points at the two grammar files.
5. `grammar/PRINCIPLES.md` — the 11-layer stack + non-negotiable commitments.
6. `grammar/BOOTSTRAP.md` — the Vocabulary Session procedure.
7. `example/README.md` — the worked example, useful for pattern-matching at first sprint.

`TECHNIQUES.md` is a reference, not first-session reading. Skim once to know what's there; dip in when relevant.

Other foundations (`02-sdd-practice.md`, `03-sdd-team-model.md`) are read as the work demands.

---

## Project layout after adoption

After the human copies sdd-kit-2 into a project (say, named `myproject/`) and starts working:

```
myproject/
├── sdd-kit-2/                              (this folder; never edit; pull updates from upstream)
├── BLACKBOARD.md                           (instantiated from sdd-kit-2/templates/BLACKBOARD.md)
├── KIT_DIARY.md                            (instantiated from sdd-kit-2/templates/KIT_DIARY.md)
├── WORKING_AGREEMENT.md                    (instantiated; project-specific overrides on top of AGENTS.md)
├── signals/
│   └── 0.1.json                            (the project's locked vocabulary, produced by the Vocabulary Session)
├── sprints/
│   ├── sprint-001-<slug>.md
│   ├── sprint-002-<slug>.md
│   └── ...
├── src/                                    (the project's actual code)
└── tests/
```

`sdd-kit-2/` is read-only — the kit's discipline. The project's own files (BLACKBOARD, KIT_DIARY, WORKING_AGREEMENT, signals/0.1.json, sprints/) are the project's evolving state.

---

*sdd-kit-2. Slim refactor of sdd-kit. Smallest viable Signal-Driven Development discipline. Text and convention. No orchestration. No deletions. The agent runs the loop; the human steers; the kit is what they read.*
