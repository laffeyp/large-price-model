# Security

Report suspected vulnerabilities privately via GitHub security advisories ("Report a vulnerability" on the Security tab). Do not open a public issue.

Two facts worth knowing:

- This repository ships no runnable service. The scripts operate on local files and one HTTPS API (Alpha-Vantage); nothing listens on a port.
- The AWS scaffolding under `scripts/aws/` provisions EC2 spot instances against the operator's own account. Read `docs/runbooks/aws-infrastructure.md` before running any of it. Every resource is tagged `Project=price-space-llm-v1` and scoped to region `us-east-1`.
