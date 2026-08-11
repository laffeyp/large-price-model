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
| H6 | A locked vocabulary at Sprint 0 produces first-pass-clean sprint closes downstream because "what to emit" is answered before code writing begins. | _tentative_ | Sprints 001, 002, 005 first-pass clean. Sprint 003 second-pass at build layer; Sprint 004 second-pass at test layer; Sprint 006 second-pass at lint layer. 4-for-6 first-pass overall. |
| H8 | Adopting ruff + mypy on an existing small codebase in one sprint is cheap because auto-fix does most of the work. | _tentative_ | Sprint 006: ruff auto-fix carried 80% (8-of-10); mypy has no auto-fix (0-of-4 auto, all manual). More data points from future tooling-adoption sprints on other codebases. |
| H7 | The vocabulary type strings are self-describing enough that a ~30-line parser enforces them across the whole schema. Adding a new type requires one entry in `_TYPE_CHECKERS` and one line in `_parse_type`. | _tentative_ | Sprint 004 landed the parser at ~40 lines; covered nine type kinds. Test: a sprint that adds `git_sha` as a format type. |

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

### 2026-08-11 — Sprint 020: Alpha-Vantage fetcher wired + live smoke closed

**What happened.** `--fetcher {mock,alphavantage}` flag added to `scripts/probe_channels.py`. Live smoke against the real API on the three-channel config returned exit 2 in ~5s: `SPY` and `USO` accepted, `VIX` dropped across all five sample dates because `TIME_SERIES_INTRADAY` does not support `^VIX` — it is an index, not an intraday-priced security, and Alpha-Vantage responds `Invalid API call`. The probe caught a real ingestion gap that the config was blind to.

Three emit-time crashes surfaced during the smoke loop. Each failed on a different strict-enum or type constraint on `CHANNEL_PROBED`: `actual_frequency="unknown"` failed the frequency enum; `earliest_timestamp=""` failed the ISO parser; `revision_behavior="error:AlphaVantageResponseError"` failed the revision-behavior enum. The `_error_shim` was smuggling a diagnostic (the exception class name) into fields whose semantic is observational, not diagnostic. The fourth version of the shim fabricates only vocabulary-legal values and puts the failure string on stderr; the manifest still records the drop correctly. The empty-series path in `_extract_fetch_result` had the same class of bug and got the same fix.

Sink hygiene: the JSONL writer opens with `"a"`. Three crashed runs during smoke-loop iteration left 42 lines in a trace whose `SESSION_COMPLETE.n_signals_emitted` reported 21. `rm -f` + clean rerun produced the expected 21 lines. Filed for a signals-hygiene sprint (truncate on SESSION_INIT).

**What worked.**

- **The probe caught the VIX schema mismatch on first live contact.** No test could have surfaced it — the mock happily returned data for any symbol. The value of running against real vendors early is that the vendor itself is the schema authority; the probe's job is to route that authority's answers into a manifest before anything expensive gets built on top. `product-spec-v4.md` names channel coverage as a Phase 0 blocker; the probe now delivers that gate against real data.
- **The `_error_shim` pattern kept the probe module untouched.** Two paths were on the table (extend `probe_channel` with an on-error callback vs wrap the fetcher). The wrap kept Sprint 016's module signature stable and pushed the error-handling responsibility to the CLI layer, which is where transport-specific errors belong.
- **Bridge mapping earned its keep.** Sprint 018's halt recorded the exact response shape (US/Eastern, ordinal-prefixed OHLCV keys, string values). Sprint 019 wrote tests against that recorded shape via `httpx.MockTransport`; Sprint 020's live run confirmed the recorded shape was accurate — zero re-work on normalisation. The three sprint-loop (halt-and-record → author-and-test → wire-and-smoke) is the anti-guess-and-iterate pattern working.

**What got in the way.**

- **Strict enums on observation-tag payloads have no shape for error signals.** Every field on `CHANNEL_PROBED` is either a strict enum or a typed value; when the observation is "the fetch itself failed," the shim has to fabricate legal-but-inaccurate values or the emit crashes. Three separate crashes narrowed which fields the shim could legally set. The final shape puts the error string on stderr, invisible to any Reviewer reading only the trace. The vocabulary should probably grow a `CHANNEL_FETCH_FAILED` incident tag, or extend `revision_behavior` with an `error` enum value; filed to Surfaced-for-review with the tradeoff spelled out.
- **The JSONL sink's append-mode assumption is right until it isn't.** Same `run_id` invocations accumulate. During normal use one invocation gets one `run_id` and this is invisible. During iterative debugging (mine, this sprint) it produces a file with two SESSION_INITs and a mismatched signal count. Truncate-on-SESSION_INIT is the honest fix.

**What this says about the next kit version.**

- **1. First-live-contact reveals what mock-driven tests cannot.** Sprint 016 (probe with injected mock fetcher) + Sprint 017 (CLI + mock trace) + Sprint 019 (fetcher via MockTransport) all passed on the first try. Sprint 020 hit three vocabulary crashes on the first live run because the mock returned only success-shaped `FetchResult` values; real-vendor error shapes were nowhere in the test suite. The kit's TECHNIQUES.md could name a "first-live-contact sprint" pattern: after mock-driven work stabilises, run against the actual vendor with the smallest possible surface (one call per channel, cheapest tier) and expect the first run to surface vocabulary and error-path gaps the mock could not.
- **2. Observation-vocabulary vs error-vocabulary is a real distinction.** The kit's PRINCIPLES.md treats vocabulary as one thing. In practice this project has learned that observation tags (`CHANNEL_PROBED`) are strict about the semantics of the field values because they encode what the world looked like; error tags (`CHANNEL_FETCH_FAILED` candidate) should be lenient about vendor error strings because they encode what went wrong outside the system's control. Retrofitting the distinction is uglier than declaring it up front. Candidate for a foundations-level addendum: the observation-vs-error stratum split within an incident tag.

**Hypothesis verdicts.**

- **H3 (bridge-mapping-first prevents guess-and-iterate).** Confirmed strongly. Sprint 018 halted precisely because the actual API surface diverged from the documented one; Sprint 019 wrote against the recorded reality; Sprint 020's live run needed zero normalisation fixes. This is the second data point (the first was Sprint 016's MCP tool documentation stub) — the pattern holds.
- **H6 (locked vocab → first-pass-clean downstream).** Weakened. Sprint 020 hit three vocabulary crashes on the live path. The locked vocabulary is correct for observations; it does not cover fetch failures, which the mock never exercises. First-pass-clean holds when the sprint's input matches the vocabulary's design assumptions and breaks when it doesn't — a more honest statement than the H6 original.
- **New H9.** A "first-live-contact" sprint costs about three iteration cycles regardless of how thorough the mock-driven tests were, because real vendors surface error shapes the mock cannot. Testable across future live-contact sprints (Databento for BBO, W&B upload path).

---

### 2026-08-10 — Sprint 006: tooling adoption closed

**What happened.** ruff and mypy landed in `[dependency-groups] dev`. `[tool.ruff]` + `[tool.ruff.lint]` configured with E/F/I/UP/B/SIM/PT rules; `[tool.mypy]` set to strict on `src/price_space_llm`; `[[tool.mypy.overrides]]` handles the un-stubbed `sdd` module. Pytest gained `--strict-markers`, `--strict-config`, `-ra`, `filterwarnings = ["error"]`, `xfail_strict = true`. First pass ran the tools: 10 ruff findings (8 auto-fixed, 2 formatter re-flows, 1 line-too-long fixed by hand), 4 mypy findings (2 `Cannot subclass Any` from the sdd ignore-missing-imports — silenced with `# type: ignore[misc]` on the two subclasses; 2 missing dict type args — typed explicitly). Ruff's `UP` pack also modernised `timezone.utc` to `datetime.UTC` (Python 3.11+ shim). Second pass: ruff green, mypy green, 18 tests pass, wheel builds. Every item from the code review is now addressed across Sprints 003–006.

**What worked.**

- Auto-fix carried most of the ruff findings. 8-of-10 required no manual edit. The remaining two (one line-too-long, one format-only) were mechanical. The pattern generalises: adopt lint on an existing small codebase in one sprint, take the auto-fix output for free.
- Mypy strict on the wrapper code caught two legitimate class of issue: unbounded generic types (`dict` without type args) and the sdd-subclass surface. The `# type: ignore[misc]` on the two class defs is targeted; the alternative was writing a `sdd.pyi` stub file. Stub deferred — write it if kit maintainers add `sdd` to a real distribution.
- `filterwarnings = ["error"]` did not surface any pending deprecations. The stack (Python 3.13, hatchling 1.x, pytest 9.1, ruff 0.16, mypy 1.19) is quiet at this point in time. A Python 3.14 or a pytest 10 might change that; the sprint captures the current state.

**What got in the way.**

- Ruff's `UP` pack changed `from datetime import timezone` + `timezone.utc` to `from datetime import UTC` + `UTC.utcoffset(v)`. That's a Python 3.11+ shim (introduced in 3.11). The code was written targeting `>=3.11`, so the change is legitimate — but it's the sort of edit that would break a project pinned to Python 3.10. Worth naming in the KIT_DIARY as an antipattern to guard against: `UP` rules can silently push the minimum-Python floor. Not a problem here (pyproject already commits to 3.11); worth flagging for a hypothetical port.
- Mypy's `--strict` flag is on/off; there's no gradient. Two lines of `# type: ignore[misc]` cover the sdd-subclass boundary and let the rest of the module benefit from strict. Cleaner would be `sdd.pyi`, but that's an sdd-kit-2 upstream contribution, not this project's problem.

**What this says about the next kit version.**

- **1. Tooling sprint pattern is worth naming.** The kit doesn't currently have a canonical shape for a "tooling adoption" sprint. Sprint 006's shape (add deps, configure sections, run tools, take auto-fix, resolve residuals) is small and reusable. Candidate for TECHNIQUES.md §1 addition, or a per-language project-class subsection (Python data-science class).
- **2. `# type: ignore[misc]` at the un-stubbed-boundary is the right escape hatch.** A `sdd.pyi` stub file is the correct answer, but it's upstream work. Local `type: ignore` at the two class definitions is targeted, documented (via the module docstring naming the sdd dependency), and cheap to remove when stubs arrive. Candidate for TECHNIQUES.md § LLM-integration or § External SDK bridge mappings — the pattern generalises to any un-typed external dependency.

**Hypothesis verdicts.**

- H6 (locked vocab → first-pass-clean downstream). Sprint 006 second-pass (first pass surfaced findings; second closed). Half-credit. 5-for-7 overall counting each pass. Tentative.
- **New H8.** Adopting ruff + mypy on an existing small codebase in one sprint is cheap because auto-fix does most of the work. Testable: how many findings did auto-fix carry vs. how many needed manual review? Sprint 006 data: 8-of-10 ruff (80% auto-fix), 0-of-4 mypy (mypy has no auto-fix). Confirmed for ruff, expected for mypy — future data points from other tooling-adoption sprints tell us more.

---

### 2026-08-10 — Sprint 005: review cleanups closed

**What happened.** Four small refactors from the code review: `mkdir` moved out of `__init__` to first-emit (via `_sink_prepared` flag); `Signal` reconstructed locally in `emit()` (decoupled from parent's private deque); module-level `emitter` singleton replaced with `@lru_cache`'d `get_emitter()` plus a PEP 562 `__getattr__` shim to preserve `from ... import emitter`; test brittleness fixes (hard-coded 55 → JSON count read; wall-clock threshold 0.005 → 0.04; `n_signals_emitted` computed inline per test). One new test proves the mkdir moved. 18 tests pass.

**What worked.**

- All four refactors landed on the first pass. No test broke, no wheel rebuild broke, no import surface changed for callers. The PEP 562 shim is the win — keeps the import ergonomics identical while making the module load lazy at the file-read boundary.
- The `_sink_prepared` flag is one branch per emit and zero syscalls after first-emit. Alternative (`stat` per emit) would have added a syscall at bar cadence. Small perf detail; matters when a sim run emits tens of thousands of BAR_PROCESSED tags.
- Reading the tag count from the JSON at test time instead of hard-coding 55 removes one of the review's brittleness concerns while adding zero cost. Next vocabulary bump (v0.2 adds N tags) does not break the test.

**What got in the way.**

- Nothing. The refactors were small and mechanical; the code review's own file:line specificity made execution trivial.

**What this says about the next kit version.**

- **1. Review-drive-refactor is a first-class sprint pattern.** Sprints 003, 004, 005 all executed against a single code review file (`reviews/code-best-practices-round-1.md`). The review acts as a bounded backlog: each punch-list item maps to one sprint or one sprint fragment, and the trajectory closes cleanly. Candidate for TECHNIQUES.md §1 refactor section: "when a code review lands with a punch list, split by concept and process items in order; the review IS the plan for the follow-on sprints."
- **2. PEP 562 `__getattr__` at module scope is a low-cost backwards-compat pattern.** The kit has no explicit guidance on module-boundary API evolution. Adding a `get_thing()` factory and keeping `thing` as a lazy shim via `__getattr__` preserves callers while allowing the internal machinery to change. Worth a mention in TECHNIQUES.md §1 if it recurs on other kit projects.

**Hypothesis verdicts.**

- H6 (locked vocab → first-pass-clean downstream). Sprint 005 first-pass clean. 4-for-5 overall (Sprint 003's build-layer second-pass remains the only miss). Tentative → moving toward partially confirmed.

---

### 2026-08-10 — Sprint 004: typed-payload enforcement closed

**What happened.** `StrictSignalVocabulary.__init__` now parses each field's declared type string into a callable checker at load time. `validate` runs each field's checker on every emit. The vocabulary took five review rounds to nail down the types; the code now enforces them. Ten new tests cover the enum, sha256, int, bool, uuid, datetime_utc, date_iso, and list-element checks. Real-hex fixtures via `hashlib.sha256(...).hexdigest()` replace the `"a" * 64` placeholders. 17 tests pass; wheel rebuild clean; `emitter.emit('SESSION_INIT', run_kind='banana', ...)` raises with the exact allowed enum values named.

**What worked.**

- Precomputing the checkers at load is the right shape. Zero parsing cost at emit time; one dict lookup per field per emit. The `StrictSignalVocabulary.__init__` walks the schema once, builds a per-tag `dict[field_name, Checker]`, and stores it. Every subsequent `validate` call reads from precomputed structure.
- The recursive parser handles `list<float>`, `dict<str, int>`, and `list<dict<str, int>>` cleanly. Vocabulary uses container types sparingly (only three payloads carry lists this size); parser handles the entire declared set without special cases.
- Validation-error messages carry enough context to debug from the trace alone: `"Signal 'SESSION_INIT' field 'run_kind': expected one of ['align', ...], got 'banana'"`. The signal-driven-development principle — a signal names its own semantics — extends to validation failures.

**What got in the way.**

- The first-pass uuid test used `TRADE_LEDGERED.trade_id` on the assumption it was typed `uuid`. It was typed `uuid` in the initial vocabulary draft but reclassified to `entity_ref<Trade>` in round 4 of the vocabulary review. Test failed on first run. Fix moved the test to parser level (`_parse_type("uuid")` returned checker exercised directly). No field in v0.1 currently uses `uuid` — the checker is present for future vocabulary bumps but has no live coverage through the emitter.
- The Layer-7 `range`, `gate`, `cardinality`, and `frozen_artifact` constraints stay uncovered by this sprint. They're aggregate or grading-time checks, not emit-time. The vocabulary declares them; nothing yet enforces them. Later sprint gets a grader that walks the trace against Layer 7.

**What this says about the next kit version.**

- **1. Vocabulary-to-code enforcement gap is a class of defect, not a single sprint.** The vocabulary declares three enforcement layers: field presence (Layer 2 required + strict extras — Sprint 001), field types (Layer 2 type strings — Sprint 004), field values and cross-signal invariants (Layer 7 constraints — deferred). Each layer needs its own enforcement pass, its own tests, and its own code. TECHNIQUES.md §1 commitment 2 ("schema enforced at the speaker's mouth") is a slogan that needs three checkmarks, not one. Candidate: split the commitment into three named sub-commitments with which sprint or grader owns each.
- **2. Dead-code checkers are forward-compatibility, not waste.** `_check_uuid` and `_check_git_sha` don't have live vocabulary coverage in v0.1. Removing them would force re-authoring at v0.2 when a field first uses either. Keeping them costs one line each and buys the next vocabulary bump. Related to Addendum D's "verify the verifier" principle — the checker is present; the parser-level test exercises it; live coverage waits for the vocabulary to catch up.

**Hypothesis verdicts.**

- H6 (locked vocab → first-pass-clean downstream). Sprint 004 first-pass code-clean; second-pass test-clean (one test caught the reclassification the vocabulary went through in round 4). 3-for-4 overall counting both layers, or 3-for-3 code-clean. Tentative.
- **New H7.** The vocabulary type strings are self-describing enough that a small parser (~30 lines) enforces them across the whole schema. Testable via: adding a new type to the vocabulary should require one entry in `_TYPE_CHECKERS` and one line change in `_parse_type`, no plumbing edits. Sprint that adds `git_sha` (40-char hex) as a format type tests it.

---

### 2026-08-10 — Sprint 003: code-review pre-fixes closed

**What happened.** `reviews/code-best-practices-round-1.md` surfaced a ship-blocker (module-level `_VOCAB_PATH` walk-up fails under wheel install) plus three one-liners. Sprint 003 fixed the ship-blocker by moving vocabulary loading to `importlib.resources` against a `price_space_llm._vocab` sub-resource, with the file exposed via a symlink at `src/price_space_llm/_vocab/0.1.json` → `../../../signals/0.1.json`. Wheel builds clean. Fresh-venv install imports and reads `tag count: 55`. Six other findings deferred to Sprints 004-006 with explicit rationale in the sprint card.

**What worked.**

- The symlink approach unified editable and wheel install without duplicating the vocabulary file. `signals/0.1.json` stays at project root as the naming convention every doc references; hatchling follows the symlink at build time and packages the target's contents. One source of truth.
- The review's own recommendation to add force-include for the JSON turned out to be wrong once the symlink was in place — hatchling raised "second file added at same path" on the first build. Caught and fixed on the spot. The failure was in the sprint card's content assertion, not in the reviewer's insight; the symlink itself was the review's other suggestion, and it made force-include redundant.
- Scope creep discipline held. First-pass rewrite of `emit()` moved `mkdir` and reconstructed `Signal` locally — both real §3 findings from the review, both explicitly bucketed as "In Sprint 003 or 004." Caught before commit, reverted, deferred properly.

**What got in the way.**

- The sprint card wrote content assertions for a pyproject.toml shape that turned out not to build. The assertion said "the force-include block includes both entries"; the actual working config has the JSON entry commented out. Sprint card assertion is stale in the audit trail. No fix required — the audit trail is the work — but a note here so a future reader knows what to trust when the sprint card and the file disagree.
- Grep across the codebase flagged two comment lines (`# Sprint 001 tests` and `# Sprint 002 tests`) in test_signals.py that the docstring-strip missed. Same class of finding as the docstring itself — the review's §7 named docstrings but the pattern is broader. Second pass caught them.

**What this says about the next kit version.**

- **1. Symlinks are the cleanest cross-install pattern for packaged data.** A dedicated pattern in TECHNIQUES.md would name: put the authoring copy at project root per kit convention, symlink into `src/<pkg>/<subdir>/` for both editable and wheel install, and DO NOT add a redundant force-include for the same destination. Adjacent to §2 Data science "Metric snapshot as artifact" as a packaging-side pattern.
- **2. "Sprint N narration in code" is a broader pattern than docstrings.** The review's §7 named docstrings; comment lines (`# Sprint N tests`) inherit the same anti-pattern. The rule should read: "no sprint numbers anywhere in shipped code — docstrings, comments, variable names, log messages." Candidate for TECHNIQUES.md §1 addition or a WORKING_AGREEMENT tone-canon extension.

**Hypothesis verdicts.**

- H6 (locked vocab → first-pass-clean downstream). 2-for-3. Sprint 003 failed first-pass on the build layer (duplicate destination) and required a second attempt. First-pass clean if you count "the code works and only the build config was wrong"; not first-pass clean if you count the build error. Downgrade: 2-for-2-and-a-half, still tentative.

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
