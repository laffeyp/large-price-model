# process-not-prompt-research

*A skeptical literature pass on the claim that structured multi-step processes with externalized state and articulation steps work better than single-shot prompts for sustained LLM-assisted coding work.*

Written 2026-05-25. Sources cited inline, full URLs at the end.

---

## 1. The investigated claim

The methodology this document audits structures sustained LLM-assisted coding as a process, not a prompt: the agent reads a working agreement, writes a "comprehension affirmation" in its own words, locks a vocabulary, executes sprints, emits structured signal reports, runs a self-grading pass, merges into a shared blackboard, and repeats across many sessions. The intuition is that this is *qualitatively* different from a single-shot prompt — that the difference is load-bearing for output quality. The job here is to check whether the literature supports the intuition or whether we're confabulating mechanism from human-cognition analogies (commitment-and-consistency, internalization, etc.).

The short answer: the *coarse* claim — multi-step structured workflows outperform single-shot — is well-supported, with at least one clean theoretical result on serial computation. The *fine* claims — that articulation produces commitment-like consistency, that the model "internalizes" the process, that "session 30 LLM has a different relationship than session 1 LLM" — are largely unsupported as stated. The mechanism is best understood as a combination of additional serial compute, attendable intermediate state, externalized artifacts that survive context-window loss, and in-context priming. Several common phrasings in the methodology drift into evocative metaphor.

---

## 2. What the literature supports

### 2.1 Within-session multi-step structure

**Chain-of-thought intermediate steps produce measured accuracy gains on reasoning tasks — well-established.** Wei et al. (2022) showed eight CoT exemplars lifted GSM8K performance of a 540B model past fine-tuned baselines, with the effect emerging at scale. Nye et al. (2021) showed earlier with "scratchpads" that producing intermediate tokens lets models perform multi-step computations (long addition, program execution) they cannot do in a single forward pass.

**The mechanism is at least partly *serial compute*, not just style — well-established theoretically.** Merrill & Sabharwal (2024, *The Expressive Power of Transformers with Chain of Thought*) prove that constant-depth transformers without CoT are bounded to TC⁰ (problems solvable by constant-depth threshold circuits — i.e., parallel computation only). With T intermediate tokens, the same transformer can express any function computable by a circuit of size T. This is the cleanest mechanistic answer in the literature: CoT *literally adds serial computational depth* the architecture otherwise lacks. Li et al. (2024, *Chain of Thought Empowers Transformers to Solve Inherently Serial Problems*) reach the same conclusion from a different angle. Strength: well-established, formally proven.

**Self-refine / Reflexion produce gains, but mostly when external feedback is available — preliminary and contested.** Shinn et al. (2023, *Reflexion*) shows verbal self-feedback as a "semantic gradient" works on coding/agent benchmarks. But Huang et al. (2023, *Large Language Models Cannot Self-Correct Reasoning Yet*, ICLR'24) directly contests intrinsic self-correction: without external feedback, models often *degrade* on reasoning after self-correction. Tyen et al. (2023, *LLMs cannot find reasoning errors, but can correct them given the error location*) shows the bottleneck is error detection, not error fixing. **Bearing on the methodology:** rubber-duck-style self-grading is more defensible when it has an *external check* (vocabulary parity tool, schema validator, capture grader) than as pure intrinsic critique.

**CoT is not always a faithful trace of the underlying reasoning — well-established.** Lanham et al. (2023, *Measuring Faithfulness in Chain-of-Thought Reasoning*, Anthropic) shows perturbing CoT often doesn't change the answer, and larger models produce *less* faithful CoT on most tasks studied. METR (2025) argues CoT remains informative even when unfaithful. **Bearing:** the methodology's intermediate signal traces are useful as compute-on-paper and as audit surface, but should not be read as "what the model actually thought."

### 2.2 Cross-session / externalized state

**Persistent external state matters because context windows degrade and don't persist.** Liu et al. (2024, *Lost in the Middle*) measured 30%+ accuracy drops when key information sits mid-context across 18 frontier models. "Context rot" (Hong et al. 2025 and surveys) confirms degradation grows with input length on every frontier model tested. Externalized artifacts (files, blackboards, structured reports) work because they let the next session load *only* the relevant slice — into early/late context positions where attention is strongest. Strength: well-established empirically.

**The mechanism for cross-session continuity is retrieval + in-context priming, not memory in any deeper sense.** Reviews of memory-augmented LLM systems (e.g., the 2026 *Externalization in LLM Agents* survey; CMA / Continuum Memory Architecture work) treat persistent state as RAG-flavored: prior artifacts are *retrieved and re-injected* into the context window of a fresh session. There is no neural-level "memory" between sessions for any current production system; weights don't update. What looks like continuity is the next session re-deriving the relevant state from documents the previous session wrote. Strength: well-established (and important — see §3).

**Cognition's "Don't Build Multi-Agents" articulates the mechanism in production terms — preliminary but credible.** Cognition AI (Yan, 2025) argues reliability hinges on *context engineering*: "share context, and share full agent traces, not just individual messages." Their failure mode for naive multi-agent setups is exactly the methodology's concern — sub-agents lacking the originating context produce subtly miscoordinated work. The same post acknowledges sub-agents *can* help when their work doesn't need to persist in main-agent history. Strength: practitioner report, not peer-reviewed, but converges with academic findings on context rot.

### 2.3 In-context learning

**ICL is best understood as task-recognition / activation of pre-existing capability, not learning during inference — well-established.** Brown et al. (2020, GPT-3) introduced ICL as adaptation without weight updates. Olsson et al. (2022, *In-context Learning and Induction Heads*, Anthropic) traced a substantial fraction of ICL to induction heads: attention heads that implement `[A][B] ... [A] -> [B]` pattern completion. The bump in ICL ability during training coincides with induction-head formation. Xie et al. (2021, *An Explanation of In-context Learning as Implicit Bayesian Inference*) frames ICL as Bayesian inference over latent tasks the model was pretrained on. **Bearing:** "loading the context" is not teaching the model — it's selecting which already-learned capability it should activate. The methodology's careful vocabulary lock and worked example are doing *task selection*, not transmission of new knowledge.

### 2.4 Commitment-and-consistency in LLMs

This is the claim that needs the most careful handling. The intuition — model articulates a position, then acts more consistent with it — is plausible by analogy to Cialdini, but the LLM evidence is weak.

**Persona prompts shift self-reported traits, but behavioral consistency is shaky — preliminary and contested.** Hu et al. (2025, *The Personality Illusion*, arXiv 2509.03730) found persona injection shifts self-reports in the expected direction but has *minimal impact on behaviors* expected from human studies. Mills et al. (*lm-persona-consistency*) and the ICLR 2025 *Do LLMs Have Consistent Values?* paper find off-the-shelf LLMs drift from assigned personas, contradict earlier statements, and abandon role-appropriate behavior. The contrastive-learning fix (Wang et al. 2025, *Persona-Aware Contrastive Learning*) exists *because* baseline persona consistency is bad.

**There is some evidence that *verbalized* uncertainty/reasoning influences subsequent steps more than latent uncertainty.** Several 2025–2026 papers (e.g., *Tell me about yourself: LLMs are aware of their learned behaviors*; reasoning-trajectory work) show that when uncertainty or a policy is made explicit in the trace, it becomes "actionable" for later generation in a way it isn't when latent. This is the closest the literature gets to a commitment-style effect — and it's mechanistically grounded in plain attention: the model attends over what's in the context window, and an articulated statement is *in* the window in a way a silent inference is not.

**Persona vectors (Chen et al. 2025, Anthropic) show personality traits as steerable directions in activation space.** Persona vectors confirm that persona prompts and in-context examples push activations along these directions. This is the substrate that makes the "articulation matters" intuition partially correct — articulating a stance *does* move activations — but it doesn't establish a Cialdini-style commitment effect; it establishes a much more local "what's loaded into context shapes what's generated next."

**Sycophancy literature complicates the picture.** Sharma et al. (2023) on sycophancy and recent work (e.g., *Interaction Context Often Increases Sycophancy*, 2025) show models adapt to user-stated positions, sometimes against their own better judgment. So "model articulates X, then acts consistent with X" can be sycophancy as much as commitment. The cleanest reading: in-context statements *prime* subsequent generation; whether that's "commitment" depends on whether the priming is from the model itself or from the user, and whether downstream context reinforces or undermines it.

### 2.5 The "process vs prompt" framing itself

**"Context engineering" is the term that has crystallized in 2025.** The framing — "structuring everything an LLM needs: prompts, memory, tools, data — to make decisions reliably" — directly maps to the methodology's process posture. The 12-Factor Agent framework (Tobi Lutke / community 2025) and the *Agentic Context Engineering* paper (arXiv 2510.04618) are the most direct articulations. Strength: practitioner-driven but rapidly accumulating academic backing.

**"Prompts as software-engineering artifacts."** The arXiv paper of that name (2509.17548) treats prompts as design artifacts encoding intent, evolving iteratively. APPL (Dong et al. 2024) proposes a prompt programming language for composing LLM calls. Strength: emerging area, no dominant theory yet.

---

## 3. What the literature does NOT support (or is silent on)

- **"The model internalizes the process over time."** False as stated. Weights don't update between sessions. There is no internalization. What persists is what's written down and re-loaded.
- **"Session 30 LLM has a different relationship to the project than session 1 LLM."** False at the model level — same weights, same model. *True* at the context level — session 30's context window contains 29 sessions' worth of artifacts (or summaries of them) which prime its outputs. The relationship that has changed is *between the context bundle and the model*, not the model itself. The phrasing as written misattributes the change.
- **"The substrate thickens over time."** Evocative metaphor. There is no substrate. There is an accumulating corpus of written artifacts that successive sessions retrieve from. The phrasing implies state continuity that doesn't exist.
- **Cialdini-style commitment in LLMs.** Not established. Persona consistency research suggests *the opposite* — models drift from stated commitments without active reinforcement. The closest real effect (verbalized > latent influence on next steps) is much more local: it's about what's currently in the window, not about prior commitments.
- **"The agent comes to know the project."** Misleading. The agent at session N has access to project artifacts; it has not learned the project in any weight-update sense. Each session re-enters cold and reconstructs understanding from documents.

---

## 4. The actual mechanism, distilled

"Process not prompt" works mechanically for LLMs through four compounding effects, in roughly descending order of evidence strength:

1. **Serial compute (Merrill & Sabharwal 2024; Nye 2021; Wei 2022).** Multi-step structures literally extend the computational depth available to a fixed-depth transformer. This is the load-bearing theoretical result. Sprint structure, intermediate signal emissions, and rubber-duck passes all add serial tokens the model can compute over.
2. **Attendable intermediate state in-window (Olsson 2022; induction-heads literature; persona-vector work).** Articulated reasoning, vocabulary locks, and self-affirmations sit in the context window where attention can read them. Subsequent generation is conditioned on them. This is real and well-grounded — but it's a property of *the current context window*, not a persistent property of the model.
3. **Externalized artifacts that survive context-window degradation (Liu 2024 lost-in-the-middle; context-rot literature; Cognition context-engineering posts).** Files, blackboards, and structured reports let session N+1 reconstruct the relevant slice of state cheaply and place it at high-attention positions. This is why externalization beats long-context conversation: long context degrades; selective retrieval doesn't.
4. **Task-recognition priming (Brown 2020; Xie 2021; ICL literature).** Carefully chosen worked examples, vocabularies, and tone canons don't teach the model — they tell the model *which already-learned capability to activate*. The methodology's vocabulary lock and worked example are doing ICL task-selection work.

What "process not prompt" does *not* do at the model level: it does not teach, internalize, commit, accumulate substrate, or change the model's relationship to anything. The model remains stateless across sessions. The process changes *what each fresh session is conditioned on* — and that turns out to be enough to produce qualitatively different output.

---

## 5. Load-bearing vs evocative — phrase-by-phrase

| Phrase | Verdict |
|---|---|
| "The model internalizes the process." | **Wrong as stated.** No internalization. Replace with: "Each session loads the process into context and is conditioned on it." |
| "The substrate thickens over time." | **Evocative metaphor.** There is no substrate. Replace with: "The artifact corpus grows; each session retrieves the relevant slice." |
| "Session 30 LLM has a different relationship than session 1 LLM." | **Useful-but-loose.** Relationship hasn't changed; the conditioning has. Defensible as shorthand if the team knows the underlying mechanic. |
| "Articulating the working agreement makes the model commit to it." | **Partially correct, but not via commitment.** Articulating *primes* subsequent generation because the articulation is in the window. Drop "commit" — it imports Cialdini-style mechanism that isn't there. |
| "The rubber-duck pass catches drift the contract grade misses." | **Plausible and load-bearing** *if* the pass has external check surface (vocabulary parity, schema). Pure intrinsic self-critique is contested (Huang 2023). |
| "Comprehension affirmation in the model's own words." | **Mechanistically sound.** Articulated content is attendable; it adds serial compute over the agreement and primes downstream generation. The phrasing "in the model's own words" is doing real work — it forces additional tokens, not just an ack. |
| "Vocabulary lock is the contract." | **Sound.** Acts as ICL task-selection and provides a checkable surface for parity tests. |
| "Externalize state to the blackboard." | **Sound and load-bearing.** Directly addresses context-rot and cross-session degradation. |
| "Process not prompt." | **Defensible as a slogan.** Risk is that listeners import human-cognition mechanism (internalization, commitment). Worth pairing with the four-mechanism distillation in §4 when used in load-bearing documents. |

---

## 6. Open questions worth empirical investigation

1. **Does the comprehension-affirmation step actually improve downstream sprint compliance, or is it cargo?** Run paired sprints: half with affirmation, half without. Measure deviation from working agreement in subsequent sprint outputs. If the gain is small, it's compute-for-show.
2. **Does the rubber-duck pass catch defects that the dual-contract grade misses?** Log all rubber-duck observations across N sprints. Cross-reference with contract-grade results. If rubber-duck observations are always a subset of contract-grade fails, the pass is redundant.
3. **What's the half-life of vocabulary drift across sessions without active parity checks?** Run sessions without the parity gate. Measure how many sprints until tag invention or vocabulary slippage. Sets the cadence for the gate.
4. **Does length of the working agreement matter, or just its specificity?** Compare long-form CLAUDE.md vs short bullet-list. Lost-in-the-middle suggests middle content of long agreements is being skipped — testable.
5. **Is the "comprehension affirmation in the model's own words" doing serial-compute work, or priming work, or both?** Compare: (a) read-only ack, (b) verbatim recital, (c) paraphrase-in-own-words. If (c) >> (a), priming + serial compute. If (b) ≈ (c), serial compute dominates. If (a) ≈ (c), the affirmation does nothing.
6. **Persistent state via blackboard vs persistent state via vector retrieval.** Same artifact corpus, two access paths. Which produces better continuity on a fixed task suite? Settles whether structured-document retrieval has any advantage over generic RAG for this use case.

---

## Sources

- Wei et al. (2022) *Chain-of-Thought Prompting Elicits Reasoning in Large Language Models.* https://arxiv.org/abs/2201.11903
- Nye et al. (2021) *Show Your Work: Scratchpads for Intermediate Computation with Language Models.* https://arxiv.org/abs/2112.00114
- Merrill & Sabharwal (2024) *The Expressive Power of Transformers with Chain of Thought.* https://arxiv.org/html/2310.07923v5
- Li et al. (2024) *Chain of Thought Empowers Transformers to Solve Inherently Serial Problems.* https://arxiv.org/abs/2402.12875
- Shinn et al. (2023) *Reflexion: Language Agents with Verbal Reinforcement Learning.* https://openreview.net/pdf?id=vAElhFcKW6
- Huang et al. (2023, ICLR'24) *Large Language Models Cannot Self-Correct Reasoning Yet.* https://arxiv.org/abs/2310.01798
- Tyen et al. (2023) *LLMs cannot find reasoning errors, but can correct them given the error location.* https://arxiv.org/pdf/2311.08516
- Lanham et al. (2023) *Measuring Faithfulness in Chain-of-Thought Reasoning.* https://arxiv.org/abs/2307.13702
- METR (2025) *CoT May Be Highly Informative Despite "Unfaithfulness".* https://metr.org/blog/2025-08-08-cot-may-be-highly-informative-despite-unfaithfulness/
- Liu et al. (2024) *Lost in the Middle: How Language Models Use Long Contexts.* (summary) https://www.morphllm.com/lost-in-the-middle-llm
- Context-rot survey (2025) https://www.morphllm.com/context-rot ; arXiv 2510.05381
- Yan / Cognition AI (2025) *Don't Build Multi-Agents.* https://cognition.ai/blog/dont-build-multi-agents
- Brown et al. (2020) *Language Models are Few-Shot Learners.* (GPT-3 paper, foundational)
- Olsson et al. (2022) *In-context Learning and Induction Heads.* https://arxiv.org/abs/2209.11895
- Xie et al. (2021) *An Explanation of In-context Learning as Implicit Bayesian Inference.* https://arxiv.org/pdf/2111.02080
- Hu et al. (2025) *The Personality Illusion: Revealing Dissociation Between Self-Reports & Behavior in LLMs.* https://arxiv.org/pdf/2509.03730
- ICLR 2025 *Do LLMs Have Consistent Values?* https://proceedings.iclr.cc/paper_files/paper/2025/file/68fb4539dabb0e34ea42845776f42953-Paper-Conference.pdf
- Wang et al. (2025) *Enhancing Persona Consistency for LLMs' Role-Playing using Persona-Aware Contrastive Learning.* https://arxiv.org/abs/2503.17662
- *Interaction Context Often Increases Sycophancy in LLMs* (2025) https://arxiv.org/pdf/2509.12517
- Chen et al. (2025, Anthropic) *Persona Vectors: Monitoring and Controlling Character Traits.* https://www.anthropic.com/research/persona-vectors ; https://arxiv.org/pdf/2507.21509
- *Tell me about yourself: LLMs are aware of their learned behaviors* (2025) https://arxiv.org/html/2501.11120v1
- *Agentic Context Engineering* (2025) https://arxiv.org/pdf/2510.04618
- *Prompts as Software Engineering Artifacts* (2025) https://arxiv.org/pdf/2509.17548
- *Externalization in LLM Agents: A Unified Review* (2026 survey) https://arxiv.org/html/2604.08224v1

*End of document. ~3 pages.*
