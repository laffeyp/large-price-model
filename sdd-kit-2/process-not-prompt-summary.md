# process-not-prompt-summary

*One-page conclusion. The longer literature pass is in `process-not-prompt-research.md` (sibling). What you're reading here is the verdict and what changed in the kit as a result.*

Written 2026-05-25.

---

## The question

The kit is structured as a sustained, multi-step process with externalized state (read working agreement → write comprehension affirmation → lock vocabulary → execute sprint → emit Signal Report → run Rubber Duck Pass → merge to BLACKBOARD → repeat across many sessions). Working hypothesis: this isn't a prompt, it's a process — and that distinction is mechanically load-bearing for LLMs, not just stylistic.

The job: check whether the LLM literature supports the intuition or whether we're confabulating mechanism from human-cognition analogies (commitment-and-consistency, internalization, "the model comes to know the project").

## The verdict

**Coarse claim (multi-step structured workflows outperform single-shot for sustained work): supported, with a clean theoretical result.** Merrill & Sabharwal (2024) prove that constant-depth transformers without intermediate tokens are bounded to TC⁰; with T intermediate tokens, the same transformer can express any function computable by a circuit of size T. Chain-of-thought literally extends serial computational depth the architecture otherwise lacks. The kit's multi-step structure is doing real work, not ceremony.

**Fine claims (model "internalizes" the process, "substrate thickens over time," "session 30 LLM has a different relationship to the project," articulation produces Cialdini-style commitment): NOT supported.** LLMs are stateless across sessions, weights don't update, and persona-consistency literature (Hu et al. 2025, ICLR 2025) actively shows models *drift* from stated commitments without active reinforcement — the opposite of the Cialdini effect. The "session 30 has a different relationship" claim is true at the *context* level (artifacts accumulating) but false at the *model* level (same weights). Phrasings that import human-cognition mechanism are evocative metaphor at best, mistaken at worst.

**The actual mechanism is four-part, in descending order of evidence strength:**

1. **Serial compute** — intermediate tokens add computational depth (Merrill & Sabharwal 2024). Load-bearing.
2. **Attendable intermediate state in-window** — articulated content sits in the context window where attention reads it; subsequent generation is conditioned on it (Olsson et al. 2022; persona vectors, Chen et al. 2025). Real, but window-local.
3. **Externalized artifacts that survive context-window degradation** — files, blackboards, structured reports persist across sessions and let the next session reconstruct the relevant slice selectively, into high-attention positions (Liu et al. 2024, *Lost in the Middle*; context-rot literature). Load-bearing for cross-session continuity.
4. **Task-recognition priming via in-context learning** — vocabularies, worked examples, tone canons don't teach the model; they tell it which already-learned capability to activate (Brown et al. 2020; Xie et al. 2021). Selection, not transmission.

**Plus a critical caveat:** intrinsic self-correction by LLMs is contested. Huang et al. (2023, ICLR'24) shows pure self-critique often *degrades* reasoning. The kit's Rubber Duck Pass is defensible because it has external check surfaces (locked vocabulary, dual contract, observation contract, tone canon) — not because of self-reflection.

## What changed in the kit

Three additive edits. No scrubbing — the kit's existing text doesn't use the mechanistically-wrong phrasings (those appeared in my conversational responses, not in the artifacts).

1. **`TECHNIQUES.md` technique #0** — new opening Section 1 entry, "Process not prompt — the four mechanisms behind why the kit's structure works." Names the four mechanisms with sources, maps each kit artifact onto which mechanism(s) it serves, and explicitly disowns the human-cognition framings the literature doesn't support.

2. **`AGENTS.md` § COMPREHENSION_AFFIRMATION** — section retitled from "ritual" to "step." New explanation of *why* "in your own words" matters mechanically: it adds serial compute (mechanism #1) and primes in-window attention (mechanism #2). Replaces the (implicit) commitment-ceremony framing. Hollow affirmations are bad not because they violate a ritual but because they prime for nothing project-specific.

3. **`AGENTS.md` § Rubber Duck Pass** — added a "Why the pass is defensible (and what it depends on)" note. Names the external check surfaces the pass grounds itself in (vocabulary, contract, invariants, tone canon) and cites Huang 2023 / Tyen 2023 on why pure intrinsic critique is contested. The pass works because of its grounding, not despite it; without the grounding it degrades into self-reflection theater.

## What was reaffirmed (not changed)

Several things the research validated as already mechanistically sound:

- "Vocabulary lock is the contract." Acts as ICL task-selection + provides external check surface. Kept as hard rule 2.
- "Externalize state to the blackboard." Directly addresses context rot. Kept as the BLACKBOARD protocol.
- "Originals over summaries." The four mechanisms favor walking the derivation (more tokens, more attendable state, more priming) over reading a summary (compressed away from these effects). Kept as hard rule 11.
- Sprint sweet spot ≤2 files / one concept. Independent of the process-not-prompt question; soundfield-derived empirical finding.

## Open empirical questions

The research doc enumerates six (§6); the load-bearing ones for the kit are:

1. Does the comprehension-affirmation step measurably improve downstream sprint compliance, or is it cargo? Paired sprints would settle this.
2. Does the Rubber Duck Pass catch defects the dual-contract grade misses, or is it redundant? Cross-reference pass observations vs contract-grade results across N sprints.
3. What's the half-life of vocabulary drift across sessions without active parity checks? Sets the cadence for the gate.

These are testable. The kit's discipline is informed by them but not yet validated against them.

## What this means going forward

The kit's value rests on four mechanically-grounded effects, not on metaphors about model cognition. When the kit is being explained, the four-mechanism framing is the load-bearing description; the "process not prompt" slogan is fine as a slogan but should be paired with the mechanisms when used in load-bearing documents. The kit's existing structure already implements the four effects; the edits above just make the *reason* legible, so future kit revisions don't drift into ceremony based on misunderstood mechanism.

---

*See `process-not-prompt-research.md` (3 pages, ~30 citations) for the underlying literature pass.*
