"""sdd.py — Signal-Driven Development reference library.

The reference implementation from foundation 02. ~120 lines. Opt-in: a project
that wants typed `emit_signal()` in Python can import this module; projects
using `os.Logger`, `console.log`, structlog, or any other transport don't
need it.

Schema enforced at the speaker's mouth (per `grammar/PRINCIPLES.md`
commitment 2). Unknown tags raise; missing required payload fields raise.
The discipline says the SignalEmitter is the contract — failures fail fast,
not silently.

For projects in languages other than Python, port the surface (the five
primitives below) into the project's language. Same API; same discipline.
"""
from __future__ import annotations
import json
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any


# ── Vocabulary ────────────────────────────────────────────────────────────────

class SignalVocabulary:
    """The stable, typed API of things your program can say.

    Define this before writing any emit() calls. It is the contract between
    your program and the LLM agent reading its capture.

    Schema dict shape:
        {
            "TAG_NAME": {
                "category": "subsystem_name",
                "payload":  ["required_field", "another_field"],   # optional
                "note":     "human-readable description",          # optional
            },
            ...
        }
    """

    def __init__(self, schema: dict[str, dict]):
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
    t: float = field(default_factory=time.monotonic)  # relative to session start

    def to_dict(self) -> dict:
        return {"tag": self.tag, "category": self.category,
                "t": round(self.t, 4), **self.payload}


# ── Emitter ───────────────────────────────────────────────────────────────────

class SignalEmitter:
    """Call emit() at decision points in your code.

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
    """A bounded session. Use as a context manager via `capture()`,
    or call format_for_ai() directly on the snapshot.
    """

    def __init__(self, emitter: SignalEmitter):
        self._emitter = emitter
        self._signals: list[Signal] = []

    def collect(self) -> None:
        self._signals = self._emitter.snapshot()

    def format_for_ai(self, context: str = "") -> str:
        self.collect()
        lines = ["## Signal Capture"]
        if context:
            lines.append(f"Context: {context}")
        lines.append(f"Total signals: {len(self._signals)}")
        lines.append("")
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


@contextmanager
def capture(emitter: SignalEmitter, context: str = ""):
    """Context manager for a bounded SignalCapture session.

    Usage:
        emit = SignalEmitter(vocabulary)
        with capture(emit, context="QA: payment retry test") as session:
            run_some_code()
            print(session.format_for_ai())
    """
    cap = SignalCapture(emitter)
    try:
        yield cap
    finally:
        cap.collect()
