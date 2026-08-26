#!/usr/bin/env bash
# Sprint 107: launch a GPU instance for training. Two modes: --dev (g5.xlarge spot,
# 2-hour walltime) and --prod (p4d.24xlarge on-demand, no walltime cap; falls back
# to g5.2xlarge on-demand if p4d quota is not approved).
#
# Tags every launch with Project=price-space-llm-v1 so Budgets filter matches.
#
# Usage:
#   provision_gpu.sh --dev [--dry-run]
#   provision_gpu.sh --prod [--dry-run] [--fallback g5.2xlarge]
#
# The --dry-run flag prints the fully-resolved RunInstances request JSON to stderr
# and exits 0 before calling the API. Use this to inspect the spec.

set -euo pipefail

MODE=""
DRY_RUN=0
FALLBACK=""
RUN_ID=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dev) MODE="dev"; shift;;
        --prod) MODE="prod"; shift;;
        --dry-run) DRY_RUN=1; shift;;
        --fallback) FALLBACK="$2"; shift 2;;
        --run-id) RUN_ID="$2"; shift 2;;
        *) echo "provision_gpu: unknown flag: $1" >&2; exit 2;;
    esac
done

if [[ -z "$MODE" ]]; then
    echo "provision_gpu: --dev or --prod is required" >&2
    exit 2
fi
if [[ -z "$RUN_ID" ]]; then
    echo "provision_gpu: --run-id <id> is required; the box uses it to fetch payload and upload traces" >&2
    exit 2
fi

REGION="us-east-1"
PROJECT_TAG="price-space-llm-v1"
SPRINT_ID="${SPRINT_ID:-107}"
INSTANCE_PROFILE="${INSTANCE_PROFILE:-pslm-v1-ec2-training}"
SECURITY_GROUP_NAME="${SECURITY_GROUP_NAME:-pslm-v1-training-sg}"

# Deep Learning OSS Nvidia Driver AMI GPU PyTorch 2.7 (Ubuntu 22.04), us-east-1.
# NVIDIA drivers + CUDA userspace preinstalled. The project ships its own torch
# via `uv sync`, so the DLAMI's PyTorch is not consumed directly.
# Refresh with:
#   aws ec2 describe-images --owners amazon \
#     --filters 'Name=name,Values=Deep Learning OSS Nvidia Driver AMI GPU PyTorch*Ubuntu 22.04*' \
#     --query 'sort_by(Images, &CreationDate)[-1].ImageId'
AMI_ID="${DEEP_LEARNING_AMI_ID:-ami-012ba162b9cd2729c}"

if [[ "$MODE" == "dev" ]]; then
    INSTANCE_TYPE="g5.xlarge"
    MARKET="spot"
    MAX_SPOT_PRICE="0.50"
    WALLTIME_MINUTES=120
elif [[ "$MODE" == "prod" ]]; then
    INSTANCE_TYPE="${FALLBACK:-p4d.24xlarge}"
    MARKET="on-demand"
    WALLTIME_MINUTES=0
fi

# Env var overrides for one-off launches (quota fallback, CPU dry-runs, etc.).
# Named on the sprint card when used; default flow uses the mode block above.
INSTANCE_TYPE="${INSTANCE_TYPE_OVERRIDE:-$INSTANCE_TYPE}"
MARKET="${MARKET_OVERRIDE:-$MARKET}"

# User-data runs on boot as root. Fetch payload from S3, verify manifest,
# unpack code, install uv, sync deps, run training, upload trace, terminate.
# The walltime shutdown remains as a backstop for hangs.
USER_DATA=$(cat <<EOF
#!/bin/bash
set -euo pipefail
exec > >(tee -a /var/log/pslm-provision.log) 2>&1
echo "pslm boot at \$(date -u +%FT%TZ)"
export AWS_DEFAULT_REGION=us-east-1
RUN_ID="${RUN_ID}"
PAYLOAD_S3="s3://price-space-llm-v1-payload/\${RUN_ID}"
LOGS_S3="s3://price-space-llm-v1-logs/\${RUN_ID}"

# Backstop walltime cap (kills the box if training hangs).
if [[ ${WALLTIME_MINUTES} -gt 0 ]]; then
    shutdown -h +${WALLTIME_MINUTES} "pslm-v1 walltime cap" || true
fi

# Trap: on any failure, upload the provision log so we can see what happened.
on_error() {
    aws s3 cp /var/log/pslm-provision.log "\${LOGS_S3}/provision.log" || true
    echo "FAIL" | aws s3 cp - "\${LOGS_S3}/FAIL" || true
    shutdown -h now || true
}
trap on_error ERR

WORK=/opt/pslm
mkdir -p "\${WORK}" && cd "\${WORK}"

# Fetch payload
aws s3 cp "\${PAYLOAD_S3}/" ./ --recursive
sha256sum -c manifest.sha256

# Unpack code
mkdir -p repo
tar -xzf code.tar.gz -C repo/
cd repo
mkdir -p data/tokenized artifacts/tokenizer artifacts/checkpoints logs
mv ../tokens.latest.pt data/tokenized/tokens.latest.pt
mv ../normalizers.latest.pt artifacts/tokenizer/normalizers.latest.pt
mv ../bucket_stats.latest.json artifacts/tokenizer/bucket_stats.latest.json

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="/root/.local/bin:\$PATH"

# Sync deps
uv sync

# Verify GPU visible
uv run python -c "import torch; assert torch.cuda.is_available(), 'no CUDA'; print('cuda ok:', torch.cuda.get_device_name(0))"

# Train
export PSLM_AUTHORIZED_GPU_RUN=1
uv run python scripts/train.py \\
    --tokens-pt data/tokenized/tokens.latest.pt \\
    --model-size xs \\
    --n-steps 50 \\
    --eval-every 25 \\
    --device cuda \\
    --seed 0 \\
    --logs-dir logs/

# Upload artifacts back
aws s3 cp logs/ "\${LOGS_S3}/logs/" --recursive
aws s3 cp artifacts/checkpoints/ "\${LOGS_S3}/checkpoints/" --recursive || true
aws s3 cp /var/log/pslm-provision.log "\${LOGS_S3}/provision.log"
echo "DONE" | aws s3 cp - "\${LOGS_S3}/DONE"

echo "training complete at \$(date -u +%FT%TZ); shutting down"
shutdown -h now
EOF
)
USER_DATA_B64=$(printf '%s' "$USER_DATA" | base64)

# TagSpecifications: Budgets filter on Project tag; RunSprint helps teardown.
TAG_JSON=$(cat <<EOF
[
  {
    "ResourceType": "instance",
    "Tags": [
      {"Key": "Project", "Value": "${PROJECT_TAG}"},
      {"Key": "RunSprint", "Value": "${SPRINT_ID}"},
      {"Key": "Mode", "Value": "${MODE}"}
    ]
  }
]
EOF
)

# Resolve security group name -> ID. On --dry-run, if the SG does not exist yet,
# emit a placeholder so the JSON is still valid + inspectable.
if [[ "$DRY_RUN" -eq 1 ]]; then
    SG_ID=$(aws ec2 describe-security-groups --region "$REGION" \
        --group-names "$SECURITY_GROUP_NAME" \
        --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo "sg-DRYRUN-PLACEHOLDER")
else
    SG_ID=$(aws ec2 describe-security-groups --region "$REGION" \
        --group-names "$SECURITY_GROUP_NAME" \
        --query 'SecurityGroups[0].GroupId' --output text)
    if [[ -z "$SG_ID" || "$SG_ID" == "None" ]]; then
        echo "provision_gpu: security group '${SECURITY_GROUP_NAME}' not found in ${REGION}" >&2
        exit 3
    fi
fi

# MetadataOptions: force IMDSv2 (session-tokened). IMDSv1 SSRF surface closed.
METADATA_OPTIONS='"MetadataOptions": {"HttpTokens": "required", "HttpEndpoint": "enabled"}'
# IamInstanceProfile: pre-created role gives the box S3 + CloudWatch Logs access.
IAM_PROFILE_JSON="\"IamInstanceProfile\": {\"Name\": \"${INSTANCE_PROFILE}\"}"
SG_JSON="\"SecurityGroupIds\": [\"${SG_ID}\"]"

if [[ "$MARKET" == "spot" ]]; then
    REQUEST_JSON=$(cat <<EOF
{
  "ImageId": "${AMI_ID}",
  "InstanceType": "${INSTANCE_TYPE}",
  "MaxCount": 1,
  "MinCount": 1,
  "InstanceMarketOptions": {
    "MarketType": "spot",
    "SpotOptions": {"MaxPrice": "${MAX_SPOT_PRICE}", "SpotInstanceType": "one-time"}
  },
  "UserData": "${USER_DATA_B64}",
  ${METADATA_OPTIONS},
  ${IAM_PROFILE_JSON},
  ${SG_JSON},
  "TagSpecifications": ${TAG_JSON},
  "InstanceInitiatedShutdownBehavior": "terminate"
}
EOF
)
else
    REQUEST_JSON=$(cat <<EOF
{
  "ImageId": "${AMI_ID}",
  "InstanceType": "${INSTANCE_TYPE}",
  "MaxCount": 1,
  "MinCount": 1,
  "UserData": "${USER_DATA_B64}",
  ${METADATA_OPTIONS},
  ${IAM_PROFILE_JSON},
  ${SG_JSON},
  "TagSpecifications": ${TAG_JSON},
  "InstanceInitiatedShutdownBehavior": "terminate"
}
EOF
)
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "provision_gpu: DRY RUN. Region=${REGION}. Request:" >&2
    echo "$REQUEST_JSON" >&2
    exit 0
fi

echo "provision_gpu: launching ${INSTANCE_TYPE} (${MARKET}) in ${REGION}..." >&2
RESPONSE=$(aws ec2 run-instances --region "$REGION" --cli-input-json "$REQUEST_JSON")
INSTANCE_ID=$(printf '%s' "$RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["Instances"][0]["InstanceId"])')
echo "provision_gpu: launched instance ${INSTANCE_ID}" >&2
echo "$INSTANCE_ID"
