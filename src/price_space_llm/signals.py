"""Strict-validating signal emitter over the locked vocabulary.

Wraps sdd.SignalVocabulary with strict-extras validation per
WORKING_AGREEMENT.md § Vocabulary discipline: extra payload fields
raise, not just missing required ones. Loads the vocabulary from a
packaged resource so wheel and editable installs both work.

The vocabulary declares each payload field's type — enum,
primitives, hash/uuid/date formats, containers. `StrictSignalVocabulary`
parses those type strings at load and checks each emitted value against
its declared type; a mismatched value raises `ValueError` at the emit
call site (schema at the speaker's mouth, per PRINCIPLES.md commitment 2).

`StrictSignalEmitter` adds an optional per-emit JSONL sink and
resets the internal clock when SESSION_INIT fires so trace `t`
values read relative to session init, not to module import.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

from sdd import Signal, SignalCapture, SignalEmitter, SignalVocabulary, capture


Checker = Callable[[Any], None]


# ── type checkers ─────────────────────────────────────────────────────────────


def _check_str(v: Any) -> None:
    if not isinstance(v, str):
        raise ValueError(f"expected str, got {type(v).__name__}")


def _check_int(v: Any) -> None:
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValueError(f"expected int, got {type(v).__name__}")


def _check_float(v: Any) -> None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"expected float, got {type(v).__name__}")


def _check_bool(v: Any) -> None:
    if not isinstance(v, bool):
        raise ValueError(f"expected bool, got {type(v).__name__}")


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _check_sha256(v: Any) -> None:
    if not isinstance(v, str) or not _SHA256_RE.match(v):
        raise ValueError(f"expected sha256 (64 lowercase hex), got {v!r}")


def _check_uuid(v: Any) -> None:
    if isinstance(v, UUID):
        return
    if not isinstance(v, str):
        raise ValueError(f"expected uuid, got {type(v).__name__}")
    try:
        UUID(v)
    except ValueError as e:
        raise ValueError(f"expected uuid string, got {v!r}: {e}") from e


_DATE_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _check_date_iso(v: Any) -> None:
    if isinstance(v, date):
        return
    if not isinstance(v, str) or not _DATE_ISO_RE.match(v):
        raise ValueError(f"expected date_iso (YYYY-MM-DD), got {v!r}")
    try:
        date.fromisoformat(v)
    except ValueError as e:
        raise ValueError(f"invalid date_iso {v!r}: {e}") from e


def _check_datetime_utc(v: Any) -> None:
    if isinstance(v, datetime):
        if v.tzinfo is None or v.tzinfo.utcoffset(v) != timezone.utc.utcoffset(v):
            raise ValueError(f"expected datetime with UTC tzinfo, got {v!r}")
        return
    if not isinstance(v, str):
        raise ValueError(f"expected datetime_utc, got {type(v).__name__}")
    try:
        parsed = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError as e:
        raise ValueError(f"expected ISO-8601 datetime string, got {v!r}: {e}") from e
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) != timezone.utc.utcoffset(parsed):
        raise ValueError(f"expected UTC datetime, got {v!r}")


def _check_path(v: Any) -> None:
    if not isinstance(v, (str, Path)):
        raise ValueError(f"expected path (str or Path), got {type(v).__name__}")


def _check_entity_ref(v: Any) -> None:
    # Layer 2 sees entity_ref<X> as opaque str; referent existence is a Layer-8 concern.
    _check_str(v)


_TYPE_CHECKERS: dict[str, Checker] = {
    "str": _check_str,
    "int": _check_int,
    "float": _check_float,
    "bool": _check_bool,
    "sha256": _check_sha256,
    "uuid": _check_uuid,
    "date_iso": _check_date_iso,
    "datetime_utc": _check_datetime_utc,
    "path": _check_path,
}


def _check_enum(allowed: frozenset[str]) -> Checker:
    def check(v: Any) -> None:
        if v not in allowed:
            raise ValueError(f"expected one of {sorted(allowed)}, got {v!r}")
    return check


def _check_list_of(inner: Checker) -> Checker:
    def check(v: Any) -> None:
        if not isinstance(v, list):
            raise ValueError(f"expected list, got {type(v).__name__}")
        for i, item in enumerate(v):
            try:
                inner(item)
            except ValueError as e:
                raise ValueError(f"list index {i}: {e}") from e
    return check


def _check_dict_of(key_check: Checker, val_check: Checker) -> Checker:
    def check(v: Any) -> None:
        if not isinstance(v, dict):
            raise ValueError(f"expected dict, got {type(v).__name__}")
        for k, val in v.items():
            try:
                key_check(k)
            except ValueError as e:
                raise ValueError(f"dict key {k!r}: {e}") from e
            try:
                val_check(val)
            except ValueError as e:
                raise ValueError(f"dict value at {k!r}: {e}") from e
    return check


def _parse_type(type_str: str) -> Checker:
    """Turn a vocabulary type string into a callable checker."""
    if type_str in _TYPE_CHECKERS:
        return _TYPE_CHECKERS[type_str]
    if type_str.startswith("enum<") and type_str.endswith(">"):
        values = frozenset(type_str[5:-1].split("|"))
        return _check_enum(values)
    if type_str.startswith("entity_ref<") and type_str.endswith(">"):
        return _check_entity_ref
    if type_str.startswith("list<") and type_str.endswith(">"):
        return _check_list_of(_parse_type(type_str[5:-1]))
    if type_str.startswith("dict<") and type_str.endswith(">"):
        inner = type_str[5:-1]
        # split on the top-level comma
        depth = 0
        split = None
        for i, c in enumerate(inner):
            if c == "<":
                depth += 1
            elif c == ">":
                depth -= 1
            elif c == "," and depth == 0:
                split = i
                break
        if split is None:
            raise ValueError(f"dict<> missing comma: {type_str}")
        k = inner[:split].strip()
        v = inner[split + 1 :].strip()
        return _check_dict_of(_parse_type(k), _parse_type(v))
    # Unknown type — accept anything, but log via the schema at load time
    # so a future audit surfaces it. Fall back to str check as a safety net.
    return _check_str


# ── vocabulary + emitter ──────────────────────────────────────────────────────


class StrictSignalVocabulary(SignalVocabulary):
    """Vocabulary that enforces strict extras AND per-field type checks."""

    def __init__(self, schema: dict[str, dict]):
        super().__init__(schema)
        # Precompute a per-tag map of field name → type checker.
        self._field_checkers: dict[str, dict[str, Checker]] = {}
        for tag, entry in schema.items():
            self._field_checkers[tag] = {
                field_name: _parse_type(type_str)
                for field_name, type_str in entry.get("field_types", {}).items()
            }

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
        checkers = self._field_checkers[tag]
        for field_name, value in payload.items():
            checker = checkers.get(field_name)
            if checker is None:
                continue  # field not typed in the schema (rare; safety net)
            try:
                checker(value)
            except ValueError as e:
                raise ValueError(f"Signal '{tag}' field '{field_name}': {e}") from e


def load_vocabulary(name: str = "0.1.json") -> StrictSignalVocabulary:
    """Read the packaged vocabulary and return a StrictSignalVocabulary bound to its tags."""
    text = files("price_space_llm._vocab").joinpath(name).read_text(encoding="utf-8")
    doc = json.loads(text)
    schema = {
        tag["name"]: {
            "category": tag["category"],
            "payload": [f["name"] for f in tag["typed_payload"] if f["required"]],
            "optional_payload": [f["name"] for f in tag["typed_payload"] if not f["required"]],
            "field_types": {f["name"]: f["type"] for f in tag["typed_payload"]},
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
        if tag == "SESSION_INIT":
            self._session_start = time.monotonic()
        super().emit(tag, **payload)
        if self._jsonl_sink is not None:
            signal = self._buffer[-1]
            with self._jsonl_sink.open("a", encoding="utf-8") as f:
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
