# Signal-Driven Development — Practice & Library
## The practical companion to `signal-driven-development.md`

*The theory document established why signals beat natural language. This document is about how to build and use them — including a reference library, backend patterns, and the path from manual paste to automated loop.*

---

## The Formal Model

Before writing a library, name the parts.

A Signal-Driven Development system has exactly four components:

```
┌─────────────────────────────────────────────────────────────────┐
│                        SIGNAL VOCABULARY                        │
│   The stable, typed API of things the program can say.          │
│   Designed upfront. Versioned like a schema. Never ad-hoc.      │
└───────────────────────────┬─────────────────────────────────────┘
                            │ validates
                            ▼
┌──────────────┐    emit    ┌─────────────────┐   format   ┌──────────┐
│   PROGRAM    │ ─────────▶ │  SIGNAL BUFFER  │ ─────────▶ │ CONSUMER │
│ (instrumented│            │ (ordered, typed,│            │ (AI, human│
│   with emit  │            │  timestamped,   │            │ dashboard)│
│   calls)     │            │  bounded)       │            │          │
└──────────────┘            └─────────────────┘            └──────────┘
```

**Vocabulary** — the contract. Defines what tags exist, what category each belongs to, and what payload fields are required. This is designed before the code is written.

**Program** — the instrumented system. Calls `emit(tag, **payload)` at decision points. Knows nothing about the consumer.

**Signal Buffer** — captures the session. Ordered, bounded (it has a max size — AI context windows are finite). Holds signals until consumed.

**Consumer** — reads the formatted buffer. Today: a human pastes it into a chat. Tomorrow: an agent subscribes to a stream.

The only interface between these four components is the Vocabulary. That's the whole discipline.

---

## Signal Is Not Log

This distinction matters for library design.

| | Log | Signal |
|---|---|---|
| **Audience** | Human reading a terminal | AI reading a context window |
| **Vocabulary** | Ad-hoc, changes with the code | Stable, versioned, validated |
| **Structure** | Text with implicit structure | Typed, schematized payload |
| **Volume** | Everything, filtered by level | Only what was designed to matter |
| **Lifetime** | Ephemeral, append-only | Session-scoped, bounded, queryable |
| **Design** | After the fact | Before the code |

A log tells you what happened. A signal tells you what *meant* something happened — within a vocabulary that was designed to be understood.

In practice: you can implement signals on top of a log system (like `os.Logger`). But the signal is the abstraction. The log is just one possible transport.

---

## Reference Implementation (Python)

Python is the reference language because it's where most AI tooling lives and where backend services are commonly built. The implementation is intentionally small — the concept should be visible through the code, not buried by it.

```python
# sdd.py — Signal-Driven Development reference library
# ~120 lines. Fork this, extend it, port it.

from __future__ import annotations
import json
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from typing import Any


# ── Vocabulary ────────────────────────────────────────────────────────────────

class SignalVocabulary:
    """
    The stable, typed API of things your program can say.
    Define this before writing any emit() calls.
    It is the contract between your program and its AI reader.
    """

    def __init__(self, schema: dict[str, dict]):
        """
        schema: {
            "TAG_NAME": {
                "category": "subsystem_name",
                "payload":  ["required_field", "another_field"],   # optional
                "note":     "human-readable description",          # optional
            },
            ...
        }
        """
        self._schema = schema

    def validate(self, tag: str, payload: dict) -> None:
        if tag not in self._schema:
            raise ValueError(
                f"Unknown signal tag '{tag}'. "
                f"Define it in your SignalVocabulary before emitting."
            )
        required = self._schema[tag].get("payload", [])
        missing = [f for f in required if f not in payload]
        if missing:
            raise ValueError(
                f"Signal '{tag}' missing required payload fields: {missing}"
            )

    def category_of(self, tag: str) -> str:
        return self._schema[tag]["category"]

    def tags(self) -> list[str]:
        return list(self._schema.keys())


# ── Signal ────────────────────────────────────────────────────────────────────

@dataclass
class Signal:
    tag: str
    category: str
    payload: dict[str, Any]
    t: float = field(default_factory=time.monotonic)   # relative to session start

    def to_dict(self) -> dict:
        return {"tag": self.tag, "category": self.category,
                "t": round(self.t, 4), **self.payload}


# ── Emitter ───────────────────────────────────────────────────────────────────

class SignalEmitter:
    """
    Call emit() at decision points in your code.
    Validates against the vocabulary at emit time — unknown tags fail loudly.
    """

    def __init__(self, vocabulary: SignalVocabulary, max_buffer: int = 500):
        self._vocab = vocabulary
        self._buffer: deque[Signal] = deque(maxlen=max_buffer)
        self._session_start = time.monotonic()

    def emit(self, tag: str, **payload: Any) -> None:
        self._vocab.validate(tag, payload)
        signal = Signal(
            tag=tag,
            category=self._vocab.category_of(tag),
            payload=payload,
            t=time.monotonic() - self._session_start,
        )
        self._buffer.append(signal)

    def flush(self) -> list[Signal]:
        signals = list(self._buffer)
        self._buffer.clear()
        self._session_start = time.monotonic()
        return signals

    def snapshot(self) -> list[Signal]:
        return list(self._buffer)


# ── Capture ───────────────────────────────────────────────────────────────────

class SignalCapture:
    """
    A bounded session. Use as a context manager or call format_for_ai() directly.
    """

    def __init__(self, emitter: SignalEmitter):
        self._emitter = emitter
        self._signals: list[Signal] = []

    def collect(self) -> None:
        self._signals = self._emitter.snapshot()

    def format_for_ai(self, context: str = "") -> str:
        """
        Produces a compact, structured string ready to paste into an AI chat
        or inject into an agent's context window.
        """
        self.collect()
        lines = ["## Signal Capture"]
        if context:
            lines.append(f"Context: {context}")
        lines.append(f"Total signals: {len(self._signals)}")
        lines.append("")

        # group by category
        by_cat: dict[str, list[Signal]] = {}
        for s in self._signals:
            by_cat.setdefault(s.category, []).append(s)

        for cat, signals in by_cat.items():
            lines.append(f"### {cat}")
            for s in signals:
                payload_str = "  ".join(f"{k}={v}" for k, v in s.payload.items())
                lines.append(f"  t={s.t:.3f}  {s.tag}  {payload_str}")
            lines.append("")

        return "\n".join(lines)

    def as_json(self) -> str:
        self.collect()
        return json.dumps([s.to_dict() for s in self._signals], indent=2)

    def pipe_to_agent(self, agent_fn, context: str = "") -> Any:
        """
        Pass the formatted capture directly to an agent function.
        agent_fn receives (signal_text: str) and returns the agent's response.
        """
        return agent_fn(self.format_for_ai(context=context))


@contextmanager
def capture(emitter: SignalEmitter, context: str = ""):
    cap = SignalCapture(emitter)
    try:
        yield cap
    finally:
        cap.collect()
```

---

## Using It — A Backend Example

An e-commerce checkout service. The vocabulary is defined first, before any business logic is written. Then the code emits against it.

```python
# checkout_signals.py — define the vocabulary for this service

from sdd import SignalVocabulary

CHECKOUT = SignalVocabulary({
    "CART_CHECKED_OUT": {
        "category": "checkout",
        "payload":  ["cart_id", "user_id", "item_count", "total_cents"],
        "note":     "User initiated checkout from cart",
    },
    "PAYMENT_ATTEMPTED": {
        "category": "payments",
        "payload":  ["cart_id", "provider", "amount_cents"],
    },
    "PAYMENT_DECLINED": {
        "category": "payments",
        "payload":  ["cart_id", "provider", "reason", "attempt"],
    },
    "PAYMENT_SUCCEEDED": {
        "category": "payments",
        "payload":  ["cart_id", "provider", "order_id"],
    },
    "INVENTORY_RESERVED": {
        "category": "inventory",
        "payload":  ["order_id", "sku", "quantity"],
    },
    "INVENTORY_EXHAUSTED": {
        "category": "inventory",
        "payload":  ["sku", "requested", "available"],
    },
    "ORDER_CONFIRMED": {
        "category": "orders",
        "payload":  ["order_id", "user_id", "total_cents"],
    },
    "CHECKOUT_ABORTED": {
        "category": "checkout",
        "payload":  ["cart_id", "step", "reason"],
    },
})
```

```python
# checkout_service.py — instrumented business logic

from sdd import SignalEmitter, capture
from checkout_signals import CHECKOUT

emit = SignalEmitter(CHECKOUT)


def process_checkout(cart_id: str, user_id: str) -> dict:
    cart = load_cart(cart_id)
    emit("CART_CHECKED_OUT",
         cart_id=cart_id, user_id=user_id,
         item_count=len(cart.items), total_cents=cart.total_cents)

    for attempt in range(1, 4):
        emit("PAYMENT_ATTEMPTED",
             cart_id=cart_id, provider="stripe", amount_cents=cart.total_cents)
        result = stripe.charge(cart.payment_method, cart.total_cents)

        if result.declined:
            emit("PAYMENT_DECLINED",
                 cart_id=cart_id, provider="stripe",
                 reason=result.decline_code, attempt=attempt)
            if attempt == 3:
                emit("CHECKOUT_ABORTED",
                     cart_id=cart_id, step="payment", reason="max_retries")
                return {"status": "failed"}
            continue

        emit("PAYMENT_SUCCEEDED",
             cart_id=cart_id, provider="stripe", order_id=result.order_id)
        break

    for item in cart.items:
        reserved = inventory.reserve(item.sku, item.quantity)
        if not reserved:
            emit("INVENTORY_EXHAUSTED",
                 sku=item.sku, requested=item.quantity,
                 available=inventory.available(item.sku))
            emit("CHECKOUT_ABORTED",
                 cart_id=cart_id, step="fulfillment", reason="inventory_exhausted")
            stripe.refund(result.order_id)
            return {"status": "failed"}
        emit("INVENTORY_RESERVED",
             order_id=result.order_id, sku=item.sku, quantity=item.quantity)

    emit("ORDER_CONFIRMED",
         order_id=result.order_id, user_id=user_id, total_cents=cart.total_cents)
    return {"status": "ok", "order_id": result.order_id}
```

When something breaks in a QA session, the developer doesn't describe the bug. They do this:

```python
with capture(emit, context="QA run: card declined on first attempt, succeeded on second, then inventory failed") as session:
    result = process_checkout("cart_abc", "user_42")
    print(session.format_for_ai())
```

Output — paste directly into the AI:

```
## Signal Capture
Context: QA run: card declined on first attempt, succeeded on second, then inventory failed
Total signals: 8

### checkout
  t=0.001  CART_CHECKED_OUT  cart_id=cart_abc  user_id=user_42  item_count=3  total_cents=4200

### payments
  t=0.042  PAYMENT_ATTEMPTED  cart_id=cart_abc  provider=stripe  amount_cents=4200
  t=0.381  PAYMENT_DECLINED   cart_id=cart_abc  provider=stripe  reason=insufficient_funds  attempt=1
  t=0.382  PAYMENT_ATTEMPTED  cart_id=cart_abc  provider=stripe  amount_cents=4200
  t=0.701  PAYMENT_SUCCEEDED  cart_id=cart_abc  provider=stripe  order_id=ord_xyz

### inventory
  t=0.702  INVENTORY_RESERVED    order_id=ord_xyz  sku=SKU-001  quantity=1
  t=0.703  INVENTORY_EXHAUSTED   sku=SKU-002  requested=2  available=0

### checkout
  t=0.703  CHECKOUT_ABORTED  cart_id=cart_abc  step=fulfillment  reason=inventory_exhausted
```

No description needed. The AI reads the sequence, sees the exact failure point, and writes the fix.

---

## The Automated Loop

Paste is the right starting point. It's low friction, always works, and keeps the human in the loop for triage. But it's a manual step in what should eventually be a closed system.

The evolution has three stages:

**Stage 1 — Capture and Paste** (start here)  
The developer triggers the behavior, copies the `format_for_ai()` output, and pastes it into the AI chat. The AI reads the signal and proposes a fix. The developer applies it. This is already a massive improvement over natural language.

**Stage 2 — Capture and Pipe**  
The developer still triggers the behavior, but the signal is routed automatically to an agent. The agent reads it, generates a hypothesis, and surfaces its analysis in a tool or chat interface. The developer still reviews and applies. The human is the decision-maker; the capture-to-analysis step is automated.

```python
# Stage 2: pipe directly to an agent
import anthropic

client = anthropic.Anthropic()

def analyze_signals(signal_text: str) -> str:
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": (
                "Here is a signal capture from our checkout service. "
                "Identify the failure point and suggest a fix.\n\n"
                + signal_text
            )
        }]
    )
    return response.content[0].text

with capture(emit, context="QA run: payment succeeded, inventory failed") as session:
    result = process_checkout("cart_abc", "user_42")
    analysis = session.pipe_to_agent(analyze_signals)
    print(analysis)
```

**Stage 3 — Continuous Observation**  
Signals stream from a running service into an agent that observes without being prompted. The agent builds a model of normal behavior from the vocabulary and signals an anomaly when something deviates. This is monitoring, but with a shared vocabulary — the agent understands `PAYMENT_DECLINED` the same way the program means it.

```python
# Stage 3 sketch: streaming signal observer
class SignalObserver:
    def __init__(self, vocabulary: SignalVocabulary, agent_fn):
        self._vocab = vocabulary
        self._agent = agent_fn
        self._window: deque[Signal] = deque(maxlen=50)

    def on_signal(self, signal: Signal) -> None:
        self._window.append(signal)
        if self._is_anomalous(signal):
            context = SignalCapture._format_window(list(self._window))
            self._agent(context)  # agent decides whether to page, file a ticket, etc.

    def _is_anomalous(self, signal: Signal) -> bool:
        # simple heuristic: three PAYMENT_DECLINED within the last 10 signals
        if signal.tag == "PAYMENT_DECLINED":
            recent_declines = sum(
                1 for s in self._window if s.tag == "PAYMENT_DECLINED"
            )
            return recent_declines >= 3
        return False
```

The Stage 3 observer works because the vocabulary is stable. The agent doesn't need to parse free text — it reads `PAYMENT_DECLINED` with `reason=card_expired` the same way every time, across every service that uses the vocabulary.

---

## What Any SDD Library Must Provide

Whether in Python, TypeScript, Swift, Go, or anything else, a Signal-Driven Development library has five required primitives and two optional ones.

**Required:**

1. `SignalVocabulary(schema)` — define the contract upfront. Validates at emit time. Throws on unknown tags.

2. `emit(tag, **payload)` — the only instrumentation call. Validates against the vocabulary. Writes to the buffer.

3. `capture()` — a session scope. Bounded (does not grow unboundedly). Produces a formatted artifact.

4. `format_for_ai()` — converts the buffer to a compact, structured, context-window-friendly string. Groups by category. Shows sequence and timing. Human-legible but optimized for AI parsing.

5. `as_json()` — the raw structured form. For piping to agents, storing as test fixtures, diffing across runs.

**Optional but high-leverage:**

6. `pipe_to_agent(fn)` — pass the formatted capture to a function. The function receives the signal text and returns anything. Enables Stage 2 with one line of code.

7. `assert_signal(tag, **partial_payload)` — a test primitive. Asserts that a signal with the given tag and partial payload appeared in the buffer. Enables signal-driven testing.

```python
# Signal-driven test example
def test_payment_failure_triggers_abort():
    with capture(emit) as session:
        process_checkout("cart_bad_card", "user_1")

    session.assert_signal("PAYMENT_DECLINED", attempt=3)
    session.assert_signal("CHECKOUT_ABORTED", reason="max_retries")
    session.assert_no_signal("ORDER_CONFIRMED")
```

The test reads exactly like the behavior it's verifying. No mocks of internal state — just assertions against the signals the system was designed to emit.

---

## The Initial Conditions Problem

One thing the library cannot solve for you: **initial conditions must be correct for signals to be meaningful**.

A signal capture is only as useful as the session that produced it. If the session starts in an unknown state, the signals describe behavior from an unknown baseline. The AI reading them can't tell what was expected.

This means Signal-Driven Development has a prerequisite: **reproducible session setup**. Before capturing, the system should be in a known, documented state. For a backend service: a seeded test database, a predictable request context, a specific user fixture. For a mobile app: a known pad configuration, a specific BPM, a fresh session.

The vocabulary alone doesn't create this. The developer has to provide it. A `context` string passed to `capture()` is the minimal version — a human note about what was set up before the session started. More sophisticated versions serialize the initial state as a signal itself:

```python
emit("SESSION_INIT",
     db_seed="fixtures/checkout_v3",
     user_fixture="user_with_expired_card",
     service_version="1.4.2")
```

The AI reading the capture now knows exactly where the session started. Every signal after that is interpretable relative to a known baseline.

---

## The Vocabulary as Onboarding

There is a secondary benefit to designing the vocabulary upfront that has nothing to do with AI: it forces you to name the things your system does.

Before you write `emit("PAYMENT_DECLINED", ...)`, you have to decide that `PAYMENT_DECLINED` is a real event in your domain — not a log line, not a comment, but a named thing that your system recognizes and reports. This is domain modeling. The vocabulary is a domain model expressed as a signal API.

A new engineer reading the `SignalVocabulary` for a service understands what that service does faster than they would reading the code. The vocabulary is the executive summary. The signals are the evidence that the summary is accurate.

This is why the vocabulary should live in its own file, be reviewed like a schema migration, and change rarely. It is not implementation. It is the description of what the implementation *means*.

---

## Next Steps for This Library

The reference implementation above (~120 lines) is a starting point, not a product. The things worth building on top of it:

- **Language ports** — TypeScript for frontend/Node services, Swift for mobile, Go for high-throughput backends. The API surface is small enough that a port is a morning's work.
- **Transport plugins** — write signals to `os.Logger`, `structlog`, `OpenTelemetry`, a WebSocket stream, or a local SQLite file. The buffer is the abstraction; the transport is pluggable.
- **Chronicle format** — a file format for storing complete signal sessions as test fixtures and regression artifacts. JSON Lines with a vocabulary header.
- **AI prompt templates** — standard system prompts that tell the AI how to read a signal capture, what the vocabulary fields mean, and what kind of response to produce. The vocabulary schema feeds directly into the prompt.
- **Vocabulary linter** — a CI check that validates every `emit()` call against the vocabulary at build time, not just at runtime. Catches tag drift before it ships.

The goal throughout is the same: the program speaks precisely, the AI listens without interpretation loss, and the human's job is to run the thing and present the output — not to translate experience into words.
