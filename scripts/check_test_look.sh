#!/usr/bin/env bash
# Sprint 064 pre-commit / commit-msg hook per tech-arch §13.
# Sprint 106 fixed the double-redirection bug that made the Sprint 064 script
# always exit nonzero with a NameError on staged filenames.
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

# Sprint 106 rewrite: pipe staged files on stdin, pass commit-msg file as argv.
# The prior Sprint 064 form used `<<PYEOF ... <<<"$STAGED_FILES"` which is two
# redirections on one command; bash keeps only the last, so the heredoc script
# never reached Python and the file list was executed as source code.
git diff --cached --name-only --diff-filter=ACM 2>/dev/null | "$PYTHON" -c '
import sys
from pathlib import Path

from price_space_llm.hooks import check_commit_for_test_look

commit_msg_file = Path(sys.argv[1])
commit_message = commit_msg_file.read_text(encoding="utf-8", errors="ignore")
staged_files = [Path(line.strip()) for line in sys.stdin if line.strip()]

should_block, reason = check_commit_for_test_look(commit_message, staged_files)
if should_block:
    print(f"check_test_look: BLOCKING commit. {reason}", file=sys.stderr)
    sys.exit(1)
sys.exit(0)
' "$COMMIT_MSG_FILE"
