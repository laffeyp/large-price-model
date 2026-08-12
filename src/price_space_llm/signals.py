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

`get_emitter()` is the module singleton factory (cached). Import-time
`from price_space_llm.signals import emitter` still works via the
module-level `__getattr__` shim (PEP 562), resolving to the same
cached instance without touching disk at package import.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any
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
        if v.tzinfo is None or v.tzinfo.utcoffset(v) != UTC.utcoffset(v):
            raise ValueError(f"expected datetime with UTC tzinfo, got {v!r}")
        return
    if not isinstance(v, str):
        raise ValueError(f"expected datetime_utc, got {type(v).__name__}")
    try:
        parsed = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError as e:
        raise ValueError(f"expected ISO-8601 datetime string, got {v!r}: {e}") from e
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) != UTC.utcoffset(parsed):
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


def check_struct(fields: dict[str, Checker]) -> Checker:
    def check(v: Any) -> None:
        if not isinstance(v, dict):
            raise ValueError(f"expected struct (dict), got {type(v).__name__}")
        allowed = set(fields.keys())
        provided = set(v.keys())
        missing = allowed - provided
        if missing:
            raise ValueError(f"struct missing fields: {sorted(missing)}")
        extras = provided - allowed
        if extras:
            raise ValueError(f"struct has unknown fields: {sorted(extras)}")
        for name, val in v.items():
            try:
                fields[name](val)
            except ValueError as e:
                raise ValueError(f"struct field {name!r}: {e}") from e

    return check


def _split_top_level(s: str, sep: str) -> list[str]:
    """Split s on `sep` at depth 0 (respecting angle-bracket nesting)."""
    parts: list[str] = []
    depth = 0
    start = 0
    for i, c in enumerate(s):
        if c == "<":
            depth += 1
        elif c == ">":
            depth -= 1
        elif c == sep and depth == 0:
            parts.append(s[start:i])
            start = i + 1
    parts.append(s[start:])
    return parts


def parse_type(type_str: str) -> Checker:
    """Turn a vocabulary type string into a callable checker."""
    if type_str in _TYPE_CHECKERS:
        return _TYPE_CHECKERS[type_str]
    if type_str.startswith("enum<") and type_str.endswith(">"):
        values = frozenset(type_str[5:-1].split("|"))
        return _check_enum(values)
    if type_str.startswith("entity_ref<") and type_str.endswith(">"):
        return _check_entity_ref
    if type_str.startswith("list<") and type_str.endswith(">"):
        return _check_list_of(parse_type(type_str[5:-1]))
    if type_str.startswith("dict<") and type_str.endswith(">"):
        inner = type_str[5:-1]
        parts = _split_top_level(inner, ",")
        if len(parts) != 2:
            raise ValueError(f"dict<K,V> must have exactly one top-level comma: {type_str!r}")
        k = parts[0].strip()
        v = parts[1].strip()
        return _check_dict_of(parse_type(k), parse_type(v))
    if type_str.startswith("struct<") and type_str.endswith(">"):
        inner = type_str[7:-1]
        fields: dict[str, Checker] = {}
        for part in _split_top_level(inner, ","):
            name_type = _split_top_level(part.strip(), ":")
            if len(name_type) != 2:
                raise ValueError(f"struct field must be 'name:type', got {part!r}")
            name, type_s = name_type[0].strip(), name_type[1].strip()
            fields[name] = parse_type(type_s)
        return check_struct(fields)
    # Unknown type string — Layer-2 authoring error. Either a typo in the
    # vocabulary JSON or an unimplemented type. Fail loudly so the author
    # corrects the typo or registers the new type in _TYPE_CHECKERS.
    raise ValueError(
        f"Unknown type string {type_str!r}. "
        f"Known primitives: {sorted(_TYPE_CHECKERS)}. "
        f"Known composites: enum<...>, entity_ref<...>, list<...>, "
        f"dict<...,...>, struct<name:type, ...>."
    )


# ── vocabulary + emitter ──────────────────────────────────────────────────────


class StrictSignalVocabulary(SignalVocabulary):  # type: ignore[misc]
    """Vocabulary that enforces strict extras AND per-field type checks."""

    def __init__(self, schema: dict[str, dict[str, Any]], version: str = "unknown") -> None:
        super().__init__(schema)
        self.version = version
        self._field_checkers: dict[str, dict[str, Checker]] = {}
        for tag, entry in schema.items():
            if "field_types" not in entry:
                raise ValueError(
                    f"Tag {tag!r} schema entry is missing 'field_types'. "
                    f"Every entry must declare field_types (may be empty dict) "
                    f"so validation cannot silently degrade."
                )
            self._field_checkers[tag] = {
                field_name: parse_type(type_str)
                for field_name, type_str in entry["field_types"].items()
            }

    def validate(self, tag: str, payload: dict[str, Any]) -> None:
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
                continue
            try:
                checker(value)
            except ValueError as e:
                raise ValueError(f"Signal '{tag}' field '{field_name}': {e}") from e


def load_vocabulary(name: str = "0.3.json") -> StrictSignalVocabulary:
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
    return StrictSignalVocabulary(schema, version=doc.get("version", "unknown"))


class StrictSignalEmitter(SignalEmitter):  # type: ignore[misc]
    """SignalEmitter with an optional JSONL sink and a per-session clock reset.

    When `jsonl_sink` is set, every successful emit appends one JSON line to
    the sink path. Every SESSION_INIT emit resets `_session_start`, so
    subsequent tags in that capture carry `t` values relative to the init.
    """

    def __init__(
        self,
        vocabulary: StrictSignalVocabulary,
        max_buffer: int = 500,
        jsonl_sink: Path | None = None,
    ) -> None:
        super().__init__(vocabulary, max_buffer=max_buffer)
        self._jsonl_sink = jsonl_sink
        self._sink_prepared = False

    def emit(self, tag: str, **payload: Any) -> None:
        if tag == "SESSION_INIT":
            self._session_start = time.monotonic()
        super().emit(tag, **payload)
        if self._jsonl_sink is not None:
            if not self._sink_prepared:
                self._jsonl_sink.parent.mkdir(parents=True, exist_ok=True)
                self._sink_prepared = True
            signal = Signal(
                tag=tag,
                category=self._vocab.category_of(tag),
                payload=payload,
                t=time.monotonic() - self._session_start,
            )
            with self._jsonl_sink.open("a", encoding="utf-8") as f:
                f.write(json.dumps(signal.to_dict()) + "\n")


@lru_cache(maxsize=1)
def get_emitter() -> StrictSignalEmitter:
    """Cached module singleton. First call reads the vocabulary; later calls return the same."""
    return StrictSignalEmitter(load_vocabulary())


def _exit_code_from_systemexit(code: Any) -> int:
    """Coerce SystemExit.code to a canonical int per Python convention."""
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    return 1  # non-integer string codes conventionally exit 1


@contextmanager
def process_session(
    run_kind: str,
    config_hash: str,
    git_sha: str,
    data_hash: str,
    seed: int,
    run_id: str | None = None,
    emitter: StrictSignalEmitter | None = None,
) -> Iterator[str]:
    """Wrap a script's work. Emits SESSION_INIT on enter, SESSION_COMPLETE on exit.

    exit_code convention: 0 on clean exit; SystemExit(N) -> N; any other exception -> 1.
    n_signals_emitted counts every signal emitted between the two boundary tags, inclusive.
    `emitter` defaults to the module singleton; pass a fresh instance to route
    a session through a custom JSONL sink without mutating the singleton.
    """
    e = emitter if emitter is not None else get_emitter()
    if run_id is None:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"{run_kind}-{ts}-{seed}"
    buffer_before = len(e.snapshot())
    start = time.monotonic()
    e.emit(
        "SESSION_INIT",
        run_id=run_id,
        run_kind=run_kind,
        vocab_version=e._vocab.version,
        config_hash=config_hash,
        git_sha=git_sha,
        data_hash=data_hash,
        seed=seed,
    )
    exit_code = 0
    raised: BaseException | None = None
    try:
        yield run_id
    except SystemExit as ex:
        exit_code = _exit_code_from_systemexit(ex.code)
        raised = ex
    except BaseException as ex:
        exit_code = 1
        raised = ex
    finally:
        # +1 because SESSION_COMPLETE emit itself has not fired yet.
        n = (len(e.snapshot()) - buffer_before) + 1
        e.emit(
            "SESSION_COMPLETE",
            run_id=run_id,
            exit_code=exit_code,
            elapsed_seconds=time.monotonic() - start,
            n_signals_emitted=n,
        )
    if raised is not None:
        raise raised


def __getattr__(name: str) -> Any:
    """PEP 562 shim: `from price_space_llm.signals import emitter` returns get_emitter()."""
    if name == "emitter":
        return get_emitter()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "Signal",
    "SignalCapture",
    "StrictSignalEmitter",
    "StrictSignalVocabulary",
    "capture",
    "check_struct",
    "get_emitter",
    "load_vocabulary",
    "parse_type",
    "process_session",
]


# Backwards-compat aliases for the previously private forms. Underscore
# imports remain valid until a future sprint's KIT_DIARY entry confirms
# no external caller uses them.
_parse_type = parse_type
_check_struct = check_struct
