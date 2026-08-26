#!/usr/bin/env bash
# Sprint 107: package the training payload + code tarball, push to S3, emit a
# SHA-256 manifest so the remote box can byte-verify. Deterministic given the
# same tree contents.
#
# Usage:
#   sync_to_gpu.sh --run-id <id> [--dry-run]
#
# Uploads to: s3://price-space-llm-v1-payload/<run-id>/
# Payload:
#   - data/tokenized/tokens.latest.pt
#   - artifacts/tokenizer/normalizers.latest.pt
#   - artifacts/tokenizer/bucket_stats.latest.json
#   - src/ + scripts/ + pyproject.toml + uv.lock (as code.tar.gz)
#   - manifest.sha256

set -euo pipefail

# Sprint 108 (review §11.4): sha256sum is GNU coreutils; macOS ships `shasum -a 256`
# under a different name. Shim so the same script runs cross-platform.
command -v sha256sum >/dev/null 2>&1 || sha256sum() { shasum -a 256 "$@"; }

RUN_ID=""
DRY_RUN=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --run-id) RUN_ID="$2"; shift 2;;
        --dry-run) DRY_RUN=1; shift;;
        *) echo "sync_to_gpu: unknown flag: $1" >&2; exit 2;;
    esac
done

if [[ -z "$RUN_ID" ]]; then
    echo "sync_to_gpu: --run-id required" >&2
    exit 2
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

BUCKET="price-space-llm-v1-payload"
S3_PREFIX="s3://${BUCKET}/${RUN_ID}"

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

PAYLOAD_FILES=(
    "data/tokenized/tokens.latest.pt"
    "artifacts/tokenizer/normalizers.latest.pt"
    "artifacts/tokenizer/bucket_stats.latest.json"
)

# Package code deterministically. GNU tar (Linux) supports --sort/--owner/--mtime;
# BSD tar (macOS) does not. Use a portable form: build a sorted file list,
# feed it to tar via -T, and pass the archive through gzip -n (no timestamp).
CODE_TAR="${STAGING}/code.tar.gz"
FILE_LIST="${STAGING}/files.txt"
(
    find src scripts -type f -print
    # sdd-kit-2/lib/sdd.py is force-included by pyproject; signals/*.json is
    # the vocabulary; both are required at build/runtime.
    find sdd-kit-2/lib signals -type f \( -name '*.py' -o -name '*.json' \) -print
    printf 'pyproject.toml\nuv.lock\n'
) | LC_ALL=C sort > "$FILE_LIST"
tar -cf - -T "$FILE_LIST" | gzip -n -c > "$CODE_TAR"

# Manifest: sha256 of every payload file + code tarball.
# Sprint 109 (from CPU dry-run bug): write hashes against basenames only.
# The remote box downloads payload files flat into a working dir and verifies
# there; a repo-relative path in the manifest would not match the flat layout.
MANIFEST="${STAGING}/manifest.sha256"
{
    for f in "${PAYLOAD_FILES[@]}"; do
        if [[ -e "$f" ]]; then
            ( cd "$(dirname "$f")" && sha256sum "$(basename "$f")" )
        else
            echo "sync_to_gpu: missing payload file: $f" >&2
            exit 1
        fi
    done
    ( cd "$STAGING" && sha256sum code.tar.gz )
} > "$MANIFEST"

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "sync_to_gpu: DRY RUN. Would upload to ${S3_PREFIX}/" >&2
    echo "sync_to_gpu: manifest:" >&2
    cat "$MANIFEST" >&2
    exit 0
fi

echo "sync_to_gpu: uploading payload to ${S3_PREFIX}/" >&2
for f in "${PAYLOAD_FILES[@]}"; do
    aws s3 cp "$f" "${S3_PREFIX}/$(basename "$f")"
done
aws s3 cp "$CODE_TAR" "${S3_PREFIX}/code.tar.gz"
aws s3 cp "$MANIFEST" "${S3_PREFIX}/manifest.sha256"

echo "sync_to_gpu: done. run_id=${RUN_ID}" >&2
