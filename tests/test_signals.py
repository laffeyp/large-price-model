"""Sprint 001 tests — StrictSignalEmitter over the locked v0.1 vocabulary."""
import pytest

from price_space_llm.signals import emitter, load_vocabulary


VALID_SESSION_INIT_PAYLOAD = {
    "run_id": "test-run-001",
    "run_kind": "eval",
    "vocab_version": "0.1",
    "config_hash": "a" * 64,
    "git_sha": "b" * 40,
    "data_hash": "c" * 64,
    "seed": 1337,
}


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
