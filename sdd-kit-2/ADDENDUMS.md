# ADDENDUMS.md — dated, project-stamped technique captures

*This file is NOT a timeless catalog. Each addendum below is a point-in-time capture from ONE named project, over ONE dated stretch of work — the techniques that project surfaced, written down while they were fresh, before they had been proven anywhere else. Every entry carries its project name and its dates so a reader knows exactly where it came from and how much weight it has earned (one project, that date range — not "the kit says so").*

*This is the holding pen between a project's `KIT_DIARY.md` (where a technique is first observed, in per-sprint narrative) and `TECHNIQUES.md` (the numbered catalog, timeless and cross-project, where a technique lands only once it has stabilized across a SECOND project). Nothing here has been back-propagated into the catalog yet; treat it as promising and real-on-one-project, not settled. Read it the same way you read `TECHNIQUES.md`: a reference, not a gate — not required per sprint. Skim once if your project shares the class; dip in when relevant. No entry here is load-bearing enough to block a sprint.*

*Top-level and visible on purpose — it sits at kit root beside `TECHNIQUES.md` so the split is obvious at a glance: `TECHNIQUES.md` is what has settled; `ADDENDUMS.md` is what's new and staged. The newest hard-won lessons are the ones a fresh session is least likely to already know, so they sit at the front of the kit, not buried in a subsection.*

*Additive only. Never delete or overwrite an existing addendum, table row, or catalog entry. When a technique is promoted into `TECHNIQUES.md`, its row here stays and is annotated with the promotion. The audit trail is the work. No emojis, no attribution.*

---

## Addendums on file

| # | Source project | Dated stretch | Class | Extends | Promoted? |
|---|---|---|---|---|---|
| A | `substrate-ui` — a read-only console projecting a runtime's signal log into a browser UI | 2026-06-17 → 2026-06-23 (captured 2026-07-01) | Browser / visual-UI verification harness (Playwright + pixel-anchor decode) | `TECHNIQUES.md` §2 Visual/UI + Web/frontend | no |
| B | `Cascade` — native iOS (Swift 6 / SwiftUI / SpriteKit) with a determinism-locked physics core | 2026-06-13 → 2026-06-14 (captured 2026-07-01) | Native-simulator observation harness, determinism-core ports, sim-unverifiable modalities | `TECHNIQUES.md` §2 iOS / Visual-UI / Audio / Game-dev / Data-science; §1 error handling | no |
| C | `Audio Object` — native iPhone looper/sampler/mixer (polyhedron-face UI) | 2026-05-03 → 2026-06-23 (captured 2026-07-01) | Native-iOS on-device audio/MIDI harness, launch-arg instrumentation | `TECHNIQUES.md` §2 iOS + Audio; CLI flag-driven instrumentation; #4, #5, #7, #9, #23, #24, #26, #34, #44, #46, #47 | no |
| D | `Audio Object` — the GRADING round (same project as C, six weeks later) | 2026-07-13 → 2026-07-14 (captured 2026-07-14) | Grading vs observation: outside gates, verified verifiers, the limits of signals/tests/a11y/fixtures | `TECHNIQUES.md` §1 #5, #23, #24, #26, #34, #4, #37; Addendum C (which observes but does not grade) | no |
| E | `glitchforge` — the RESOURCE round (memory/OOM arc + speed round 2) | 2026-07-17 → 2026-07-19 (captured 2026-07-19) | Resources as graded channels: fixture-realism, the right kill metric, byte-exact streaming restructures, falsify-then-localize, coupled-channel gating | `TECHNIQUES.md` §1 #5, #23, #24, #38, #41; §2 iOS; Addendum D (D4/D7 are the parents) | no |

*(Add a row when you add an addendum. Never delete a row; if an addendum is folded into `TECHNIQUES.md`, keep the row and note the promotion.)*

---

# Addendum A — `substrate-ui`: the visual / UI verification harness (browser class)

**Captured from:** `substrate-ui` — a read-only console that projects a runtime's signal log into a browser UI.
**Dates:** 2026-06-17 through 2026-06-23 (source: `substrate-ui/process/KIT_DIARY.md`, eight entries, hypotheses H1–H8). Captured into the kit 2026-07-01.
**Weight:** one project, that stretch of work. Not yet reproduced elsewhere; not yet in the numbered catalog.
**Harness:** headless Chrome driven by Playwright (`chromium.launch({ channel: "chrome" })`).
**Extends:** the Visual/UI and Web subsections of `TECHNIQUES.md` §2.

The through-line: **a green structural test (DOM text assertions) is the most seductive possible cover for skipping the real check, because it is genuinely rigorous and still only half the job.** Everything below is a consequence of that.

### A1. Three verification lenses, not one

Split the observation contract for a visual surface into three tracks, each of which catches a defect class the others structurally cannot:

- **Structural** — the wiring works: component mounted, correct element/cell count, tab shows and hides by state. Gradable mechanically, in the CI-gated E2E. Blind spot: it cannot see paint, and structurally identical frames (same cell count, different positions) read as equal.
- **Perceptual (decode)** — the pixels on screen *are* the data (see A2). Blind spot: only applies where state is mechanically recoverable.
- **Adversarial-review** — the surface does not *misrepresent* the spec and cannot ship a fake. Needs an independent reviewer asking "could this lie?"

The load-bearing case (substrate-ui review #42): the canvas drew Route edges to every triggered Producer, *implying data flow that does not occur*. Structural passes it; perceptual can miss it; only the adversarial lens caught it. Name and run all three — two tracks and a "pass" line lets the third defect hide.

### A2. Deterministic pixel-anchor decode

For any visual whose meaning is mechanically recoverable state (a grid, a board, a chart with known anchors): **screenshot the rendered element, decode the actual PNG pixels at each known coordinate, reconstruct the state, and assert it equals ground truth.** Do not eyeball the screenshot, and do not check the DOM class — the first is lossy and subjective, the second proves the DOM, not the paint.

Concretely (substrate-ui `harness/capture_scene.js`):
- Element-screenshot the bounded surface (`.scene-grid`), not the full page.
- Decode the PNG with **zero external dependencies**: Node's built-in `zlib` inflates the IDAT chunk, then un-filter the scanlines by hand (None / Sub / Up / Average / Paeth). Roughly thirty lines; no `pngjs`.
- Classify each cell at its center coordinate — `x = round((c + 0.5)/cols * width)`, `y = round((r + 0.5)/rows * height)` — by the anchor color (a live cell is green-dominant: `g > 110 && g > r + 40 && g > b + 40`).
- Assert the reconstructed grid equals the record's ground-truth grid, cell for cell. Emit the decoded grid as an ASCII signal (`.###.`), so the agent "sees" a text state-snapshot, not an image.

The decode is the mechanical half of two-track grading; the screenshot is still written to disk for a human or vision-model polish look. Both, not either — the decode proves the state, the look proves the polish.

### A3. Choose fixtures sensitive to the bug class you cannot otherwise see

A symmetric fixture has a symmetric blind spot. The Game-of-Life **blinker is mirror-symmetric** — it maps to itself under an L-R flip, so a pure mirror render bug is invisible to it. Fix: add an **asymmetric, moving** fixture (a glider) and additionally assert each decoded frame is not equal to its own L-R mirror. The blinker proves oscillation; the glider proves the decode would actually diverge on a mirror bug. Generalize: pick a fixture whose asymmetry is sensitive to the failure mode you are trying to exclude.

### A4. The harness is code too — verify the observer, fix races at root

A PASS from a buggy observer is worth nothing. `capture_scene` read the page state before the record finished loading and decoded the *previous* record's grid at the new record's sequence numbers — a plausible-looking pass that was wrong. Fix at root, never with a sleep: fetch ground-truth sequence numbers from the API, then wait on a real condition (`STATE.events[last].seq === record.maxSeq`) before decoding. Hold the observer to the same "verify, don't trust" bar as the observed.

### A5. Repo-scope the observation tooling, or the required contract is skippable

The harness once lived in `/tmp/pw-substrate` (a prior session's install that vanished), and "I can't run it right now" twice became a proposed skip of a *required* contract — the finished-does-not-equal-worked failure the kit exists to stop. A required contract that can be skipped is not required. Pin the harness in-repo as a lockfile-pinned devDependency with a one-command run. "The environment doesn't have the tool" is never a license to skip — it is an instruction to make the repo carry the tool, then run it.

### A6. Capture viewable artifacts, or the perceptual track fails closed silently

A `fullPage` screenshot at `deviceScaleFactor: 2` blew past the agent's image-view size limit (>2000px), so a frame that was "captured" could not be opened — which is the entire point of the perceptual track. A screenshot too large to view is a screenshot not looked at; the track quietly degrades to "captured but not looked at." Element-screenshot or viewport-only shots of bounded surfaces; cap dimensions.

### A7. Structural assertions live in the CI-gated harness, not the capture script

The scene's structural assertions once rode in the capture script (`capture_scene.js`), which is not part of the CI-gated E2E (`e2e_console.js`). An assertion outside the gate does not protect against regression. Fold every structural assertion into the gated harness; the capture script produces artifacts, it does not hold the only copy of a check.

### A8. Correlate the log with the image; do not narrate the pixels

When a visual looks wrong, the fix comes from a mechanical log-to-geometry correlation, not from describing what the pixels seem to show. The run-graph spawn-dot confusion was diagnosed by lining up the `run_graph` signal (fired / started / ended) against the rendered geometry (dot at 0.96 = the producer queued for 94% of its bar; 53 of 53 lanes matched), not by guessing from the picture.

### A9. A reader/projector UI binds the tone canon instead of locking a vocabulary

A UI that only READS a locked vocabulary needs no `signals/` of its own — a second vocabulary would be ceremony. Its founding contract is the tone canon, not a vocabulary lock. (The kit's templates assume every project locks a vocabulary; the reader/projector case is the named exception. Tentative-confirmed, one project.)

### A10. A companion sub-project gets its own git home and core artifacts before its second increment

A UI or companion project that grows OUT of a disciplined parent silently inherits none of the parent's discipline — no git history, no BLACKBOARD, no KIT_DIARY — and its build history leaks into the parent's ledger. The trigger for founding its own home (git + BLACKBOARD + WORKING_AGREEMENT + KIT_DIARY) is: "this code now has more than one increment and lives in its own directory." Do it then, not retroactively.

### Cross-reference (Addendum A)

- Origin and full narrative: `substrate-ui/process/KIT_DIARY.md` (eight dated entries, hypotheses H1–H8).
- Catalog entries these extend: `TECHNIQUES.md` §2 — Visual/UI ("Deterministic pixel anchors...", "Two-track visual grading") and Web/frontend ("Browser-as-runtime requires out-of-process signal capture").
- The mobile-native sibling of this harness (the `xcrun simctl` / `ios-simulator-mcp` driving path, accessibility-identifier hazards, the `N.INT` visual gate) is catalogued in `TECHNIQUES.md` §2 iOS class and expanded in Addendums B and C below; it is not repeated here.

---

# Addendum B — `Cascade`: native-iOS simulator observation harness + determinism core

**Captured from:** `Cascade` — the kit's first native-iOS (Swift 6 / SwiftUI / SpriteKit) SDD project, and its first with a determinism-locked physics core, a sim-based observation harness, and human-on-device feel/audio verification.
**Dates:** the live-diagnosed failures below are dated 2026-06-13 → 2026-06-14; extracted from Cascade's `KIT_DIARY.md`. Captured into the kit 2026-07-01.
**Weight:** one project. None confirmed against a second project — Cascade-contributed candidates for `TECHNIQUES.md`, not yet universal kit canon. A later project that hits the same class either confirms an entry (promote it) or contradicts it (annotate here).
**Extends:** `TECHNIQUES.md` §2 iOS/visual/audio/game-dev subsections (written thin — the originals were CLI/backend/LLM projects); §1 universal error handling.

*Same rules as `TECHNIQUES.md`: a reference, not a gate. Skim once if your project is native-mobile / has a determinism core / grades a sim; dip in when relevant.*

## Section A — Native-simulator observation harness (→ TECHNIQUES §iOS)

**B-A1. XCUITest is the BEHAVIORAL driver; the MCP/idb channel is VISUAL-only.** For a SwiftUI/SpriteKit (or any GPU-render-loop) app, drive behavior through an XCUITest target, not through `simctl launch` + the `mcp__ios-simulator__*` a11y/tap channel. *Why:* a bare `simctl launch` with nothing attached can **suspend the app's render loop mid-run**, so the physics never reaches the state under test (a merge "failed" 3× under bare launch, succeeded every time under a driver); and the popular `mcp__ios-simulator__*` servers are built on **idb** (public releases dormant since ~2022), whose a11y walk returns **empty** for a `simctl`-launched app on current Xcode. XCUITest's own driver keeps the app foreground-active so taps land and the loop pumps. Doctrine: **XCUITest + the observation runner are the behavioral proof; the MCP channel is the visual proof (screenshots of state).** Re-learned three times under time pressure (12S–018S, 2026-06-14) — the failure mode is abandoning recorded doctrine when a "just show me" ask tempts a faster channel.

**B-A2. Keep a channel attached across the whole run; gate on a terminal signal, not a `sleep`.** The observation runner must hold an attachment alive for the run's duration (even a `log stream` attach keeps the render loop pumping) and decide "did the run complete?" by waiting for a genuinely-terminal signal to land on disk — never a fixed sleep. *Why:* liveness is stack-dependent and invisible until measured; a fixed sleep either races the behavior or wastes wall-clock. Corollary (B-A2b): the **terminal tag must be the last CHRONOLOGICAL event** (`SCORE_AWARDED`, `RESTART_COMPLETED`), never a boot-time tag (`RUN_STARTED`, `HUD_RENDERED`) — a boot tag as the wait target returns immediately, before the behavior, and the assert then passes the early tags and fails the rest. Argues for a first-class, validated `terminal_tag` field in the observation-contract format rather than the implicit tail of an `--expect` list.

**B-A3. `build-for-testing` is the real "does it compile" gate for a test-target scheme, not plain `build`.** *Why:* plain `xcodebuild build` can **fail the app-Validate step** on test frameworks (XCTest / Testing / XCUIAutomation) embedded without Info.plists — a packaging/validation quirk, not a compile error (every Swift file linked first). `build-for-testing` sidesteps it and is what the observation UITests need anyway.

**B-A4. Verify the BUILD (exit code), not the ARTIFACT.** A deploy/verify step must assert `BUILD SUCCEEDED` via the process exit code — never "the `.app` exists." *Why:* `ls .app && echo OK` finds a **stale `.app` from a prior successful build** when the current build fails, so you ship old binaries while claiming success — a silent claim-invalidator that ate ~an hour. Also: capture `xcodebuild`'s exit directly; **never judge it through a pipe** (the pipe's exit is the tail command's, not the build's).

**B-A5. Simulator-lifecycle hazards on a shared/multi-agent box.** When multiple agent sessions share one Mac: (a) **never pass `booted`** to `simctl`/`xcrun` — with several sims up it's ambiguous and drives the wrong (possibly another session's) device; always use explicit `id=$UDID`. (b) **Never run two `xcodebuild test` against one sim concurrently** — they deadlock over the device (observed: 26-min hang, empty `.xcresult`). One sim, one driver. (c) On Xcode 26 a `simctl boot`-ed device is **headless (no display port)** until a Simulator *window* binds to it (`open -a Simulator --args -CurrentDeviceUDID`) — the "Device does not have a 'default' display port" (code 22) error. (d) **Quitting Simulator.app shuts down GUI-booted devices** (only `simctl`-booted ones survive) — so "quit to rebind a window" is not side-effect-free on a shared box; snapshot boot state before/after.

## Section B — Observation legibility and assertion strength (→ TECHNIQUES §Visual/UI + §Game-dev)

**B-B1. The four-channel LLM-legibility model.** A behavior sprint reads on-screen state through four cross-validating channels, structured-first: (1) **accessibility tree** — the primary structured channel for UI *and* board; (2) **deterministic pixel-anchor strip** — state encoded into known pixels, decoded from any screenshot; (3) **JSONL signal trace** — the canonical typed record of what happened; (4) **raw screenshot + VLM** — perceptual backstop only. The sprint passes only when the channels **agree**; disagreement is the bug. *Why:* each channel has a blind spot another covers — cross-validation is not ceremony (it caught a real Box2D-bridge SIGTRAP that the JSONL-only view showed merely as a truncated trace).

**B-B2. Canvas-rendered nodes are NOT in the a11y tree — instrument them, and beware the container trap.** SpriteKit renders the whole board to one canvas; `SKNode`s (the game pieces) do not appear in the UIKit/SwiftUI accessibility tree by default, so `ui_describe_all` sees the HUD but is **blind to game state**. Fix: `isAccessibilityElement = true` + a structured `accessibilityLabel` ("tier 2 bead, col 3, row 1") on each piece node. *Trap:* a **zero-size container `SKNode` blocks discoverability of its children** — label leaves directly or set the scene's `accessibilityElements` explicitly. (This is the SpriteKit twin of the known SwiftUI hazard where an `accessibilityIdentifier` on a parent propagates to children unless `.accessibilityElement(children: .contain)` is set — generalize to: *identify leaves, not containers.*)

**B-B3. Assert NAME + VALUE + PATH — a signal FIRING is not the signal being CORRECT.** The single-vocab name-gate (validate the tag name at the speaker's mouth) is necessary but **not sufficient**. Assert the payload values/positions and the emitting code path too. *Why:* two live escapes a presence-check passed — a `SCORE_POP_SHOWN` that fired with the right amount but the **wrong position** (a Y-up scene point for a floor merge that belonged at the tray bottom), and a `RUN_ENDED` carrying **stale 0.1-vintage payload fields** under a debug driver (valid *name*, wrong *payload*, debug-only *path*). Only a value-level + path-level check caught either.

**B-B4. Verify the verifier.** A witness (pixel-anchor strip, debug overlay, a11y label) with no live path to actually fire is not a witness. Confirm the verifier is on and observable before trusting a green result. *Why:* the pixel-anchor strip sat `isHidden=true` with no unhide path for a long stretch — it had **never been usable** while nominally "part of the contract." A witness you never see fire proves nothing.

**B-B5. Structured channels are the system of record; the VLM is perception + tiebreak.** Use the a11y tree + pixel-anchor + JSONL for **exact** state (counts, positions, tiers) — the channels you control. Use the vision model only for **perceptual** judgments the structured channels can't make ("does this read as a relic, not candy"; "is the danger-line pulse visible") and as a tiebreak when structured channels disagree. *Why:* current-research consensus (CVPR-2025 GUI-agent surveys; UI-TARS / Ferret-UI line) is that VLM grounding is strong for perception but unreliable for exact visually-similar-component counts — the surviving production pattern separates a perception model from the system of record. Don't make the VLM the source of truth for game/UI state.

## Section C — Trace-capture hygiene (→ TECHNIQUES §iOS + §38 test-fixtures)

**B-C1. Find the run by its UNIQUE DEFINING TAG across ALL app containers — never by newest-mtime; wipe before a graded capture.** *Why:* every `xcodebuild test` reinstall mints a new `Application/<UUID>` data container, and `-only-testing` runs sometimes uninstall the app entirely (so `get_app_container` errors). Reading "the newest run in the container" returned a days-old, wrong-engine run from a churned UUID — 247 stale run files had accumulated. Assert on a tag that exists *nowhere but the new code* (`daily_complete`), searched across all containers; and **uninstall to wipe `runs/`** before a clean capture so exactly one launch's trace exists.

**B-C2. An id-changing lifecycle event fragments the trace — read the UNION.** A pooled restart (or any new-run event) mints a new `runId`, so post-event tags land in a different `runs/{newRunId}/signals.jsonl` (or the boot file, for run-id-less tags). The canonical trace is the **union** across run files; an id-changing event is a documented trace-seam the runner must concatenate across, not a single-file read.

**B-C3. A cross-channel witness pair catches each other's blind spot.** Pair a view-state witness (a11y card-appeared) with the byte witness (JSONL grep). *Why:* while the byte-grep was hunting the wrong container (B-C1), the a11y "result card rendered" told me the logic had actually run — it kept the diagnosis honest. Two channels on the same fact is the cheapest guard against a single channel's failure mode.

## Section D — Determinism core and 1:1 ports (→ TECHNIQUES §Game-dev + §Data-science determinism)

**B-D1. A determinism fixture is the acceptance gate for any port claiming fidelity (diff-to-zero).** When a solver/engine is re-implemented on a new stack (or the canonical source changes mid-project), make the reference deterministic — **seeded RNG + fixed-step accumulator + a JSONL body-trace sink** — and grade the port against the captured fixture by **byte-identical diff-to-zero**, across multiple seeds, long runs, and the terminal path. *Why:* "feel is the game and you can't reverse-tune one solver into another" becomes a checkable claim: the port either diffs to zero or it localizes exactly where its numerics depart. Also proves self-reproducibility (same seed twice → zero-diff, in-process AND cross-process).

**B-D2. The numeric-reproducibility contract for a zero-diff port.** Identical serialization is not enough; the arithmetic must be reproducible. Concretely: **`Double` everywhere, never `Float`** (float32 integration diverges within tens of steps — real divergence, not a serialization artifact); **preserve arithmetic order** (`x += vx + gx*h*h` — do not reassociate); **separate RNG streams for separate concerns** (seed rotation off a distinct stream so seeding it doesn't perturb which pieces appear); **replicate the exact RNG draw schedule** (a silent extra draw at reset desyncs the whole stream); and **seed from an explicit number, never wall-clock** (`Date.now()`-derived seeds are the nondeterminism). Fixed-step loop, one step per call — no frame-batched substeps.

**B-D3. Engine-OVERRIDE is the determinism-safe extension pattern.** To add tuning/feel knobs (or a runtime input like a tilt vector) to a determinism-locked engine WITHOUT touching it: make each knob a `nil`-default runtime override resolved `effectiveX = override ?? const`. The byte-locked determinism fixture never sets them, so the canonical core stays bit-identical while the dev surface grows freely. *Why:* this is the reusable answer to "how do you make a locked engine tunable" — overrides, not edits. Edits fork the fixture; overrides don't.

## Section E — Sim-unverifiable modalities (→ TECHNIQUES §Audio + §iOS)

**B-E1. A sim-unrenderable feedback channel pairs with a TRACE-WITNESS, gated identically.** When a modality can't be rendered/asserted on the simulator (audio, haptics, taptic), the locked signal it pairs with **is** the observation-contract witness — gated identically to the modality (`guard sfxEnabled` before `emit(SFX_PLAYED)`) so the trace mirrors what the player would hear/feel. *Why:* "is the sound playing?" becomes a `grep`, not a vibe — `HAPTIC_FIRED` solved it for haptics first; `SFX_PLAYED` reused the pattern 1:1, and the existing UITests witnessed audio with zero change. Live proof: a phantom "sound on every drop", mis-diagnosed by grep-and-guess five times, was nailed in one pass by building for the sim and reading the `SFX_PLAYED` trace (it was the warning-tick firing for a fraction of a second per drop). Doctrine: **on a contradiction, go to the trace on the FIRST pass, not the fifth — the trace ends the argument; prose extends it.**

**B-E2. The sim-verifiable vs device-only HONESTY SPLIT for hardware-sensor features.** For a feature needing real hardware (accelerometer/tilt, camera, GPS): prove everything **mechanically reachable** in CI (the orientation→gravity mapping unit-tested across attitudes; the lose-on-invert path IS sim-testable by applying the gravity vector via the override and asserting the terminal signals), and **name explicitly** what only the human on-device can judge (the rotate-the-phone feel). *Why:* stating the boundary up front — rather than claiming feel-verification you can't do on a sim — is what keeps the trust. The trace tells you WHAT fires; only the human on-device judges whether it's good.

## Section F — Making feel measurable (→ TECHNIQUES §Game-dev)

**B-F1. The game-evaluation loop: metrics from the LOCKED trace, virtual personas, replay fixtures — human only on affective sign-off.** Fold automated playtesting into the observation harness with no new vocabulary: (a) **feel metrics computed from the existing JSONL trace** (input→drop latency, input-rejection rate, drops/min, time-to-first-merge, settle-time distribution, placement spread); (b) **seeded virtual-player personas** (rapid-dropper, spread-dropper, merge-seeker, edge-case) extending the auto-drivers; (c) **input-replay fixtures** — a confirmed-good session whose latency/rejection numbers become a regression gate (the game-dev analogue of `assert_signal`). The worker iterates code→build→run-personas→extract-metrics→compare-to-targets **autonomously**, surfacing ONE build for the human's affective sign-off. *Why:* remove the human from the measurable middle (responsiveness, fairness, coverage, regression) and spend their attention only on the irreducibly subjective "does it feel good."

## Section G — Release-readiness and human-authoring (→ TECHNIQUES §iOS + §Visual/UI)

**B-G1. Release-readiness is a checklist, and "default off in code" is not "off in the shipped install."** For an iOS ship, audit: (a) **persisted `UserDefaults` / dev-only flags that survive Debug→Release** — the bundle id is shared across installs, so a dev-session Tweak (`CascadeGroove=true`) drove *Release* behavior even though the code default was off and the `#if DEBUG` panel was stripped; ship a one-time reset/migration. (b) **Framework privacy strings for any API actually reached at runtime** (CoreMotion → `NSMotionUsageDescription`) — this is a **crash-on-use, not a lint**. (c) opaque icon / no alpha. (d) dev surfaces `#if DEBUG`-gated. *Why:* `#if DEBUG` strips the *panel* but the *persisted flag* still ships — necessary, not sufficient.

**B-G2. The human-AUTHORING loop — a throwaway local tool is the mirror of the observation contract.** The observation contract kills lossy prose on the *grading* side; the same move applies to *creating* visual/affective artifacts. For layout/design work where round-tripping prose ("move it up a bit") is the lossy step, stand up a **disposable local tool** (a tiny `http.server` + a drag/resize canvas) that lets the human manipulate directly and POSTs the exact result; the agent reproduces it deterministically at full quality. *Why:* human arranges by hand, agent renders — far faster and more faithful than the agent guessing coordinates from descriptions.

## Section H — Doctrine (→ TECHNIQUES §1 universal, error handling)

**B-H1. The observation contract IS the RUN step — don't improvise a faster channel under pressure.** "Drive the sim" means compose and run the observation contract through the established driver **once**, then READ the result — it is a sprint activity, not ad-hoc infra. *Why:* the dominant failure mode under a "just show me it working" ask is dropping into worker-at-the-terminal and hand-fighting a brittle shortcut (`simctl io screenshot`, the idb tap channel) — burning an hour re-deriving a fix the diary already recorded. The native RUN cycle costs 30–120s **by design**; that cost buys the four-channel proof. Pair with B-E1's rule: on any contradiction between a claimed fix and observed behavior, the first move is the trace, not more static reasoning.

### Cross-reference (Addendum B)

Origin: Cascade's `KIT_DIARY.md`. Catalog entries extended: `TECHNIQUES.md` §2 iOS / Visual-UI / Audio / Game-dev / Data-science determinism; §1 universal error handling. None back-propagated — promotion waits for a second project to reproduce the finding.

---

# Addendum C — `Audio Object`: native-iOS on-device audio/MIDI harness

**Captured from:** Audio Object — a native iPhone looper / sampler / mixer built around a physical-instrument metaphor (a polyhedron body, one instrument surface per face, no tabs/buttons/menus). Swift 5.9+ / SwiftUI / AVFoundation, iOS 17+. One of sdd-kit-2's four founding projects; it practiced the SDD ancestor patterns (`LAYOUT_SIZE` / `FACE_TRAVERSE` / `EDGE_GRAB` signal tags) before the kit formalized them.
**Dates:** ledger material spans 2026-05-03 → 2026-06-23; captured into the kit 2026-07-01.
**Note on source.** Audio Object has NO formal `KIT_DIARY.md` — it predates the kit's per-project artifacts. This capture is grounded in its functional equivalent: the in-repo `docs/dev-techniques.md` catalogue plus the agent memory ledger and the `docs/sdd/` audits. Every entry below is additionally grounded in a real harness file, not paraphrase.
**Weight.** One project, that stretch. Not yet reproduced elsewhere. Not yet in the numbered catalog. Treat all of it as tentative; C11 is doubly so (the source itself marks it "noted, not yet applied").
**Harness / tooling.** `os.Logger` signal emitter (unified log, subsystem `audioobject.p2`, emits at `.info`); a launch-arg-gated runtime signal filter (`SignalScope`); XCUITest walks as the capture driver; `xcrun simctl` / `devicectl` for build-install-launch-observe; a dedicated simulator addressed by UDID; physical iPhone 16e over cable for audio judgement. No Python orchestrator, no `lib/sdd.py` — the signal library is hand-written Swift.
**Extends.** iOS class; Audio class; CLI "flag-driven instrumentation"; and catalog entries #4, #5, #7, #9, #23, #24, #26, #34, #44, #46, #47.

### C1 — Launch-arg signal scoping: a runtime category allowlist for small on-device paste-backs

*Grounds/extends: #7 (stratified emission), CLI "flag-driven instrumentation", iOS "spawn booted log stream", Audio "human captures OSLog, pastes back".*

**File.** `AudioObjectP2/AudioObjectP2/Signals/SignalScope.swift`.

**Bug it kills.** On-device the human pastes the log back by hand. A full-run capture is unreadable and too big to paste: `METER_RMS_SUBMITTED` fires ~30 Hz per channel, `LAYOUT_SIZE` every layout pass, `VOLUME_APPLY` per fader-drag tick. The signal you care about drowns.

**Technique.** A runtime signal-category allowlist engaged by a launch arg, no rebuild required. Set `-SignalScope <surface>` (e.g. `perform`, `loopAdjust`, `metronome`, `io`, `tutorial`, `all`) on the scheme; each surface preset maps to the set of `SignalCategory` that may emit while it is active. Foundation maps `-Name value` launch args into `UserDefaults` (the `NSArgumentDomain`), so the gate engages at app boot — before any audio actor spins up — with no on-device UI. Three load-bearing details:
- **Deadline auto-clear** (`-SignalScopeMinutes`, default 10). A forgotten scope cannot silently hide a future bug: the next emit after expiry clears it (and the triggering signal is let through so the capture stays complete).
- **Noisy-tag excludes.** High-frequency probe tags (`METER_RMS_SUBMITTED`, `LAYOUT_SIZE`, `VOLUME_APPLY`, `SCHEDULE_BUFFER`) are dropped even when their category is allowlisted; opt one back in with `-SignalScopeIncludeNoisy <TAG>`.
- **`.engine` is always on.** `BOOT_*`, `CMD`, and `SIGNAL_SCOPE_*` lines stay visible regardless of scope, so a scoped run does not read as a hang.

**How to apply.** Before an on-device walk, scope to the one surface under test. The paste-back shrinks to all-signal for that surface. This is the on-device analog of the CLI catalog's `--signals-out` flag, but as a live category filter rather than a sink — the difference the catalog does not yet carry is the deadline-auto-clear and the noisy-tag exclude, both of which exist because the consumer is a human pasting text, not a file.

### C2 — XCUITest walk as the deterministic signal-capture driver (not idb / MCP tap)

*Grounds/extends: iOS "ios-simulator-mcp + simctl integration" (sharpens it); #24 (observation contract).*

**Files.** `AudioObjectP2/AudioObjectP2UITests/TutorialFlowUITests.swift`; `docs/dev-techniques.md`; memory `reference_simulator_tooling`.

**Bug it kills.** The catalog's iOS section lists `mcp__ios-simulator__ui_tap` / `ui_swipe` and idb as the UI-driving path. On this project idb `ui tap` / `describe-all --nested` repeatedly drops the companion ("Connection lost" / "Connect call failed"); MCP `ui_tap` is flaky; two-finger gestures are not sim-testable at all. Hand-driving the flow every run is slow and non-deterministic, and a dropped tap silently truncates the capture.

**Technique.** Write an XCUITest that walks the flow deterministically against stable `accessibilityIdentifier`s (e.g. `testTourWalkCapture` taps `tutorial-advance` to completion, then fires `restore`), run it with `-only-testing:AudioObjectP2UITests/TutorialFlowUITests/testTourWalkCapture`, and stream the unified log concurrently. The XCUITest IS the driver; the signal stream is the observation. XCUITest re-taps on retry and fails loudly rather than truncating, so the capture is reproducible. Pair with the C3 launch-arg seams to land directly in the precondition state and with C1 to keep the stream small.

**How to apply.** When the catalog says "drive the UI to run the observation contract," reach for a committed XCUITest walk over ad-hoc MCP/idb taps whenever the flow is more than a couple of steps or must be reproducible.

### C3 — DEBUG launch-arg test seams for deterministic preconditions

*Grounds/extends: iOS class; #24 (observation contract); "accessibility identifier on every interactive element" (complements it).*

**Files.** `App/AppDependencies.swift` (`-UITestStartFace`, `-UITestSeedClips`); `Audio/AudioSessionConfig.swift` (`-UITestSkipMicPrompt`); `VisualObject/FaceBoundsInvariant.swift` (`-UITestBoundsProbe`); plus `-hasSeenGuidedTour` (argument-domain override of a UserDefaults one-shot).

**Bug it kills.** Verifying a state-dependent surface means hand-driving the app into that state every run — slow and non-deterministic. And a permission alert at launch can phantom-touch the app underneath (see C6b), dismissing the launch UI before the test sees it.

**Technique.** Gate deterministic entry points behind `#if DEBUG` launch args so one `app.launch()` lands in the state under test: `-UITestStartFace perform.0` opens directly on a face; `-UITestSeedClips` fills every slot with a synthetic looping clip; `-UITestSkipMicPrompt` removes the system mic alert that otherwise blocks bootstrap. Because argument-domain `-Name value` args have highest `UserDefaults` precedence, `-hasSeenGuidedTour NO` forces a one-shot flag either way → order-independent tests. Keep every seam `#if DEBUG` so it cannot ship.

**How to apply.** Add a seam whenever a verification needs a precondition that is tedious to reach by hand. Identifiers (catalog) are the *handle* for driving; these seams are the *precondition* — the two compose.

### C4 — A `BUILD_ID` boot signal kills the stale-build-masquerades-as-wrong-change failure

*Grounds/extends: #9 (SESSION_INIT declares starting state); Audio "human-on-device verified"; #23 (dual contract).*

**File.** `AudioObjectP2/AudioObjectP2/App/AppDependencies.swift` (`logBuildID()` → `Signals.engine.buildId(...)`).

**Bug it kills.** The single most expensive failure in the click-drum-machine round was a *stale build*: the simulator showed correct code while the iPhone ran an old binary, so every fix read as "still wrong / completely incorrect." The investigation cost was paid on the code, which was fine.

**Technique.** Emit a `BUILD_ID` line at boot carrying the executable's modification time (linker-set when a fresh binary is produced), the bundle version, and a developer-bumpable `BUILD_TAG` string. Grep `BUILD_ID` and compare the mtime against the previous run before judging any behavior: different = fresh binary, same = you are testing a cached build. Bump `BUILD_TAG` before testing a tricky fix to mark the checkpoint in the log.

**How to apply.** This is the SESSION_INIT baseline (catalog #9) extended with build-freshness. On any project where sim and device can diverge, make "is the running binary the one I just built" a signal, not an assumption.

### C5 — Device has no rootless `os.Logger .info` live tail — capture on the sim

*Grounds/extends: iOS "spawn booted log stream" (sharpens with the device-side impossibility); Audio "human captures OSLog, pastes back".*

**Files.** `docs/dev-techniques.md`; `docs/reference/on-device-audio-midi-debugging.md`; memory `project_tailing_signal_logs`.

**Bug it kills.** Time burned trying to tail a physical device. The facts, each verified live: `log stream --device` is unsupported for iOS (exit 64); `idevicesyslog` reads the legacy syslog relay and does NOT carry `os.Logger .info` (≈0 lines); `log collect --device-udid …` works but requires root ("Must be root to collect logs from attached device").

**Technique.** Verify platform-independent logic on the dedicated simulator, where capture is free: `xcrun simctl spawn <udid> log stream --level info --style compact --predicate 'subsystem == "audioobject.p2"' > sim.log` (background), driven by the C2 XCUITest walk, then `grep` for the proof signal. `--level info` is REQUIRED — signals emit at `.info` and the default level drops them. Fall back to the device only for device-specific behavior (audio): the human captures via Console.app or `sudo log collect --device-udid <udid> --last Nm` then `log show … --predicate … --info`, and pastes back.

**How to apply.** Default the SDD capture loop to the sim stream; reserve the device+human-paste path for behavior that genuinely cannot be observed on the sim.

### C6 — iOS simulator / CoreSimulator operational traps

*Grounds/extends: iOS class.*

**Files.** memory `reference_simulator_tooling`, `feedback_dedicated_simulator`; `docs/dev-techniques.md`.

**(a) CoreSimulator serializes per device.** A wedged `simctl install`/`launch` from *another project* on the *same booted sim* hangs your `xcodebuild test` post-compile — it stalls at the UITests `CopySwiftLibs`/install step and looks like a broken build but is not. Diagnose with `pgrep -fl simctl`; fix by retargeting `-destination id=<other booted sim>`. Do NOT `pkill` a build mid `CopySwiftLibs` — an incomplete stdlib copy forces a full redo. (Hit live 2026-06-13, a Cascade-project install wedged every run.)

**(b) System-alert phantom touch (sim-only).** Tapping "Allow" on a permission alert delivers a stray touch to the app underneath, which can dismiss whatever is shown at launch. Pre-grant the permission and don't tap, or gate launch UI on permission resolution (the `-UITestSkipMicPrompt` seam in C3 exists for this). Does NOT reproduce on a real device.

**(c) Dedicated simulator, addressed by UDID only.** Scripting `simctl` against "the booted sim" can touch or shut down a simulator the user is actively using. Spin up a dedicated sim and address it by UDID, never by "booted". (Practice / courtesy rule — tentative as a general finding.)

### C7 — Swift incremental-build traps around the signal-vocabulary enum

*Grounds/extends: #4 (tags as stable identifiers); iOS "Swift 6 invariants" (adds an incremental-build hazard); #23 (dual-contract grading).*

**Files.** `AudioObjectP2/AudioObjectP2/Signals/Vocabulary.swift` (`SignalTag` enum); memory `project_xcode_test_gotchas`; `docs/dev-techniques.md`.

**Bug it kills.** Two traps that made green code look broken (one caused a commit on a false red):
- **Mid-enum insertion corrupts the incremental test build.** After inserting a `SignalTag` case in the *middle* of the enum, ~25 unrelated signal-assertion tests failed with impossible errors (one tag resolving to another's rawValue — `expected LOOP_CUT_TO_NEXT_PAD_NOOP` in a traverse test). A `xcodebuild clean` then full run was 100% green.
- **`xcodebuild test … | tail` reports the pipe's exit code, not xcodebuild's.** A run prints `** TEST FAILED **` while the shell shows exit 0 (tail succeeded).

**Technique.** Append new `SignalTag` cases at the END of their section (or clean before judging red after any widely-referenced enum edit). Never trust `&&` / exit code after a pipe to `tail`/`grep`: use `set -o pipefail` + `${PIPESTATUS[0]}`, or grep the output for `** TEST SUCCEEDED **` / `** TEST FAILED **` explicitly.

**How to apply.** Every sprint that adds a signal edits this enum, so both traps recur. When a broad cross-domain swath of signal tests fails right after an enum edit, suspect the stale incremental build first — clean and re-run before debugging the "failures."

### C8 — `.xcstrings` canonical-writer byte-for-byte round-trip; the em-dash mojibake trap

*Grounds/extends: #44 (SEARCH/REPLACE preserves accreted detail — the format-preserving-edit-over-reflow-rewrite instinct); new localization material adjacent to iOS class.*

**Files.** memory `project_xcstrings_localization_gotchas`; `docs/localization-pipeline.md`; `scripts/merge_translations.py`.

**Bug it kills.** `merge_translations.py` re-serializes with plain `json.dump`, reflowing all ~91 catalog keys and burying a one-key change in a huge cosmetic diff. Separately, pulling English source with `s.encode().decode("unicode_escape")` reinterprets UTF-8 em-dash bytes as Latin-1 (`—` → mojibake), so the catalog key no longer equals the `LKey` rawValue and the string silently falls back to English at runtime.

**Technique.** Xcode's `.xcstrings` serialization differs from `json.dump` in exactly one thing: the colon separator. Emitting with `json.dumps(cat, ensure_ascii=False, indent=2, sort_keys=True, separators=(",", " : ")) + "\n"` round-trips the current catalog byte-for-byte (verified `raw == canon`). So `json.load` → mutate the dict → re-emit with that exact serializer yields a diff that is purely your edits, no reflow. For the em-dash: read as UTF-8 and only undo `\"`→`"` and `\\`→`\`; never `unicode_escape`. Source-as-key means a new `LKey` resolves to its English literal with no catalog entry, so catalog work can land in a later commit without breaking the build.

**How to apply.** Any tool-owned serialized file (an IDE catalog, a lockfile, a generated config): find the tool's exact serializer deviations, reproduce them, and do load → mutate → re-emit so the diff is only the change. This is #44's preserve-accreted-detail instinct applied to whole-file generators.

### C9 — The two-ended diagnostic loop for cross-boundary I/O (iOS MIDI → USB Mac)

*Grounds/extends: #46 / #47 (external-SDK bridge mapping; substrate-gap honesty).*

**Files.** `docs/reference/ios-midi-to-mac-over-usb.md`; memory `reference_ios_midi_to_mac_usb`.

**Bug it kills.** Shipped a CoreMIDI virtual source (`MIDISourceCreateWithProtocol` + `MIDIReceivedEventList`) against an unverified brief assumption — it is inter-app ONLY and delivered zero MIDI to the Mac. The symptom (no MIDI at the DAW) has three distinct causes: we don't send, the Mac doesn't receive, or the DAW is on the wrong port.

**Technique (the transferable part).** The two-ended diagnostic loop: confirm the *send* end emits (`idevicesyslog -u <udid> | grep MIDI_`, and make sure the run scheme's `-SignalScope` includes the `midi` category or the tag is filtered out — see C1) AND confirm the *receive* end sees it (a ~30-line `swift` CoreMIDI probe counting `0xF8` clock bytes per source; ~34/s == 85 BPM). This splits "we send" from "Mac receives" from "wrong port" in minutes instead of guessing. Domain fact (Audio-Object-specific): to reach a USB Mac you must broadcast to *destinations* via an output port (`MIDIOutputPortCreate` + `MIDISendEventList`), not a virtual source; the Mac receives on a port named "iPhone", never the app's source name.

**Weight caveat.** The two-ended-loop shape generalizes to any cross-boundary I/O (send end + receive end + routing, each independently probed). The CoreMIDI specifics are Audio-Object-specific. Tentative on the generalization.

### C10 — The gotcha → technique → document loop, split across an in-repo catalogue and agent memory

*Grounds/extends: #34 (diary discipline — this is a pre-kit ancestor of the KIT_DIARY, in a two-surface variant); #36 (round-N); #37 (no deletions).*

**Files.** `docs/dev-techniques.md` (the catalogue); the agent memory ledger (`MEMORY.md` + `project_*` / `reference_*`); memory `feedback_gotcha_discovery_loop`.

**The practice.** Standing directive: *every gotcha is an unsolved tooling problem.* On any hit (sim quirk, flaky command, framework footgun, a "feels off" prose can't pin down): (1) work around it once to unblock; (2) turn the workaround into a reusable surface — a launch-arg seam, a signal tag, a script, a recipe; (3) document it. Documentation lives on two synchronized surfaces: `docs/dev-techniques.md` is the in-repo catalogue (what + how to invoke), and the agent memory is the recall index (one durable lesson per file, linked). The converse also holds — any newly invented development technique is written down even if no gotcha prompted it.

**Why it is the delta.** The catalog's #34 diary discipline is a single `KIT_DIARY.md`. Audio Object ran the same instinct before the kit existed, but split it: a human/agent-readable in-repo catalogue for transfer, plus a memory index for cross-session recall, kept in sync. That two-surface split is the observation the single-file diary entry does not carry.

### C11 — Typed constraint vocabulary: `violation_example` + `rectification` + `SELF_CHECK` (TENTATIVE)

*Grounds/extends: #5 (self-grading needs an external check surface); #26 (Rubber Duck Pass); #0/#2 (process-not-prompt: attendable intermediate state in-window).*

**File.** `docs/sdd/finding-self-check-vs-operator-steer.md`.

**The finding.** Extend SDD from the *emit* layer (the signal vocabulary) to the *constraint* layer. Each agent-contract CONSTRAINT carries not just a rule but a `violation_example` (one concrete instance of what the violation looks like at the call site) and a `rectification` (the corrective direction). OPERATIONS gains a `SELF_CHECK` step that validates each emit artifact against CONSTRAINTS before commit. The operator-side STEER table (what redirect to paste on a misfire) stays separate: it is a *recovery* tool, and importing it into the agent contract risks negative-anchoring the agent on its own failure patterns. Belt-and-braces — the agent self-validates pre-commit, the operator catches what self-check misses. The `CONSTRAINT.NAME` + `violation_example` pair is to the rule what the `tag` + `payload` pair is to the signal: the typed instance that makes it executable rather than abstract.

**Weight caveat — doubly tentative.** The source itself is marked "noted, not yet applied to in-flight prompts," with open empirical questions: does a `SELF_CHECK` step reliably trigger pre-commit reflection in current models, and does `violation_example` still cause negative anchoring? This is a design proposal that has not run, captured because it is a clean generalization of the kit's external-check-surface principle (#5), not because it is proven.

### Cross-reference (Addendum C)

**Source diary / ledger (Audio Object repo):**
- `docs/dev-techniques.md` — the in-repo technique catalogue (functional diary; C1–C8, C10).
- `docs/sdd/finding-self-check-vs-operator-steer.md` — C11.
- `docs/reference/ios-midi-to-mac-over-usb.md`, `docs/reference/on-device-audio-midi-debugging.md` — C5, C9.
- Agent memory: `project_tailing_signal_logs`, `project_xcode_test_gotchas`, `project_device_build_loop`, `project_xcstrings_localization_gotchas`, `reference_simulator_tooling`, `reference_ios_midi_to_mac_usb`, `feedback_gotcha_discovery_loop`, `feedback_dedicated_simulator`.
- Harness code: `Signals/SignalScope.swift` (C1), `AudioObjectP2UITests/TutorialFlowUITests.swift` (C2), `App/AppDependencies.swift` (C3, C4), `Signals/Vocabulary.swift` (C7).

**Catalog entries this addendum extends (in `TECHNIQUES.md`):** iOS class, Audio class, CLI "flag-driven instrumentation"; #4, #5, #7, #9, #23, #24, #26, #34, #44, #46, #47. None are back-propagated — per the additive-only rule, promotion into the numbered catalog waits for a second project to reproduce the finding.

---

# Addendum D — `Audio Object`: the grading round

**Captured from:** the same project as Addendum C, six weeks later. Where C catalogued a harness for
OBSERVING a program, D is about JUDGING one. **The two are not the same thing and the project spent a
long time believing they were.**

**Dates:** 2026-07-13 → 2026-07-14. Captured into the kit 2026-07-14.

**Numbering note.** These entries were authored in the source project as B1–B12, and their internal
references to "A1–A11" mean the observation harness that is **Addendum C** in this kit. Renumbered
here as D1–D12; the cross-references are rewritten to C. Nothing else is changed.

**Weight.** One project. Tentative. But note that D1 was arrived at by **falsifying a belief the
project had been operating on for weeks**, and the falsification came with a shipped bug attached —
so it is not merely a nice idea that has never been under load.

**The kit-level observation that motivates this addendum:** every one of C1–C11 makes the app easier
to **observe**, and **none of them grades anything.** That gap is what D fills.

**The one-sentence version.** A signal the program emits about itself can DRIVE the work and can
never GRADE it — and neither can a test that has retyped the code it is testing, a correctness suite
looking at a latency bug, an accessibility query looking at a layout bug, or a mechanical audit
nobody has ever watched fail.

### D1 — Signals drive; they cannot grade. The engine that produced the bytes cannot judge them

*Grounds/extends: #5 (self-grading needs an external check surface) — this is the hard case of #5,
with a shipped bug as the evidence.*

**The belief being falsified.** That a well-instrumented program can be graded by its own
instrumentation. Every signal in Audio Object is typed, ratified, and honest. The project had been
closing sprints on "the tags fired with plausible payloads."

**What happened.** CROP — destructive audio editing — shipped to the Architect's phone graded by
nothing but `SAMPLER_CROPPED`, which emitted a clean line with sensible numbers. Adding one real
outside gate (read the written file back off disk with an independent reader and count the frames)
found, on its FIRST RUN, that `AVAudioFile.read(into:)` **returns short**: a 96,000-frame file came
back as 95,232. Every NORMALIZE had been dropping 16 ms off the tail and every CROP writing a file
shorter than the region the user asked for.

**Why nothing caught it, which is the whole lesson.** The `Clip`'s `durationFrames` was computed from
the same short read. So the clip AGREED with the truncated file. Every check inside the app was
consistent with every other check inside the app, and the signal was a faithful report of a wrong
number. **There was no internal vantage point from which this was visible.**

**The gate then caught the bad fix.** The first repair looped the read into the destination buffer —
but a read does not append; it fills from the start and sets that buffer's `frameLength` to what the
single call returned. Each chunk stamped over the last. The gate went red in seconds. Without it, a
worse bug than the original would have shipped, and the signals would have looked fine throughout.

**How to apply.** For any behaviour-touching claim, the grader must be something that **did not
produce the artifact**: rendered PCM read by an independent reader, a foreign parser (this project
used CoreMIDI's `MusicSequenceFileLoad` to grade its own MIDI writer), ffmpeg, a Goertzel filter, a
measurement. The observation harness (all of Addendum C) tells you what the program DID. It cannot
tell you whether that was right.

### D2 — Outside the PROCESS is not outside the CODE

*Grounds/extends: D1 (this is the failure mode D1's doctrine walks straight into); #23.*

**Bug it kills.** A test that satisfies the letter of D1 perfectly and is a tautology.

`KeyboardTests.testAKeyTransposesTheSample` rendered real audio through a real engine and measured
real frequencies off the result. Its header was entirely about not trusting a rate the code sets. It
**never constructed a `KeyboardVoicePool`.** It built its own player-plus-varispeed graph, retyped the
production line (`varispeed.rate = Float(pow(2.0, semitones/12.0))`), and graded the copy. Deleting
the entire keyboard would not have failed it.

The signal could not save it either: `KEYBOARD_KEY_HIT` carries `rate`, which had been advertised as
THE discriminator — and the pool reads that value back off `varispeed.rate` one line after assigning
it. The app echoing a number it just wrote, sold as proof the number took effect.

**The test to apply to every gate:** *if I deleted the production type this test is named for, would
it still pass?* If yes, it is grading a copy of the code, not the code.

**Corollary (D2b).** A test that asserts an ABSENCE must name the feature's own handle. A UI test
called `testKeybdIsStillAnInertStub` passed for two sprints after the keyboard shipped, because it
checked for the absence of a button belonging to a DIFFERENT panel. A passing test whose name is the
negation of the truth.

### D3 — A gate you have not watched fail is not a gate — including the gates that check the gates

*Grounds/extends: #5, #26 (Rubber Duck Pass); this is the recursive case.*

**Bug it kills.** The vocabulary audit — the script whose entire purpose is to catch declared tags
that no live code path can reach — claimed to enforce "every declared tag has an emit site" and
implemented it by grepping for `tag: .<case>`. That pattern appears in exactly one place: **inside
the typed emitter wrapper.** So the check was satisfied by the WRAPPER EXISTING, not by anything
calling it.

Two tags were dead (`SAMPLER_STUB_TAPPED`, both stub panels replaced two sprints earlier; and
`FACE_TESTS`) and the audit reported clean. The project had been citing "audit: clean" as sprint
evidence for two rounds. It was evidence of nothing.

**The rule.** Verify-the-verifier means: **plant the exact defect the gate exists to catch, run the
gate, watch it go red, then restore.** Do this for every gate, and do it for the gates that check the
gates — which is the one nobody thinks to do.

**Sharper form of the discipline.** A single sabotage is not enough; the useful question is WHICH
tests go red. When the sample-bank export was made to ship the raw take instead of the tuned pad,
**only** the test that opened the exported WAV and measured its pitch went red — every filename,
index and round-trip assertion stayed green while the kit went out wrong. That distribution of
red-vs-green tells you which of your gates is load-bearing and which is decoration.

### D4 — A correctness suite cannot see a performance failure, and a performance failure presents as a broken feature

*Grounds/extends: #24 (observation contract); new — the catalog has no latency entry.*

**Bug it kills.** A pitch detector (YIN) that was CORRECT and never RETURNED. At 48 kHz with a 40 Hz
floor, YIN is ~23 million double-precision operations, and it was running on the audio actor in a
debug build. The readout stayed blank forever and the LOCK button stayed dead.

Every unit test passed. They measured the same code, correctly. **A test harness waits patiently for
an answer a user never gets.** From the outside, a feature that is right but never arrives is
indistinguishable from one that is broken.

The fix (decimate to 8 kHz before analysis — Nyquist carries a 2 kHz fundamental with room to spare;
the work drops 36x) also took the detector's own test suite from 35 seconds to 1. The runtime had
been screaming the answer and the wrong instrument was being read.

**How to apply.** Anything on an actor that a UI waits on must be observed RUNNING — a device trace
showing the command dispatched AND the result arriving — not merely proved right.

### D5 — UI driving proves reachability. Only a screenshot proves legibility

*Grounds/extends: #24; "two-track visual grading" (this is the case that proves the perceptual track
is not optional).*

**Bug it kills.** A control row crammed onto one line, rendering as "TU…", "A3…" and a lone "L".
Every element present. Every element unreadable.

The XCUITest passed while this was on screen, because it asked whether the LOCK button existed and
whether it was enabled. Both true. **That is ALL an accessibility query can ask:** the element is
there, at some size, saying something.

**How to apply.** Every behaviour-touching UI change needs a screenshot in the loop, read by a
vision-capable judge or a human — not just a walk. *The project had this technique written down in
its own catalogue and did not use it, which is its own finding.*

### D6 — "It installed" is not an observation

*Grounds/extends: C4 (BUILD_ID); #24.*

**The practice being falsified.** Ship the feature, run `devicectl`, watch it say "App installed",
report done. Five features in a row — a destructive crop, three record modes, octave shifts, a
keyboard, pitch lock — were declared complete this way. **Nothing was ever observed.** No screenshot,
no trace, no walk. When the Architect said nothing was on his screen, the response was speculation
("your phone is probably locked") rather than pulling the trace that would have answered it in thirty
seconds.

**What one hour of actually looking found.** Four defects in ONE feature, none of which any test in
the repo could see (D4, D5, D7 and a dead detector).

| hypothesis | status |
|---|---|
| Green unit tests + a clean audit + a successful install = the feature works. | **falsified, expensively.** All three were true while the feature was dead on the device. |
| The observation techniques are for hard bugs. | **falsified.** They are for ordinary ones. |

### D7 — A fixture that cannot express the failure makes the walk green and the feature untested

*Grounds/extends: C3 (test seams — this is the constraint C3 does not state); #24.*

The sampler's synthetic seed was eight decaying bursts in a quarter of a second, built so the
under-pad waveform strip would look rhythmic. It is a **pulse train, not a note** — so the pitch
detector correctly REFUSED to name a pitch for it, and that correct refusal was one step from being
filed as a bug. The feature could not be observed with the fixture that existed.

**How to apply.** When writing an observation contract, check that the FIXTURE can express the
failure the contract is meant to catch. A new seam (a sustained tone, deliberately 22 cents flat) was
part of the fix, not an afterthought to it.

### D8 — A signal cannot see a field that does not exist

*Grounds/extends: #4 (tags as stable identifiers) — the limit case.*

Keyboard recording **could not have worked**. The `MidiEvent` type stored WHICH PAD and WHEN, with no
field for a note, so a keyboard performance had nowhere to exist.

**The failure shape is the lesson.** Had the wiring been present without the field, a recorded melody
would have come back rhythmically perfect and tonally dead: every hit on its beat, the right count,
the right pad, the tune gone. It sounds like a stuck note.

No hit-count assertion catches that. No signal-coverage check catches it — every tag fires, every
payload validates. **The gap is in the DOMAIN TYPE.**

**How to apply.** When a feature extends an existing recording path, ask what the NEW source records
that the OLD one did not. If the domain type has no room for the answer, the feature cannot work, and
every test will pass, because they were written against the old source.

### D9 — An architecture pivot orphans its own instrumentation

*Grounds/extends: #4; #37 (no deletions — this is where that rule needs a caveat).*

A sprint built a live scheduler that played a beat by re-firing sampler pads in time, with three
ratified tags. A later sprint replaced it with a BOUNCE (the beat renders to audio and becomes an
ordinary loop) — the right call, and it made the scheduler unreachable.

Nobody noticed that its tags could no longer fire. **A declared tag that cannot fire makes every
observation contract citing it VACUOUSLY green — which is a stronger claim than having no contract at
all, resting on nothing.** Two hundred lines of subtle host-time scheduling also stayed in the tree,
compiling, reading as load-bearing.

**How to apply.** A pivot is not done when the new path works. It is done when the old path's CODE and
its TAGS are both gone, or their retention is written down. A vocabulary audit can check that a
declared tag is emitted from somewhere; it cannot check that the somewhere still runs. (D3's rebuilt
audit closes exactly this gap.)

### D10 — When one thing becomes two, every operation on it must be re-audited

*Grounds/extends: #23 (dual contract).*

A Perform pad used to hold audio. It came to hold audio AND the recipe (the event list) that produced
it. `.clear` unloaded the audio and left the recipe alive inside the audio actor.

The pad then counted as occupied forever (so "record to the next empty pad" skipped the very pad the
user had emptied in order to record onto), OVERDUB kept merging into a beat that was gone from the
screen, and a save wrote the deleted beat back into the manifest.

**The handler's own comment stated the invariant it was breaking** — "the audio-side state needs to
match the UI-side empty slot" — and the recipe IS audio-side state. The comment was right and the
code had drifted out from under it.

**Same shape, different file.** The persistence writer forgot a newly-added pad field TWICE (the
sampler filter at schema v6, the MIDI recipe at v7) because the pad-to-manifest conversion existed in
**two copies**: the domain gained a field, one copy learned it, the other kept writing without it, and
nothing failed. The fix is structural — ONE converter, used by every caller — and the same rule caught
it a third time before it happened, when sample banks were added.

### D11 — Read the paper. A confident summary of a paper is not the paper

*Grounds/extends: nothing in the catalog. New.*

Three separate instances in this project, escalating:

1. **YIN implemented from memory was wrong twice.** Taking the global minimum of the
   cumulative-mean-normalised difference walks the estimate down the octaves (440 Hz → 40 Hz); taking
   the first dip over-corrects (82 Hz → 2000 Hz). Reading de Cheveigné & Kawahara (2002) corrected two
   specifics that no amount of reasoning would have produced: the cumulative mean runs from τ=1, and
   the absolute threshold is 0.1.
2. **A fetched SUMMARY of a paper was wrong on nearly every parameter.** Asked to summarise Dixon's
   *Onset Detection Revisited* (DAFx-06), a capable model returned: moving MEDIAN over 6 frames, 1.5x
   multiplier, 50 ms minimum inter-onset interval, hop 512. The paper says: moving MEAN over an
   ASYMMETRIC window (reaching back 3x further than it reaches forward, w=3, m=3), a δ OFFSET (not a
   multiplier), a decaying threshold, and hop 441. The 50 ms is the EVALUATION TOLERANCE for scoring a
   detection as correct — not a constraint on the algorithm at all. Every number was plausible. Every
   number was wrong.
3. **The pattern:** a summary is fluent precisely where the paper is specific, because the specific
   details are the ones that do not compress.

**How to apply.** For any named algorithm — YIN, spectral flux, a filter design, a psychoacoustic
model — read the primary source. Not the blog post, not the summary, and not your own recollection.
The five minutes it costs is always less than the cost of shipping a detector that reports 40 Hz for
an A440.

### D12 — Sprint cards pay as a CONTRACT before the work and lose to git as a RECORD after it

*Grounds/extends: #34 (diary discipline); C10.*

**Honest report against the kit's own artifacts.** Over three sprints the cards and BLACKBOARD were
written, then quietly abandoned — while the CODE stayed disciplined (outside gates, verified
verifiers, honest instrumentation). The discipline lived in the gates and in the commit messages, not
in the cards.

**The half that paid: the pre-work contract.** Writing the observation contract BEFORE the code forced
the question *"what would this feature's failure look like, and what could not see it?"* — and that
question is what produced D4, D7 and D8. One sprint was HALTED by it, correctly.

**The half that did not: the post-hoc record.** Git already had it, in more detail, with the diff
attached.

**How to apply.** Keep the pre-work half. Stop pretending the post-work half happens by itself —
either it is written at commit time (in the commit message, where it is unavoidable) or it does not
exist.

### Cross-reference (Addendum D)

Origin: `Audio Object`'s grading round, 2026-07-13 → 2026-07-14 — the same project as Addendum C, six
weeks on. C observes; D grades. Catalog entries extended: §1 #5 (external check surface — D1 is its
hard case), #23, #24, #26, #34, #4, #37. None back-propagated; promotion waits for a second project to
reproduce the finding.

---

# Addendum E — `glitchforge`: the RESOURCE round (memory, then the speed that memory touched)

**Captured from:** glitchforge — the native video-glitch app (frozen pure-Python engine + `apple/`
adapter + Rust codecs), during the M-arc: a Jetsam OOM on real phone videos (1080p/4K) fixed to a
bounded-memory streaming pipeline, then the speed decomposition that followed.
**Dates:** 2026-07-17 → 2026-07-19. Captured 2026-07-19, same session as the work.
**Weight:** one project, that stretch. D4/D7 (Addendum D) are the parents — E is those lessons
re-landing on RESOURCES instead of correctness/latency, plus what the fix itself taught.
**Files (all in-repo):** `apple/harness/bench_mem.py`, `bench_render.py`, `mem_stream_parity.py`,
`mem_decode_stream_parity.py`, `harness/README.md`; `native/src/{mpeg4,mpeg2}.rs` (start_frame,
ref-carry); `apple/PythonBridge/gf_apple_media.py`; `apple/Core/GFMux.swift`, `GFVideoToolbox.swift`.

### E1 — A resource is a graded channel, and the fixture set must be able to express the failure

The four-channel gate proves CORRECT; the timing bench proves FAST; NEITHER can see a resource
failure — and on a phone a memory peak IS a crash (Jetsam, ~2–3GB, long before physical RAM). A
12.7GB-at-1080p pipeline shipped all-green because every fixture was 480p×2s: the fixture set spanned
none of the dimensions users actually bring (resolution, length, codec, orientation). Doctrine:
**per project class, enumerate the user-input dimensions and audit the fixture set against them**
(the fixture-realism audit); then make peak resource a bench with a budget gate, record-first.

### E2 — Gate on the metric the PLATFORM kills on, not the metric your tool prints

`ps rss` over-reported device pressure by GIGABYTES: it counts file-backed page cache that iOS mostly
does not charge to the Jetsam footprint. Gating on rss would have sent the fix chasing memory a phone
never sees — an instrument measuring the wrong killer is a second false floor (D7's metric-shaped
twin). The Jetsam-relevant number is `phys_footprint` (`proc_pid_rusage`/RUSAGE_INFO_V4; verify your
offset against `footprint(1)` once). Report both; gate on footprint.

### E3 — Bound memory by restructuring to BYTE-EXACT streaming, with the old whole-pass as oracle

The OOM was whole-clip materialization at every seam. The fix pattern that kept every correctness
guarantee: (a) encoders gain a `start_frame` so GOP-multiple WINDOWS concatenate byte-exactly with the
single whole-clip call (strip the repeated container headers; gate: windowed == single, byte-for-byte,
both backends, sabotage leg drops the offset and MUST go red); (b) decoders gain REFERENCE-CARRY chunk
entry points (pass the previous chunk's padded reference in, get the new one out) so ANY chunk
sequence reproduces the whole-stream decode — including streams with deleted I-frames and concealment
holds across the seam (gate: streamed == whole on clean + effect-shaped + corrupted streams). The
whole-pass function you are replacing IS the oracle; keep it callable forever.

### E4 — In Apple media loops, `autoreleasepool` per frame is not optional — and it hides behind
### every other leak until they fall

The dominant OOM residue (after all Python-side streaming) was autoreleased per-frame objects
(`copyNextSampleBuffer` buffers, `FileHandle.read` Data) in tight Swift loops that never return to a
runloop: the pool never drains; the clip accumulates as dirty MALLOC_LARGE. Four loops had it
(decode→rgb, rgb→mp4, hardware prep, frame-seek). One `autoreleasepool` per iteration: 3960→221MB.
Two structural fixes landed FIRST and were falsified as the cause by re-measure (bounded writer pool —
kept, correct; F_NOCACHE — kept, real relief): **after two falsified guesses, stop guessing and
CATEGORIZE the peak** (`footprint(1)` mid-render names the region type: MALLOC_LARGE vs IOSurface vs
mapped-file told the whole story in one dump).

### E5 — When two graded channels share a knob, gate them together

The streaming-window budget (memory channel) silently throttled the per-GOP encoder parallelism
(time channel) 2.4× at 1080p — invisible because the memory gate was green and the time budget was
calibrated on fixtures small enough that the window never binds. Any change to a shared knob must run
BOTH benches (plus the byte gate) in the same close. Corollary from the same afternoon: an A/B of the
knob measured nothing because the knob was read at import time (A4 — the observer is code too);
identical numbers on both arms are a finding about the INSTRUMENT until proven otherwise.

### E5b — A PROBE must report what the DECODER produces, or a derived size lies

A native `gf_vt_probe` reported the source's CODED size (`track.naturalSize` = 1920×1080) while the
decoder returned DISPLAY-oriented frames (a 90°-rotated iPhone portrait clip → 1080×1920). Any value
DERIVED from the probe (here `prep.size`, once made source-native — E5's own fix) then disagreed with
the actual frames, and the size-honouring path (edit_codec) mis-sized to a garbled 1088×1080. The
lesson generalizes past video: **when two instruments describe the same object (a prober and a
decoder, a schema-reader and a row-reader), they must agree on the object's shape, or anything built
on the disagreeing one is wrong in a way each instrument alone looks right about.** The decoder was
already display-correct; the probe was the liar. Fix: make the probe apply the SAME orientation table
the decoder uses. And — E1/D7 again — this was invisible until a ROTATED fixture existed: coded≠display
only happens under rotation, so a fixture set without a rotated clip cannot express it. Reproduce the
mis-size FIRST (D3) so the fix has a red to turn green.

### E6 — Keyword-call across FFI, and gate the JOIN, not just the callee

A positional call into the Rust encoder had put `fps` in the `qp` slot since the encoder landed —
every shipped render quality-degraded, both components individually gated green (the correctness gate
grades the datamosh signature, which is blind to a quality delta). Found only when a byte-exactness
gate happened to run through the call site. Doctrine: cross-language calls use keywords; the
WORKING_AGREEMENT bridge map records signatures AT THE CALL SITE; and every FFI join gets at least one
gate that would go red if the arguments shifted.

### Cross-reference (Addendum E)

Origin: glitchforge `KIT_DIARY.md` 2026-07-18/19 entries + `MEM-ROADMAP.md` + `PERF-ROADMAP.md`
Round 2. Extends `TECHNIQUES.md` §1 #5 (external check surface), #23/#24 (contracts — the missing
RESOURCE row), #38/#41 (fixtures/cautions), §2 iOS. Parents: Addendum D (D4: a correctness suite
cannot see a performance failure → E1 is that for resources; D7: fixture expressiveness → E1/E2).
None promoted; a second project confirms or contradicts.

---

*ADDENDUMS.md — dated, project-stamped captures of techniques surfaced on single projects, held here until they stabilize across a second and can fold into the numbered `TECHNIQUES.md` catalog. Each addendum names its project and dates so its weight is legible: real-on-one-project, that date range, not yet catalog-settled. When one is promoted, keep its row and note the promotion; never delete — the audit trail is the work. On file: Addendum A (`substrate-ui`, browser/visual harness), Addendum B (`Cascade`, native-iOS sim harness + determinism core), Addendum C (`Audio Object`, native-iOS on-device audio/MIDI harness), Addendum D (`Audio Object`, the grading round), Addendum E (`glitchforge`, the resource round).*
