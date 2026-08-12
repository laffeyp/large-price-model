#!/usr/bin/env python3
"""CLI wrapper around `register_test_look`.

Refuses to register beyond the pre-registered 3-look budget. Every
successful registration appends one JSON line to `experiments/test_looks.log`
and emits TEST_LOOK_REGISTERED. An attempted 4th look emits
TEST_LOOK_BUDGET_EXHAUSTED and exits 2.
"""

import argparse
import hashlib
import sys
from pathlib import Path

from price_space_llm.git import git_sha
from price_space_llm.script_harness import script_session
from price_space_llm.testlook import (
    DEFAULT_BUDGET,
    DEFAULT_LOG_PATH,
    TestLookBudgetExhausted,
    register_test_look,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="register_test_look")
    parser.add_argument(
        "--reason",
        required=True,
        help="Non-empty prose reason for consuming a test-partition look.",
    )
    parser.add_argument(
        "--run-id",
        required=True,
        help="The run_id of the eval or sim run that will query the test partition.",
    )
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG_PATH)
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    parser.add_argument("--logs-dir", type=Path, default=Path("logs"))
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    commit_sha = git_sha()
    session_run_id = f"testlook-register-{args.seed:016d}"
    config_hash = hashlib.sha256(args.reason.encode("utf-8")).hexdigest()
    data_hash = hashlib.sha256(
        args.log_path.read_bytes() if args.log_path.exists() else b""
    ).hexdigest()

    with script_session(
        run_kind="eval",  # v0.3 has no `testlook` run_kind; eval is the closest fit.
        run_id=session_run_id,
        config_hash=config_hash,
        data_hash=data_hash,
        seed=args.seed,
        logs_dir=args.logs_dir,
    ) as (emitter, sink_path):
        try:
            record = register_test_look(
                reason=args.reason,
                run_id=args.run_id,
                commit_sha=commit_sha,
                emitter=emitter,
                log_path=args.log_path,
                budget=args.budget,
            )
        except TestLookBudgetExhausted as ex:
            print(f"register_test_look: {ex}", file=sys.stderr)
            print(f"register_test_look: trace={sink_path}", file=sys.stderr)
            return 2
        except ValueError as ex:
            print(f"register_test_look: invalid input: {ex}", file=sys.stderr)
            return 1

    print(
        f"register_test_look: OK. used {record.looks_used}/{args.budget}; "
        f"remaining {record.looks_remaining}; log={args.log_path}; trace={sink_path}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
