# Signal-Driven Development
## A methodology for AI-assisted work where the program speaks for itself

---

## The Problem It Solves

The standard AI-assisted development loop has a lossy step in the middle:

```
Human observes problem → Human describes it in words → AI interprets → AI codes
```

The description step is where fidelity dies. Natural language is a compression format with a high error rate for technical state. "The animation feels snappy but then it hitches at the end" is nearly useless compared to a frame timing trace. "The loop starts in the wrong place" is hard to act on compared to a log showing the quantized beat position vs. the actual record-start sample offset.

This problem is especially bad for:

- **Pixel-level visual work** — spatial relationships, alignment, scale, and color are extremely hard to convey in words
- **Timing and animation** — "feels off" describes a subjective experience, not a frame duration
- **Audio behavior** — you cannot describe a buffer artifact in prose
- **State machine bugs** — "when I do X then Y then Z" degrades rapidly past two steps
- **Concurrent systems** — what actually happened across threads is not what the human thinks happened

The solution is to remove the description step entirely and replace it with a **signal**: structured, machine-readable output that the running program emits about its own behavior, captured by the human and given directly to the AI.

```
Human runs program → Program emits signal → Human captures and pastes → AI reads directly → AI codes
```

The human's job shifts from *interpreter* to *operator*: run the thing, trigger the behavior, capture the output. This is a dramatically lower-bandwidth task.

---

## What Is a Signal

A signal is any artifact a running program can produce that gives an AI direct visibility into program state or behavior — without requiring the human to describe it.

Signals have these properties when well-designed:

- **Structured** — parseable, not just prose. Tagged fields, not freeform sentences.
- **Contextual** — includes surrounding state, not just the triggering event. The five lines before the error matter.
- **Temporal** — timestamped and ordered. Sequences reconstruct causality.
- **Categorical** — tagged by subsystem. The AI knows whether it's looking at audio, layout, or navigation.
- **Stable** — the vocabulary doesn't change on every build. Signal tags are an API.

A signal is not a debug string you happen to paste. It's designed output with a known structure and a known consumer.

---

## Signal Types

### 1. Structured Logs

The foundational type. Categories (`engine`, `transport`, `face`, `transition`) and stable uppercase tags (`FACE_TRAVERSE`, `EDGE_GRAB`, `RECORD_START`) create a vocabulary the AI recognizes across sessions. The human copies a log excerpt; the AI reads a precise sequence of labeled events in the subsystems that matter.

**What it replaces**: Narrative bug descriptions.  
**Best for**: State machine bugs, sequence errors, concurrency issues, anything where "what order did things happen" is the question.

**Design principle**: Tags are stable identifiers, not prose. `RECORD_ARM_REJECTED` is better than `"recorder: couldn't arm because [...]"`. The former is greppable, recognizable, and survives refactoring. The latter is noise.

### 2. Screenshots at Key Frames

The program captures (or the human takes) a screenshot at a specific moment — layout composed, animation mid-frame, error state displayed — and passes it directly to the AI. The AI sees exactly what the human sees without any spatial or visual translation.

**What it replaces**: Layout descriptions, "the button is too far left", "the padding looks wrong."  
**Best for**: Any pixel-level visual work. Especially powerful for: component layout, animation keyframes, theme/color application, gesture hit target sizing.

**Design principle**: The screenshot should be taken *at the right moment*, not just whenever. For animations, a capture at the hitch frame is worth more than a capture at steady state. The program should make it easy to freeze at key moments.

### 3. State Snapshots (Structured Dumps)

On a triggering condition — assertion failure, unexpected transition, user-initiated capture — the program serializes its full relevant state as structured data (JSON, property list, a custom debug description) and emits it to the log or a file. The AI reads the exact values in every field at the moment of interest.

**What it replaces**: "I think the loop region is set to the wrong bar" or "the transport might be in the wrong state when this happens."  
**Best for**: Finding the exact divergence between expected state and actual state. Especially useful when a bug is reproducible but the cause is unclear.

**Design principle**: State dumps should be self-describing. Include field names, not just values. Include the timestamp and the triggering condition. A good state dump reads like a test assertion that failed.

### 4. Assertion Failures with Context

Instead of crashing silently or emitting a bare assertion message, a failed assertion emits a rich payload: the assertion itself, the values that violated it, the recent event history leading up to the failure, and the current state of the relevant subsystem. The AI receives a complete incident report, not just a line number.

**What it replaces**: Crash logs that require manual reproduction and investigation.  
**Best for**: Invariant violations, precondition failures, contract breaches between subsystems. Works well paired with the structured log — the assertion failure includes a backscroll of recent log events.

**Design principle**: Treat assertion failures as first-class signal events, not error conditions. They are the program telling you something precise about what went wrong. Make them verbose.

### 5. Performance Timelines

Frame durations, buffer deadlines, audio callback timings, render pass durations. Emitted as structured data: timestamp, duration, subsystem, whether a deadline was met. The AI can identify where jank or underruns originate without the human having to perceive and describe a timing problem.

**What it replaces**: "It feels laggy" or "the loop playback stutters sometimes."  
**Best for**: Frame pacing, audio buffer performance, animation smoothness, any deadline-driven work.

**Design principle**: Log at the boundary, not in the middle. A frame timing signal should fire when the frame commits, not when a calculation inside it completes. Timestamps should use the same clock as the audio engine.

### 6. Audio Renders / Waveform Captures

For audio applications specifically: capture the actual output buffer as a waveform image or a short audio file and hand it to the AI. This is the audio equivalent of a screenshot — the AI hears (or sees the shape of) what came out, rather than reading a description of it.

**What it replaces**: "There's a click at the loop point" or "the recording starts late."  
**Best for**: Loop crossfade quality, click/pop detection, latency measurement, record start/stop precision.

**Design principle**: The waveform capture should include time markers — bar lines, beat lines, the quantized target — so the AI can see the relationship between the intended grid and the actual audio.

### 7. Gesture / Interaction Traces

Touch coordinates, velocities, durations, and gesture recognizer state transitions logged at each sample. For interaction work where the question is "what exactly did the user do and how did the system respond," a gesture trace is far more precise than any description.

**What it replaces**: "When I swipe fast at the edge" — which is not a reproducible specification.  
**Best for**: Gesture recognizer debugging, hit area sizing, edge-grab sensitivity tuning, multi-touch conflicts.

**Design principle**: Log gesture events at the recognizer layer, not the view layer. The recognizer's state machine is what the AI needs to see. Include the touch position relative to the target region, not absolute screen coordinates.

### 8. Event Chronicles

A time-ordered, immutable log of state transitions across the entire system — not free-form text but a proper event log that can be replayed. Each entry: timestamp, event type, before-state (abbreviated), after-state. The AI can reconstruct exactly how the system arrived at any configuration.

**What it replaces**: Complex multi-step reproduction instructions.  
**Best for**: Bugs that only appear after specific interaction sequences. Also useful as a testing primitive — a chronicle of a known-good session becomes a regression artifact.

**Design principle**: Events should be typed, not stringly. `PadArmed(padIndex: 3, slotIndex: 1)` is better than `"pad 3 armed in slot 1"`. The chronicle is an API.

---

## Designing Signals as an API

The key shift in Signal-Driven Development is treating instrumentation as a first-class design artifact, not an afterthought. You design the signals before (or alongside) the code, the same way you design data models before writing business logic.

A signal vocabulary has:

**Categories** — coarse-grained subsystem groupings. The reader uses these to filter noise. In Audio Object: `engine`, `transport`, `recorder`, `mixer`, `face`, `transition`. These map to actual architectural boundaries.

**Tags** — fine-grained event identifiers. Stable, uppercase, specific. They name things that happen, not things that went wrong. `FACE_TRAVERSE` fires on every navigation. `RECORD_QUANTIZE_FALLBACK` fires when free-form recording kicks in. Both are informative whether or not a bug is present.

**Payloads** — the data attached to each event. Minimal but complete. A `RECORD_START` tag carries the sample position, the current beat position, the BPM, and whether quantization was applied. It doesn't carry everything — just what's needed to reconstruct the decision.

**Stability contract** — signal tags and category names do not change. They are refactored like public APIs, with intent. A tag the AI learned to recognize last week should still mean the same thing today.

---

## The Human's Role

In Signal-Driven Development, the human is an operator, not a narrator.

The human:
1. Runs the program
2. Triggers the behavior of interest
3. Captures the relevant signal (copies logs, takes a screenshot, dumps state)
4. Pastes it to the AI

The human does not need to explain what happened. The signal explains what happened. The human only needs to provide the intent: "I was trying to arm pad 2 for recording and this came out."

This is a much simpler communication task. It's also a more honest one — the human can't accidentally introduce interpretation errors, because they're not interpreting anything.

---

## The AI's Role

The AI reads signals as primary data. It does not ask the human to describe the problem in more detail — it asks for a better signal if the current one is insufficient. "Can you share the log output from around the record-arm event?" is a signal request. "Can you describe more precisely what the button looked like?" is a description request and is the wrong direction.

The AI also designs signals. When introducing new subsystem code, it should propose the logging vocabulary for that subsystem — the categories, the tags, the payloads — as part of the implementation, not as an optional add-on.

---

## Why Logging Conventions Are Architecture

A log is not a debugging tool. A log is a real-time API between the running program and any system that needs to understand it — including a human, including an AI, including a future version of the program reading its own history.

A log with a stable vocabulary and a clear signal design is an architectural artifact on the same level as a data model or a protocol. It reflects the domain concepts and the subsystem boundaries. It exposes the state machine. It makes the program legible from the outside without requiring source inspection.

This is why the Audio Object logging convention names subsystems (`engine`, `face`) rather than files or classes, and why tags are typed identifiers (`EDGE_GRAB`) rather than sentences. The log is a projection of the domain model into the observable world. Its design should be as considered as the domain model itself.

---

## Extending the Loop

The signal loop doesn't have to be manual. Extensions worth building:

**Signal aggregators** — a script that tails the system log, filters for a known category/tag vocabulary, and formats the output for pasting. Reduces capture friction to a single command.

**Screenshot capture scripts** — a shortcut that saves a timestamped screenshot to a known location, ready to drag into the chat. For simulator: `xcrun simctl io booted screenshot --type=png`.

**State dump commands** — a hidden gesture or developer menu option that serializes current state to the clipboard. One tap, ready to paste.

**Performance dashboards** — a secondary view (dev builds only) that renders live performance timelines alongside the production UI. The AI can read a screenshot of the dashboard.

**Replay files** — an event chronicle written to disk during a session, loadable in a later session to reproduce exact state transitions. The file becomes a test fixture.

---

## Summary

Signal-Driven Development is a practice built on one principle: **the program knows more than the human can say**. The goal is to design programs that speak for themselves — through logs, snapshots, renders, traces — and to build a development workflow that routes those signals directly to the AI rather than through the bottleneck of human description.

The design work is in the instrumentation: choosing what to emit, how to structure it, what vocabulary to use, and how to make it stable. That work pays dividends on every subsequent debugging session and every subsequent AI conversation, because the AI is reading clean signal instead of parsing ambiguous prose.

The human's job becomes simpler and more reliable: run, trigger, capture, paste.

The AI's job becomes possible in cases where natural language would fail entirely.
