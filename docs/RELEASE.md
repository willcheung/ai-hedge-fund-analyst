# Dashboard staging and release

This public repository releases dashboard source and a synthetic offline demo only. It does not contain or control private automations, Hermes jobs, trading execution, wiki contents, credentials, or portfolio/account data. Those systems are separate and must never be synchronized or imported here.

## Boundaries

- Keep secrets, personal/portfolio data, live snapshots, runtime state, and private configuration outside the checkout.
- Never add `automation/`, `deploy/jobs/`, or `trading-execution/`; the source gate rejects all three removed trees.
- Treat wiki inputs as external operator-controlled data. Repository fixtures are synthetic and are not real research.
- Do not deploy, publish, access credentials, or modify external systems from this workflow.

## Fresh isolated verification

Use Python 3.12 and Node 22.23.2 in a disposable checkout. Do not reuse an external Hermes environment or production dependencies. Dependency acquisition may use package registries; application tests may not.

`tools/staging/offline.sh` uses Bubblewrap with an explicit mount allowlist, network and PID namespaces, fresh `/proc`, private `/tmp` and `/run`, and a cleared environment. Set `STAGING_ROOT` only to the disposable checkout or its dedicated parent. Establishing isolation must succeed; never rerun application tests unsandboxed. If nested namespace creation is unavailable, report those tests as blocked.

The authoritative sequence is `.github/workflows/staging.yml`. It retains only `source-safety`, `dashboard-python`, and `dashboard-js-build`; actions are SHA-pinned, repository permissions are read-only, checkout credentials are not persisted, and the uploaded artifact is synthetic.

## Change and release

1. Make the smallest reviewed dashboard-only change.
2. Run preflight and source/privacy tests, then the affected dashboard tests inside isolation.
3. Review the diff and confirm `SOURCE-MANIFEST.json` exactly matches current tracked and untracked public source.
4. Scan committed history with `gitleaks detect --source . --redact --exit-code 1` before publication.
5. Require the three current workflow checks for the exact PR SHA: `source-safety`, `dashboard-python`, and `dashboard-js-build`.
6. Review the synthetic artifact and rehearse rollback only in a disposable staging location.

Production release, live data publication, wiki access, and changes to any private system require separate authorization and procedures outside this repository. A green public build does not imply that an external installation changed.

Keep branch protection, secret scanning, push protection, Dependabot alerts, SHA-pinned actions, read-only tokens, and outside-contributor workflow approval enabled. Do not store production credentials in repository secrets or deployment environments. Report vulnerabilities through [SECURITY.md](../SECURITY.md).
