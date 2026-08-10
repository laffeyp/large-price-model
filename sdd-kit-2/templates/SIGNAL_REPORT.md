# SIGNAL_REPORT — Sprint {NNN}

*Foundation 03's four-section diagnostic frame (Observed / Expected / Delta / Hypothesis) with the operational AAR subsections nested at `###` level. The Agent emits this at sprint close. The Architect reads to grade. This file is the template; the Agent writes the per-sprint report inline in the session (in chat or to a sprint-close file at `signal-reports/sprint-NNN-report.md`).*

*Inherited from `sdd-kit/foundations/03-sdd-team-model.md`. The four-section outer frame is foundation 03's "Signal Report"; the nine `###` subsections are the operational record the collapsed-three-role agent fills as Worker + Monitoring-Agent in one pass.*

---

## 1. Observed

*Foundation 03: "the signal sequence that actually fired, compressed and annotated." In the collapsed-team kit, this outer section also names what the Agent understood to be in scope and what it did.*

### scope_confirmation

*One or two sentences. The Agent restates the sprint card's `## scope` in its own words. Mismatch with the card → halt at grade time. Per AGENTS.md hard rule 5 (comprehension-as-prerequisite).*

> {Agent fills}

### work_performed

*3-5 bullets in past tense. Tie each bullet to a sprint-card invariant or artifact-contract item.*

- {past-tense action 1, e.g., "Authored src/cradle/operators/price_state_encoder.py with encode_price_state(symbol, bar) → PriceState."}
- {past-tense action 2}
- ...

### signal_trace

*Chronological list of signals fired during the work, in time order. Format: `t={float} TAG_NAME field1=value1 field2=value2`. Every signal MUST be in the project's locked vocabulary (`signals/0.1.json`). Out-of-vocabulary tags surface as `VOCABULARY_DRIFT` per Trading System's pattern; don't silently invent.*

```
t=0.001  SPRINT_DISPATCHED      sprint_id={NNN}
t=0.012  WORKER_CYCLE_BEGUN
t=2.341  ARTIFACT_AUTHORED      file_path=src/cradle/operators/price_state_encoder.py size_bytes=2107
t=3.108  ARTIFACT_AUTHORED      file_path=tests/cradle/test_price_state_encoder.py size_bytes=892
t=3.114  WORKER_CYCLE_COMPLETED artifacts_count=2 emits_count=4
```

### signal_trace_tags

*Flat list of unique tag names that fired in `### signal_trace`. The Architect (or a future agent) uses this list as the canonical "fired" set for the dual-contract grade against the sprint card's declared `Emits`.*

- `SPRINT_DISPATCHED`
- `WORKER_CYCLE_BEGUN`
- `ARTIFACT_AUTHORED`
- `WORKER_CYCLE_COMPLETED`

---

## 2. Expected

*Foundation 03: "the signal sequence that should have fired, derived from the vocabulary and requirements."*

*One short paragraph confirming which tags from the sprint card's `## signal contract → Emits` were expected to fire on this run, plus any that the card declared as conditional. The dual-contract grade cross-references this confirmation against the declared `Emits` and against `### signal_trace_tags` to compute the Delta.*

> {Agent fills, e.g., "Sprint 7's signal contract declared `Emits: SPRINT_DISPATCHED, WORKER_CYCLE_BEGUN, ARTIFACT_AUTHORED, WORKER_CYCLE_COMPLETED`. I expected all four on the happy path; `ARTIFACT_AUTHORED` fires twice (once per declared file)."}

---

## 3. Delta

*Foundation 03: "what's in Expected but not Observed (missing signals), and what's in Observed but not Expected (unexpected signals)." This is also where the Agent's self-grade lands and where proposed BLACKBOARD surfacings are structured.*

### dual_contract_self_grade

*Two stanzas — signal contract + artifact contract — plus an overall pass/fail line. The Agent grades its own work against the sprint card's contracts; the Architect's grade is independent and authoritative; disagreement between Agent and Architect is itself a signal worth noting.*

*Per `sdd-kit/AGENTS.md` § "The dual contract (and observation contract)" for the full discipline.*

**signal contract:**

- `SPRINT_DISPATCHED` — fired [pass]
- `WORKER_CYCLE_BEGUN` — fired [pass]
- `ARTIFACT_AUTHORED` (x2) — fired x2 [pass]
- `WORKER_CYCLE_COMPLETED` — fired [pass]

*Signal contract: pass*

**artifact contract:**

- `src/cradle/operators/price_state_encoder.py` — exists; parses; contains `def encode_price_state` [pass]
- `tests/cradle/test_price_state_encoder.py` — exists; parses; contains `def test_encode_price_state` [pass]
- `pytest tests/cradle/test_price_state_encoder.py` returns 0 — *requires Architect to run* [pending]

*Artifact contract: pending Architect verification*

**overall:** pass-pending-architect-verification

### blackboard_append

*Structured blocks the Agent proposes appending to specific BLACKBOARD sections. The Agent writes via `Edit` per single-writer discipline (see `templates/BLACKBOARD.md`); never to `## Decisions`.*

```
### Section: ## Built
- **{YYYY-MM-DD}** — Sprint {NNN} ({sprint slug}) closed. Files authored: src/cradle/operators/price_state_encoder.py, tests/cradle/test_price_state_encoder.py. Dual contract: pass/pending-architect-verification.

### Section: ## Sprint tail
{compressed close entry per the same BLACKBOARD format above}

### Section: ## Open questions
- **B-Q-{N}.** Should `encode_price_state` accept an optional `prior_state` parameter for chain-encoding? Surfaced from Rubber Duck observation 2.
```

---

## 4. Hypothesis

*Foundation 03: "the most likely code location and change that would close the delta. This is where the Coding Agent starts." In the collapsed-team kit, the Agent IS the Coding Agent, so the hypothesis arrives as the actual code in `### artifact_payloads` plus the rubber-duck-walk that justifies it.*

### rubber_duck_observations

*Three steps per `sdd-kit/AGENTS.md` § "Sprint close: the Rubber Duck Pass": sequence narration, six-category taxonomic observation, four-state bounded disposition.*

**Sequence narration:**

> SPRINT_DISPATCHED fired at t=0.001 declaring sprint_id={NNN}. WORKER_CYCLE_BEGUN fired at t=0.012. ARTIFACT_AUTHORED fired at t=2.341 for the encoder file. ARTIFACT_AUTHORED fired at t=3.108 for the test file. WORKER_CYCLE_COMPLETED fired at t=3.114 with artifacts_count=2.

**Observations (six closed categories: missing pair / order violation / vocabulary gap / payload anomaly / timing surprise / tone trace):**

- **Observation 1 (missing pair):** none.
- **Observation 2 (vocabulary gap):** the encoder's pseudocode used a `tier` field for `PriceState` that the locked vocabulary's `PRICE_STATE_ENCODED` payload schema doesn't include. Surfaced as candidate `PAYLOAD_FIELD_PROPOSED` for v0.2.
- ...

**Dispositions (four closed states per observation: resolved-here / surfaced / halted / deferred):**

- **Observation 1 disposition:** N/A.
- **Observation 2 disposition:** surfaced. Wrote to `## Open questions` per blackboard_append above; Architect ratifies via `## Decisions`.
- ...

### status_and_blockers

*One line. The Agent declares its terminal status.*

`status: complete` — or `status: needs-review` (work plausible, Architect should second-pair-of-eyes) or `status: blocked; blocker: {description}` or `status: failed; reason: {typed_code}` or `status: vocabulary-change-required; proposal: {add_tag | rename_tag | add_field | rename_field | deprecate_tag | tag_split | tag_merge | entity_merge}`.

> status: {agent fills}

### artifact_payloads

*Load-bearing section. The actual code the Agent authored or modified. The Agent's `Write` / `Edit` tool calls already wrote these to disk during the session; this section is the record of what was written, included verbatim in the Signal Report for audit. For each file, `# path:` header followed by a fenced block. Per `sdd-kit/foundations/02-sdd-practice.md` — fence languages match file extensions; no abbreviations; no "see above"; full content included.*

```python
# path: src/cradle/operators/price_state_encoder.py
"""Price-state encoder per ADR-006."""
from cradle.types import Bar, PriceState

def encode_price_state(symbol: str, bar: Bar) -> PriceState:
    """Encode a market bar into a PriceState representation."""
    return PriceState(
        symbol=symbol,
        regime=_classify_regime(bar),
        atr_pct=bar.atr / bar.close,
        timestamp=bar.timestamp,
    )

def _classify_regime(bar: Bar) -> str:
    """Classify bar into trending / mean-reverting / chop regime."""
    # ... implementation ...
```

```python
# path: tests/cradle/test_price_state_encoder.py
"""Tests for price-state encoder."""
import pytest
from cradle.operators.price_state_encoder import encode_price_state
from cradle.types import Bar

def test_encode_price_state():
    bar = Bar(close=100.0, atr=2.0, timestamp=0)
    result = encode_price_state("AAPL", bar)
    assert result.symbol == "AAPL"
    assert result.atr_pct == 0.02
```

---

*SIGNAL_REPORT — template. Foundation 03's four-section frame (Observed / Expected / Delta / Hypothesis) with nine `###` subsections (scope_confirmation, work_performed, signal_trace, signal_trace_tags, dual_contract_self_grade, blackboard_append, rubber_duck_observations, status_and_blockers, artifact_payloads). The Agent emits this at sprint close; the Architect reads to grade. The Architect runs the command-exit-code checks; the Agent does not.*
