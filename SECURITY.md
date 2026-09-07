# Security policy

## Reporting a vulnerability

Use this repository's [private vulnerability reporting](https://github.com/willcheung/ai-hedge-fund-analyst/security/advisories/new). Do not open a public issue with exploit details or sensitive information.

Include the affected commit, affected component, expected versus actual behavior, and a minimal reproduction using synthetic data. Never submit real credentials, account information, broker sessions, private wiki contents or production logs. If a credential was exposed, revoke or rotate it through its provider; removing a Git commit alone does not revoke it.

Reports are handled on a best-effort basis; there is no guaranteed response time. Review currently targets the latest `main` source. This repository does not provide a managed production service or a security guarantee for separately deployed copies.

## Safe testing and contributions

- Test only in disposable environments and against systems you own or are explicitly authorized to test.
- Keep execution disabled; do not connect to real brokers, submit orders, activate jobs, post content or publish production snapshots to demonstrate a problem.
- Keep secrets, real account data, wiki contents and mutable runtime state outside Git and CI. Public source, logs and artifacts must remain safe to disclose.
- Changes go through a PR and the required CI checks. Review dependency updates before merging; security-update PRs are not automatically merged or deployed.
- GitHub Actions use read-only repository permissions, full-SHA action pins and hosted disposable runners. Review outside-contributor workflows before approving them; do not supply production credentials to make tests pass.

See [the release runbook](docs/RELEASE.md) for the isolation and deployment boundaries. Passing offline tests is not proof that all dependency vulnerabilities are absent or that a production deployment is authorized.
