"""Sprint 107: provision_gpu.sh --dry-run emits a valid RunInstances request."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "aws" / "provision_gpu.sh"


def _run(*args: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        [str(SCRIPT), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_provision_dev_dry_run_prints_g5xlarge_spot_request():
    code, _, stderr = _run("--dev", "--dry-run", "--run-id", "test-run-id")
    assert code == 0, stderr
    assert "DRY RUN" in stderr
    payload = stderr.split("Request:", 1)[1]
    payload = payload[payload.find("{") : payload.rfind("}") + 1]
    body = json.loads(payload)
    assert body["InstanceType"] == "g5.xlarge"
    assert body["InstanceMarketOptions"]["MarketType"] == "spot"
    tags = body["TagSpecifications"][0]["Tags"]
    tag_map = {t["Key"]: t["Value"] for t in tags}
    assert tag_map["Project"] == "price-space-llm-v1"
    assert tag_map["Mode"] == "dev"


def test_provision_prod_dry_run_prints_ondemand_request():
    code, _, stderr = _run("--prod", "--dry-run", "--run-id", "test-run-id")
    assert code == 0, stderr
    payload = stderr.split("Request:", 1)[1]
    payload = payload[payload.find("{") : payload.rfind("}") + 1]
    body = json.loads(payload)
    assert body["InstanceType"] == "p4d.24xlarge"
    assert "InstanceMarketOptions" not in body


def test_provision_prod_dry_run_fallback_flag_switches_instance_type():
    code, _, stderr = _run(
        "--prod", "--fallback", "g5.2xlarge", "--dry-run", "--run-id", "test-run-id",
    )
    assert code == 0, stderr
    payload = stderr.split("Request:", 1)[1]
    payload = payload[payload.find("{") : payload.rfind("}") + 1]
    body = json.loads(payload)
    assert body["InstanceType"] == "g5.2xlarge"


def test_provision_requires_mode():
    code, _, stderr = _run()
    assert code == 2
    assert "--dev or --prod is required" in stderr


def test_provision_dev_tags_include_current_sprint():
    proc = subprocess.run(
        [str(SCRIPT), "--dev", "--run-id", "test-run-id", "--dry-run"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={"SPRINT_ID": "108", "PATH": subprocess.os.environ["PATH"]},
    )
    assert proc.returncode == 0
    payload = proc.stderr.split("Request:", 1)[1]
    payload = payload[payload.find("{") : payload.rfind("}") + 1]
    body = json.loads(payload)
    tags = body["TagSpecifications"][0]["Tags"]
    tag_map = {t["Key"]: t["Value"] for t in tags}
    assert tag_map["RunSprint"] == "108"


def test_provision_requires_run_id():
    """Sprint 109: the box uses --run-id to fetch payload; missing → exit 2."""
    code, _, stderr = _run("--dev", "--dry-run")
    assert code == 2
    assert "--run-id" in stderr


def test_provision_run_id_templated_into_user_data():
    """Sprint 109: the S3 payload path in user-data reflects the caller's --run-id."""
    import base64
    code, _, stderr = _run("--dev", "--dry-run", "--run-id", "sprint109-cloud")
    assert code == 0, stderr
    payload = stderr.split("Request:", 1)[1]
    payload = payload[payload.find("{") : payload.rfind("}") + 1]
    body = json.loads(payload)
    user_data = base64.b64decode(body["UserData"]).decode()
    # Run-id is templated into a shell assignment; the S3 paths are constructed
    # from it at boot time.
    assert 'RUN_ID="sprint109-cloud"' in user_data
    assert "s3://price-space-llm-v1-payload/" in user_data
    assert "s3://price-space-llm-v1-logs/" in user_data
    assert "PSLM_AUTHORIZED_GPU_RUN=1" in user_data
    assert "shutdown -h now" in user_data


def test_provision_json_includes_instance_initiated_shutdown_terminate():
    """Sprint 109 fix (CPU dry-run v3 bug): on-demand `shutdown -h` stops by default.

    Without `InstanceInitiatedShutdownBehavior=terminate` the box stops but does
    not terminate — EBS keeps costing money and the instance sits around.
    """
    code, _, stderr = _run("--dev", "--dry-run", "--run-id", "shutdown-test")
    assert code == 0, stderr
    payload = stderr.split("Request:", 1)[1]
    payload = payload[payload.find("{") : payload.rfind("}") + 1]
    body = json.loads(payload)
    assert body.get("InstanceInitiatedShutdownBehavior") == "terminate"


def test_provision_dry_run_includes_metadata_options_and_instance_profile_and_sg():
    """Sprint 108 review fixes: RunInstances JSON carries IMDSv2 + IAM role + SG."""
    code, _, stderr = _run("--dev", "--dry-run", "--run-id", "test-run-id")
    assert code == 0, stderr
    payload = stderr.split("Request:", 1)[1]
    payload = payload[payload.find("{") : payload.rfind("}") + 1]
    body = json.loads(payload)
    assert body["MetadataOptions"]["HttpTokens"] == "required"
    assert body["MetadataOptions"]["HttpEndpoint"] == "enabled"
    assert body["IamInstanceProfile"]["Name"] == "pslm-v1-ec2-training"
    assert isinstance(body["SecurityGroupIds"], list)
    assert len(body["SecurityGroupIds"]) >= 1
