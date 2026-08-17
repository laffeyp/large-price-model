#!/usr/bin/env bash
# Sprint 064 pre-commit / commit-msg hook per tech-arch §13.
#
# Install by symlinking to `.git/hooks/commit-msg`:
#     ln -sf "$(pwd)/scripts/check_test_look.sh" .git/hooks/commit-msg
#
# Fails any commit whose staged config files carry dates >= 2024-01-01
# unless the commit message contains `[test-look]`. Delegates to
# `price_space_llm.hooks.check_commit_for_test_look`.
#
# Args:
#   $1 = path to the commit message file (git commit-msg hook convention).

set -euo pipefail

COMMIT_MSG_FILE="${1:-}"
if [[ -z "$COMMIT_MSG_FILE" ]]; then
    echo "check_test_look.sh: usage: check_test_look.sh <path/to/COMMIT_EDITMSG>" >&2
    exit 2
fi
if [[ ! -f "$COMMIT_MSG_FILE" ]]; then
    echo "check_test_look.sh: commit message file not found: $COMMIT_MSG_FILE" >&2
    exit 2
fi

# Resolve repo root so the Python script runs against the project's venv.
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
    PYTHON="$(command -v python3)"
fi

STAGED_FILES="$(git diff --cached --name-only --diff-filter=ACM || true)"

"$PYTHON" - "$COMMIT_MSG_FILE" <<'PYEOF' <<<"$STAGED_FILES"
import sys
from pathlib import Path

from price_space_llm.hooks import check_commit_for_test_look

commit_msg_file = Path(sys.argv[1])
commit_message = commit_msg_file.read_text(encoding="utf-8", errors="ignore")
staged_lines = [line.strip() for line in sys.stdin.readlines()]
staged_files = [Path(line) for line in staged_lines if line]

should_block, reason = check_commit_for_test_look(commit_message, staged_files)
if should_block:
    print(f"check_test_look: BLOCKING commit. {reason}", file=sys.stderr)
    sys.exit(1)
sys.exit(0)
PYEOF
