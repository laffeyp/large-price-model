# WORKING_AGREEMENT.md — {Project Name}

*Per-project overrides and additions on top of `sdd-kit/AGENTS.md`. The Agent reads AGENTS.md first (the methodology) and then this file (the project specifics). When the two conflict, AGENTS.md wins — this file augments, it doesn't override the methodology's hard rules. Copy this template to project root as `WORKING_AGREEMENT.md`; do not edit this template.*

---

## Project identity

- **Project name:** {fill}
- **Project type:** {e.g., iOS app, Python backend, CLI tool, Swift package, browser extension}
- **Primary language(s):** {fill}
- **Primary build commands:** {e.g., `swift build && swift test`; `pytest`; `npm run build && npm test`; `cargo build && cargo test`}
- **Adopted SDD kit version:** {fill — e.g., `sdd-kit v0.1`}

---

## Project scope (verbatim from BLACKBOARD ## Decisions)

> {restate the first BLACKBOARD ## Decisions entry here; the Agent reads this to ground its understanding of the project}

---

## Canonical home registry

*Per AGENTS.md hard rule 7. Name which file owns which public type. The Agent consults this before authoring; without it, multi-sprint sequences thrash by silently re-declaring types across files.*

| Type / module | Canonical home |
|---|---|
| `{TypeName1}` | `{path/to/file.ext}` |
| `{TypeName2}` | `{path/to/file.ext}` |
| ... | ... |

Add rows as new types stabilize. When a sprint surfaces a "where does this type live" question, the Architect's answer goes here.

---

## External SDK bridge mappings

*Per AGENTS.md hard rule 10 (the bridge_mapping_required halt). When the project uses an external SDK (an LLM library, an audio framework, an HTTP client, etc.), the Architect reverse-engineers the SDK's actual public API surface and documents it here BEFORE any sprint authoring code that imports the SDK. The Agent reads this to honor the actual API rather than guessing from spec prose.*

*Examples from the soundfield project — what would have prevented many sprints of guess-and-iterate:*

### {SDK name 1, e.g., "MLX Swift LM"}

- **Package URL:** `https://github.com/ml-explore/mlx-swift-lm`
- **Required imports for usage:** `MLXLLM`, `MLXLMCommon`, `MLXHuggingFace`, `HuggingFace`, `Tokenizers`
- **Critical API surface (verbatim from upstream source):**
  - `GenerateParameters(maxTokens: Int?, temperature: Float = 0.6, topP: Float = 1.0, topK: Int = 0, ...)` — note `Float` not `Double`; no `seed:` parameter.
  - `ModelContainer.prepare(input:) async throws → LMInput` — required before `.generate()`.
  - `ModelContainer.generate(input:parameters:) async throws → AsyncStream<Generation>` — `Generation` cases: `.chunk(String)`, `.info(GenerateCompletionInfo)`, `.toolCall(ToolCall)`.
- **Bridge mapping (our type ↔ their type):** {table per project; e.g., our `ModelInput.prompt` → their `UserInput(prompt: String, ...)`.}
- **Substrate gaps from spec (what the SDK doesn't provide):** {e.g., MLX high-level API doesn't expose per-token top-K or entropy; spec'd events for these are dropped in v0.}

### {SDK name 2, e.g., "AVFoundation / AVAudioEngine"}

- **Critical API gotchas:**
  - `engine.attach(engine.mainMixerNode)` CRASHES — it's auto-attached.
  - `AVAudioUnitEQ.bands[0].bypass` defaults to TRUE → silent filter trap.
  - `AVAudioSourceNode` render block runs on real-time audio thread → MUST NOT capture `self` (actor), MUST NOT allocate, MUST NOT acquire blocking locks.
- ...

Add a section per external SDK as the project encounters it. The first sprint that imports an SDK without a bridge mapping in this file MUST halt with `bridge_mapping_required` (per AGENTS.md hard rule).

---

## Vocabulary discipline overrides

*Per `sdd-kit/grammar/PRINCIPLES.md`, projects may declare overrides on the default vocabulary discipline.*

- **Validator-extras posture:** `strict` (default; payload fields not in schema are rejected) | `documentation-only` (Trading System pattern; extras appear in emitted payloads but the validator does not enforce them).
- **View-payload-universal convention:** Apply the four-field convention (`frame, visible, scene_id, layer`) to every view-category tag? Yes/no/customized — if customized, list the project's universal view fields.
- **Vocabulary location:** `signals/0.1.json` (default) or per-project alternative.
- **Vocabulary CI gate command:** {e.g., `scripts/check_vocab.sh`} — the command the Architect runs to verify no emit site references out-of-vocab tags.

---

## Build and verification commands

*Per AGENTS.md: the Architect (human) runs build commands; the Agent does not silently retry failed builds.*

- **Primary build:** `{command}` — expected exit code 0
- **Test suite:** `{command}` — expected exit code 0
- **Linter:** `{command}` — expected exit code 0 (optional)
- **Format checker:** `{command}` — expected exit code 0 (optional)

---

## Observation contract environment (for UI-touching projects)

*Per `sdd-kit/AGENTS.md` hard rule 9 and `sdd-kit/AGENTS.md` § "The dual contract (and observation contract)". The Architect names the tools used to verify product behavior.*

- **Simulator / runtime environment:** {e.g., iPhone 17 Pro simulator, UDID `<UDID>`}
- **Build-and-install command:** {e.g., `xcodebuild build ... && xcrun simctl install booted ...`}
- **Launch command:** {e.g., `xcrun simctl launch booted app.example.MyApp`}
- **Log tail command:** {e.g., `xcrun simctl spawn booted log stream --predicate 'subsystem == "app.example.MyApp"'`}
- **Screenshot command:** {e.g., `xcrun simctl io booted screenshot /tmp/shot.png`}
- **UI driving tools available:** {e.g., `mcp__ios-simulator__ui_tap`, `mcp__ios-simulator__ui_describe_all`, `mcp__ios-simulator__ui_find_element`}

If no UI, omit this section.

---

## Hand-author authorization log

*Per AGENTS.md hard rule 10 (hand-author requires explicit human authorization). When the Architect authorizes the Agent to bypass the normal sprint discipline for a specific hand-author, the authorization is logged here.*

*(empty until first authorization)*

- **{YYYY-MM-DD}** — Sprint {NNN}: authorized hand-author for {file or change} because {reason}. Bypassed: {what was bypassed, e.g., dual-contract grade, observation contract, vocabulary check}. Acknowledged drift: {what risk was accepted}.

---

## Tone canon (for UI-touching or content-producing projects)

*If the project has player-facing or user-facing strings, name the voice/tone canon here. The Agent reads this when populating Layer 7 (Evidence) tonal constraints during the Vocabulary Session and when authoring strings during regular sprints.*

- **Voice register:** {e.g., "lowercase, terse, no exclamation marks, no marketing language"}
- **Forbidden constructions:** {e.g., "no second-person address in narration"; "no emojis"}
- **Reference:** {path to the voice canon document if separate}

---

## Drift surface log

*Patterns the project has identified as worth watching across sprints. Migrates here from `BLACKBOARD.md ## Drift watchlist` when the pattern becomes stable enough to name as a project invariant.*

*(empty on project start)*

- **DS-1.** {pattern description}; mitigation: {what to do when the pattern surfaces}.

---

## Sprint cadence policy

*Per AGENTS.md: two cadence bands (plan-mode-per-sprint, auto-within-phase). The project declares which phases run in which band.*

- **Phase 0 (Vocabulary Session):** plan-mode (Architect drives interactively).
- **Phase 1 ({phase name}):** {plan-mode-per-sprint | auto-within-phase}
- **Phase 2 ({phase name}):** {fill}
- ...

When a phase is `auto-within-phase`, the Agent dispatches subsequent sprints in the phase without per-card review; surfaces only on halt or phase close.

---

## Project-specific halt conditions

*In addition to the base halt conditions in AGENTS.md, the project may declare its own. Each carries a typed reason name and a resume condition.*

- `{halt_reason_name}` — fires when {condition}. Resume: {what the Architect does to unblock}.

---

## Custom techniques

*Project-specific techniques that aren't part of the kit's universal catalog but the project uses repeatedly. Document here so the Agent applies them by default.*

- **{Technique name}** — {one-paragraph description, including when to apply and what success looks like}.

---

*WORKING_AGREEMENT.md — template. Copy to project root and fill. The Agent reads AGENTS.md (the methodology) then this file (the project specifics). Augments, never overrides, AGENTS.md hard rules.*
