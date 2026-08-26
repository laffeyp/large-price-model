# AWS infrastructure runbook

**Account:** `648879824221` (awsPro)
**Region:** `us-east-1` (all resources; enforced via IAM `aws:RequestedRegion` deny)
**Owner:** laffeypeter@gmail.com
**First provisioned:** Sprint 107 (2026-08-24)
**Role in v1:** **not the primary training environment.** Kept warm as a scale-up option.

## Purpose

v1 training runs on the operator's M5 Max (18 CPU cores, 40 GPU cores, 128 GB unified memory) via PyTorch's MPS backend. The full training arc — model-size sweep, context-length sweep, baseline ladder, ablations, held-out sim, kappa sensitivity, v1 report — fits in an afternoon of local wall-clock. Sprint 109's MPS smoke reported bit-identical `final_train_loss` on CPU vs MPS across xs/sm/md/lg (`3.5182`, `3.6494`, `3.5005`, `3.5688`). Determinism holds cross-device. Cloud rental adds no throughput the workload asks for.

This runbook still exists because a real scale-up may need it. Concrete triggers:

- A v2 model at ~300M+ params where MPS memory bandwidth becomes the constraint.
- A comparative sweep across many seeds where wall-clock parallelism matters more than the M5 Max's single-node throughput.
- A held-out reproduction the reader wants to run on a specific documented CUDA machine (A100/H100) for scientific comparability.

None of those apply to v1. The AWS resources sit idle at effectively zero cost: S3 storage is pennies per month, Budgets and IAM and SNS are free, quota tickets stay open indefinitely at no charge. First live spend against the account so far: under $0.05 (three t3.medium dry-run boxes during Sprint 109 pre-flight diagnostics, all terminated).

This runbook is the single source of truth for what AWS resources exist, why, and how to reproduce or rotate them. Every command below is meant to be copy-pasteable from a clean shell. Nothing here should reference secrets on disk; secrets live only in `~/.aws/credentials`.

---

## 1. Inventory

| Resource | Name | Purpose |
|---|---|---|
| IAM user | `price-space-llm-v1` | Scoped programmatic-access user for every day-to-day operation. Replaces root credentials in the CLI. |
| IAM customer-managed policy | `PriceSpaceLLMV1` | Grants EC2 + S3 (two buckets) + CloudWatch + Budgets + SNS + narrow-scope `iam:PassRole` for the training instance profile + self-identity. Denies IAM escalation, out-of-region API calls, and `s3:DeleteBucket` on the two named buckets. Source: `scripts/aws/iam-policy.json` (~4KB, over the 2048-byte inline limit, so shipped as a managed policy: `arn:aws:iam::648879824221:policy/PriceSpaceLLMV1`). |
| IAM role | `pslm-v1-ec2-training` | Assumed by EC2 via `sts:AssumeRole`; carries an inline role policy `EC2TrainingRole` (source: `scripts/aws/instance-role-policy.json`) that grants the running box `s3:Get/PutObject/ListBucket` on the two buckets and `logs:Create/Put/DescribeStreams` on the CloudWatch log group. |
| IAM instance profile | `pslm-v1-ec2-training` | Wraps the role for EC2 attachment. Passed to `RunInstances` via `IamInstanceProfile.Name`. |
| Security group | `pslm-v1-training-sg` | In the default VPC. Zero ingress rules; one egress rule 443/TCP to `0.0.0.0/0` (S3, Alpha-Vantage, package repos over HTTPS). |
| S3 bucket | `price-space-llm-v1-payload` | Holds one prefix per run_id containing tokens.latest.pt, normalizers.latest.pt, bucket_stats.latest.json, code.tar.gz, manifest.sha256. Versioning ON, public access blocked, AES-256 encryption. |
| S3 bucket | `price-space-llm-v1-logs` | Holds `signals.jsonl` traces + PNG artifacts fetched back from EC2 post-run. Same hardening. |
| SNS topic | `price-space-llm-v1-alerts` | Fan-out target for Budgets. One email subscription: `laffeypeter@gmail.com`. |
| Budget | `pslm-v1-500` | Advisory alert at $500 monthly, tag-filtered to `Project=price-space-llm-v1`. Notifies on 100% actual + 90% forecast. |
| Budget | `pslm-v1-1500` | Same shape; $1,500 monthly tier. |
| Budget | `pslm-v1-3000` | Same shape; $3,000 monthly tier. "Investigate before continuing." |
| AWS CLI profile | `pslm-v1` | Uses the scoped user's access key. Every subsequent CLI command should carry `--profile pslm-v1` or set `AWS_PROFILE=pslm-v1`. |

No auto-halt actions on any budget. AWS Budgets only email; the training runs continue past every threshold. Named on the Sprint 107 card as a deliberate design choice.

Every EC2 instance launched via `scripts/aws/provision_gpu.sh` carries three tags: `Project=price-space-llm-v1`, `RunSprint=<id>`, `Mode={dev,prod}`. The Budgets filter reads `Project` and rolls up every tagged instance's cost.

---

## 2. First-time provisioning (Sprint 107)

Assumes the operator is authenticated as root (`aws sts get-caller-identity` returns `arn:aws:iam::648879824221:root`). Every step below runs under root **only** for the IAM-user creation; the rest runs under the new scoped user via `--profile pslm-v1`.

### 2.1 Create the scoped IAM user and policy (under root)

```bash
cd "<repo-root>"

# 1. Create user
aws iam create-user --user-name price-space-llm-v1

# 2. Create the customer-managed policy and attach it.
# (The policy is 3735 bytes, over the 2048-byte inline limit; managed is
#  the AWS-recommended path anyway.)
POLICY_ARN=$(aws iam create-policy \
    --policy-name PriceSpaceLLMV1 \
    --policy-document file://scripts/aws/iam-policy.json \
    --description "Sprint 107 scoped policy for price-space-llm-v1 user" \
    --query 'Policy.Arn' --output text)
aws iam attach-user-policy --user-name price-space-llm-v1 --policy-arn "$POLICY_ARN"

# If the policy already exists (re-provisioning), skip create and just
# publish a new version:
# aws iam create-policy-version --policy-arn "$POLICY_ARN" \
#     --policy-document file://scripts/aws/iam-policy.json --set-as-default

# 3. Mint an access key. The secret is returned exactly once; capture and stash.
aws iam create-access-key --user-name price-space-llm-v1 \
    > /tmp/pslm-v1-key.json

# 4. Install the key into ~/.aws/credentials under profile [pslm-v1]
python3 - <<'PY'
import configparser, json, os
from pathlib import Path
data = json.loads(Path("/tmp/pslm-v1-key.json").read_text())["AccessKey"]
cred_path = Path.home() / ".aws" / "credentials"
cfg = configparser.ConfigParser()
cfg.read(cred_path)
if "pslm-v1" not in cfg:
    cfg["pslm-v1"] = {}
cfg["pslm-v1"]["aws_access_key_id"] = data["AccessKeyId"]
cfg["pslm-v1"]["aws_secret_access_key"] = data["SecretAccessKey"]
with cred_path.open("w") as fh:
    cfg.write(fh)
print("wrote profile pslm-v1 to", cred_path)
PY

# 5. Confirm the swap
aws sts get-caller-identity --profile pslm-v1
# Expect: arn:aws:iam::648879824221:user/price-space-llm-v1

# 6. Shred the key file
rm /tmp/pslm-v1-key.json
```

**From this point every command runs with `--profile pslm-v1`** (or with `export AWS_PROFILE=pslm-v1` at the top of the shell session).

### 2.2 Create the SNS topic and email subscription (as pslm-v1)

```bash
aws sns create-topic --profile pslm-v1 --region us-east-1 \
    --name price-space-llm-v1-alerts
# Capture the returned TopicArn.

TOPIC_ARN="<paste from above>"

aws sns subscribe --profile pslm-v1 --region us-east-1 \
    --topic-arn "$TOPIC_ARN" \
    --protocol email \
    --notification-endpoint laffeypeter@gmail.com
```

An email lands at `laffeypeter@gmail.com` within seconds. Click the confirmation link before continuing; unconfirmed subscriptions do not deliver.

### 2.3 Create the two S3 buckets (as pslm-v1)

```bash
for BUCKET in price-space-llm-v1-payload price-space-llm-v1-logs; do
    aws s3api create-bucket --profile pslm-v1 --region us-east-1 \
        --bucket "$BUCKET"
    aws s3api put-bucket-versioning --profile pslm-v1 --region us-east-1 \
        --bucket "$BUCKET" --versioning-configuration Status=Enabled
    aws s3api put-public-access-block --profile pslm-v1 --region us-east-1 \
        --bucket "$BUCKET" --public-access-block-configuration \
        BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
    aws s3api put-bucket-encryption --profile pslm-v1 --region us-east-1 \
        --bucket "$BUCKET" --server-side-encryption-configuration \
        '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
done
```

### 2.4 Create the three Budgets (as pslm-v1)

Budgets creation needs the account ID as an argument, not from the caller identity.

```bash
ACCOUNT_ID=648879824221

for AMOUNT in 500 1500 3000; do
    NAME="pslm-v1-${AMOUNT}"
    cat > /tmp/budget-${AMOUNT}.json <<EOF
{
    "BudgetName": "${NAME}",
    "BudgetLimit": {"Amount": "${AMOUNT}", "Unit": "USD"},
    "TimeUnit": "MONTHLY",
    "BudgetType": "COST",
    "CostFilters": {"TagKeyValue": ["user:Project\$price-space-llm-v1"]}
}
EOF
    cat > /tmp/notifs-${AMOUNT}.json <<EOF
[
  {
    "Notification": {
      "NotificationType": "ACTUAL",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 100.0,
      "ThresholdType": "PERCENTAGE",
      "NotificationState": "ALARM"
    },
    "Subscribers": [{
      "SubscriptionType": "SNS",
      "Address": "${TOPIC_ARN}"
    }]
  },
  {
    "Notification": {
      "NotificationType": "FORECASTED",
      "ComparisonOperator": "GREATER_THAN",
      "Threshold": 90.0,
      "ThresholdType": "PERCENTAGE"
    },
    "Subscribers": [{
      "SubscriptionType": "SNS",
      "Address": "${TOPIC_ARN}"
    }]
  }
]
EOF
    aws budgets create-budget --profile pslm-v1 --region us-east-1 \
        --account-id "$ACCOUNT_ID" \
        --budget file:///tmp/budget-${AMOUNT}.json \
        --notifications-with-subscribers file:///tmp/notifs-${AMOUNT}.json
    rm /tmp/budget-${AMOUNT}.json /tmp/notifs-${AMOUNT}.json
done
```

### 2.4a Create the EC2 instance profile (as root, Sprint 108)

The scoped `pslm-v1` user cannot create roles (`DenyIAMEscalation`). This block runs under root once.

```bash
cat > /tmp/ec2-trust-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "ec2.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
EOF

aws iam create-role \
    --role-name pslm-v1-ec2-training \
    --assume-role-policy-document file:///tmp/ec2-trust-policy.json \
    --description "EC2 instance role for price-space-llm-v1 training runs"

aws iam put-role-policy \
    --role-name pslm-v1-ec2-training \
    --policy-name EC2TrainingRole \
    --policy-document file://scripts/aws/instance-role-policy.json

aws iam create-instance-profile \
    --instance-profile-name pslm-v1-ec2-training

aws iam add-role-to-instance-profile \
    --instance-profile-name pslm-v1-ec2-training \
    --role-name pslm-v1-ec2-training

rm /tmp/ec2-trust-policy.json
```

### 2.4b Create the dedicated security group (as pslm-v1, Sprint 108)

```bash
VPC_ID=$(aws ec2 describe-vpcs --profile pslm-v1 --region us-east-1 \
    --filters Name=is-default,Values=true \
    --query 'Vpcs[0].VpcId' --output text)

SG_ID=$(aws ec2 create-security-group --profile pslm-v1 --region us-east-1 \
    --group-name pslm-v1-training-sg \
    --description "egress-443-only for pslm-v1 training instances" \
    --vpc-id "$VPC_ID" \
    --query 'GroupId' --output text)

# Revoke the default allow-all egress AWS attaches
aws ec2 revoke-security-group-egress --profile pslm-v1 --region us-east-1 \
    --group-id "$SG_ID" \
    --ip-permissions '[{"IpProtocol":"-1","IpRanges":[{"CidrIp":"0.0.0.0/0"}]}]'

# Add 443/TCP egress only
aws ec2 authorize-security-group-egress --profile pslm-v1 --region us-east-1 \
    --group-id "$SG_ID" \
    --ip-permissions '[{"IpProtocol":"tcp","FromPort":443,"ToPort":443,"IpRanges":[{"CidrIp":"0.0.0.0/0","Description":"HTTPS egress for S3+APIs+repos"}]}]'
```

`provision_gpu.sh` resolves the SG by name at launch, so callers do not need to know the SG ID.

### 2.5 Verify everything

```bash
aws sts get-caller-identity --profile pslm-v1
# arn:aws:iam::648879824221:user/price-space-llm-v1

aws s3 ls --profile pslm-v1 | grep price-space-llm-v1
# 2026-08-24 ... price-space-llm-v1-logs
# 2026-08-24 ... price-space-llm-v1-payload

aws budgets describe-budgets --profile pslm-v1 --region us-east-1 \
    --account-id 648879824221 \
    --query 'Budgets[].BudgetName'
# ["pslm-v1-500", "pslm-v1-1500", "pslm-v1-3000"]

aws sns list-subscriptions --profile pslm-v1 --region us-east-1 \
    --query 'Subscriptions[?TopicArn==`'$TOPIC_ARN'`].[Endpoint,SubscriptionArn]'
# [["laffeypeter@gmail.com", "arn:aws:sns:...:<uuid>"]]   -- confirmed subscription
```

### 2.6 Rotate the root access key (operator step; not automated)

Root access keys should not exist. After the scoped user works, delete the root access key:

1. Log into the AWS Console as root (browser).
2. IAM → Security credentials → Access keys → Delete the active root key.
3. Verify locally: `aws sts get-caller-identity` (with no `--profile`) should now fail because the root key is gone.
4. Move the CLI default: `export AWS_PROFILE=pslm-v1` in `~/.zshrc` (or `~/.bashrc`).

This step is manual because it invalidates the credentials the Agent is currently authenticated with; the Agent cannot rotate its own keys mid-session.

---

## 3. Cloud training flow (used only if a scale-up trigger fires)

**Not the day-to-day flow.** Local M5 Max via `--device mps` runs every v1 sprint. This section documents the cloud path so that a future scale-up sprint has a working recipe; it should not be invoked casually.

When it applies:

Every training-run cycle is three shell commands:

```bash
export AWS_PROFILE=pslm-v1

# 1. Package + upload payload
scripts/aws/sync_to_gpu.sh --run-id <run-id>

# 2. Launch instance (dev: g5.xlarge spot, 2hr walltime; prod: p4d.24xlarge on-demand)
INSTANCE_ID=$(scripts/aws/provision_gpu.sh --dev)
# ...or --prod for the real sweep.

# 3. When done, teardown
scripts/aws/teardown_gpu.sh --instance-id "$INSTANCE_ID"
# ...or --sprint <id> to kill every instance tagged with that sprint id.
```

`provision_gpu.sh --dry-run` prints the exact `RunInstances` request JSON without firing the API. Use it to sanity-check the instance spec before every real launch.

The training entrypoint refuses to run on EC2 unless `PSLM_AUTHORIZED_GPU_RUN=1` is set. This is intentional; a bare `python scripts/train.py` on a still-alive rented box exits 1 with a fix-path message. The instance's user-data script exports the var before invoking training.

---

## 3a. Cost-coverage caveat (added Sprint 108)

The three Budgets tag-filter on `Project=price-space-llm-v1`. That filter captures **EC2 compute costs only**, because tag inheritance is inconsistent across resource types:

- **EC2 instances:** tagged by `provision_gpu.sh`. Covered.
- **EBS volumes:** may or may not inherit the instance's tags depending on whether the launch used a launch template or a bare `RunInstances` call. Currently uncovered.
- **S3 storage:** buckets carry tags on the bucket itself; storage bytes are not tagged. Uncovered.
- **CloudWatch Logs:** log groups may be tagged; log stream bytes are not. Uncovered.
- **Data transfer, NAT gateway, VPC endpoints:** never tagged. Uncovered.

Expect a small monthly "unattributed" line in the AWS bill outside the three Budget tiers. For v1 volumes (~gigabytes of S3, small log volume) this is dollars per month at worst.

## 4. Failure modes and recovery

**Spot reclamation.** `--dev` runs on spot capacity. Spot can be reclaimed with 2 minutes' notice. Training in progress dies. Restart with `provision_gpu.sh --dev` again; the tokenized payload is still in S3 so `sync_to_gpu.sh` need not re-run.

**p4d quota not approved.** New accounts start with `p4d.24xlarge` quota at 0. First `--prod` launch returns `VcpuLimitExceeded` or `InsufficientInstanceCapacity`. Two paths:

- Request the quota bump: `aws service-quotas request-service-quota-increase --profile pslm-v1 --service-code ec2 --quota-code L-FE5A380F --desired-value 96` (96 vCPU covers one p4d.24xlarge). Approval takes hours to days.
- Fall back to `g5.2xlarge` on-demand: `provision_gpu.sh --prod --fallback g5.2xlarge`. Slower but no quota gate.

**Budget alarm fires.** Email lands at `laffeypeter@gmail.com`. Nothing halts. Decide whether to `teardown_gpu.sh --sprint <id>` or let the run finish. The $3,000 alarm is "investigate," not "stop."

**Orphaned resources.** `teardown_gpu.sh --sprint <id>` is idempotent and covers: terminated instances, cancelled spot requests. **EBS volumes:** the script assumes the root EBS volume has `DeleteOnTermination=true`, which the AWS Deep Learning AMI sets by default; root volumes clean up automatically on terminate. Any secondary EBS attached by a future sprint would orphan; if `provision_gpu.sh` ever adds `BlockDeviceMappings`, extend `teardown_gpu.sh` with an explicit `aws ec2 delete-volume` pass on the sprint tag.

**Lost secret key.** `~/.aws/credentials` corruption: re-run step 2.1's `create-access-key` (this creates a *new* key alongside the old; each user can hold two active keys). Deactivate the old key via `aws iam update-access-key --user-name price-space-llm-v1 --access-key-id <old-id> --status Inactive`.

---

## 5. Teardown (end of v1)

At the end of the project, unwind everything:

```bash
export AWS_PROFILE=pslm-v1

# 1. Kill any live instances
scripts/aws/teardown_gpu.sh --sprint ALL   # not actually implemented; instead do:
# aws ec2 describe-instances ... --filters Name=tag:Project,Values=price-space-llm-v1

# 2. Empty then delete S3 buckets
aws s3 rm s3://price-space-llm-v1-payload --recursive
aws s3 rm s3://price-space-llm-v1-logs --recursive
aws s3api delete-bucket --bucket price-space-llm-v1-payload
aws s3api delete-bucket --bucket price-space-llm-v1-logs

# 3. Delete Budgets
for NAME in pslm-v1-500 pslm-v1-1500 pslm-v1-3000; do
    aws budgets delete-budget --account-id 648879824221 --budget-name "$NAME"
done

# 4. Delete SNS topic
aws sns delete-topic --topic-arn "$TOPIC_ARN"

# 5. Delete IAM user (last, so it can perform the teardown)
# Switch back to root creds for this step.
aws iam delete-user-policy --user-name price-space-llm-v1 --policy-name PriceSpaceLLMV1
aws iam list-access-keys --user-name price-space-llm-v1 --query 'AccessKeyMetadata[].AccessKeyId' --output text | \
    xargs -n1 aws iam delete-access-key --user-name price-space-llm-v1 --access-key-id
aws iam delete-user --user-name price-space-llm-v1
```

---

## 6. Change log

- **2026-08-24, Sprint 107** — initial provisioning. Root creds swapped for scoped `price-space-llm-v1` IAM user. Two S3 buckets, three Budgets, one SNS topic. `scripts/aws/{provision,sync,teardown}_gpu.sh` land in the repo alongside the training-script EC2 guard.
- **2026-08-24, Sprint 107 execution log** — two policy gaps caught during live provisioning: (1) `sns:CreateTopic` was missing from the first pass; the scoped user failed `AuthorizationError` on the first `aws sns create-topic`. Added SNS create/subscribe/delete/publish permissions in the `BudgetsAndSNS` statement. (2) `budgets:CreateBudget` internally checks `budgets:ModifyBudget` under the hood; that permission was also missing. Added. After both fixes the policy grew to 3735 bytes, past the 2048-byte inline-policy limit, so we switched from an inline policy to a customer-managed policy (`arn:aws:iam::648879824221:policy/PriceSpaceLLMV1`) with `create-policy-version --set-as-default` for subsequent updates. Every resource was created under the scoped `--profile pslm-v1` credential, not root. Root access key deletion is a manual operator step; the Agent cannot rotate the credential it's currently authenticated with.
- **2026-08-24, Sprint 109 closes on MPS parity** — hardware verified as MacBook Pro Mac17,7, Apple M5 Max (18 CPU cores: 6 efficiency + 12 performance; 40 GPU cores), 128 GB unified memory, Metal 4, macOS 26.5.1. Bench across xs/sm/md/lg on `--device cpu` vs `--device mps`: bit-identical `final_train_loss` at every size (`3.5182 / 3.6494 / 3.5005 / 3.5688`); MPS starts winning at md (1.38×) and lg (1.57×). Cross-device determinism preserved. Conclusion: cloud rental adds no throughput v1 needs. The AWS resources stay warm as a scale-up option for v2 or a comparative sweep; day-to-day training moves to the M5 Max. The two GPU quota tickets (`L-3819A6DF` spot; `L-DB2E81BA` on-demand) stay open for future use. Runbook framing pivoted: this file is a scale-up recipe, not a day-to-day workflow. Total live AWS spend across Sprints 107-109: under $0.05.

- **2026-08-24, Sprint 109 pre-flight dry-run** — first live spend against the account: three t3.medium on-demand instances used to smoke the boot-script pipeline. Cost: pennies. Total wall-clock for all three attempts: ~15 minutes. Three bugs caught before any GPU spend:
  1. **Spot service-linked role missing.** New accounts do not have `AWSServiceRoleForEC2Spot`; `RunInstances` fails with `AuthFailure.ServiceLinkedRoleCreationNotPermitted`. Fixed by `aws iam create-service-linked-role --aws-service-name spot.amazonaws.com` under root. One-time; never needs to run again on this account.
  2. **Spot + on-demand GPU quotas at zero.** New accounts start with 0 vCPU quota for both "All G and VT Spot Instance Requests" (`L-3819A6DF`) and "Running On-Demand G and VT instances" (`L-DB2E81BA`). Both quota-bump requests submitted (async approval, typically hours to a couple of days). Ticket IDs stashed in the Sprint 109 sprint card.
  3. **Payload manifest carried repo-relative paths.** `sync_to_gpu.sh` wrote hashes against `data/tokenized/tokens.latest.pt` but uploaded files under basename `tokens.latest.pt`. `sha256sum -c` on the flat download directory failed every payload entry, trap fired, `FAIL` marker written, box shut down. Fix: compute the hash inside the file's dir with `basename` so the manifest is flat. Regression test `test_sync_manifest_uses_basenames_only`.
  4. **Code tarball omitted `sdd-kit-2/lib/sdd.py` + `signals/*.json`.** `pyproject.toml` force-includes `sdd-kit-2/lib/sdd.py` into the wheel; `uv sync` on the box failed with `FileNotFoundError: Forced include not found`. Fix: extend the tarball file list to include `sdd-kit-2/lib` and `signals/`. Regression test `test_sync_code_tarball_includes_sdd_kit_and_signals`.
  5. **On-demand `shutdown -h` stops, does not terminate.** The three t3.medium boxes shut down cleanly via the boot script's explicit `shutdown -h now`, but EC2's default `InstanceInitiatedShutdownBehavior` for on-demand is `stop` — the boxes lingered in the stopped state with EBS attached (cost: pennies but non-zero indefinitely). Fix: add `InstanceInitiatedShutdownBehavior=terminate` to every `RunInstances` request. Regression test `test_provision_json_includes_instance_initiated_shutdown_terminate`. Terminated the three lingering instances manually.

  After all four repo-side fixes the CPU boot pipeline runs cleanly through payload download → manifest verify → code unpack → uv install → uv sync → package build (`price-space-llm==0.15.0`) → torch install → the intentional `AssertionError: no CUDA` (that's the guard I wrote for exactly this case). Trap fires, FAIL marker + provision log upload, box terminates. Total wall-clock from launch to FAIL: ~2 minutes 30 seconds. Every step of the pipeline that runs on a GPU box is now verified except the training step itself, which needs the actual GPU quota approval.

- **2026-08-24, Sprint 108** — review-driven tightening pass. Landed all five §12 blockers from `reviews/aws-and-phase-g-review.md`: created IAM role `pslm-v1-ec2-training` + instance profile (source `scripts/aws/instance-role-policy.json`); published policy v3 with a `Deny s3:DeleteBucket` statement on the two named buckets, a scoped `iam:PassRole` Allow on the training role ARN (conditioned on `iam:PassedToService = ec2.amazonaws.com`), and a `CloudWatchAndLogs` split into `cloudwatch:*` on `Resource: *` and `logs:*` on the specific log-group ARN; wired `MetadataOptions`, `IamInstanceProfile`, and `SecurityGroupIds` into `provision_gpu.sh`; renamed `SPRINT_107_AUTHORIZED_RUN` → `PSLM_AUTHORIZED_GPU_RUN`. Non-blocking should-fixes also landed: dedicated security group `pslm-v1-training-sg` (zero ingress, egress 443/TCP only), `sha256sum` → `shasum -a 256` cross-platform shim in `sync_to_gpu.sh`, explicit `-h` on the walltime `shutdown` command. Tests +6 (four IAM-policy-shape assertions pinning the review fixes; one provision-JSON assertion for IMDSv2 + role + SG; one shell-level shim test; one defensive rename test proving the old env-var name no longer bypasses the guard). Note: AWS caps managed policies at 5 stored versions; we're at v3 now, so v6 will need to delete an old version first.
