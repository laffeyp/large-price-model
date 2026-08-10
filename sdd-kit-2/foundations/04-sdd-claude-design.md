# Signal-Driven Design with Claude Design
## Extending the SDD vocabulary into the design phase

*Fourth document in the series. The first established the theory. The second gave the library. The third described the team model and the loop. This one covers the design phase — specifically how to use Claude Design so that the handoff package it produces is vocabulary-aware, making the design-to-code handoff a signal-native event rather than a translation problem.*

---

## What Claude Design Is

Claude Design (Anthropic Labs, April 2026) is a conversational design studio powered by Claude Opus 4.7. You describe what you want; it creates an interactive prototype. From there you refine it through direct requests or edits. When a design is ready to build, you hit **Share → Handoff to Claude Code**, and it packages everything into a handoff bundle: a tar archive containing a README spec, an HTML prototype, design tokens, component structure, layout hierarchy, and referenced assets. Claude Code reads the bundle and writes production code matched to the visual output.

The closed loop — exploration → prototype → handoff → production code — happens entirely within Anthropic's toolchain. Claude Design can also ingest your existing design system (codebase, design files, token libraries) to keep every prototype consistent with your brand.

This is the right pipeline for getting from a rough idea to shipped UI without losing fidelity in the translation. But as shipped, the handoff bundle speaks only the visual language: colors, spacing, components, interaction states. It does not know anything about your signal vocabulary.

That gap is what Signal-Driven Design closes.

---

## The Gap in the Standard Handoff

The standard Claude Design handoff bundle answers: *what does this look like?* It carries:

- Design tokens (colors, type scales, spacing, radii)
- Component structure (what components exist, how they nest)
- Layout hierarchy (how screens relate to each other)
- Interaction notes (what happens on tap, hover, state change)
- The HTML prototype (the reference implementation)

What it does not carry: *what does this mean?*

In a Signal-Driven Development project, every visual state corresponds to a domain event. A pad turning red is not just a color change — it is the visual representation of `PAD_STATE_ARMED`. A face rotating is not just an animation — it is `FACE_TRAVERSE` with a bearing and a destination face index. The design knows what these things look like. It does not know what they are called in the system that will emit signals when they occur.

When the Coding Agent reads a standard handoff bundle, it sees the visual and infers the domain event. That inference is a lossy translation step — exactly the kind of step SDD is designed to eliminate.

The fix is to give Claude Design the vocabulary before the prototype exists, so that every state it designs is named using the vocabulary. The handoff bundle then carries the vocabulary mapping as a first-class artifact, not an afterthought.

---

## Signal-Driven Design: The Vocabulary-First Design Session

The SDD design workflow has one rule: **give Claude Design the vocabulary before it draws a single frame.**

The vocabulary is the contract. When Claude Design knows that `PAD_STATE_ARMED` is a real named thing in your system, it will label the armed pad state with that name throughout the prototype. The README it generates will reference `PAD_STATE_ARMED` as the signal tag for that visual state. The Coding Agent reading the bundle will know exactly what to emit when the user arms a pad — not because it inferred from the color red, but because the spec said so.

### The Design Prompt Structure

A Claude Design prompt for an SDD project has three sections:

**1. Visual description** — what to build, how it should look and feel. This is what you'd write for any Claude Design session.

**2. Design system** — your existing tokens, type scale, brand colors, component library. If you have a design system file or codebase, attach it. Claude Design will apply it.

**3. Signal vocabulary** — the domain events that this interface needs to represent. Paste the vocabulary directly. Ask Claude Design to label every component state with its corresponding signal tag.

Example prompt for Audio Object:

```
Build an interactive prototype of the Audio Object looper app.

VISUAL:
The app is a cube (6 faces). The user navigates between faces by pulling from 
the wood-grain border panel at the edge of the current face. The body rotates 
as a single physical object. No tabs, no menus, no buttons except the 
instrument controls on each face surface.

Current face: the Perform Surface. It shows a 4x2 grid of 16 pads. Each pad 
has four distinct visual states. Wood-grain borders are visible on all four 
edges. The transport bar (BPM, bar counter) lives at the bottom.

DESIGN SYSTEM:
[attach _phase1/design-system-handoff-package/ and DesignTokens.swift]

SIGNAL VOCABULARY:
Every component state in the prototype should be labeled with its signal tag 
name from the vocabulary below. Include a Signal Mapping table in your README.

Face navigation:
  FACE_TRAVERSE       — face transition begins (bearing, from_face, to_face)
  FACE_SETTLE         — face transition completes (face_index)
  EDGE_GRAB_BEGIN     — user begins pulling from a wood border (edge_bearing)
  EDGE_GRAB_CANCEL    — user releases without completing transition

Pad states:
  PAD_STATE_EMPTY     — pad is empty, no clip assigned
  PAD_STATE_ARMED     — pad is ready to record
  PAD_STATE_RECORDING — pad is actively recording
  PAD_STATE_QUEUED    — pad is queued to begin playing on next bar boundary
  PAD_STATE_PLAYING   — pad is playing
  PAD_STATE_MUTED     — pad is muted

Transport:
  TRANSPORT_TEMPO_CHANGED   — BPM changed (bpm, source)
  TRANSPORT_BAR_TICK        — bar boundary crossed (bar_number)
  RECORD_QUANTIZE_START     — quantized record begin (bar, beat, sample_offset)
  RECORD_QUANTIZE_STOP      — quantized record end
  RECORD_FREEFORM_FALLBACK  — quantization missed, falling back to free-form

Please label every pad state variant in the prototype with its PAD_STATE_* tag.
Label the in-progress face transition with FACE_TRAVERSE. Include a Signal 
Mapping section in the handoff README.
```

---

## The Enhanced Handoff Bundle

When Claude Design has been given the vocabulary, the README it generates for the handoff bundle should include — in addition to the standard visual spec — a **Signal Mapping** section. This section is the bridge between the design and the code.

An enhanced handoff README Signal Mapping looks like this:

```markdown
## Signal Mapping

This section maps every interactive state in the prototype to its signal vocabulary tag.
The Coding Agent should instrument these tags at the corresponding state transitions.

### Pad Component States
| Visual State       | Signal Tag           | Payload Fields                    |
|--------------------|----------------------|-----------------------------------|
| Empty (gray)       | PAD_STATE_EMPTY      | pad_index, slot_index             |
| Armed (red ring)   | PAD_STATE_ARMED      | pad_index, slot_index             |
| Recording (red fill + pulse) | PAD_STATE_RECORDING | pad_index, slot_index, bar_start |
| Queued (amber pulse) | PAD_STATE_QUEUED   | pad_index, slot_index, target_bar |
| Playing (green)    | PAD_STATE_PLAYING    | pad_index, slot_index, loop_bars  |
| Muted (dim green)  | PAD_STATE_MUTED      | pad_index, slot_index             |

### Face Transition States
| Visual State                    | Signal Tag        | Payload Fields                     |
|---------------------------------|-------------------|------------------------------------|
| Border pull in progress         | EDGE_GRAB_BEGIN   | edge_bearing                       |
| Body rotating (mid-transition)  | FACE_TRAVERSE     | from_face, to_face, bearing        |
| New face settled                | FACE_SETTLE       | face_index                         |
| Pull released without transition| EDGE_GRAB_CANCEL  | edge_bearing, displacement         |

### Transport Bar
| Visual State         | Signal Tag               | Payload Fields          |
|----------------------|--------------------------|-------------------------|
| BPM field edit       | TRANSPORT_TEMPO_CHANGED  | bpm, source             |
| Bar counter advance  | TRANSPORT_BAR_TICK       | bar_number              |

### Coding Agent Instructions
- Emit PAD_STATE_* tags at every pad state transition, not just on user tap.
  State can change due to quantization events even without direct user interaction.
- FACE_TRAVERSE fires when the transition gesture commits, before animation completes.
  FACE_SETTLE fires when the new face is fully visible and interactive.
- RECORD_QUANTIZE_START payload must include sample_offset — the number of samples 
  between the bar boundary and the actual record-start sample. This is the latency 
  compensation value and is diagnostic.
```

This README is now a signal-aware spec. The Coding Agent does not have to infer what to emit when a pad turns red. The spec tells it: `PAD_STATE_ARMED`, with `pad_index` and `slot_index`. The visual design and the domain model are aligned from before the first line of code is written.

---

## Practical Workflow: Design Phase in SDD

The design phase slots between Vocabulary Design and the Build loop described in `sdd-team-model.md`:

```
  Phase 0: Vocabulary Design
    Human + AI define the SignalVocabulary.
    Output: signals.py (or signals.swift, signals.ts, etc.)

  Phase 0.5: Signal-Driven Design Session  ← NEW
    Human prompts Claude Design with visual description + design system + vocabulary.
    Claude Design produces prototype with vocabulary-labeled states.
    Human refines: "make the armed state more visually distinct; keep the tag PAD_STATE_ARMED"
    Output: handoff bundle with Signal Mapping section in README

  Phase 1: Build Loop
    Coding Agent reads handoff bundle.
    The Signal Mapping section tells it exactly what to emit, when, with what payload.
    No inference needed. The design and the code share the same vocabulary.
    Monitoring Agent reads signal captures and compares against expected sequences 
    derived from the Signal Mapping table.
```

The critical point: **the vocabulary does not change between Phase 0, Phase 0.5, and Phase 1.** The same tag names that were defined in the vocabulary session are the ones Claude Design used to label prototype states, and the same ones the Coding Agent emits. There is no translation at any boundary.

---

## Using Claude Design for 3D / Physical Interface Design

Audio Object's physical metaphor — a rotating polyhedron body — makes it a useful test case for what Claude Design can and can't do for unusual interfaces.

Claude Design's native strength is 2D screen design: layouts, components, flat interactions. For a 3D rotating polyhedron, you will get the most value by splitting the design work:

**What to do in Claude Design:**
- Each face surface as a flat 2D screen design (the Perform Surface, Loop Adjust Surface, Settings Surface, etc.)
- The transition states: mid-rotation frame showing both wood panels, the blur/reveal at settle
- The wood border panels as component variants (idle, hover, grabbed, releasing)
- Each pad as a component with all its state variants explicitly designed and labeled

**What to do outside Claude Design (Phase 1 reference assets):**
- The 3D perspective render of the polyhedron body — use the Phase 1 `_phase1/docs/design/` renders
- The physical material details (wood grain texture, bezel, screws) — port directly from Phase 1 `DesignTokens.swift` and `InstrumentTheme.swift`
- The rotation math and the "body rotates as one object" behavior — this is code, not design

Give Claude Design the 3D renders as reference images alongside the prompt. It will extract the visual language (materials, lighting, border geometry) and apply it to the 2D face designs. The handoff bundle will carry the design tokens for wood grain, bezel color, and screw detail, which the Coding Agent uses to match the render in SwiftUI.

---

## The DESIGN.md Pattern

A pattern emerging in the Claude Design ecosystem is the **DESIGN.md** file: a single structured Markdown document that Claude Design reads at the start of every session to apply a consistent design system without you re-describing it.

For an SDD project, DESIGN.md is the natural carrier for the combined design + vocabulary context. Instead of pasting the vocabulary into every Claude Design prompt, you maintain one DESIGN.md file that includes both:

```markdown
# DESIGN.md — Audio Object

## Design System
[design tokens, type scale, color palette, component library reference]

## Signal Vocabulary
[the full SignalVocabulary schema in structured Markdown table format]

## Mapping Instructions
When designing any interactive state, label it with its signal tag from the 
vocabulary above. If a state does not have a corresponding signal tag, flag it 
— it means either the vocabulary is incomplete or the state is not meaningful 
to the domain model.

## Naming Convention
All component state variants in this project are named by their signal tag, not 
by their visual appearance. "Armed" is not a color — it is PAD_STATE_ARMED 
with a specific visual representation. Do not name states by visual properties 
(red, glowing, pulsing). Name them by domain meaning.
```

The last instruction is the most important. It enforces the principle that visual design names and domain model names are the same names. A designer (human or AI) who calls it "the red state" has introduced a translation layer. A designer who calls it `PAD_STATE_ARMED` has not.

---

## What This Gives You End to End

With a vocabulary-first Claude Design session and a Signal Mapping in the handoff bundle, the full pipeline looks like this:

```
Human defines vocabulary
       ↓
Claude Design receives vocabulary + visual description
       ↓
Claude Design produces prototype where every state has a signal tag name
       ↓
Handoff bundle includes:
  - design tokens
  - component states (labeled with signal tags)
  - Signal Mapping table
  - HTML prototype
       ↓
Coding Agent reads handoff bundle
  - Knows what to build (visual spec)
  - Knows what to emit (Signal Mapping)
  - No inference, no translation
       ↓
Code runs, signals emit, Monitoring Agent reads captures
  - Expected sequences derived from Signal Mapping table
  - Delta = what the design said should happen vs. what the signals report
       ↓
Loop closes
```

The design is no longer a handoff artifact that gets handed off and forgotten. It is a living spec with a named vocabulary that propagates through every phase — from the first Claude Design session to the production signal stream.

The handoff package is not the end of design's influence on the codebase. It is the beginning of a shared language that design and code maintain together.

---

Sources:
- [Introducing Claude Design by Anthropic Labs](https://www.anthropic.com/news/claude-design-anthropic-labs)
- [Anthropic launches Claude Design — TechCrunch](https://techcrunch.com/2026/04/17/anthropic-launches-claude-design-a-new-product-for-creating-quick-visuals/)
- [Claude Design to Claude Code: AI Design Handoff](https://claudefa.st/blog/guide/mechanics/claude-design-handoff)
- [From Prompt to Production — Design Systems Collective](https://www.designsystemscollective.com/from-prompt-to-production-a-designers-step-by-step-workflow-with-claude-design-claude-code-a7705daad026)
- [What Is Claude Design? — DataCamp](https://www.datacamp.com/blog/claude-design)
- [Using Claude Design for prototypes and UX](https://claude.com/resources/tutorials/using-claude-design-for-prototypes-and-ux)
