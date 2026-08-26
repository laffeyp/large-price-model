# Sprint 108 -- AWS pre-flight tightening (address every §12 finding)

---

```yaml
---
id: 108
status: closed
phase: H.prep
pass_kind: architecture
determinism_budget: bit-deterministic
---
```

## scope

Close every actionable finding from `reviews/aws-and-phase-g-review.md`. Five §12 blockers + four §12 should-fixes + two runbook notes. Sprint 109 becomes the actual GPU boot; Sprint 108 makes the scaffolding ready.

## deliverables (indexed to review section)

### §12 blockers (five)

**1. EC2 instance profile.** Create IAM role `pslm-v1-ec2-training` under root (the scoped user cannot create roles per its `DenyIAMEscalation` guard); attach a role policy scoped to `s3:Get/PutObject` on the two buckets + `logs:CreateLogStream/PutLogEvents` on the log group. Create instance profile with the same name, add the role. Grant `pslm-v1` a narrow `iam:PassRole` scoped to that specific role ARN (remove `iam:PassRole` from the broad `DenyIAMEscalation` list; add it back as a scoped Allow). Wire `IamInstanceProfile.Name = "pslm-v1-ec2-training"` into `provision_gpu.sh`'s RunInstances JSON.

**2. Drop the `"*"` wildcard from `CloudWatchAndLogs.Resource`.** Split into two statements: `cloudwatch:GetMetricStatistics` + `cloudwatch:PutMetricData` on `Resource: "*"` (metrics do not accept per-resource ARNs); `logs:Create/Put/Describe/Get*` on `arn:aws:logs:us-east-1:648879824221:log-group:/aws/ec2/price-space-llm-v1/*`. If any log action requires `*` at runtime (list operations sometimes do), widen individually and record why in the policy comment.

**3. Explicit `Deny s3:DeleteBucket` on the two named bucket ARNs.** One statement. Prevents a misfired teardown script from deleting production data. Deny beats Allow in AWS's evaluation.

**4. IMDSv2-only.** Add `MetadataOptions: {HttpTokens: "required", HttpEndpoint: "enabled"}` to `provision_gpu.sh`'s RunInstances JSON. Forces session-tokened metadata service; IMDSv1 SSRF surface closed.

**5. Rename `SPRINT_107_AUTHORIZED_RUN` → `PSLM_AUTHORIZED_GPU_RUN`.** Sprint-numbered env vars accrue and confuse future readers. `scripts/train.py`, `tests/test_train_ec2_guard.py`, and `docs/runbooks/aws-infrastructure.md` all touched.

### §12 should-fixes (four)

**6. Dedicated security group.** Create `pslm-v1-training-sg` under `pslm-v1`: no ingress rules; egress 443/TCP to `0.0.0.0/0` (needed for S3, Alpha-Vantage, package repos over HTTPS). Grant `pslm-v1` `ec2:CreateSecurityGroup / AuthorizeSecurityGroupEgress / RevokeSecurityGroupEgress / DeleteSecurityGroup` (already has `DescribeSecurityGroups`). Wire the SG ID into `provision_gpu.sh`.

**7. `sha256sum` shim.** One-line fallback at the top of `sync_to_gpu.sh` for macOS operators: `command -v sha256sum >/dev/null 2>&1 || sha256sum() { shasum -a 256 "$@"; }`.

**8. Runbook note: tag-filtered budgets cover EC2 compute only.** S3 storage, CloudWatch Logs, and EBS costs land in an untagged bucket the three tiers do not see. Document under §4 in the runbook.

**9. Runbook note: teardown assumes root EBS `DeleteOnTermination=true`.** The Deep Learning AMI sets this, so we ride the default. If a future sprint attaches secondary EBS, `teardown_gpu.sh` needs an explicit `delete-volume` pass. Document under §4 or §5.

### Non-blocker: §11.2 explicit `shutdown -h`

Change `shutdown +${WALLTIME_MINUTES} "..."` to `shutdown -h +${WALLTIME_MINUTES} "..."` in `provision_gpu.sh`. Explicit halt; some Ubuntu variants default to reboot without `-h`.

## tests (+6)

1. `test_train_ec2_guard.py` — every test renamed to reference `PSLM_AUTHORIZED_GPU_RUN`. Add one new test that the old env var `SPRINT_107_AUTHORIZED_RUN` no longer bypasses the guard (defensive: proves the rename actually happened, not aliased).
2. `test_aws_provision_dry_run.py` — one new test asserts the emitted RunInstances JSON carries `MetadataOptions.HttpTokens == "required"`, `IamInstanceProfile.Name == "pslm-v1-ec2-training"`, `SecurityGroupIds` non-empty.
3. `test_aws_iam_policy_shape.py` — new. Asserts (a) exactly one statement mentions `s3:DeleteBucket` and its `Effect` is `Deny`; (b) the `CloudWatchAndLogs` split exists (no statement has both `logs:*` and `Resource: "*"` alongside a specific log-group ARN); (c) `iam:PassRole` appears in an `Allow` scoped to `role/pslm-v1-ec2-training` and does NOT appear in the `Deny` block; (d) SecurityGroup Create/Authorize actions are present.
4. `test_aws_sync_manifest.py` — one new test verifies the `sha256sum` shim runs on a Bash session that lacks `sha256sum` (mock `PATH` without a linux sha256sum).

Test count 615 → 621.

## artifact contract

Files created or modified:

- `scripts/aws/iam-policy.json` — edit (five statement changes).
- `scripts/aws/instance-role-policy.json` — new. Scoped role policy attached to the EC2 role.
- `scripts/aws/provision_gpu.sh` — edit (add `IamInstanceProfile`, `MetadataOptions`, `SecurityGroupIds`, explicit `-h` on shutdown).
- `scripts/aws/sync_to_gpu.sh` — edit (add sha256sum shim).
- `scripts/train.py` — edit (rename env var).
- `tests/test_train_ec2_guard.py` — edit + one new test.
- `tests/test_aws_provision_dry_run.py` — one new test.
- `tests/test_aws_iam_policy_shape.py` — new.
- `tests/test_aws_sync_manifest.py` — one new test.
- `docs/runbooks/aws-infrastructure.md` — edit (instance profile section, security group section, tag-budget caveat, EBS delete note, env var rename).

AWS resources created live (under root for the role, under pslm-v1 for the SG):

- IAM role `pslm-v1-ec2-training` (root) + inline policy `EC2TrainingRole` (root).
- IAM instance profile `pslm-v1-ec2-training` with role attached (root).
- Managed policy `PriceSpaceLLMV1` new default version (pslm-v1, with the four statement changes).
- Security group `pslm-v1-training-sg` in the default VPC (pslm-v1), egress 443 only.

Content assertions:

- `grep -q "IamInstanceProfile" scripts/aws/provision_gpu.sh`
- `grep -q "HttpTokens" scripts/aws/provision_gpu.sh`
- `grep -q "PSLM_AUTHORIZED_GPU_RUN" scripts/train.py`
- `! grep -q "SPRINT_107_AUTHORIZED_RUN" scripts/train.py`

## signal contract

Zero new tags. Every change is either AWS-side or repo-side scaffolding; no SDD emit surface touched.

## observation contract

- `aws iam get-instance-profile --instance-profile-name pslm-v1-ec2-training --profile pslm-v1` succeeds.
- `aws ec2 describe-security-groups --group-names pslm-v1-training-sg --profile pslm-v1 --region us-east-1` returns egress-only (no ingress).
- `scripts/aws/provision_gpu.sh --dev --dry-run` emits JSON with `IamInstanceProfile`, `MetadataOptions`, `SecurityGroupIds` populated.
- `PSLM_AUTHORIZED_GPU_RUN=1 AWS_EC2_INSTANCE_ID=i-abc uv run python scripts/train.py --help` exits 0; the same command with `SPRINT_107_AUTHORIZED_RUN=1` (old name) exits 1 with the fix-path message.

## commands

```
uv run ruff check .
uv run mypy
uv run pytest -q
```

## notes

- The `DenyIAMEscalation` statement currently blocks `iam:PassRole`. The scoped fix is to remove `iam:PassRole` from that Deny list and add it back as an `Allow` scoped to `arn:aws:iam::648879824221:role/pslm-v1-ec2-training`. Deny-general + Allow-scoped is the common pattern for pass-role narrowing.
- The instance-role policy (`instance-role-policy.json`) is a *role* policy attached to the EC2 role, not to `pslm-v1`. The two are separate documents. Runbook records both.
- Sprint 109 opens next: rent the first `g5.xlarge` spot; sync the payload; one xs=1M end-to-end run against the 2015-2022 corpus; verify parity with local CPU numbers within numerical noise.
