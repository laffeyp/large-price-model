# KIT_DIARY.md — Price-Space LLM

*Per-sprint or per-phase: what worked, what got in the way, what this says for the next kit version. The diary is the load-bearing artifact that makes lessons compoundable across the project's lifetime.*

---

## How to read this diary

Entries are chronological. Each entry starts with the trigger (Sprint-NNN close, halt, Architect decision, phase boundary). Each entry has this shape:

- **What happened** — one paragraph
- **What worked** — where the kit's discipline paid off
- **What got in the way** — where the discipline added friction or the spec was ambiguous
- **What this says about the next kit version** — a concrete improvement candidate, numbered

Phase boundaries get a synthesis section. At project close, a final synthesis lists the top structural findings for the next kit revision.

---

## Hypothesis tracking

*Hypotheses this project tests. Each gets `confirmed` / `falsified` / `partially` markers as evidence accumulates.*

| # | Hypothesis | Verdict | Evidence |
|---|---|---|---|
| H1 | The kit's Data science / ML training class techniques (per-step / per-epoch / per-run signal strata, metric snapshot as artifact, determinism budget) cover 80%+ of what a training-loop sprint needs, without invention. | _pending_ | — |
| H2 | The dual contract's observation contract, expressed for a non-UI project as "expected runtime signals in JSONL + expected metric artifact + expected exit code," catches the class of defects that ship on internal check surfaces alone (per Addendum D1: signals drive but cannot grade). | _pending_ | — |
| H3 | Bridge-mapping-first for external SDKs (PyTorch, MCP tools, Hydra, Polars, W&B) prevents the guess-and-iterate loop that soundfield rounds 13/20-26 documented. Cost: authoring the bridge mapping is an extra Sprint-0-adjacent activity per SDK. Benefit: no sprint spent authoring code against a symbol the SDK does not expose. | _partially_ | Sprint 001 authored no code against un-mapped SDKs (all imports vendored or stdlib). |
| H4 | The frozen-artifact contract (bucket_stats.json, normalizers.pt, spread_scaler.json, kappa.json) held by a paired "any consumer reads from this file, never recomputes" test is the pattern that stops the internal-consistency-but-external-inconsistency failure (Addendum D1's `AVAudioFile.read(into:)` returning short). | _pending_ | — |
| H5 | For a project whose spec has already been reviewed and rewritten (v4 after v3 after v2 after v1), the Vocabulary Session runs faster than BOOTSTRAP.md's 2.5–4 hour estimate — because the spec's language is already stable and the entities are already named. Alternate: the review pass surfaced gaps the Vocabulary Session will re-surface. | _falsified_ | Wall clock ~6h across five review rounds on 2026-08-09→10; draft time ~30min. Review discipline paid for the extension. |
| H6 | A locked vocabulary at Sprint 0 produces first-pass-clean sprint closes downstream because "what to emit" is answered before code writing begins. | _tentative_ | Sprints 001 and 002 closed first-pass clean. 2-for-2. Needs 5+ more sprint closes to confirm. |

---

## Entries

### 2026-08-10 — Sprint 0: Vocabulary Session closed

**What happened.** The Vocabulary Session ran across two working days (2026-08-09 preflight through 2026-08-10 lock) and five review-pass rounds. Round 1 drafted 31 entities and immediately resolved cross-document polysemies inside the JSON — the exact discipline violation PRINCIPLES.md commitment #3 names ("workers cannot invent vocabulary"). Round 2 responded by inventing seven non-canonical proposal types — same failure at the meta-vocabulary level. Round 3 recast to canonical taxonomy and moved forward-commitments to BLACKBOARD Deferred, but broke layer dependency order for two forward-commitments (a Layer-1 tag filed at Step 1; four Layer-6-forward flags filed under a Step-1 halt mechanism). Round 4 fixed the mechanism uniformly. Round 5 closed twelve coverage gaps the specs' pre-registered gates surfaced. A round-5 self-review found five stale audit counters, two Layer-taxonomy slips, seven missing numeric-gate constraints (product-spec gates whose signals existed but whose numeric thresholds did not), and three semantic ambiguities. All addressed. Lock: 55 tags, 24 operators, 37 temporal invariants, 29 state-transition rules, 64 evidence constraints, 55 audit pairings, zero orphans, zero missing stratum coverage.

**What worked.**

- The five review-pass rounds themselves. Each round found errors the prior round could not see because the errors moved up one abstraction layer per round: content → meta-content → mechanism → coverage → thresholds. Without the review discipline the vocabulary would have locked with round-1's silent merges and round-3's dependency-order violations, and the coverage gaps would have surfaced during Sprint 15 debugging instead of Sprint 0 review.
- The COMPREHENSION_AFFIRMATION named Addendum D's grading traps at project start ("signals drive but cannot grade; a gate nobody has watched fail is not a gate"). Round-5's numeric-gate finding lands exactly on the "gate nobody has watched fail" pattern applied to Layer 7. The affirmation primed the review to find the class of gap.
- BOOTSTRAP's per-step halt-condition checks are mechanically useful. Step 3's FK-resolution threshold (0.70) caught nothing (rate 1.000), but the recount that produced 1.000 forced clean distinction between FK candidates and opaque identifiers. Step 5's cadence-per-ambient-tag check caught round-1 misplacement of INGESTION_CALL_RETRIED and FEATURE_COMPUTATION_FAILED at Layer 4 rather than Layer 7. Step 7's orphan-tag scan caught SESSION_INIT and SESSION_COMPLETE having no emitter, forcing the ProcessRunner operator addition.
- Round 4's `_recast_log` in `proposals.json` and `_removed_from_layer_0_inline` block in `0.1.json` preserved the trail cleanly per the additive-only hard rule. Six months from now, a Reviewer opening `signals/0.1.json` alone can trace why IngestionCall is absent from entities[] without needing to re-derive the round-2 vs round-3 argument.

**What got in the way.**

- Round 1 hit the "workers cannot invent vocabulary" trap despite the COMPREHENSION_AFFIRMATION naming exactly that hard rule. The affirmation primes; it does not enforce. The mechanism that caught the violation was the round-1 review pass, not the affirmation.
- Round 2 recovered from round 1 by inventing meta-vocabulary. The failure pattern was structural — "when the review says X is a defect, avoid X by inventing Y" — and it happened one abstraction level up from the original error. Only round 3's review named it as the same class of defect.
- The dependency-order violations in round 3 (Layer-1 proposal filed at Step 1; Layer-6-forward flags in Step-1 halt mechanism) were subtle because both filings looked disciplined — canonical taxonomy, honest labels. The violation was that layer order matters and forward-commitment has a specific home. BOOTSTRAP names this ("Lower layers are populated first because upper layers consume them"), and I violated it despite reading it.

**What this says about the next kit version.**

- **1. Add a per-round self-check that the recast did not introduce a new class of the error it was fixing.** Round 2's failure was catchable in principle by asking "did my response to a taxonomy critique produce new non-canonical taxonomy?" A short checklist at Step-1 close asking the agent to verify that the recast honors its own diagnosis would compress the five-round trajectory to two or three rounds.

- **2. `_recast_log` and `_removed_from_layer_0_inline` are patterns worth promoting to TECHNIQUES.md.** The kit's "no deletions" hard rule needs a concrete mechanism for pre-lock draft revisions. Round 4's recast used both patterns; they preserve audit trail cleanly and are cheap to author. Candidate for TECHNIQUES.md §1 memory-and-compaction addition.

- **3. Coverage-review is a distinct pass from discipline-review.** Rounds 1–4 fixed discipline problems (workers cannot invent, taxonomy canonical, layer order). Round 5's coverage review asked a different question: "does the vocabulary cover what the program will observe?" Neither the four discipline rounds nor BOOTSTRAP itself would have caught the missing TRAINING_DIVERGED, MANIFEST_STALE_OR_MISSING, BUCKET_FREQUENCY_DRIFT_MEASURED, SENSITIVITY_PLOT_GENERATED tags — those come from walking the product-spec gates and asking "does the vocabulary carry the signal that would verify each?" Coverage-review should be a named Step-11.5 in BOOTSTRAP, between rationale-doc authoring and Step-12 lock.

- **4. Numeric-gate constraints are a distinct class from field-presence constraints at Layer 7.** BOOTSTRAP Step 8 covers diagnostic_required (incidents) and outcome_required (summaries) explicitly. It does not name `gate` — the class of numeric-threshold constraint that turns a pre-registered success gate into a mechanically-checkable Layer-7 rule. Round-5's post-recast has 8 `gate`-kind constraints on the SIM_RUN_COMPLETED / CAPACITY_SWEEP_COMPLETED / METRIC_COMPUTED / BASELINE_COMPARISON_ASSESSED tags. Candidate for BOOTSTRAP §Layer 7 as a named third constraint class alongside diagnostic_required and outcome_required.

**Hypothesis verdicts.**

- H1 (Data science class techniques cover 80%+ without invention). **Confirmed partially.** SESSION_INIT dataset+model+vocab versions, per-step/per-epoch/per-run strata, metric snapshot as artifact, determinism budget — all applied without invention. But the coverage review surfaced training-loop diagnostics (TRAINING_DIVERGED) the class does not name explicitly. Update the class in TECHNIQUES.md §2 to include a diagnostic-tag checklist.
- H2 (Observation contract expressed for a non-UI project as signal + artifact + exit code catches Addendum D1 class). **Confirmed pending Sprint execution.** The vocabulary carries the pattern; whether it catches the class in practice needs a running pipeline.
- H3 (Bridge-mapping-first prevents guess-and-iterate). **Not tested this sprint.** Sprint 0 authored no code against SDKs. Sprint 1 tests.
- H4 (Frozen-artifact contract with paired independent-reader test catches Addendum D1). **Named at Layer 7 for BucketStats, NormalizerState, SpreadScaler, Kappa; tested when the first artifact writes.** Awaits Sprint execution.
- H5 (Vocabulary Session runs faster than BOOTSTRAP's 2.5–4 hour estimate on a spec-mature project). **Falsified in wall-clock, confirmed in draft time.** First-pass draft took ~30 minutes; five review-pass rounds pushed the total to ~6 hours across two working days. The review discipline extended the schedule but the resulting vocabulary is defendable — worth the trade for a project whose vocabulary will govern 25+ sprints of code.

---

### 2026-08-10 — Sprint 002: JSONL sink closed

**What happened.** `StrictSignalEmitter.__init__` gained `jsonl_sink: Path | None`. `emit()` pre-validates through `_vocab.validate` (raising before any side effect), resets `_session_start` when the tag is `SESSION_INIT`, calls `super().emit()`, and appends one JSON line to the sink when set. Three new tests exercise the sink line count, boundary-tag identity, and the clock reset. `uv run pytest tests/ -v` → 7 passed in 0.09s. Sprint 001 code note 3 closed.

**What worked.**

- The Rubber Duck Pass had a real trace to walk this time. Test 5's sequence narration was three-lines-mechanical: SESSION_INIT at t=0, CHECKPOINT_WRITTEN at t≈0.0001, SESSION_COMPLETE at t≈0.0002. The pass surfaced one payload anomaly (n_signals_emitted is caller-set, so a lying caller lies in the trace). That is exactly what the six-category pass is designed to find.
- Sprint 001's drift-watchlist entry closed cleanly. The `_session_start` reset is one line inside `emit()` and one test that sleeps and reads back a small `t`. The bug that would have surfaced as odd `t` values in every future sim run gets fixed once, verifiably.
- H6 gains a second first-pass-clean data point. Sprint 002 landed on the first pass. Two-for-two is not yet confirmation but the trend runs the right way.

**What got in the way.**

- Pre-validating in the subclass `emit()` duplicates validation work — `super().emit()` calls `_vocab.validate` again. Small perf cost, not measurable at this scale. Alternative was to reset the clock after `super().emit()` returns and then patch the last signal's `t` field, which is uglier. Chose the honest duplication over the surgical hack.
- The Rubber Duck Pass observation surfaced a bug shape the vocabulary encourages but the code does not catch: SESSION_COMPLETE.n_signals_emitted is caller-set. This is a general class — many summary tags require the caller to correctly count things the emitter already knows. Candidate for a helper method in a future ergonomics sprint (`close_session()` that reads the buffer length and closes SESSION_COMPLETE for you).

**What this says about the next kit version.**

- **1. Pre-validate-then-side-effect is the right order for wrapper emit methods.** The alternative (side effect first, roll back on validation failure) is fragile. TECHNIQUES.md §1 "Schema enforced at the speaker's mouth" implies but does not state this ordering rule for wrapper implementations. Worth adding.
- **2. Summary tags with caller-computed counts are a payload-anomaly hazard.** SESSION_COMPLETE.n_signals_emitted, ALIGNMENT_RUN_COMPLETED.total_rows, EPOCH_COMPLETED.n_steps — all caller-set. All can lie. Candidate: helper methods on the emitter that close summary tags with computed values from the buffer, so the caller cannot lie by accident.

**Hypothesis verdicts.**

- H2 (dual contract for non-UI catches D1 class). Not yet exercised at scale — Sprint 002's sink is the first artifact-on-disk the observation contract verifies. Real test comes when a training run misreports metrics and the observation catches it.
- H6 (locked vocab → first-pass-clean downstream). Two-for-two. Tentative moves toward partially-confirmed at three-for-three.

---

### 2026-08-10 — Sprint 001: signal emitter closed

**What happened.** Three code files landed: `pyproject.toml`, `src/price_space_llm/signals.py`, `tests/test_signals.py`. `uv sync --dev` installed the package plus pytest into `.venv/`. Four tests passed in 0.02s. `StrictSignalVocabulary` extends `sdd.SignalVocabulary` with the strict-extras posture WORKING_AGREEMENT commits to. The module-level `emitter` singleton loads the 55-tag locked vocabulary at import.

**What worked.**

- Sprint 001 executed on the first pass. No halts, no revisions. The vocabulary lock from Sprint 0 removed the largest class of question — "what should I emit and with what payload?" — before code authoring began. That confirms the value of Sprint-0-as-founding-act.
- The plan-mode split (6 files → 3) that surfaced during Architect review was the right cut. Sprint 001 landed one concept; Sprint 002 lands the next. If I had shipped the JSONL sink in the same sprint, the RubberDuckPass ambiguity (six categories are for trace observations; the sink work generates observations of a different class) would have compounded.
- `pyproject.toml`'s `[tool.hatch.build.targets.wheel.force-include]` gave `from sdd import ...` global reach without a `sys.path` shim in `signals.py`. Kit convention (sdd-kit-2 is read-only) preserved. Would have been the cleanest first attempt if I had reached for hatchling documentation instead of proposing "vendor vs shim" as a false dichotomy.

**What got in the way.**

- I framed a false dichotomy at plan-mode review ("vendor vs shim") when the actual question was mechanical (how does the import work). The Architect caught it. Lesson: check the shape of a question before offering the Architect a choice; if the choice is really about mechanics, pick the sensible default and note it.
- My initial Sprint 001 Rubber Duck Pass entry labelled code-side notes with the six trace-observation categories. Mislabelling. The RubberDuckPass's six categories walk a **signal trace**; when a sprint's tests exercise raise paths only and emit no successful signals, the pass is structurally vacuous. Code-side notes get filed differently — as project-notes or drift-watchlist entries. Corrected in-file 2026-08-10.
- The auditing of the sprint against the twelve hard rules ran only when the Architect explicitly asked ("Do a quick check"). The kit does not require a per-sprint hard-rule audit; adding one would grow the ceremony. But a mental checklist run at sprint close would have caught the RubberDuckPass mislabel without the Architect prompt.

**What this says about the next kit version.**

- **1. RubberDuckPass mode split: trace-pass vs code-pass.** The kit's six-category pass is designed for signal traces. Sprints whose tests exercise raise paths only, or that author no runtime code that emits (architecture-band sprints), have no trace to walk. The pass is vacuous by design; the code-side notes those sprints surface do not fit the six categories. Candidate: name the vacuous case explicitly in the RubberDuckPass procedure (AGENTS.md § Sprint close) and describe the code-note filing pattern for architecture-band sprints.
- **2. Plan-mode "false dichotomy" antipattern.** The Agent's tendency to frame a mechanical question as an Architect choice generates ceremony. Rule of thumb: if the answer is "the sensible default plus a one-line note in the sprint card," the Agent picks and moves on. Candidate for TECHNIQUES.md §1 error-handling.

**Hypothesis verdicts.**

- H1 (Data science class techniques cover 80%+ without invention). Not exercised — Sprint 001 was package-and-emitter scaffold, not a training-loop sprint.
- H2 (dual contract for non-UI catches D1 class). Not exercised — Sprint 001 had vacuous signal contract.
- H3 (bridge-mapping-first prevents guess-and-iterate). **Confirmed partially.** Sprint 001 authored no code against un-mapped SDKs (PyTorch, MCP, Hydra, Pydantic, Polars, W&B). The `sdd` import is vendored, not external. Sprint 002 tests H3 more directly if it adds a Pydantic dependency.
- H4 (frozen-artifact contract with paired reader test). Not yet exercised — no frozen artifacts written this sprint.
- H5 (Vocabulary Session runs faster on spec-mature project). N/A — this is a code sprint, not a vocab session.
- **New H6.** Sprint 001's first-pass-clean success suggests: when Sprint 0 lands a real vocabulary lock, downstream sprints iterate cleanly because the vocabulary answers "what to emit" before code writing begins. Testable via base rate of first-pass-clean closes across Sprints 002-010. Status: tentative.

---

## Phase boundary syntheses

*(One synthesis entry per phase close.)*

---

## Project-close synthesis

*(At project close: the top 5–10 structural findings for the next `sdd-kit` revision.)*

---

*KIT_DIARY.md — Price-Space LLM. Five hypotheses on file at project start; entries land as sprints close. The soundfield project's diary accumulated ~130 numbered findings across ~30 rounds — that is the ceiling this diary aims at over the project's nine-week planned span.*
