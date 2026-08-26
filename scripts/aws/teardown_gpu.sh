#!/usr/bin/env bash
# Sprint 107: terminate an instance and clean up orphaned resources.
#
# Usage:
#   teardown_gpu.sh --instance-id i-abc
#   teardown_gpu.sh --sprint <id>      # terminates all instances tagged RunSprint=<id>
#
# Idempotent: safe to run twice; terminated instances stay terminated.

set -euo pipefail

INSTANCE_ID=""
SPRINT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --instance-id) INSTANCE_ID="$2"; shift 2;;
        --sprint) SPRINT="$2"; shift 2;;
        *) echo "teardown_gpu: unknown flag: $1" >&2; exit 2;;
    esac
done

REGION="us-east-1"

if [[ -n "$SPRINT" ]]; then
    INSTANCE_IDS=$(aws ec2 describe-instances --region "$REGION" \
        --filters "Name=tag:RunSprint,Values=${SPRINT}" \
                  "Name=instance-state-name,Values=pending,running,stopping,stopped" \
        --query 'Reservations[].Instances[].InstanceId' --output text)
    if [[ -z "$INSTANCE_IDS" ]]; then
        echo "teardown_gpu: no live instances tagged RunSprint=${SPRINT}" >&2
        exit 0
    fi
elif [[ -n "$INSTANCE_ID" ]]; then
    INSTANCE_IDS="$INSTANCE_ID"
else
    echo "teardown_gpu: --instance-id or --sprint required" >&2
    exit 2
fi

echo "teardown_gpu: terminating ${INSTANCE_IDS}" >&2
# shellcheck disable=SC2086  # word-splitting intended for multi-instance case
aws ec2 terminate-instances --region "$REGION" --instance-ids $INSTANCE_IDS >/dev/null

echo "teardown_gpu: waiting for terminated state..." >&2
# shellcheck disable=SC2086
aws ec2 wait instance-terminated --region "$REGION" --instance-ids $INSTANCE_IDS

# Cancel any open spot requests for this sprint.
if [[ -n "$SPRINT" ]]; then
    SPOT_REQ_IDS=$(aws ec2 describe-spot-instance-requests --region "$REGION" \
        --filters "Name=tag:RunSprint,Values=${SPRINT}" \
                  "Name=state,Values=open,active" \
        --query 'SpotInstanceRequests[].SpotInstanceRequestId' --output text)
    if [[ -n "$SPOT_REQ_IDS" ]]; then
        echo "teardown_gpu: cancelling spot requests: ${SPOT_REQ_IDS}" >&2
        # shellcheck disable=SC2086
        aws ec2 cancel-spot-instance-requests --region "$REGION" \
            --spot-instance-request-ids $SPOT_REQ_IDS >/dev/null
    fi
fi

echo "teardown_gpu: done." >&2
