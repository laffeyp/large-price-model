"""Sprint 108: pin the shape of scripts/aws/iam-policy.json against review §12 findings.

Every finding the review flagged as a blocker gets an assertion here so a future
policy edit that regresses one of them fails at pytest time, not in production.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / "scripts" / "aws" / "iam-policy.json"


def _policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _statements() -> list[dict]:
    return _policy()["Statement"]


def _get_actions(stmt: dict) -> list[str]:
    action = stmt.get("Action")
    if isinstance(action, str):
        return [action]
    if isinstance(action, list):
        return action
    return []


def test_policy_has_explicit_deny_on_s3_delete_bucket():
    """Review §3: prevent misfired teardown from deleting a bucket."""
    matches = [
        s for s in _statements()
        if s["Effect"] == "Deny" and "s3:DeleteBucket" in _get_actions(s)
    ]
    assert len(matches) == 1, "expected exactly one Deny statement covering s3:DeleteBucket"
    resources = matches[0]["Resource"]
    if isinstance(resources, str):
        resources = [resources]
    assert set(resources) == {
        "arn:aws:s3:::price-space-llm-v1-payload",
        "arn:aws:s3:::price-space-llm-v1-logs",
    }


def test_cloudwatch_logs_split_drops_wildcard():
    """Review §3: no statement has both a specific log-group ARN and `*` in Resource.

    The Sprint 107 draft had `"Resource": ["<specific-arn>", "*"]`, making the ARN meaningless.
    """
    for stmt in _statements():
        resources = stmt.get("Resource")
        if isinstance(resources, str):
            resources = [resources]
        if not isinstance(resources, list):
            continue
        has_specific_log_group = any(
            isinstance(r, str) and r.startswith(
                "arn:aws:logs:us-east-1:648879824221:log-group:/aws/ec2/price-space-llm-v1"
            )
            for r in resources
        )
        if has_specific_log_group:
            assert "*" not in resources, (
                f"statement {stmt.get('Sid')} mixes a specific log-group ARN with '*'; "
                "the wildcard makes the ARN scoping meaningless"
            )


def test_iam_pass_role_is_allowed_scoped_and_not_denied():
    """Review §12 blocker 1: pass-role narrowing for the training instance profile.

    iam:PassRole must NOT appear in DenyIAMEscalation, and MUST appear in a
    scoped Allow bound to the pslm-v1-ec2-training role ARN.
    """
    deny_actions: list[str] = []
    allow_pass_role: list[dict] = []
    for stmt in _statements():
        if stmt["Effect"] == "Deny":
            deny_actions.extend(_get_actions(stmt))
        if stmt["Effect"] == "Allow" and "iam:PassRole" in _get_actions(stmt):
            allow_pass_role.append(stmt)
    assert "iam:PassRole" not in deny_actions, (
        "iam:PassRole must not appear in a Deny statement; the scoped Allow "
        "below would be shadowed"
    )
    assert len(allow_pass_role) == 1, "expected exactly one Allow iam:PassRole"
    stmt = allow_pass_role[0]
    resource = stmt["Resource"]
    assert resource == "arn:aws:iam::648879824221:role/pslm-v1-ec2-training"
    # Should be conditioned on the EC2 service so the pass is bound to instance profiles only.
    cond = stmt.get("Condition", {})
    assert cond.get("StringEquals", {}).get("iam:PassedToService") == "ec2.amazonaws.com"


def test_ec2_actions_include_security_group_create_and_authorize():
    """Review §12 should-fix 6: pslm-v1 needs to create and manage the dedicated SG."""
    ec2_actions: set[str] = set()
    for stmt in _statements():
        if stmt["Effect"] != "Allow":
            continue
        for a in _get_actions(stmt):
            if a.startswith("ec2:"):
                ec2_actions.add(a)
    required = {
        "ec2:CreateSecurityGroup",
        "ec2:AuthorizeSecurityGroupEgress",
        "ec2:RevokeSecurityGroupEgress",
        "ec2:DeleteSecurityGroup",
    }
    missing = required - ec2_actions
    assert not missing, f"policy missing EC2 SG actions: {sorted(missing)}"


def test_policy_size_under_managed_limit():
    """Customer-managed policy JSON must stay under 6144 bytes."""
    size = POLICY_PATH.stat().st_size
    assert size <= 6144, f"policy is {size} bytes; over the 6144 managed-policy limit"
