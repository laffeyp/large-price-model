"""Test-look budget guard.

Product-spec §13: at most three authorized queries against the held-out
test partition across the whole project's lifetime. Every look must be
registered here, with a commit_sha and a written reason, BEFORE any
test-partition metric is computed. Each successful registration writes
one JSON line to `experiments/test_looks.log` and emits
`TEST_LOOK_REGISTERED`. Any registration beyond the budget emits
`TEST_LOOK_BUDGET_EXHAUSTED` and raises.

The log is append-only. Deleting or editing entries defeats the guard
and violates the budget contract. A pre-commit hook (later sprint)
verifies the commit message carries the `[test-look]` token when new
log entries are staged.
"""

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from price_space_llm.signals import StrictSignalEmitter

DEFAULT_BUDGET = 3
DEFAULT_LOG_PATH = Path("experiments/test_looks.log")


class TestLookBudgetExhausted(RuntimeError):
    """Raised after emitting TEST_LOOK_BUDGET_EXHAUSTED so the caller can exit nonzero."""

    # Prevent pytest from collecting the exception class as a test class.
    __test__ = False


@dataclass(slots=True, frozen=True, kw_only=True)
class TestLookRecord:
    date: str  # ISO date at registration time
    run_id: str
    reason: str
    commit_sha: str
    looks_used: int
    looks_remaining: int

    # Prevent pytest from collecting the dataclass as a test class.
    __test__ = False


def _read_existing(log_path: Path) -> list[dict[str, object]]:
    """Read every JSON line from the log. Returns an empty list if the log does not exist."""
    if not log_path.exists():
        return []
    lines = log_path.read_text(encoding="utf-8").splitlines()
    out: list[dict[str, object]] = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            raise ValueError(f"malformed test_looks.log entry: {raw!r}")
        out.append(obj)
    return out


def register_test_look(
    *,
    reason: str,
    run_id: str,
    commit_sha: str,
    emitter: StrictSignalEmitter,
    log_path: Path = DEFAULT_LOG_PATH,
    budget: int = DEFAULT_BUDGET,
    now: datetime | None = None,
) -> TestLookRecord:
    """Register one authorized test-partition look; emit the tag; append the log.

    Raises `TestLookBudgetExhausted` after emitting `TEST_LOOK_BUDGET_EXHAUSTED`
    if this attempt would push the total over `budget`.

    `reason` must be non-empty (contract from the pre-commit hook that also
    checks for the `[test-look]` token in the commit message).
    """
    if not reason.strip():
        raise ValueError("test-look reason must be non-empty")
    if not commit_sha.strip():
        raise ValueError("test-look commit_sha must be non-empty")

    existing = _read_existing(log_path)
    existing_looks = len(existing)

    if existing_looks >= budget:
        emitter.emit(
            "TEST_LOOK_BUDGET_EXHAUSTED",
            existing_looks=existing_looks,
            attempted_run_id=run_id,
            commit_sha=commit_sha,
        )
        raise TestLookBudgetExhausted(
            f"test-look budget of {budget} already spent; refusing to register {run_id!r}"
        )

    stamp = (now or datetime.now(UTC)).date().isoformat()
    looks_used = existing_looks + 1
    looks_remaining = budget - looks_used
    record = TestLookRecord(
        date=stamp,
        run_id=run_id,
        reason=reason,
        commit_sha=commit_sha,
        looks_used=looks_used,
        looks_remaining=looks_remaining,
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(record), sort_keys=True) + "\n")

    emitter.emit(
        "TEST_LOOK_REGISTERED",
        date=stamp,
        run_id=run_id,
        reason=reason,
        commit_sha=commit_sha,
        looks_used=looks_used,
        looks_remaining=looks_remaining,
    )
    return record


def looks_used(log_path: Path = DEFAULT_LOG_PATH) -> int:
    """How many looks have been consumed so far."""
    return len(_read_existing(log_path))
