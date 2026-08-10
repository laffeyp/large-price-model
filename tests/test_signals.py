"""Tests for the strict signal emitter over the locked vocabulary."""
import hashlib
import json
import time
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

VALID_SESSION_COMPLETE_PAYLOAD = {
    "run_id": "test-run-001",
    "exit_code": 0,
    "elapsed_seconds": 0.001,
    "n_signals_emitted": 2,
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


def test_locked_vocabulary_loads_with_55_tags():
    vocab = load_vocabulary()
    assert len(vocab.tags()) == 55


def test_unknown_tag_raises():
    with pytest.raises(ValueError, match="Unknown signal tag"):
        emitter.emit("NOT_A_REAL_TAG")


def test_missing_required_payload_raises():
    with pytest.raises(ValueError, match="missing required payload fields"):
        emitter.emit("SESSION_INIT", run_id="test-run-001")


def test_extra_payload_field_raises():
    with pytest.raises(ValueError, match="unknown payload fields"):
        emitter.emit("SESSION_INIT", bogus_field="not allowed", **VALID_SESSION_INIT_PAYLOAD)


# Typed-payload enforcement tests (Sprint 004) ---------------------------------


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
    # No field in v0.1 currently types as `uuid` (trade_id is entity_ref<Trade>),
    # so the uuid checker is exercised at parser level rather than through emit().
    from price_space_llm.signals import _parse_type
    uuid_check = _parse_type("uuid")
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
    # TRADING_SESSION_STARTED requires session_date: date_iso
    bad = {
        "session_date": "2024/06/01",  # slashes, not dashes
        "first_bar_timestamp": "2024-06-01T13:30:00+00:00",
        "target_symbol": "SPY",
    }
    with pytest.raises(ValueError, match="session_date"):
        emitter.emit("TRADING_SESSION_STARTED", **bad)


def test_list_element_type_mismatch_raises():
    # BUCKET_FREQUENCY_DRIFT_MEASURED has train_frequency_by_bucket: list<float>
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
    # A canary — the strictness upgrade should not break the base case.
    e = StrictSignalEmitter(load_vocabulary())
    e.emit("SESSION_INIT", **VALID_SESSION_INIT_PAYLOAD)
    e.emit("SESSION_COMPLETE", **VALID_SESSION_COMPLETE_PAYLOAD)


# JSONL sink tests --------------------------------------------------------------


def test_jsonl_sink_writes_one_line_per_emit(tmp_path: Path):
    sink = tmp_path / "signals.jsonl"
    e = StrictSignalEmitter(load_vocabulary(), jsonl_sink=sink)
    e.emit("SESSION_INIT", **VALID_SESSION_INIT_PAYLOAD)
    e.emit("CHECKPOINT_WRITTEN", **VALID_CHECKPOINT_WRITTEN_PAYLOAD)
    complete = {**VALID_SESSION_COMPLETE_PAYLOAD, "n_signals_emitted": 3}
    e.emit("SESSION_COMPLETE", **complete)
    lines = sink.read_text().strip().split("\n")
    assert len(lines) == 3


def test_session_init_and_complete_bookend_the_trace(tmp_path: Path):
    sink = tmp_path / "signals.jsonl"
    e = StrictSignalEmitter(load_vocabulary(), jsonl_sink=sink)
    e.emit("SESSION_INIT", **VALID_SESSION_INIT_PAYLOAD)
    e.emit("SESSION_COMPLETE", **VALID_SESSION_COMPLETE_PAYLOAD)
    lines = [json.loads(line) for line in sink.read_text().strip().split("\n")]
    assert lines[0]["tag"] == "SESSION_INIT"
    assert lines[-1]["tag"] == "SESSION_COMPLETE"


def test_session_init_resets_the_clock(tmp_path: Path):
    sink = tmp_path / "signals.jsonl"
    e = StrictSignalEmitter(load_vocabulary(), jsonl_sink=sink)
    time.sleep(0.05)  # emitter has been alive; without a reset t would read ~0.05
    e.emit("SESSION_INIT", **VALID_SESSION_INIT_PAYLOAD)
    line = json.loads(sink.read_text().strip())
    assert line["t"] < 0.005
