"""Tests for the strict signal emitter over the locked vocabulary."""

import hashlib
import json
import time
from importlib.resources import files
from pathlib import Path

import pytest

from price_space_llm.signals import (
    StrictSignalEmitter,
    emitter,
    load_vocabulary,
)

_REAL_HASH = hashlib.sha256(b"test-run-001").hexdigest()
_REAL_DATA_HASH = hashlib.sha256(b"training-data-2015-2022").hexdigest()
_REAL_GIT_SHA = "1" * 40  # 40 lowercase hex; git_sha is typed str in v0.1


VALID_SESSION_INIT_PAYLOAD = {
    "run_id": "test-run-001",
    "run_kind": "eval",
    "vocab_version": "0.1",
    "config_hash": _REAL_HASH,
    "git_sha": _REAL_GIT_SHA,
    "data_hash": _REAL_DATA_HASH,
    "seed": 1337,
}

# n_signals_emitted is computed at each call site; it depends on how many
# tags each test emits and does not belong in a shared constant.
VALID_SESSION_COMPLETE_PARTIAL = {
    "run_id": "test-run-001",
    "exit_code": 0,
    "elapsed_seconds": 0.001,
}

VALID_CHECKPOINT_WRITTEN_PAYLOAD = {
    "run_id": "test-run-001",
    "step": 100,
    "path": "/tmp/ckpt.pt",
    "val_nll": 0.5,
    "val_ece": 0.03,
    "val_brier": 0.1,
    "val_rps": 0.2,
    "val_dir_acc": 0.55,
    "val_top1": 0.3,
    "val_top3": 0.6,
}


# Validator tests ---------------------------------------------------------------


def test_locked_vocabulary_loads_all_tags():
    vocab = load_vocabulary()
    raw = json.loads(
        files("price_space_llm._vocab").joinpath("0.2.json").read_text(encoding="utf-8")
    )
    assert len(vocab.tags()) == len(raw["tags"])


def test_unknown_tag_raises():
    with pytest.raises(ValueError, match="Unknown signal tag"):
        emitter.emit("NOT_A_REAL_TAG")


def test_missing_required_payload_raises():
    with pytest.raises(ValueError, match="missing required payload fields"):
        emitter.emit("SESSION_INIT", run_id="test-run-001")


def test_extra_payload_field_raises():
    with pytest.raises(ValueError, match="unknown payload fields"):
        emitter.emit("SESSION_INIT", bogus_field="not allowed", **VALID_SESSION_INIT_PAYLOAD)


# Typed-payload enforcement tests ----------------------------------------------


def test_enum_value_outside_declared_set_raises():
    bad = {**VALID_SESSION_INIT_PAYLOAD, "run_kind": "banana"}
    with pytest.raises(ValueError, match="run_kind"):
        emitter.emit("SESSION_INIT", **bad)


def test_sha256_wrong_length_raises():
    bad = {**VALID_SESSION_INIT_PAYLOAD, "config_hash": "abc123"}
    with pytest.raises(ValueError, match="config_hash"):
        emitter.emit("SESSION_INIT", **bad)


def test_sha256_non_hex_raises():
    bad = {**VALID_SESSION_INIT_PAYLOAD, "config_hash": "z" * 64}
    with pytest.raises(ValueError, match="config_hash"):
        emitter.emit("SESSION_INIT", **bad)


def test_int_type_mismatch_raises():
    bad = {**VALID_SESSION_INIT_PAYLOAD, "seed": "not an int"}
    with pytest.raises(ValueError, match="seed"):
        emitter.emit("SESSION_INIT", **bad)


def test_bool_masquerading_as_int_raises():
    bad = {**VALID_SESSION_INIT_PAYLOAD, "seed": True}
    with pytest.raises(ValueError, match="seed"):
        emitter.emit("SESSION_INIT", **bad)


def test_uuid_parser_rejects_malformed():
    from price_space_llm.signals import parse_type

    uuid_check = parse_type("uuid")
    uuid_check("550e8400-e29b-41d4-a716-446655440000")  # valid, no raise
    with pytest.raises(ValueError, match="uuid"):
        uuid_check("not-a-uuid")


def test_datetime_utc_malformed_raises():
    bad = {
        "trade_id": "trade-abc",
        "entry_ts": "not-a-datetime",
        "exit_ts": "2024-06-01T15:45:00+00:00",
        "direction": "long",
        "size": 1.0,
        "pnl_net": 12.34,
        "cost_spread": 0.5,
        "cost_slippage": 0.1,
    }
    with pytest.raises(ValueError, match="entry_ts"):
        emitter.emit("TRADE_LEDGERED", **bad)


def test_date_iso_malformed_raises():
    bad = {
        "session_date": "2024/06/01",
        "first_bar_timestamp": "2024-06-01T13:30:00+00:00",
        "target_symbol": "SPY",
    }
    with pytest.raises(ValueError, match="session_date"):
        emitter.emit("TRADING_SESSION_STARTED", **bad)


def test_list_element_type_mismatch_raises():
    bad = {
        "run_id": "r1",
        "split": "val",
        "train_frequency_by_bucket": [0.5, "not a float", 0.3],
        "realized_frequency_by_bucket": [0.4, 0.3, 0.3],
        "max_absolute_deviation": 0.1,
        "outer_bucket_ratio": 1.0,
    }
    with pytest.raises(ValueError, match="train_frequency_by_bucket"):
        emitter.emit("BUCKET_FREQUENCY_DRIFT_MEASURED", **bad)


def test_valid_payload_still_passes_after_type_upgrade():
    e = StrictSignalEmitter(load_vocabulary())
    e.emit("SESSION_INIT", **VALID_SESSION_INIT_PAYLOAD)
    e.emit("SESSION_COMPLETE", n_signals_emitted=2, **VALID_SESSION_COMPLETE_PARTIAL)


# JSONL sink tests --------------------------------------------------------------


def test_jsonl_sink_writes_one_line_per_emit(tmp_path: Path):
    sink = tmp_path / "signals.jsonl"
    e = StrictSignalEmitter(load_vocabulary(), jsonl_sink=sink)
    e.emit("SESSION_INIT", **VALID_SESSION_INIT_PAYLOAD)
    e.emit("CHECKPOINT_WRITTEN", **VALID_CHECKPOINT_WRITTEN_PAYLOAD)
    e.emit("SESSION_COMPLETE", n_signals_emitted=3, **VALID_SESSION_COMPLETE_PARTIAL)
    lines = sink.read_text().strip().split("\n")
    assert len(lines) == 3


def test_session_init_and_complete_bookend_the_trace(tmp_path: Path):
    sink = tmp_path / "signals.jsonl"
    e = StrictSignalEmitter(load_vocabulary(), jsonl_sink=sink)
    e.emit("SESSION_INIT", **VALID_SESSION_INIT_PAYLOAD)
    e.emit("SESSION_COMPLETE", n_signals_emitted=2, **VALID_SESSION_COMPLETE_PARTIAL)
    lines = [json.loads(line) for line in sink.read_text().strip().split("\n")]
    assert lines[0]["tag"] == "SESSION_INIT"
    assert lines[-1]["tag"] == "SESSION_COMPLETE"


def test_session_init_resets_the_clock(tmp_path: Path):
    sink = tmp_path / "signals.jsonl"
    e = StrictSignalEmitter(load_vocabulary(), jsonl_sink=sink)
    time.sleep(0.05)
    e.emit("SESSION_INIT", **VALID_SESSION_INIT_PAYLOAD)
    line = json.loads(sink.read_text().strip())
    # Threshold 0.04 comfortably distinguishes a reset (t < 1ms typically)
    # from no-reset (t >= 0.05 from the pre-emit sleep). 40x noise margin.
    assert line["t"] < 0.04


# Struct type kind -------------------------------------------------------------


def test_struct_parser_accepts_valid_record():
    from price_space_llm.signals import parse_type

    check = parse_type("struct<size_usd:float, sharpe:float, sharpe_se:float>")
    check({"size_usd": 1_000_000.0, "sharpe": 1.2, "sharpe_se": 0.3})


def test_struct_parser_rejects_missing_field():
    from price_space_llm.signals import parse_type

    check = parse_type("struct<size_usd:float, sharpe:float>")
    with pytest.raises(ValueError, match="missing fields"):
        check({"size_usd": 1_000_000.0})


def test_struct_parser_rejects_extra_field():
    from price_space_llm.signals import parse_type

    check = parse_type("struct<size_usd:float>")
    with pytest.raises(ValueError, match="unknown fields"):
        check({"size_usd": 1_000_000.0, "unexpected": 42})


def test_struct_parser_rejects_wrong_type_on_field():
    from price_space_llm.signals import parse_type

    check = parse_type("struct<size_usd:float, sharpe:float>")
    with pytest.raises(ValueError, match="sharpe"):
        check({"size_usd": 1_000_000.0, "sharpe": "not a number"})


def test_struct_parser_handles_nested_types():
    from price_space_llm.signals import parse_type

    check = parse_type("list<struct<size_usd:float, sharpe:float, sharpe_se:float>>")
    check(
        [
            {"size_usd": 100_000.0, "sharpe": 0.5, "sharpe_se": 0.2},
            {"size_usd": 500_000.0, "sharpe": 0.8, "sharpe_se": 0.25},
        ]
    )
    with pytest.raises(ValueError, match="list index 1"):
        check(
            [
                {"size_usd": 100_000.0, "sharpe": 0.5, "sharpe_se": 0.2},
                {"size_usd": 500_000.0, "sharpe": "bad", "sharpe_se": 0.25},
            ]
        )


# Parser and vocabulary strictness ---------------------------------------------


def test_parse_type_raises_on_unknown_type_string():
    from price_space_llm.signals import parse_type

    with pytest.raises(ValueError, match="Unknown type string"):
        parse_type("nonexistent_type")


def test_vocabulary_raises_on_missing_field_types():
    from price_space_llm.signals import StrictSignalVocabulary

    bad_schema = {
        "SOME_TAG": {
            "category": "session",
            "payload": ["run_id"],
            "optional_payload": [],
            # field_types missing on purpose — must raise
        }
    }
    with pytest.raises(ValueError, match="missing 'field_types'"):
        StrictSignalVocabulary(bad_schema)


# Sink tests --------------------------------------------------------------------


def test_sink_parent_created_on_first_emit_not_construction(tmp_path: Path):
    sink = tmp_path / "nested" / "dirs" / "signals.jsonl"
    e = StrictSignalEmitter(load_vocabulary(), jsonl_sink=sink)
    assert not sink.parent.exists()
    e.emit("SESSION_INIT", **VALID_SESSION_INIT_PAYLOAD)
    assert sink.parent.exists()
