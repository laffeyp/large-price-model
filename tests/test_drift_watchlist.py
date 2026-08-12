"""Lint-style tests that fail if code drifts back into known anti-patterns.

Each test here corresponds to an entry in `BLACKBOARD.md § Drift watchlist`.
When a test fails, the fix is to remove the reintroduced anti-pattern —
NOT to update the test.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from price_space_llm.signals import StrictSignalEmitter, load_vocabulary

REPO_ROOT = Path(__file__).resolve().parents[1]


def _catch_names(node: ast.expr | None) -> list[str]:
    """Extract the exception type names an `except` clause catches."""
    if node is None:
        return ["<bare-except>"]
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    if isinstance(node, ast.Tuple):
        names: list[str] = []
        for elt in node.elts:
            names.extend(_catch_names(elt))
        return names
    return []


def _try_body_calls_emit(node: ast.Try) -> bool:
    for stmt in node.body:
        for sub in ast.walk(stmt):
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "emit"
            ):
                return True
    return False


def test_no_emit_call_caught_by_except_valueerror():
    """Anti-pattern from BLACKBOARD drift-watchlist (2026-08-11).

    The vocabulary's emit path raises ValueError when a payload violates the
    schema. Catching that ValueError and continuing means widening the shim
    to make the emitter stop refusing. The correct response is
    halt-and-articulate — halt the run, examine why the vocabulary refused,
    either evolve the vocabulary or remove the code that has nothing honest
    to say. Sprints 022-023 retracted this anti-pattern after it shipped in
    Sprint 020; this test fails the suite the next time it returns.
    """
    offenders: list[str] = []
    py_files = list((REPO_ROOT / "src").rglob("*.py")) + list((REPO_ROOT / "scripts").rglob("*.py"))
    for py in py_files:
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            if not _try_body_calls_emit(node):
                continue
            for handler in node.handlers:
                if "ValueError" in _catch_names(handler.type):
                    offenders.append(f"{py.relative_to(REPO_ROOT)}:{handler.lineno}")
    assert not offenders, (
        "Anti-pattern reintroduced: try:.emit(...) caught by except ValueError.\n"
        "See BLACKBOARD § Drift watchlist entry dated 2026-08-11.\n"
        "Offenders:\n  " + "\n  ".join(offenders)
    )


def test_session_init_truncates_prior_sink(tmp_path: Path):
    """BLACKBOARD drift-watchlist (2026-08-11): SESSION_INIT owns the trace file.

    Same-run_id re-invocations would otherwise append to a prior run's file
    and produce a trace with two SESSION_INIT lines and a mismatched
    n_signals_emitted. Fixed 2026-08-11.
    """
    sink = tmp_path / "logs" / "signals.jsonl"

    def _run_one_session() -> None:
        e = StrictSignalEmitter(load_vocabulary(), jsonl_sink=sink)
        e.emit(
            "SESSION_INIT",
            run_id="dedup-test",
            run_kind="probe",
            vocab_version="0.3",
            config_hash="0" * 64,
            git_sha="0" * 40,
            data_hash="0" * 64,
            seed=0,
        )
        e.emit(
            "SESSION_COMPLETE",
            run_id="dedup-test",
            exit_code=0,
            elapsed_seconds=0.001,
            n_signals_emitted=2,
        )

    _run_one_session()
    _run_one_session()

    lines = [json.loads(line) for line in sink.read_text(encoding="utf-8").splitlines()]
    session_inits = [line for line in lines if line["tag"] == "SESSION_INIT"]
    assert len(session_inits) == 1, (
        f"Sink held {len(session_inits)} SESSION_INIT lines; expected 1. "
        f"Same-run_id re-invocation must truncate the prior trace. Trace:\n"
        + "\n".join(json.dumps(line) for line in lines)
    )
    assert len(lines) == 2  # exactly one INIT + one COMPLETE from the second session
