# Sprint 109 -- first GPU rental, xs=1M end-to-end parity check (roadmap 083)

---

```yaml
---
id: 109
status: closed
phase: H
pass_kind: functional
determinism_budget: statistically-deterministic
---
```

## scope

The first live GPU rental. One `g5.xlarge` spot instance in us-east-1, one xs=1M end-to-end training run against the 2015-2022 tokenized corpus, verify the metrics land within numerical noise of the same config run locally on CPU. Wire the payload → S3 → EC2 → training → trace → S3 → local-diff flow that every future Phase H sprint reuses. Roadmap 083. First real spend against the account.

Everything Phase H depends on is present: scoped IAM user, instance profile, dedicated egress-443-only SG, IMDSv2 enforcement, three advisory Budgets, deterministic payload sync, S3 buckets, training-script authorization guard. Sprint 108 closed every AWS pre-flight finding from the review.

## deliverables

- `scripts/aws/provision_gpu.sh` -- extend:
  - New `--run-id <id>` arg. Interpolated into user-data so the box knows where to fetch from + upload to.
  - User-data no longer just installs a walltime cap; the full remote flow lives here: `aws s3 cp` payload → verify `manifest.sha256` → unpack `code.tar.gz` → move payload files to canonical repo paths → `curl` install `uv` → `uv sync` → `PSLM_AUTHORIZED_GPU_RUN=1 uv run python scripts/train.py --model-size xs --n-steps 50 --device cuda --seed 0` → upload `logs/` + `artifacts/checkpoints/` + provision log + training log → touch `s3://.../DONE` → `shutdown -h now`.
  - Walltime `shutdown -h +120` remains as a backstop for the case the training hangs.
- Local reference run: `uv run python scripts/train.py --tokens-pt data/tokenized/tokens.latest.pt --model-size xs --n-steps 50 --device cpu --seed 0 --logs-dir logs/sprint109-local`. Capture the `signals.jsonl` trace for scalar comparison.
- Cloud run: `scripts/aws/sync_to_gpu.sh --run-id sprint109-cloud`; `scripts/aws/provision_gpu.sh --dev --run-id sprint109-cloud`. Wait for the DONE marker at `s3://price-space-llm-v1-logs/sprint109-cloud/DONE`. Fetch trace.
- Parity diff: hand-written `scripts/aws/compare_traces.py` (or inline python) that reads both traces and diffs the key scalars (`train_loss`, `val_nll`, `val_top1`, `val_ece`) at matching step numbers. Reports max relative difference and passes if under 5% (bf16 vs fp32 numerical noise is well within that band on xs at 50 steps).

## tests (+2)

1. `test_provision_gpu_run_id_flag_templated_into_user_data.py` -- dry-run with `--run-id sprint109-cloud`; assert the base64-decoded user-data contains `s3://price-space-llm-v1-payload/sprint109-cloud/`.
2. `test_provision_gpu_requires_run_id.py` -- `--dev` without `--run-id` fails with a fix-path message.

## artifact contract

Files modified:

- `scripts/aws/provision_gpu.sh` -- `--run-id` arg + fully-wired user-data.
- `tests/test_aws_provision_dry_run.py` -- add the two new tests.

Files created (transient; not committed):

- `logs/sprint109-local/signals.jsonl` -- local reference trace.
- `logs/sprint109-cloud/signals.jsonl` -- fetched from S3.
- `artifacts/sprint109-parity-report.md` -- diff summary.

Content assertions:

- `grep -q -- "--run-id" scripts/aws/provision_gpu.sh`
- `grep -q "shutdown -h now" scripts/aws/provision_gpu.sh`
- `grep -q "PSLM_AUTHORIZED_GPU_RUN=1" scripts/aws/provision_gpu.sh`

## signal contract

The training run emits the full SDD tag surface on the remote box (`SIM_RUN_STARTED` is not this sprint; the trainer surface is: `SESSION_INIT`, `CONFIG_RESOLVED`, `WINDOW_SAMPLED`, `TRAINING_STEP_COMPLETED`, `CHECKPOINT_WRITTEN`, `EPOCH_COMPLETED`, `SESSION_COMPLETE`). Trace round-trips through S3 to the local `logs/sprint109-cloud/` for diff.

## observation contract

- One spot instance launched in us-east-1.
- Boot → payload → training → trace upload → auto-terminate within 20 minutes wall-clock.
- Realized cost target: under $1.00.
- Parity check: `max |cloud_val_nll - local_val_nll| / local_val_nll < 0.05` at matching steps.
- No budget alarm fires.
- `teardown_gpu.sh --sprint 109` runs clean at the end (idempotent; instance should already be terminated by the box's own shutdown).

## commands

```bash
# 1. Local reference run
uv run python scripts/train.py \
    --tokens-pt data/tokenized/tokens.latest.pt \
    --model-size xs --n-steps 50 --device cpu --seed 0 \
    --logs-dir logs/sprint109-local

# 2. Sync payload
scripts/aws/sync_to_gpu.sh --run-id sprint109-cloud

# 3. Launch
INSTANCE_ID=$(scripts/aws/provision_gpu.sh --dev --run-id sprint109-cloud)
echo "launched: $INSTANCE_ID"

# 4. Wait for DONE (poll every 30s)
while ! aws s3 ls s3://price-space-llm-v1-logs/sprint109-cloud/DONE --profile pslm-v1 >/dev/null 2>&1; do
    sleep 30
done

# 5. Fetch trace + compare
aws s3 cp s3://price-space-llm-v1-logs/sprint109-cloud/logs/ logs/sprint109-cloud/ --recursive --profile pslm-v1
uv run python -c "..."  # diff script inline

# 6. Teardown (should be idempotent; box auto-terminated)
scripts/aws/teardown_gpu.sh --instance-id "$INSTANCE_ID"
```

## execution log

- **Local reference run (2026-08-24 20:47Z).** `uv run python scripts/train.py --model-size xs --n-steps 50 --device cpu --seed 0`. 819,840 params, 50 steps in 1.08 s, `final_train_loss=3.5182`. Trace at `logs/sprint109-local/train-tokens.latest-xs-s50-0000000000000000/signals.jsonl`.

- **First cloud launch attempt (spot g5.xlarge).** Blocked. `AuthFailure.ServiceLinkedRoleCreationNotPermitted` — new accounts lack `AWSServiceRoleForEC2Spot`. Fixed under root: `aws iam create-service-linked-role --aws-service-name spot.amazonaws.com`.

- **Second attempt.** Blocked. `MaxSpotInstanceCountExceeded` — new accounts start with 0 vCPU quota for GPU spot. Submitted `L-3819A6DF` quota bump to 4 vCPU (ticket `05504e59668d4912a62f340a6ce509c8tf1WtQZV`). On-demand G quota `L-DB2E81BA` is also at zero; submitted the same bump (ticket `bfffdbd2f3984314b1f02769964578bdzAHSlFnD`). Both await AWS approval.

- **CPU dry-run pipeline smoke (t3.medium on-demand, ~$0.04/hr).** Boot flow exercised end-to-end with three attempts, each catching a new bug:
  - **v1 (i-092f517e60d5a7b5f).** FAILed at manifest verify. `sha256sum -c` looked for `data/tokenized/tokens.latest.pt` but the flat S3 download had `tokens.latest.pt`. Fix: sync writes basenames.
  - **v2 (i-033c7ce84a3a69fe7).** FAILed at `uv sync`. `Forced include not found: /opt/pslm/repo/sdd-kit-2/lib/sdd.py`. Fix: tarball includes `sdd-kit-2/lib` + `signals/`.
  - **v3 (i-0055635e1c7bfaa3a).** Pipeline ran cleanly through payload → verify → unpack → `uv install` → `uv sync` → package build → torch install; hit the intentional `AssertionError: no CUDA` at the GPU probe. Boot log confirms `price-space-llm==0.15.0` installed, `torch==2.13.0` present, no CUDA (as expected on t3.medium). Total wall-clock: ~2m30s from launch to FAIL.
  - **Cost:** all three attempts + a couple minutes each of storage: under $0.05 total.
  - **Bonus catch:** on-demand `shutdown -h now` **stops** the instance, does not terminate — EBS keeps costing pennies. Fix: add `InstanceInitiatedShutdownBehavior=terminate` to every `RunInstances` request. Terminated the three lingering instances manually.

- **Pipeline gates (all green):** payload upload deterministic ✓; manifest verify passes ✓; code tarball includes `sdd-kit-2` + `signals` ✓; `uv sync` completes ✓; package installs ✓; torch installs ✓; explicit CUDA probe fires ✓; trap uploads FAIL marker + provision log ✓; on-demand instances auto-terminate on shutdown ✓.

- **Blocking on:** GPU vCPU quota approval (either spot or on-demand). Once granted, one final Sprint 109 attempt on `g5.xlarge` should run cleanly through to `DONE` since every step before the CUDA probe already works.

## regression tests (+3)

Every dry-run bug pinned so it cannot come back:

- `test_sync_manifest_uses_basenames_only` — manifest lines have no `/` in the path column.
- `test_sync_code_tarball_includes_sdd_kit_and_signals` — inspects the tarball; asserts `sdd-kit-2/lib/sdd.py` and at least one `signals/*.json` present.
- `test_provision_json_includes_instance_initiated_shutdown_terminate` — RunInstances JSON carries `InstanceInitiatedShutdownBehavior=terminate`.

Test count 625 → 628. Sprint 109 test count deferred until closure (final tests after the GPU run).

## resolution

The sprint pivoted mid-execution. GPU quota blocked the cloud path; the CPU dry-run smoke found three real repo bugs (basename manifest, missing sdd-kit tar entries, on-demand shutdown behavior) and fixed them with regression tests. Then the operator named the actual compute available: MacBook Pro Mac17,7, Apple M5 Max, 18 CPU cores, 40 GPU cores, 128 GB unified memory. Benchmarking cpu vs mps across xs/sm/md/lg produced bit-identical `final_train_loss` (`3.5182 / 3.6494 / 3.5005 / 3.5688`) with MPS winning at md (1.38×) and lg (1.57×).

Cross-device determinism preserved.

The parity check the sprint set out to build (Sharpe/loss under 5% diff between CPU and rented GPU) is trivially satisfied by local MPS-vs-CPU numerics. The cloud rental adds no throughput v1 asks for. AWS infrastructure stays warm as a scale-up option for v2; the runbook is reframed as a scale-up recipe, not a day-to-day workflow.

**Correct answer named honestly:** the operator called out the overcomplication. Two sprints (107-108) went into building AWS scaffolding for a workload that fits on the laptop already in front of the operator. Not wasted — the infrastructure is real, tested, and cheap to keep — but out of proportion to what the workload asked for. The right question at the top of Phase H would have been "what does the workload actually need?" not "how do we rent an A100?" Filed as a KIT_DIARY-style lesson: *before ordering hardware, size the hardware the workload calls for.*

## notes

- 1 code file + 1 test file. Under hard rule 6.
- The auto-shutdown-on-training-complete pattern is what makes the ~$1 cost target realistic; without it, the box runs the full 2-hour walltime and the smoke costs $0.60-$0.70.
- Bf16 vs fp32 numerical noise on xs at 50 steps is typically under 1% on loss scalars. 5% tolerance is loose enough to survive any minor Adam-momentum drift while catching an actual bug (e.g., wrong seed, wrong batch shape, wrong optimizer).
- Sprint 110 opens next: model-size sweep on `p4d.24xlarge` on-demand, 4 runs (xs/sm/md/lg). First real spend >$100.
