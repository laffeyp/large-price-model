"""Tests for the test-look budget guard."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from price_space_llm.signals import StrictSignalEmitter, load_vocabulary
from price_space_llm.testlook import (
    DEFAULT_BUDGET,
    TestLookBudgetExhausted,
    looks_used,
    register_test_look,
)


def _fresh_emitter() -> StrictSignalEmitter:
    return StrictSignalEmitter(load_vocabulary())


def _fixed_now() -> datetime:
    return datetime(2026, 8, 12, tzinfo=UTC)


# Successful registration ------------------------------------------------


def test_first_look_registers_and_emits(tmp_path: Path):
    e = _fresh_emitter()
    log = tmp_path / "test_looks.log"
    record = register_test_look(
        reason="Sprint 034 smoke",
        run_id="eval-final-1",
        commit_sha="a" * 40,
        emitter=e,
        log_path=log,
        now=_fixed_now(),
    )
    assert record.looks_used == 1
    assert record.looks_remaining == 2
    assert record.date == "2026-08-12"
    tags = [s.tag for s in e.snapshot()]
    assert tags == ["TEST_LOOK_REGISTERED"]
    payload = e.snapshot()[0].payload
    assert payload["looks_used"] == 1
    assert payload["looks_remaining"] == 2


def test_three_looks_fill_the_budget(tmp_path: Path):
    e = _fresh_emitter()
    log = tmp_path / "test_looks.log"
    for i in range(3):
        register_test_look(
            reason=f"look {i}",
            run_id=f"eval-{i}",
            commit_sha="b" * 40,
            emitter=e,
            log_path=log,
        )
    assert looks_used(log) == 3
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    # Each line is valid JSON with the expected fields.
    for i, raw in enumerate(lines):
        entry = json.loads(raw)
        assert entry["looks_used"] == i + 1
        assert entry["looks_remaining"] == 2 - i


# Budget exhaustion -------------------------------------------------------


def test_fourth_look_emits_budget_exhausted_and_raises(tmp_path: Path):
    e = _fresh_emitter()
    log = tmp_path / "test_looks.log"
    for i in range(3):
        register_test_look(
            reason=f"look {i}",
            run_id=f"eval-{i}",
            commit_sha="c" * 40,
            emitter=e,
            log_path=log,
        )
    with pytest.raises(TestLookBudgetExhausted, match="already spent"):
        register_test_look(
            reason="one too many",
            run_id="eval-fourth",
            commit_sha="d" * 40,
            emitter=e,
            log_path=log,
        )
    exhaust = next(s for s in e.snapshot() if s.tag == "TEST_LOOK_BUDGET_EXHAUSTED")
    assert exhaust.payload["existing_looks"] == 3
    assert exhaust.payload["attempted_run_id"] == "eval-fourth"


def test_budget_is_persistent_across_emitter_lifetimes(tmp_path: Path):
    """A fresh emitter with the same log path still respects the accumulated budget."""
    log = tmp_path / "test_looks.log"
    for i in range(3):
        e = _fresh_emitter()
        register_test_look(
            reason=f"look {i}",
            run_id=f"eval-{i}",
            commit_sha="e" * 40,
            emitter=e,
            log_path=log,
        )
    e_new = _fresh_emitter()
    with pytest.raises(TestLookBudgetExhausted):
        register_test_look(
            reason="past-budget attempt",
            run_id="eval-4",
            commit_sha="f" * 40,
            emitter=e_new,
            log_path=log,
        )


def test_no_write_on_budget_exhausted(tmp_path: Path):
    """The exhausted attempt must NOT append to the log."""
    e = _fresh_emitter()
    log = tmp_path / "test_looks.log"
    for i in range(3):
        register_test_look(
            reason=f"look {i}",
            run_id=f"r-{i}",
            commit_sha="0" * 40,
            emitter=e,
            log_path=log,
        )
    prior_bytes = log.read_bytes()
    with pytest.raises(TestLookBudgetExhausted):
        register_test_look(
            reason="rejected",
            run_id="r-4",
            commit_sha="0" * 40,
            emitter=e,
            log_path=log,
        )
    assert log.read_bytes() == prior_bytes


# Input validation --------------------------------------------------------


def test_empty_reason_rejected(tmp_path: Path):
    e = _fresh_emitter()
    with pytest.raises(ValueError, match="reason"):
        register_test_look(
            reason="   ",
            run_id="x",
            commit_sha="a" * 40,
            emitter=e,
            log_path=tmp_path / "log",
        )


def test_empty_commit_sha_rejected(tmp_path: Path):
    e = _fresh_emitter()
    with pytest.raises(ValueError, match="commit_sha"):
        register_test_look(
            reason="valid",
            run_id="x",
            commit_sha="",
            emitter=e,
            log_path=tmp_path / "log",
        )


def test_malformed_log_line_raises(tmp_path: Path):
    log = tmp_path / "log"
    log.write_text("[1, 2, 3]\n", encoding="utf-8")  # JSON list, not object
    e = _fresh_emitter()
    with pytest.raises(ValueError, match="malformed"):
        register_test_look(
            reason="new",
            run_id="x",
            commit_sha="a" * 40,
            emitter=e,
            log_path=log,
        )


# looks_used --------------------------------------------------------------


def test_looks_used_returns_zero_when_log_absent(tmp_path: Path):
    assert looks_used(tmp_path / "does-not-exist") == 0


def test_looks_used_counts_only_non_empty_lines(tmp_path: Path):
    log = tmp_path / "log"
    log.write_text(
        '{"run_id": "a"}\n\n{"run_id": "b"}\n   \n{"run_id": "c"}\n',
        encoding="utf-8",
    )
    assert looks_used(log) == 3


def test_budget_default_matches_product_spec():
    assert DEFAULT_BUDGET == 3
