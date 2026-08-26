# Full review — Phase G close + AWS scaffolding

**Reviewer:** Claude Code (Opus 4.7), acting in Agent role.
**Date:** 2026-08-24.
**Scope:** Sprints 100-107. Phase G refactor arc (100 mark-to-market + guards; 101 required checkpoint kwargs; 102 vectorized bootstrap; 103 perf cleanup; 104 extract helpers; 105 delete dead walkers; 106 audit + commit-hook install + shell-wrapper bugfix) plus Sprint 107 AWS pre-provisioning (IAM policy, budgets, three shell scripts, `scripts/train.py` EC2 guard, runbook at `docs/runbooks/aws-infrastructure.md`). Test count 585 → 615 (+30). Vocabulary version unchanged at v0.7.
**Verdict:** Phase G closes correctness-clean. AWS scaffolding is defensible but carries one policy shape that should tighten before Sprint 108's live boot, and two script-level items belong on the punch list. SDD discipline continues at cadence.

---

## 1. Phase G — every review item landed

`reviews/full-review-phase-f-close.md` §7 named eight items for Phase G. All eight closed:

- **§2 walker-hooks refactor.** Sprint 105 sidestepped by deletion instead of refactor — `grep` confirmed zero production callers of `run_simulation_with_predictions` and `run_simulation_with_policy`. Both were incremental scaffolding walkers superseded by `run_simulation_with_trades`. Deleted ~220 lines from `skeleton.py` plus their walker-integration tests (7 tests removed). Two production walkers survive (`run_simulation_skeleton` for CLI-facing bar-only, `run_simulation_with_trades` for production). CLAUDE.md guidance quoted verbatim on the sprint card: *"If you are certain that something is unused, you can delete it completely."*
- **§2 SimResult discriminated union.** Sprint 103 landed `notes: Literal["skeleton", "predictions-only", "predictions+policy", "predictions+policy+trades"]` — the poor-man's-discriminated-union path, checkable at mypy time.
- **§2 extract position helpers.** Sprint 104 moved `close_position_and_record`, `emit_position_opened`, `emit_position_closed`, `emit_trade_ledgered` from `skeleton.py` to `positions.py` alongside their `Position`+`Trade` dataclasses. Underscores dropped (module-public surface). `skeleton.py` shrank by ~130 lines.
- **§3.1 vectorize `derive_prices_from_log_returns`.** Sprint 103 replaced the Python loop with `torch.where(isfinite, r, 0) → cumsum → exp`. Semantically identical (NaN log-return means zero log-return means price stays flat). Pinned bit-tight against the retained loop reference on 100-bar mixed-NaN input.
- **§3.2 vectorize block bootstrap.** Sprint 102's one-file, ~50× wall-clock win. Same seed produces bit-identical `(se, positive_fraction)` against the reference loop.
- **§3.3 `searchsorted` in `build_equity_curve`.** Sprint 103. `np.searchsorted(sorted_bar_ts, exit_epochs, side="right")` in one call. Mypy overload fought; resolved via explicit `np.asarray(..., dtype=np.int64)` cast.
- **§3.4 cached `train_means_tensor`.** Sprint 103. Plain property, not `@cached_property` — the latter fights `frozen=True + slots=True` and the honest workaround (`__slots__` cache + `object.__setattr__` bypass) is worse than the construct-once contract.
- **§6.2 shared axis-sweep helper.** Sprint 104's new `simulation/sweeps.py::run_axis_sweep(...)` — capacity and sensitivity both delegate. Capacity uses `policy_field="position_size_usd"` + identity; sensitivity uses `policy_field="slippage_frac"` + template multiplication.

The correctness bundle in **Sprint 100** landed six review items under one hard-rule-6 stretch (mark-to-market equity, NaN-probs guards, non-positive exit-price guard, absolute-drawdown fallback, NaN raw-target skip, plus the `Trade` dataclass extension mark-to-market required). Stretch named on the card; the single concept ("close out the correctness gap the Sprint 097 approximation introduced") holds it together.

Sprint 100 live smoke reports the delta cleanly: mark-to-market Sharpe = **-0.8965** vs Sprint 097's step-function 0.0. The pre-registered gates (Sharpe > 0.5; Sharpe − SE > 0; block_bootstrap ≥ 0.70) now consume tech-arch §11.5's intended continuous metric. `max_drawdown=3.77` (>100%) is honest math on a degenerate ledger — the peak-to-trough loss exceeded the modest positive peak; named on card. A Sprint 108 GPU-trained model with real reversals produces well-formed drawdown ratios.

**Sprint 106's two drift catches** are the loudest signal that the audit was worth running:

- **Drift #1.** `scripts/check_test_look.sh` existed but `.git/hooks/commit-msg` was never symlinked. The pre-commit test-look guard **never fired on any commit in this repo's history**. The hook shipped in Sprint 064 with a one-line install command in its header comment; nobody ran it. Fix: `ln -sf "$(pwd)/scripts/check_test_look.sh" .git/hooks/commit-msg`; symlink noted on the sprint card as operator-local (does not travel with clones).
- **Drift #2.** The Sprint 064 shell wrapper contained `"$PYTHON" - "$COMMIT_MSG_FILE" <<'PYEOF' <<<"$STAGED_FILES"` — two competing stdin redirections. Bash keeps only the last. The heredoc Python script **never reached the interpreter**; the Python process instead read the staged-files list as its source code and died with `NameError: name 'configs' is not defined`. The pure-Python `check_commit_for_test_look` had test coverage; the shell wrapper around it did not. Test-coverage gap named on the card. Sprint 106 rewrote the wrapper (pipe `git diff --cached --name-only` on stdin, pass commit-message path via argv) and added four shell-level tests exercising the wrapper end-to-end with a stub `git` on `PATH`.

Two live-verified fixes; two real production defects that would have shipped through to a held-out sim run. That is exactly what an audit sprint is for. Cite Sprint 106 in KIT_DIARY as the pattern: *when a shell wrapper exists around tested Python, test the shell wrapper end-to-end — the Python tests don't cover it.*

---

## 2. AWS scaffolding — inventory

Sprint 107 shipped five files under `scripts/aws/`:

| file | purpose |
|---|---|
| `iam-policy.json` | Customer-managed policy for the scoped IAM user |
| `budgets.json` | Three cost tiers ($500/$1500/$3000) + two notification rules |
| `provision_gpu.sh` | Launch g5.xlarge (dev/spot) or p4d.24xlarge (prod/on-demand) with `--dry-run` and `--fallback` |
| `sync_to_gpu.sh` | Deterministic tar of code + payload files, SHA-256 manifest, upload to S3 |
| `teardown_gpu.sh` | Terminate by `--instance-id` or by `--sprint` tag filter, cancel orphan spot requests |

Plus `scripts/train.py::_enforce_ec2_authorization_guard()` invoked at the top of `main()`, refuses to run on EC2 unless `SPRINT_107_AUTHORIZED_RUN=1` is set. `PSLM_SKIP_EC2_CHECK=1` bypass for tests.

Plus `docs/runbooks/aws-infrastructure.md` — the runbook is the single source of truth for what AWS resources exist and how to reconstitute them.

**Live-verified as of Sprint 107 close:** IAM user `price-space-llm-v1` in account 648879824221 (region us-east-1); customer-managed policy `PriceSpaceLLMV1` (3735 bytes; the 2048-byte inline-policy limit forced the managed-policy path); two S3 buckets `price-space-llm-v1-{payload,logs}` with versioning ON, public-access-block on all four flags, AES-256 default encryption; SNS topic `price-space-llm-v1-alerts` with pending email subscription; three tag-filtered Budgets on `Project=price-space-llm-v1`, notified at 100% actual + 90% forecast.

---

## 3. IAM policy — line-by-line

The policy has seven statements. Discipline shape is right (two `Deny` guards on top, five scoped `Allow` blocks below). One real tightening:

**`RegionLock` (lines 5-21).** `Effect: Deny` on `NotAction: [iam:GetUser, iam:ListAccessKeys, sts:GetCallerIdentity, budgets:*, cloudwatch:GetMetricStatistics, s3:ListAllMyBuckets]` under `Condition: aws:RequestedRegion != us-east-1`. Correct: the whitelisted services are legitimately global or need cross-region visibility. Denies everything else outside the intended region. Standard AWS pattern.

**`DenyIAMEscalation` (lines 22-36).** Explicit `Deny` on eight IAM/PassRole actions. Correct. Prevents the scoped user from ever granting itself more permissions — even if the `PriceSpaceLLMV1` policy is misedited to add IAM actions, the explicit Deny wins. Textbook.

**`EC2Compute` (lines 37-62).** Sixteen EC2 actions on `Resource: "*"`. Right for a compute-only IAM user; EC2 does not support fine-grained resource ARNs on `RunInstances` in the ways one might want. `CreateTags` present — required for Budgets to attribute cost via `Project` tag. `DeleteVolume` present but the teardown script does not delete EBS volumes explicitly (§5 below).

**`S3PayloadAndLogs` (lines 63-73).** `s3:*` scoped to the two named buckets and their objects. Correct. Grants all S3 actions on those specific ARNs; the `RegionLock` Deny prevents cross-region S3 usage.

**`S3ListBuckets` (lines 74-79).** `s3:ListAllMyBuckets` on `Resource: "*"` (required — the action does not accept a specific ARN). Correct.

**`CloudWatchAndLogs` (lines 80-97).** **This is the one policy shape to tighten before Sprint 108.** The `Resource` list is `["arn:aws:logs:us-east-1:648879824221:log-group:/aws/ec2/price-space-llm-v1/*", "*"]`. The wildcard `"*"` in the list makes the specific ARN meaningless — every action gets `Resource: *`. Either drop the wildcard and rely on the specific log-group ARN, or split the statement into two:
- One statement for `logs:*` scoped to the specific ARN.
- One statement for `cloudwatch:GetMetricStatistics` and `cloudwatch:PutMetricData` on `Resource: "*"` (CloudWatch metrics do not accept per-metric ARNs; wildcard is required).

Currently the second is silently in effect for logs too. Not a security hole (the IAM user is scoped; only a compromised session inside the box could exploit it), but the intent-vs-implementation gap will confuse a future reader.

**`BudgetsAndSNS` (lines 98-132).** Twenty-nine actions on `Resource: "*"`. Budgets and SNS do not accept per-resource ARNs in every action; wildcard is customary. The scoped user cannot escalate to global control because `DenyIAMEscalation` blocks the IAM path. Two gaps caught during live provisioning were fixed inline: `sns:CreateTopic` was missing from the first draft; `budgets:CreateBudget` internally checks `budgets:ModifyBudget` which was also missing. Both listed now. Runbook change-log records the pattern — cite as a KIT_DIARY entry: *AWS actions sometimes internally require sibling actions; grant on live-provisioning failure and record the reason.*

**`IdentitySelf` (lines 133-142).** `iam:GetUser`, `iam:ListAccessKeys`, `sts:GetCallerIdentity` on self. Required for the scoped user to see who it is.

**Missing (worth adding before Sprint 108):**

- **No `Condition: aws:MultiFactorAuthPresent: true` on the two `Deny` statements.** The escalation and region-lock Denies stand without MFA, which is fine for a scoped user without a console login. But a stronger form is: require MFA for actions that could delete production data (S3 DeleteObject on the buckets, EC2 TerminateInstances). Not blocking; worth a rationale-doc entry on the trade-off.
- **No `s3:PutObject` encryption condition.** The buckets have AES-256 default encryption enabled, so every PUT gets encrypted server-side regardless. Belt-and-suspenders would be a `Condition: s3:x-amz-server-side-encryption: AES256` on the PutObject action. Skippable given default encryption is on.
- **No explicit `Deny` on `s3:DeleteBucket`.** The `s3:*` grant on the two named buckets includes `s3:DeleteBucket`. A misfired teardown script could delete the payload bucket. Add an explicit `Deny` on `s3:DeleteBucket` scoped to the two ARNs. One-line addition; big blast-radius reduction.

---

## 4. Budgets + SNS — correctness

`budgets.json` declares three cost tiers ($500 / $1500 / $3000) at monthly cadence, tag-filtered on `user:Project$price-space-llm-v1`. Notification rules: 100% actual (ALARM) + 90% forecasted (OK). SNS topic wired.

**Correct shape.** The `Notes` field on the JSON is explicit that these are advisory-only: *"AWS Budgets emails via SNS; no RunInstances stop action wired. A breach informs, it does not halt."* That is honest. AWS supports Budget Actions that can, e.g., attach a restrictive IAM policy on breach — deliberately not wired.

**The tag key format** `user:Project$price-space-llm-v1` uses AWS Budgets' documented `<key_type>:<key>$<value>` syntax. `user:` prefixes user-defined tags (as opposed to `aws:` for AWS-generated). Correct.

**One concern.** Tag-filtered budgets only capture costs on resources that carry the tag. `provision_gpu.sh` correctly tags every instance with `Project=price-space-llm-v1`. But: EBS volumes attached to the instance inherit the instance's tags in some cases and not others (depends on launch template vs `RunInstances` call). S3 storage costs against the two buckets are not tagged by resource (buckets don't tag storage; buckets tag themselves). CloudWatch Logs costs against the log group not tagged. **The three Budgets may under-report** if EBS or S3 or CloudWatch costs land untagged. Worth a runbook note: *"tag-filtered budgets cover EC2 compute only; expect S3 storage + CloudWatch logs + EBS to appear under an untagged cost bucket that the three tiers do not see."*

---

## 5. `provision_gpu.sh` — correctness

**Modes correct.** `--dev` = g5.xlarge spot + 2-hour walltime + max spot price $0.50; `--prod` = p4d.24xlarge on-demand + no walltime + `--fallback` for g5.2xlarge when p4d quota not approved. Sensible.

**Walltime enforcement.** User-data runs `shutdown +${WALLTIME_MINUTES} "..."` at boot when `WALLTIME_MINUTES > 0`. The `${WALLTIME_MINUTES}` interpolates at client-side (unquoted heredoc `<<EOF`), so the cloud-init script receives literal `shutdown +120 "..."`. Correct. Note that `shutdown +120` triggers OS shutdown, which terminates a spot instance but does NOT terminate an on-demand instance's billing on some AWS instance-type configurations — for spot the shutdown behavior is safe.

**`\$(date -u +%FT%TZ)` in the heredoc.** Backslash escapes the `$` so cloud-init receives literal `$(date -u +%FT%TZ)`. Correct.

**Payload wiring is not present.** User-data has a commented placeholder: `# echo "aws s3 cp s3://price-space-llm-v1-payload/<run_id>/ ..."`. Sprint 108's scope. Correct absence at Sprint 107.

**Tags.** Three tags: `Project=price-space-llm-v1` (Budgets filter), `RunSprint=<sprint-id>` (teardown filter), `Mode={dev,prod}`. Good.

**`--dry-run`.** Prints the fully-resolved RunInstances JSON to stderr and exits 0 before calling the API. Textbook operator-safety flag.

**Response parsing.** `python3 -c 'import json,sys; print(json.load(sys.stdin)["Instances"][0]["InstanceId"])'` — correct, works cross-platform.

**Missing:**
- **No `IamInstanceProfile` in the RunInstances request.** The EC2 instance itself needs an instance-profile-attached IAM role to fetch payload from S3 or emit CloudWatch logs. Currently the instance has no role attached; the running box has no AWS credentials. Sprint 108 needs an instance profile before the training payload can pull. **Blocker for Sprint 108.**
- **No `KeyName` for SSH.** The user cannot ssh into the box after launch. `ec2:CreateKeyPair` is in the IAM allow list but the script never creates or references one. Blocker if any interactive debugging is needed.
- **No `SubnetId` or `SecurityGroupIds`.** RunInstances will use the default VPC's default subnet and default security group. Fine for a smoke; a production run wants a dedicated security group with `Egress: 443/HTTPS to S3 + Alpha-Vantage` and no ingress. Sprint 108 candidate.
- **`--dev` spot max price `$0.50`.** g5.xlarge on-demand is ~$1.006/hr; spot is typically 60-80% off. $0.50 is comfortably above typical spot pricing but below a spike. Reasonable.

---

## 6. `sync_to_gpu.sh` — correctness

**Deterministic tar.** `find src scripts -type f -print | LC_ALL=C sort > files.txt; tar -cf - -T files.txt | gzip -n -c > code.tar.gz`. Sorted file list + no-timestamp gzip. Cross-platform (BSD tar on macOS lacks `--sort/--owner/--mtime`; the manual sorted-list + `gzip -n` reaches the same determinism). Textbook.

**Payload list.** `data/tokenized/tokens.latest.pt`, `artifacts/tokenizer/normalizers.latest.pt`, `artifacts/tokenizer/bucket_stats.latest.json`. Three latest-symlinks; `aws s3 cp` follows symlinks. Good.

**SHA-256 manifest.** Local computation before upload. `sha256sum` on Linux; **not native on macOS** (`shasum -a 256` is). If Sprint 108's operator runs on macOS, the script errors. One-line fix: `command -v sha256sum >/dev/null 2>&1 || sha256sum() { shasum -a 256 "$@"; }`. Small.

**Missing payload verification.** The script uploads the manifest but never re-downloads and byte-verifies the S3 copy. On the remote box a Sprint-108 script needs to `aws s3 cp s3://.../manifest.sha256 . && sha256sum -c manifest.sha256`. Named as remote-side responsibility; the sync script itself does not verify. Fine.

**Missing:** the S3 uploads do not use `--only-show-errors` or `--no-progress`, so a Sprint 108 CI run gets noisy stdout. Cosmetic.

---

## 7. `teardown_gpu.sh` — correctness

**Idempotent.** `aws ec2 terminate-instances` on already-terminated instances is a no-op. `aws ec2 wait instance-terminated` returns immediately. Good.

**Two modes.** `--instance-id` (single) or `--sprint` (tag filter). Both work; the `--sprint` mode also cancels open spot requests filtered by the same tag. Good.

**Missing: EBS cleanup.** The Sprint 107 comment says "cleans orphaned EBS + open spot requests." The script cancels spot requests but does NOT delete EBS volumes explicitly. On spot instances, `DeleteOnTermination` on the root EBS is set to true by default (via the AMI's block device mapping), so root volumes get cleaned automatically. Any attached secondary EBS would orphan. Sprint 107's provisioning script does not attach secondary EBS, so this is not a live problem today. Worth a runbook note: *"the teardown script assumes root EBS `DeleteOnTermination=true`, which the Deep Learning AMI sets; if a future sprint attaches secondary EBS, add an explicit `aws ec2 delete-volume` pass here."*

**No CloudWatch log group cleanup.** Log groups from prior sprints accumulate. Not a cost issue at v1's expected volume, but a Sprint 108+ cleanup routine could `logs:DeleteLogGroup` old groups. Deferrable.

---

## 8. Training-script EC2 guard

`scripts/train.py::_enforce_ec2_authorization_guard()` invoked at the top of `main()`. Detects EC2 via IMDSv2 or `AWS_EC2_INSTANCE_ID` env var. Refuses unless `SPRINT_107_AUTHORIZED_RUN=1` is set. `PSLM_SKIP_EC2_CHECK=1` bypass for tests.

**Good shape.** Exactly the halt-and-articulate discipline applied to expensive resources: an explicit environment ratification gate must be set before the walker burns wall-time. Prevents an accidental `scripts/train.py` invocation from someone SSH'd into a rented box from spending money on a smoke.

**One small concern.** The gate variable name is `SPRINT_107_AUTHORIZED_RUN`. Sprint-numbered env vars accrue: Sprint 108's live training run needs the same gate, so the variable name locks the semantic to a sprint that will soon be historical. Better: `PSLM_AUTHORIZED_GPU_RUN=1`. Rename before Sprint 108 to avoid the "why is Sprint 107's variable name still gating my Sprint 112 training run" future-reader question. One-line fix.

---

## 9. AWS best-practices scoreboard

| item | status |
|---|---|
| Region-locked IAM policy | ✓ |
| Deny IAM escalation | ✓ |
| S3 buckets versioning on | ✓ |
| S3 buckets public-access-block on (all four flags) | ✓ |
| S3 default encryption AES-256 | ✓ |
| S3 grants scoped to specific buckets | ✓ |
| Budget alerts wired via SNS | ✓ (advisory, named on card) |
| Budget tag filter matches instance tags | ✓ (EC2 compute only; §4 caveat) |
| Root credentials not used after initial setup | ✓ (scoped `pslm-v1` profile used) |
| IMDSv2 (metadata service) used in provisioning | ✓ (`--metadata-options HttpTokens=required` recommended; script does not pass — see §11) |
| Instance profile for S3/CloudWatch access | ✗ (blocker for Sprint 108, §5) |
| Dedicated security group | ✗ (uses default VPC's default SG; §5) |
| SSH key pair | ✗ (§5) |
| Explicit Deny on `s3:DeleteBucket` | ✗ (§3 tightening) |
| Explicit `logs:*` resource scoping (drop wildcard) | ✗ (§3 blocker) |
| MFA condition on Deny statements | ✗ (rationale worth naming) |
| Deterministic sync payload + manifest | ✓ |
| Idempotent teardown | ✓ |
| Cost-boundary alarms before compute wired | ✓ |
| Training-script EC2 authorization guard | ✓ |

---

## 10. SDD-technique observations

**Sprint 100 stretch named on the card.** Six review items bundled under one hard-rule-6 stretch. The single-concept framing ("close the correctness gap the Sprint 097 step-function approximation opened") holds them together. Named, not bypassed.

**Sprint 101 fail-loud kwargs pattern applied to placeholders.** Six placeholder `checkpoint_run_id="sprint-NNN-no-checkpoint-id"` defaults gone. Every walker + sweep driver requires the three kwargs. Call sites that omit any of them raise `TypeError` at the call itself. Sprint 077's fail-loud shape applied to the "legal but lying" default class.

**Sprint 102's card names it "pure accumulator swap".** Vectorized bootstrap produces bit-identical `(se, positive_fraction)` against the retained loop reference implementation. Live smoke reruns Sprint 100's exact configuration: identical numeric output on every field. The refactor is honest.

**Sprint 105 cites CLAUDE.md verbatim before deletion.** *"If you are certain that something is unused, you can delete it completely. Avoid backwards-compatibility hacks."* Grep-verified zero production callers; deletion is behavior-preserving (live smoke identical). Right shape.

**Sprint 106 caught two real drift bugs during audit.** Both had test coverage on the surface that would have caught them if the shell layer had been tested (the Sprint 064 wrapper had no shell-level test; the pure-Python function did). Test-coverage gap named on the card and filed to KIT_DIARY-style memory: *when a shell wrapper exists around tested Python, test the shell wrapper end-to-end.*

**Sprint 107 IAM gaps caught in live provisioning.** `sns:CreateTopic` missing from first draft; `budgets:CreateBudget` internally requires `budgets:ModifyBudget`. Both fixed inline; runbook change-log records the pattern. Cite as KIT_DIARY entry: *AWS action grants sometimes require sibling actions the docs do not list; grant on live-provisioning failure and record the pattern.*

**Sprint 107 named "one secret exposure" honestly.** *"`~/.aws/credentials` reading showed the pslm-v1 secret access key in the session transcript during the install-key step."* Not hidden. Documented so the operator can decide to rotate. Same discipline as Sprint 020's misframing retraction: honest reporting of an inconvenient fact.

**Runbook as single source of truth.** `docs/runbooks/aws-infrastructure.md` covers inventory + first-time provisioning + day-to-day flow + failure modes + end-of-v1 teardown. Not scattered across sprint cards. Correct level of abstraction — a Sprint 108 operator reads one file.

---

## 11. Small findings

**11.1 `provision_gpu.sh` does not set `MetadataOptions.HttpTokens=required` in the RunInstances request.** IMDSv2 (session-tokened metadata service) is AWS's current best practice; IMDSv1 (open metadata service) is vulnerable to SSRF attacks. Add `"MetadataOptions": {"HttpTokens": "required", "HttpEndpoint": "enabled"}` to the RunInstances JSON. Two-line change; forces IMDSv2 on every rented box.

**11.2 `provision_gpu.sh` walltime `shutdown +${WALLTIME_MINUTES}` sends a text message.** The final positional argument to `shutdown` is the message shown to logged-in users. That works but a stricter form is `shutdown -h +${WALLTIME_MINUTES}` — the `-h` flag halts (does not reboot). On some Ubuntu variants `shutdown` without `-h` defaults to halt; on others it defaults to reboot with the same time semantics. Explicit is safer.

**11.3 The `USER_DATA` heredoc has `[[ ${WALLTIME_MINUTES} -gt 0 ]]` interpolated at client side.** For `--prod` mode, `WALLTIME_MINUTES=0` (line 53) so the branch never fires — correct. For `--dev` mode, `WALLTIME_MINUTES=120` and the shutdown fires. The client-side interpolation is safe here because the value is always numeric. If a future flag ever passes a shell-metacharacter value, the interpolation opens command injection into cloud-init. Not exploitable today; worth a comment naming the trust boundary.

**11.4 `sync_to_gpu.sh` uses `sha256sum` (Linux); macOS has `shasum -a 256`.** §6 above. One-line shim covers it.

**11.5 Sprint-numbered env var name.** `SPRINT_107_AUTHORIZED_RUN=1` should be `PSLM_AUTHORIZED_GPU_RUN=1`. §8 above.

**11.6 CloudWatch logs resource wildcard.** §3 above — the wildcard makes the ARN-scoping ineffective. Drop the wildcard or split the statement.

**11.7 Explicit Deny on `s3:DeleteBucket`.** §3 above. One-line addition; big blast-radius reduction.

**11.8 Instance profile missing.** §5, §9 above. Blocker for Sprint 108.

---

## 12. Pre-Sprint-108 punch list

**Must fix before booting the first live instance:**

1. Add an EC2 instance profile with a role granting the box `s3:Get/PutObject` on the two buckets + `logs:CreateLogStream/PutLogEvents`. Attach to the RunInstances request via `IamInstanceProfile`. Without this the box has no AWS credentials.
2. Drop the `"*"` wildcard from `CloudWatchAndLogs.Resource` — either scope to the specific log-group ARN or split into two statements.
3. Add explicit `Deny` on `s3:DeleteBucket` for the two named bucket ARNs. Prevents an accidental teardown-script bug from deleting production data.
4. Add `MetadataOptions.HttpTokens=required` to the RunInstances JSON. IMDSv2 only.
5. Rename `SPRINT_107_AUTHORIZED_RUN` to `PSLM_AUTHORIZED_GPU_RUN` in `scripts/train.py` + test file + runbook.

**Should fix (non-blocking):**

6. Dedicated security group for the training instance (egress-443-only to S3 + Alpha-Vantage, no ingress).
7. `sha256sum` → `shasum` shim in `sync_to_gpu.sh`.
8. Runbook note: tag-filtered budgets cover EC2 compute only; S3/CloudWatch/EBS costs land in an untagged bucket the three tiers do not see.
9. Runbook note: teardown script assumes root EBS `DeleteOnTermination=true`.

**MFA condition on Deny statements** — deferrable; worth a rationale-doc entry naming the trade-off.

---

## 13. Bottom line

Phase G closed correctness-clean: eight review items landed, mark-to-market equity replaced the step-function approximation the pre-registered gates would have misread, and Sprint 106's audit caught two production defects (never-installed commit hook + broken shell wrapper) that would have shipped through to a real held-out sim. The correctness debt from Phase F is paid.

Sprint 107's AWS scaffolding is well-shaped and matches the AWS best-practice patterns for a scoped-user compute environment: region-locked, IAM-escalation-denied, S3 bucket-scoped, versioned, encrypted, tag-budgeted. Five items belong on the pre-Sprint-108 punch list — one blocker (instance profile), three tightenings (log-group resource, S3 delete-bucket deny, IMDSv2), one naming cleanup (env var).

SDD discipline continues at cadence: two live IAM gaps caught in provisioning and recorded, one secret-exposure named honestly, two Phase G refactors that landed as behavior-preserving deletions with grep + live-smoke verification, one review-driven audit sprint that found real defects. Twenty-nine sprints in the arc, one legitimate stretch named (Sprint 100), zero silent bypasses.

Recommendation: fix the five §12 blockers, then Sprint 108 boots the first live g5.xlarge spot for an xs=1M end-to-end smoke against the 2015-2022 corpus.
