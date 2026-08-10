# KIT_DIARY.md — wordcount

*Per-sprint or per-phase: what worked, what got in the way, what this says about the next kit version. The diary is this project's accumulating memory about how sdd-kit-2 serves the work. Soundfield's ~130 numbered v2-kit findings are the canonical example of what this discipline enables; this is the much smaller version for a 3-sprint example.*

---

## Entry 1 — Sprint 002 close (2026-05-22)

**What worked.** The dual-contract pattern paid for itself immediately: when sprint 002's first implementation used `os.walk` (which inlines file iteration with subdirectory descent), it never emitted `DIR_ENTERED` for the `nested/` subdirectory because the iteration happened "inside" the parent's yield. The signal contract caught this — the test asserted exactly one `DIR_ENTERED` per directory, and the test failed cleanly with "expected 2 DIR_ENTERED signals, got 1". I switched to manual recursion that explicitly emits per-directory and the contract closed. Without the signal contract, this would have shipped silently (the file counts were still correct; only the trace was wrong).

The `SignalCapture` pattern from `lib/sdd.py` made the test cheap to write: 4 lines of setup, run `scan_dir`, snapshot, assert on the snapshot. The fidelity test from TECHNIQUES.md technique #38 isn't abstract — it's the natural shape these tests want to take.

**What got in the way.** The vocabulary's `note` field for `DIR_ENTERED.entry_count` was silent on whether the count is recursive or non-recursive. I had to make a call (non-recursive) during sprint 002 and add a Drift watchlist entry. This is the kind of ambiguity the Vocabulary Session should have caught — sprint-time decisions about vocabulary semantics are vocabulary debt.

**Hypothesis.** *The Vocabulary Session should produce a sub-doc for "semantic boundaries" — questions the vocabulary's structure invites but doesn't answer. Status: tentative.* If sprint 003 surfaces a second case of this pattern, the hypothesis is confirmed. (Confirmation update at entry 2: did not recur; sprint 003 had no ambiguity issues. So the hypothesis remains tentative — one data point isn't enough to commit.)

**Kit suggestion.** Add to `grammar/BOOTSTRAP.md`'s Step 9 (dual-contract audit) a sub-step: "Walk every payload field. Is its semantic boundary obvious from the type alone? If not, write a note." This would have caught `entry_count` at lock time, not sprint time.

---

## Entry 2 — Sprint 003 close (2026-05-23, project complete)

**What worked.** Three sprints, three clean closes (with two minor in-sprint resolves caught by the Rubber Duck Pass). The kit's overhead — vocabulary lock + sprint cards + BLACKBOARD + Rubber Duck Pass + KIT_DIARY — was visible but never wasted. The vocabulary lock in sprint 001 paid back in sprints 002-003: the agent never had to ask "what should I name this signal" mid-sprint; the answer was in `signals/0.1.json`.

The CLI class techniques from TECHNIQUES.md Section 2 mattered. Specifically: "stdout for data, stderr for narration" gave the test in sprint 003 a clean grading surface — `python -m wordcount ... > /tmp/wc_report.json 2>/tmp/wc_stderr` separates the assertable JSON from the assertable summary line. Mixing them would have made the test card harder to write. And "flag-driven instrumentation" made the JSONL sink a clean optional rather than a baked-in side effect: tests can run with `--signals-out=/tmp/...`; production runs can omit it.

The Rubber Duck Pass in sprint 003 caught a real bug. The initial implementation emitted `REPORT_EMITTED` with `byte_count` measured *before* `sys.stdout.write()`, which meant the count was the length of the in-memory string, not what was actually written (which could differ by trailing-newline conventions). The Pass's sequence narration read "REPORT_EMITTED byte_count=247" and the next observation noted that the vocabulary's invariant says "byte_count must equal the size of the bytes written to destination" — but the write happened after the emit. Fix was one-line: move the emit to after the write. Without the Pass, this would have shipped with a subtle off-by-one in the trace.

**What got in the way.** Nothing significant. The kit's friction in this project was acceptable; in a 1-sprint project it would have been overhead-heavy (the discipline pays off across sprints, not within them).

One subtle thing: the kit asks for a COMPREHENSION_AFFIRMATION at first-session, and on this project that affirmation was ~300 words. For a 3-sprint project that's noticeably front-loaded; for a 30-sprint project it would be invisible. The kit's bias is toward longer projects; not a problem for the example, but worth noting.

**Hypothesis.** *The kit's overhead is proportional to vocabulary size, not project size.* If true, a project with 8 tags (this one) has roughly the same per-sprint overhead as a project with 80 tags, because per-sprint the agent re-reads only the tags it's working with. Status: tentative — needs a multi-sprint project at larger vocab to test.

**Hypothesis.** *Three sprints is the minimum useful project size for sdd-kit-2 demonstration purposes.* Sprint 001 establishes contracts; sprint 002 lands the first behavior; sprint 003 closes the loop. Any fewer and the discipline doesn't get to compound. Status: tentative; supported by this project but trivially so (the project was designed to be three sprints).

**Kit suggestion.** The COMPREHENSION_AFFIRMATION procedure (folded into AGENTS.md) is well-specified at the top of a real project but heavy for a 3-sprint demo. The kit could note that for projects under 5 sprints, the affirmation can be a shorter 1-2 sentence form. Or leave as-is — the longer form makes the demo's discipline more visible, which is the point.

**Project-level conclusion.** sdd-kit-2 served this project well. The cuts from `sdd-kit/` (no separate procedure files, no TECHNIQUES application gates, no overlarge grammar treatise) did not bite; the discipline was still legible end-to-end via AGENTS.md alone. The `example/` folder did what it needed to do: gave the kit a concrete object to point at when explaining what "discipline applied" looks like.

---

## Hypothesis tracking

| Hypothesis | Status | Evidence |
|---|---|---|
| The Vocabulary Session should produce a "semantic boundaries" sub-doc. | tentative | One observation (`DIR_ENTERED.entry_count`) at sprint 002; no recurrence at sprint 003. Insufficient evidence. |
| Kit overhead is proportional to vocabulary size, not project size. | tentative | Only one project run; can't compare across scales. |
| Three sprints is the minimum useful project size for kit demonstration. | tentative | Supported by this project trivially (designed for three). Real test needs a 1-sprint and 2-sprint variant. |

---

*KIT_DIARY.md for wordcount. Two entries across three sprints. Two hypotheses tentative; one kit suggestion logged. The diary is small because the project is small; it's the *shape* of the discipline that matters for the example, not the volume.*
