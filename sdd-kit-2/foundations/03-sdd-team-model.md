# Signal-Driven Development — The Team Model & The Loop
## How SDD scales from one agent to a full development team

*Third document in the series. The first established the theory. The second gave the library. This one describes the development process itself — how a human and AI (or a team of AIs) build software together using signals as the only communication protocol between agents.*

---

## The Founding Act: Vocabulary-First Collaboration

The only time natural language is strictly necessary in Signal-Driven Development is at the very beginning, before any code exists.

The human has requirements. They may be rough — "a payment system that handles retries and inventory reservation" — or detailed. Either way, the first session is not a coding session. It is a **vocabulary session**. The human and AI sit together and formalize the signal vocabulary: what events exist in this system, what category each belongs to, what payload each carries.

This is domain modeling in the form of API design. When you define `PAYMENT_DECLINED` with fields `[cart_id, reason, attempt]`, you are making a claim about what your system knows and cares about when a payment fails. The vocabulary forces that claim to be explicit before a single line of business logic is written.

The output is a `SignalVocabulary` file. Once it exists, natural language has done its job. Everything after this point — building, running, debugging, iterating — is signals.

The vocabulary session should feel like a whiteboard session with a senior engineer. The human provides the domain knowledge. The AI helps formalize, challenges missing cases ("what happens if payment succeeds but inventory runs out?"), and catches vocabulary gaps before they become code gaps.

---

## The Communication Protocol Inversion

On a human software team, the communication substrate is natural language: Slack messages, PRs, code review comments, standup updates, incident postmortems. Natural language is lossy, ambiguous, and asynchronous. It works because humans are exceptionally good at resolving ambiguity in context.

AI agents are not. But AI agents are exceptionally good at reading structured, typed, sequential data.

Signal-Driven Development inverts the communication substrate. Instead of agents passing natural language to each other ("the payment service is behaving oddly"), they pass signals — the same typed, categorized events the program itself emits. The log stream becomes the team's shared communication channel.

```
Human software team:
  Engineer A → (Slack: "payment retries seem broken after the deploy") → Engineer B

SDD team:
  Coding Agent → [runs program] → signal stream:
    t=0.042  PAYMENT_ATTEMPTED   attempt=1
    t=0.380  PAYMENT_DECLINED    reason=network_timeout  attempt=1
    t=0.381  PAYMENT_ATTEMPTED   attempt=2
    t=0.382  PAYMENT_DECLINED    reason=network_timeout  attempt=2
    t=0.383  CHECKOUT_ABORTED    step=payment  reason=max_retries
  → Monitoring Agent reads stream → routes targeted fix back to Coding Agent
```

No natural language between agents. The program described its own behavior precisely. The monitoring agent read it. The coding agent acts on the analysis.

---

## The Simplest Viable Loop: One Agent

Before building a team, understand the atomic unit. The simplest Signal-Driven Development loop is a single agent cycling through four steps:

```
  ┌─────────────────────────────────────────────────────────┐
  │                                                         │
  │    1. WRITE           Write or modify code.             │
  │       ↓               The vocabulary is the spec.       │
  │    2. RUN             Execute the code. Let it emit.    │
  │       ↓               Capture the signal buffer.        │
  │    3. READ            Read the signal capture.          │
  │       ↓               No description needed.            │
  │    4. CLOSE           Make a targeted change.           │
  │       ↓               Return to step 1.                 │
  │    (repeat)                                             │
  └─────────────────────────────────────────────────────────┘
```

The agent's entire context for each iteration is: the vocabulary, the current code, and the signal capture from the last run. No human description. No interpretation. The program reported what happened; the agent reads it and acts.

The human's role in this loop is:
- Define the vocabulary (once, at the start)
- Trigger the behavior of interest (run the program, exercise the feature)
- Observe whether the final output matches intent
- Redirect if the agent has drifted

The human does not narrate bugs, explain what went wrong, or translate observations into instructions. They operate the system and let the signals do the talking.

---

## The Loop Speed Problem

The single-agent loop has a rate. That rate is determined almost entirely by how fast step 2 (RUN) completes.

**Hot-reload environments** (Node.js with nodemon, Python with uvicorn --reload, React with HMR, Expo with fast refresh):
- Step 2 takes 1–3 seconds
- A full loop cycle is under 10 seconds
- The agent can iterate continuously, in near-real-time
- The signal stream genuinely becomes a stream

**Compile-required environments** (Swift/iOS, Go, C++, Rust):
- Step 2 takes 30–120 seconds for a full build
- A full loop cycle is 1–3 minutes
- Each cycle is expensive — signal design matters more, not less
- The agent must extract maximum information per cycle

**Partial hot-reload** (SwiftUI previews, Storybook):
- UI logic iterates fast; system/audio/network logic requires full build
- Mixed cycle times depending on what changed
- Separate the hot-path work from the cold-path work deliberately

The methodology works at any loop speed. But hot-reload transforms SDD from a batch feedback pattern into a continuous one. If you are building a new service and have a choice of runtime, pick one with fast reload specifically because of the loop speed advantage.

For environments that can't hot-reload, the compensating discipline is **richer signals per cycle**. If each run costs two minutes, design the vocabulary to capture maximum information in one pass. One well-designed signal capture from a two-minute build cycle is worth more than ten vague log lines.

---

## The Team Model: Roles Map to Agents

A real software team has specialization because no one person is equally good at everything and because parallel work compounds. The same logic applies to agent teams, with one addition: agents can share a signal stream that a human team could not, because agents read structured data at machine speed.

The roles:

**Vocabulary Keeper** — owns the `SignalVocabulary` file. Reviews every proposed tag addition. Enforces stability. Rejects tags that duplicate existing ones or that are too narrow to be reusable. This is the team's domain model guardian.

**Coding Agent** — writes and modifies code. Reads the vocabulary as its spec. Emits signals at every decision point. Hands signal captures to the Monitoring Agent after each run.

**Monitoring Agent** — reads signal captures. Compares observed signal sequences against expected ones. Identifies gaps (signals that should have fired but didn't), unexpected sequences, payload anomalies, and timing issues. Produces a **signal report**: a structured analysis of what the last run revealed.

**Test Agent** — maintains the signal-driven test suite. Converts confirmed-good signal captures into regression fixtures. Adds `assert_signal` / `assert_no_signal` assertions for every verified behavior. When the Coding Agent introduces a regression, the Test Agent is the first to see it in the signal capture.

**Integration Agent** — runs the full system end-to-end and captures cross-service signal traces. Reads signals across vocabulary boundaries to detect contract violations between services.

In practice, these roles are not rigid. The simplest team is one agent that does all of them in sequence. The value of naming them is that when a loop cycle fails — when the agent is spinning without progress — it's usually because two roles are in conflict and need to be separated. The Coding Agent should not also be evaluating whether its own signals are correct. That's the Monitoring Agent's job.

---

## The Signal Report: How Agents Talk to Each Other

When the Monitoring Agent reads a signal capture, it produces a Signal Report. This is the structured artifact that the Coding Agent reads to understand what needs to change. It is not natural language prose — it is a typed analysis against the vocabulary.

A Signal Report has four sections:

**Observed** — the signal sequence that actually fired, compressed and annotated.

**Expected** — the signal sequence that should have fired, derived from the vocabulary and requirements.

**Delta** — what's in Expected but not Observed (missing signals), and what's in Observed but not Expected (unexpected signals).

**Hypothesis** — the most likely code location and change that would close the delta. This is where the Coding Agent starts.

```
SIGNAL REPORT — run #7, checkout service

OBSERVED:
  CART_CHECKED_OUT    ✓
  PAYMENT_ATTEMPTED   ✓  (attempt=1)
  PAYMENT_DECLINED    ✓  (reason=network_timeout)
  PAYMENT_ATTEMPTED   ✓  (attempt=2)
  PAYMENT_DECLINED    ✓  (reason=network_timeout)
  CHECKOUT_ABORTED    ✓  (step=payment, reason=max_retries)

EXPECTED (after max retries exhausted):
  ORDER_CONFIRMED or CHECKOUT_ABORTED  ✓
  — but missing: any PAYMENT_ATTEMPTED with attempt=3

DELTA:
  MISSING: PAYMENT_ATTEMPTED attempt=3
  NOTE: retry loop is exiting after 2 attempts, not 3

HYPOTHESIS:
  checkout_service.py line ~34: range(1, 4) should be range(1, 4)
  but the loop body breaks on attempt==3 before the third attempt fires.
  Check the break condition.
```

The Coding Agent reads this report, makes one targeted change, runs again, and produces a new signal capture. The loop closes.

---

## The Collapsing Team

The team model above assumes multiple specialized agents running in parallel or in coordinated sequence. This is the target state. But the simplest deployable version is a single agent that collapses all four roles into one, cycling through them sequentially.

The collapse works because the roles are sequential, not concurrent. You write, then run, then monitor, then test, then write again. A single agent that switches hats each step is functionally equivalent to a specialized team for a single-threaded workflow.

The reason to build toward a team even when a single agent works: **parallelism compounds**. A Coding Agent that doesn't have to stop and evaluate its own signal output can iterate faster. A Test Agent that runs continuously against every signal capture catches regressions before the Coding Agent has moved on. A Monitoring Agent that builds a model of normal signal sequences across many runs can detect subtle drift that a single-agent loop would miss.

Start with one. Design as if you'll have many.

---

## What This Looks Like End to End

Putting it all together for a new backend service, from blank slate to working system:

**Session 0 — Vocabulary Design** (human + AI, ~1 hour)
Human describes the system in broad strokes. AI formalizes the vocabulary. Human reviews, challenges, adds missing cases. Output: `signals.py` with a complete `SignalVocabulary`. High-level requirements written as expected signal sequences, not as prose.

**Session 1 — Scaffold** (Coding Agent)
Agent reads the vocabulary and requirements. Writes the project structure, dependency setup, and placeholder emit calls. No business logic yet — just the skeleton with all the signal calls in the right places, emitting with dummy payloads. First run produces a signal capture showing which signals fire in which order. Monitoring Agent confirms the sequence matches the vocabulary design.

**Session 2–N — Build** (Coding Agent + Monitoring Agent loop)
Each session: Coding Agent fills in business logic for one vocabulary section (e.g., the payments category). Runs. Signal capture goes to Monitoring Agent. Signal Report identifies deltas. Coding Agent closes them. Loop repeats until the signal sequence for that section matches the expected sequence exactly.

**Continuous — Test Fixture Accumulation** (Test Agent)
Every confirmed-good signal capture becomes a regression fixture. By the time the service is feature-complete, the test suite is a library of actual signal sequences from actual runs — not hand-written mocks of imagined behavior.

**Ongoing — Stream Observation** (Monitoring Agent in production)
The same vocabulary that drove development now drives production monitoring. `PAYMENT_DECLINED` in production means exactly what it meant in development. The Monitoring Agent that learned the normal sequence in development recognizes deviation in production. The vocabulary is the shared language across the entire software lifecycle.

---

## The Deeper Pattern

Signal-Driven Development is not fundamentally about logs or libraries or agents. It is about a specific claim regarding where meaning lives in a software project.

In conventional development, meaning lives in the human's head and leaks imperfectly into natural language communication. The code implements that meaning, but the connection between the human's intent and the code's behavior is mediated by descriptions, comments, tickets, and conversations — all of which degrade, become stale, and introduce translation errors.

In Signal-Driven Development, meaning lives in the vocabulary — a typed, versioned, machine-readable artifact that was designed collaboratively before the code was written. The code implements the vocabulary. The signals are the code proving, at runtime, that it did so correctly. The agents read those proofs and act on them.

The human's role shifts from narrator to architect. Define the vocabulary. Verify the final behavior. Everything in between is the loop.
