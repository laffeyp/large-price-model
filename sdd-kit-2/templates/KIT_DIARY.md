# KIT_DIARY — {Project Name}

*A working diary of what the kit does well, what gets in the way, and what the next kit version should change. Each entry corresponds to a sprint close, a halt, an architect decision, or a phase boundary. The diary is the load-bearing artifact that makes lessons compoundable across the project's lifetime — without it, every kit-improvement insight evaporates with the conversation that produced it.*

*The soundfield project's KIT_DIARY accumulated ~130 numbered v2-kit findings across ~30 rounds of work; most of the structural lessons that informed this kit's design came from that diary. Maintain yours with the same discipline.*

*Copy this template to project root as `KIT_DIARY.md`; do not edit this template.*

---

## How to read this diary

- **Entries are chronological.** Each entry starts with the trigger (sprint-NNN close, halt, decision, phase boundary).
- **Each entry has the same shape:**
  - **What happened** (one paragraph: what the kit / Agent / Architect did)
  - **What worked** (where the kit's discipline paid off)
  - **What got in the way** (where the discipline added friction or where the prompt/spec was ambiguous)
  - **What this says about the next kit version** (concrete improvement candidate)
- **Phase boundaries get a synthesis section:** did the phase deliver its acceptance criteria? what's the through-line of what we learned?
- **At project close:** a final synthesis with the top 5–10 structural findings for the next kit revision.

---

## Hypothesis tracking

*Hypotheses you're testing throughout the project. Each gets `confirmed` / `falsified` / `partially` markers as evidence accumulates.*

| # | Hypothesis | Verdict | Evidence |
|---|---|---|---|
| H1 | {hypothesis at project start} | _pending_ | — |

---

## Entries

*(Entries appear below as sprints close. Each entry uses the shape described above. Examples below show the format.)*

---

### {YYYY-MM-DD} (round N) — Sprint NNN: {sprint title} closed

**What happened:** {one paragraph}

**What worked:**

- {bullet 1}
- {bullet 2}

**What got in the way:**

- {bullet 1}
- {bullet 2}

**What this says about the next kit version:**

- {numbered finding, e.g., "10. Sprint cards need an explicit `## observation contract` section for behavior-touching sprints."}

---

## Phase boundary syntheses

*(Insert one synthesis entry per phase close, summarizing the phase's hypothesis verdicts and the through-line of findings.)*

---

## Project-close synthesis

*(At project close, list the top 5–10 structural findings that should inform the next version of `sdd-kit/`. Propagate these upstream to the kit maintainer.)*

---

*KIT_DIARY.md — template. The diary is the project's accumulating memory about how the kit serves the work. Maintain per-sprint or per-phase; without it, kit-improvement insights evaporate.*
