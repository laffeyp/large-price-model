"""Strict-validating signal emitter over the locked v0.1 vocabulary.

Wraps sdd-kit-2/lib/sdd.py's SignalVocabulary with strict-extras validation
per WORKING_AGREEMENT.md § Vocabulary discipline. Reads signals/0.1.json
at module import; exports a singleton `emitter` every downstream module uses.

Sprint 002: StrictSignalEmitter gains an optional JSONL sink that appends
one JSON line per emit, and resets the internal clock when SESSION_INIT
fires so `t` values read relative to session init, not to module import.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from sdd import Signal, SignalCapture, SignalEmitter, SignalVocabulary, capture

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_VOCAB_PATH = _PROJECT_ROOT / "signals" / "0.1.json"


class StrictSignalVocabulary(SignalVocabulary):
    """SignalVocabulary that rejects unknown payload fields, not only missing ones."""

    def validate(self, tag: str, payload: dict) -> None:
        super().validate(tag, payload)
        entry = self._schema[tag]
        allowed = set(entry.get("payload", [])) | set(entry.get("optional_payload", []))
        extras = [k for k in payload if k not in allowed]
        if extras:
            raise ValueError(
                f"Signal '{tag}' has unknown payload fields: {extras}. "
                f"Allowed fields: {sorted(allowed)}."
            )


def load_vocabulary(path: Path = _VOCAB_PATH) -> StrictSignalVocabulary:
    """Read signals/0.1.json and return a StrictSignalVocabulary bound to its tags."""
    doc = json.loads(path.read_text())
    schema = {
        tag["name"]: {
            "category": tag["category"],
            "payload": [f["name"] for f in tag["typed_payload"] if f["required"]],
            "optional_payload": [f["name"] for f in tag["typed_payload"] if not f["required"]],
            "note": tag.get("note", ""),
        }
        for tag in doc["tags"]
    }
    return StrictSignalVocabulary(schema)


class StrictSignalEmitter(SignalEmitter):
    """SignalEmitter with an optional JSONL sink and a per-session clock reset.

    When `jsonl_sink` is set, every successful emit appends one JSON line to
    the sink path. Every SESSION_INIT emit resets `_session_start`, so
    subsequent tags in that capture carry `t` values relative to the init.
    """

    def __init__(
        self,
        vocabulary: SignalVocabulary,
        max_buffer: int = 500,
        jsonl_sink: Path | None = None,
    ) -> None:
        super().__init__(vocabulary, max_buffer=max_buffer)
        self._jsonl_sink = jsonl_sink
        if jsonl_sink is not None:
            jsonl_sink.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, tag: str, **payload: Any) -> None:
        self._vocab.validate(tag, payload)  # pre-validate; raises before any side effect
        if tag == "SESSION_INIT":
            self._session_start = time.monotonic()
        super().emit(tag, **payload)
        if self._jsonl_sink is not None:
            signal = self._buffer[-1]
            with self._jsonl_sink.open("a") as f:
                f.write(json.dumps(signal.to_dict()) + "\n")


emitter: StrictSignalEmitter = StrictSignalEmitter(load_vocabulary())

__all__ = [
    "Signal",
    "SignalCapture",
    "StrictSignalEmitter",
    "StrictSignalVocabulary",
    "capture",
    "emitter",
    "load_vocabulary",
]
