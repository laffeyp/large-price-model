"""Strict-validating signal emitter over the locked v0.1 vocabulary.

Wraps sdd-kit-2/lib/sdd.py's SignalVocabulary with strict-extras validation
per WORKING_AGREEMENT.md § Vocabulary discipline. Reads signals/0.1.json
at module import; exports a singleton `emitter` every downstream module uses.
"""
from __future__ import annotations

import json
from pathlib import Path

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
    """SignalEmitter bound to a StrictSignalVocabulary.

    Sprint-2 extension point for the JSONL sink; Sprint 1 body is empty by design.
    """


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
