"""Sprint 001 + 002 tests — StrictSignalEmitter over the locked v0.1 vocabulary."""
import json
import time
from pathlib import Path

import pytest

from price_space_llm.signals import (
    StrictSignalEmitter,
    emitter,
    load_vocabulary,
)


VALID_SESSION_INIT_PAYLOAD = {
    "run_id": "test-run-001",
    "run_kind": "eval",
    "vocab_version": "0.1",
    "config_hash": "a" * 64,
    "git_sha": "b" * 40,
    "data_hash": "c" * 64,
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


# Sprint 001 tests --------------------------------------------------------------


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


# Sprint 002 tests --------------------------------------------------------------


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
