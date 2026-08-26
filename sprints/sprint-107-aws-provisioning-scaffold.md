# Sprint 107 -- AWS GPU pre-provisioning scaffolding (roadmap 083 prep)

---

```yaml
---
id: 107
status: closed
phase: H.prep
pass_kind: architecture
determinism_budget: bit-deterministic
---
```

## scope

Everything that must exist before an EC2 GPU instance boots for the first time in Sprint 108. AWS Budgets alarms (advisory-only, no halt actions); an IAM user + policy scoped to EC2 + S3 + CloudWatch only; S3 buckets for the sync payload and the trace logs; three shell scripts (`provision_gpu.sh`, `sync_to_gpu.sh`, `teardown_gpu.sh`); an authorized-run env-var guard on the training entrypoint. All against account `648879824221` (awsPro), region us-east-1.

Ratified before opening: three advisory-only alarm thresholds at `$500`, `$1,500`, `$3,000` emailing `laffeypeter@gmail.com`. No `RunInstances` stop action, no auto-terminate on breach — alerts inform, they do not halt. Estimated v1 total ~$1,700 with a ~$2,500 headroom multiplier; the $3,000 alarm sits above the realistic total and is the "investigate before continuing" trigger.

## deliverables

### AWS resources created

- **IAM user `price-space-llm-v1`** with programmatic-access key pair. `~/.aws/credentials` switches to these keys after creation; root key rotation follows in a subsequent operator step (documented on the card, not automated — key rotation touches the CLI's current session).
- **IAM policy `PriceSpaceLLMV1`** attached to the user. Grants: `ec2:RunInstances`, `ec2:TerminateInstances`, `ec2:DescribeInstances`, `ec2:CreateTags`, `ec2:DescribeImages`, `ec2:DescribeSpotPriceHistory`, `ec2:RequestSpotInstances`, `ec2:CancelSpotInstanceRequests`, `s3:*` scoped to two buckets, `cloudwatch:GetMetricStatistics`, `logs:*` scoped to `/aws/ec2/price-space-llm-v1/*`, `budgets:ViewBudget`. Region condition: `aws:RequestedRegion == us-east-1`. Explicit deny on `iam:*` beyond `iam:GetUser` (this user cannot self-escalate).
- **S3 bucket `price-space-llm-v1-payload`** in us-east-1. Holds the sync payload (tokenized artifact, normalizers, bucket_stats, code tarball). Bucket versioning ON, public access blocked, default encryption AES-256.
- **S3 bucket `price-space-llm-v1-logs`** in us-east-1. Holds `signals.jsonl` traces + PNG artifacts fetched back post-run. Same hardening.
- **Three Budgets** at `$500`, `$1,500`, `$3,000` monthly, tag-filtered to `Project=price-space-llm-v1` on the EC2 side, emailing `laffeypeter@gmail.com` on 100% actual + 90% forecast. Advisory only.
- **SNS topic `price-space-llm-v1-alerts`** with the email subscribed and confirmed.

### Repo files

- `scripts/aws/provision_gpu.sh` -- launches a GPU instance. Two modes:
  - `--dev` -- `g5.xlarge` spot request at ~$0.35/hr (A10G 24GB). 2-hour max walltime enforced via user-data-installed `shutdown +120`. Bootstraps: mount EBS, pull code + payload from S3, activate the venv, print instance metadata + spot price to stderr.
  - `--prod` -- `p4d.24xlarge` on-demand (8× A100 40GB) if the p4d quota is approved; falls back to `g5.2xlarge` on-demand (A10G) if not. No walltime cap. Same bootstrap.
  - Tags every instance with `Project=price-space-llm-v1`, `RunSprint=<current-sprint-id>`, `Mode={dev,prod}` so Budgets can filter.
  - `--dry-run` flag prints the fully-resolved `RunInstances` request as JSON and exits before the API call.
- `scripts/aws/sync_to_gpu.sh` -- packages the payload and pushes to `s3://price-space-llm-v1-payload/{run_id}/`. Payload: `data/tokenized/tokens.latest.pt`, `artifacts/tokenizer/{normalizers,bucket_stats}.latest.{pt,json}`, code tarball `src/ + scripts/ + pyproject.toml + uv.lock`. SHA-256 manifest written alongside so the remote box can byte-verify.
- `scripts/aws/teardown_gpu.sh` -- given an instance-id or a `--sprint <id>` tag filter, calls `TerminateInstances`, waits for the terminated state, deletes any orphaned EBS volumes, cancels any pending spot request tied to the same tag. Idempotent.
- `scripts/train.py` -- add a guard at the top: `if os.environ.get("AWS_EC2_INSTANCE_ID") and not os.environ.get("SPRINT_107_AUTHORIZED_RUN"): sys.exit(1)`. Detects EC2 via IMDSv2 (`http://169.254.169.254/latest/meta-data/instance-id` with token). Refuses a bare `python scripts/train.py` on a still-alive instance — the operator must explicitly export the env var before invoking. Prevents accidental wall-time burn.

### Tests

- `tests/test_aws_provision_dry_run.py` -- new. Runs `provision_gpu.sh --dry-run --dev` (mocks AWS CLI via a stub on `PATH`) and asserts the emitted JSON carries the right `InstanceType`, `SpotPrice`, `TagSpecifications`.
- `tests/test_aws_sync_manifest.py` -- new. `sync_to_gpu.sh --dry-run` produces a SHA-256 manifest that lists every payload file; the manifest is deterministic byte-for-byte given the same tree.
- `tests/test_train_ec2_guard.py` -- new. Faking `AWS_EC2_INSTANCE_ID=i-abc` without `SPRINT_107_AUTHORIZED_RUN=1` → `sys.exit(1)`. With both set → normal path.

## artifact contract

Files created:

- `scripts/aws/provision_gpu.sh`, `scripts/aws/sync_to_gpu.sh`, `scripts/aws/teardown_gpu.sh` -- new.
- `scripts/aws/iam-policy.json` -- new, the exact policy attached.
- `scripts/aws/budgets.json` -- new, the three budget definitions.
- `scripts/train.py` -- edit: add the IMDSv2 EC2 guard at module top.
- `tests/test_aws_provision_dry_run.py`, `tests/test_aws_sync_manifest.py`, `tests/test_train_ec2_guard.py` -- new.

AWS-side artifacts (not in repo):

- IAM user `price-space-llm-v1` + policy `PriceSpaceLLMV1` + access key ID recorded in the sprint card (secret written to `~/.aws/credentials` only, never on disk in the repo, never in the sprint card).
- S3 buckets `price-space-llm-v1-payload` + `price-space-llm-v1-logs`.
- Three Budgets under names `pslm-v1-500`, `pslm-v1-1500`, `pslm-v1-3000`.
- SNS topic `price-space-llm-v1-alerts` + one confirmed email subscription.

Content assertions:

- `test -x scripts/aws/provision_gpu.sh`
- `grep -q "aws:RequestedRegion" scripts/aws/iam-policy.json`
- `grep -q "SPRINT_107_AUTHORIZED_RUN" scripts/train.py`

## signal contract

Zero new tags. AWS-side alarms fire via SNS email, outside the SDD signal path.

## observation contract

- `aws sts get-caller-identity` after the credentials swap reports `arn:aws:iam::648879824221:user/price-space-llm-v1`, not `.../root`.
- `aws budgets describe-budgets --account-id 648879824221` returns three budgets.
- `aws s3 ls s3://price-space-llm-v1-payload` succeeds.
- `scripts/aws/provision_gpu.sh --dry-run --dev` prints a valid `RunInstances` request JSON to stderr and exits 0.
- `SPRINT_107_AUTHORIZED_RUN` unset + faked EC2 metadata → `scripts/train.py` exits 1 with a fix-path message.

## commands

```
uv run ruff check .
uv run mypy
uv run pytest -q
```

## notes

- The root-account-in-CLI state is documented on the card. Sprint 107 replaces it with the scoped IAM user; the operator must delete the root access keys via the AWS console after confirming the new keys work. Named as an operator step, not an Agent step (the Agent's own working credentials would be invalidated mid-session).
- No auto-halt on budget alarm. Every alarm is advisory. The $3,000 alarm is "investigate before continuing," not "stop."
- Spot for dev, on-demand for prod. Named on the card. Spot can be reclaimed with 2 minutes' notice; a p4d.24xlarge production sweep run cannot afford that latency.
- p4d.24xlarge quota is off by default on new accounts. First `--prod` launch may 400 with `InsufficientInstanceCapacity` or fail the quota check. If so, request the quota bump via `aws service-quotas request-service-quota-increase` and fall back to `g5.2xlarge` on-demand until approved. Named on the card.
- The IMDSv2 guard on `scripts/train.py` prevents an accidental `python scripts/train.py` on a still-running instance from silently starting a new training run. The intended flow is: `provision_gpu.sh --dev` boots the box; `sync_to_gpu.sh` pushes the payload; user-data on the box pulls the payload; user-data on the box invokes `SPRINT_107_AUTHORIZED_RUN=1 python scripts/train.py ...`. Any other `python scripts/train.py` on a live EC2 box exits 1.
- Sprint 108 opens roadmap 083: rent, deploy, verify one xs=1M end-to-end run matches local CPU numbers within numerical noise.
