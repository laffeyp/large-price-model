# BLACKBOARD — {Project Name}

*The project's working scratchpad. Seven sections. Single-writer per section (discipline, not code-enforced). The Architect (human) does not read this by default; the Agent surfaces what matters via `## Surfaced for review` plus plain-English summaries in chat. Copy this template to the project root as `BLACKBOARD.md`; do not edit this template.*

---

## Surfaced for review

*Agent + Architect. Halts, partial verdicts, comprehension affirmations, observations from the Rubber Duck Pass marked `surfaced`. The Architect reads this section.*

*(empty on project start)*

---

## Decisions

*Architect-only. Append-only. The Agent never writes here. If the Agent thinks a decision is needed, surface to `## Surfaced for review` and ask.*

- **{YYYY-MM-DD}** — Project scope: {one-paragraph statement of what this project is, who it's for, what success looks like, what's out of scope. The Agent reads this at session start as ground truth.}

---

## Built

*Agent appends one entry per sprint close. Append-only. One short paragraph per sprint: sprint id, files authored, dual-contract outcome.*

*(empty until first sprint closes)*

---

## Deferred

*Anyone may append. Items deferred from a sprint, with the re-visit condition.*

*(empty on project start)*

---

## Open questions

*Anyone may append. Questions not yet answered.*

*(empty on project start)*

---

## Drift watchlist

*Agent maintains. Patterns to monitor across sprints. When the same observation surfaces in three consecutive sprints, escalate to `## Surfaced for review`.*

*(empty on project start)*

---

## Sprint tail

*Agent maintains. Rolling log of recent sprint closes. Last 10 sprint summaries; older entries roll into `## Built` as compressed paragraphs.*

*(empty until first sprint closes)*

---

## Single-writer-per-section discipline

Per `sdd-kit/AGENTS.md` hard rule and `sdd-kit/foundations/03-sdd-team-model.md`'s communication-protocol-inversion principle.

| Section | Who writes | What they write |
|---|---|---|
| `## Surfaced for review` | Agent + Architect | Halts (Agent), comprehension affirmations (Agent at session start), partial verdicts (Agent), specific feedback (Architect) |
| `## Decisions` | Architect ONLY (append-only) | Project scope at start; binding decisions during the project; resolutions of halts |
| `## Built` | Agent (append-only) | One paragraph per sprint close |
| `## Deferred` | Anyone | Items deferred with re-visit condition |
| `## Open questions` | Anyone | Questions not yet answered |
| `## Drift watchlist` | Agent maintains | Observations to track across sprints |
| `## Sprint tail` | Agent maintains | Last 10 sprint closes; older roll into `## Built` |

When in doubt: the Agent surfaces to `## Surfaced for review` and asks the Architect. The Agent does NOT write to `## Decisions`; that's the human's prerogative.

---

*BLACKBOARD.md — template. Copy to project root as `BLACKBOARD.md`; fill `## Decisions` with project scope; leave other sections empty for the first sprint to populate. Single-writer per section is discipline, not code-enforced.*
