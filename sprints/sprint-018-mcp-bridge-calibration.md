# Sprint 018 — bridge mapping calibration (halted on transport gap)

---

```yaml
---
id: 018
status: halted
phase: 1
pass_kind: architecture
determinism_budget: n/a
---
```

---

## scope

Verify the Alpha-Vantage bridge mapping against the actual MCP tool surface. Invoke real tools; record observed signatures and response shapes; update `WORKING_AGREEMENT.md § External SDK bridge mappings` with corrections. Halt on any divergence per hard rule 10 (`bridge_mapping_required`).

---

## outcome

**HALTED.** Two findings surfaced during discovery:

### Finding 1 — signature divergence

Every tool carries a `return_full_data: bool` parameter absent from the WORKING_AGREEMENT documented shape. `TIME_SERIES_INTRADAY` accepts five parameters beyond `(symbol, interval, month, outputsize)`: `adjusted`, `datatype`, `entitlement`, `extended_hours`, `return_full_data`. `CPI` accepts a `datatype` param not documented.

### Finding 2 — transport gap

The `mcp__claude_ai_Alpha_Vantage_MCP_Server__*` tools live in the agent's MCP namespace. A shell-invoked `python scripts/probe_channels.py` has no access to them at runtime. Pipeline needs one of:

- **(a)** `httpx` + Alpha-Vantage HTTP API + `ALPHAVANTAGE_API_KEY` env var.
- **(b)** `mcp` Python SDK + a locally-runnable Alpha-Vantage MCP server binary (existence unverified).
- **(c)** Agent-mediated dump-and-read: agent invokes MCP tools, dumps JSON to `data/raw/mcp/`, script reads.

Response shape (from a real `TIME_SERIES_INTRADAY(SPY, 15min, compact, json)` call):
- Timestamps default `US/Eastern`, not UTC.
- Values are strings, not numbers.
- OHLCV keys carry ordinal prefixes (`"1. open"`, `"2. high"`).
- Compact returns 100 latest points; historical months require `outputsize=full` + `month=YYYY-MM`.
- Vendor gives no `known_at` — latency budget must be project-side.

The fetcher normalisation layer must strip ordinal prefixes, coerce string values to float/int, convert US/Eastern timestamps to UTC, and stamp `known_at` from a channel-manifest latency budget.

Resume: Architect writes to `BLACKBOARD.md § Decisions` picking one of (a), (b), (c). Sprint 019 authors the fetcher against the chosen transport.

---

## artifacts of the halt

- `WORKING_AGREEMENT.md § External SDK bridge mappings § Alpha-Vantage MCP` — updated with observed signatures and response-shape notes.
- `BLACKBOARD.md § Surfaced for review` — halt entry `bridge_mapping_required` with the transport-gap analysis.

No production code authored this sprint. No test additions. No dep pins. Sprint 019 dispatches with a chosen transport.

---

## prerequisites

- Sprint 017 closed.

---

## context_files

- `WORKING_AGREEMENT.md § External SDK bridge mappings`
- `signals/0.2.json` (source enum + payload schemas)
- Deferred-tools listing for `mcp__claude_ai_Alpha_Vantage_MCP_Server__*`

---

## notes

**Why not just author the HTTP fetcher this sprint.** Discovery-first was cheaper. Halting on the transport question surfaces the vocabulary implication (`source: "mcp_av"` label ambiguity if transport is HTTP not MCP) as a real decision point. Sprint 019 lands with the transport chosen and the mapping calibrated; no rework.

**Vocabulary implication.** `source: enum<mcp_av|polygon>` treats source as a transport label. Under path (a), the transport is HTTP but the data provenance is Alpha-Vantage — the label could rename to `"alphavantage"` in a v0.3 evolution or stay as `"mcp_av"` as a provenance tag. Architect calls with the transport choice.

---

*Sprint 018. Bridge mapping calibrated; transport question surfaced. Halt-and-articulate. Sprint 019 dispatches on Architect Decision.*
