# Security

Report suspected vulnerabilities privately via GitHub security advisories ("Report a vulnerability" on the Security tab). Do not open a public issue.

This repository ships no runnable service. The scripts operate on local files and one HTTPS API (Alpha-Vantage). Nothing listens on a port.

The AWS setup scripts under `scripts/aws/` provision EC2 spot instances against the operator's own account. Read `docs/runbooks/aws-infrastructure.md` before running any of them. Every resource is tagged `Project=price-space-llm-v1` and scoped to region `us-east-1`.
