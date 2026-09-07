# Staging and controlled releases

This repository is a source-of-truth candidate, not an automatically deployed service. External installations are managed separately. No command in this runbook enables jobs, starts a broker, publishes a market snapshot or changes production aliases.

## Boundaries

- **Source:** Git tracks application code, synthetic tests, sanitized definitions and deployment examples.
- **Secrets:** provision outside the checkout with restrictive permissions. Never commit real `.env`, auth/session files, broker configuration or account data. Token refreshes are not source-code changes.
- **Runtime:** each install needs separate state/cache/output directories. Never copy mutable scheduler state or execution history into Git.
- **External wiki:** restore separately under operator control; configure application paths and validate required contracts. No wiki contents or tooling are imported by this staging work. Demo fixtures are not real research.
- **Execution:** package/test only, disabled by default; no vendor GUI, evaluator, broker login or order path is activated.

## Before work

```sh
python3 tools/preflight/github_readiness.py --owner willcheung --repo ai-hedge-fund-analyst --expected-login willcheung --expected-visibility public --workdir .
git status --short
git fetch origin
```

Confirm expected identity, explicitly approved public visibility for this repository, Git write/workflow permission and source stability. Other repositories still default to private in the preflight; never change the expected visibility merely to bypass an unexpected mismatch. Coordinate with other editors. If someone fixes a live script, review and capture that change before developing against an obsolete copy. Never reset away unknown changes.

## Fresh, isolated verification

Clone into a disposable directory **outside `/root`**, including on this VPS. Use Python 3.12 and Node 22.23.2. Create a new virtual environment; do not reuse Hermes' venv or production node_modules. Dependency installation may use the registry network; application tests may not.

`tools/staging/offline.sh` uses Bubblewrap with an explicit mount allowlist: the disposable tree is writable; system libraries and the CI toolchain are read-only. Host homes, wiki/runtime mounts, shared sockets and host procfs are not exposed. PID/network namespaces, fresh `/proc`, private `/tmp` and `/run`, and a cleared environment isolate tests. Set `STAGING_ROOT` to the disposable checkout (or its dedicated parent containing its fresh environments), never a broad/live directory. Invoke the trusted launcher with a clean environment before Bash starts: `env -i PATH="$PATH" STAGING_ROOT="$STAGING_ROOT" bash tools/staging/offline.sh COMMAND`. Run the launcher as the owner of the disposable tree. CI copies only the checked-out source into a new root-owned `/tmp/analyst-ci` directory, creates fresh dependencies there, and launches the same sandbox as root. It does not grant broader permissions to the runner's private home or disable network isolation. Local root-owned staging uses the same ownership model. Establishing isolation must succeed; never rerun unsandboxed. Other operating systems require a disposable Linux VM/container with equivalent boundaries.

Download hash-pinned third-party wheels using `pip download --only-binary=:all: --require-hashes` into the disposable tree, then install with `--no-index --find-links` inside isolation. Build/install the local package inside isolation too. Use `npm ci --ignore-scripts` for dependency installation. No source-distribution build hooks run during online Python dependency acquisition.

The authoritative executable verification sequence is `.github/workflows/staging.yml`; component README files describe package-specific setup. Python and JavaScript tests are separate jobs so one cannot hide failures in the other. Live-only integrations are explicitly skipped; they are not reported as passing. Workflow credentials have read-only repository scope and checkout does not persist the token.

## Fix → commit → release

1. Create a focused branch from current source. Search existing code before adding another abstraction.
2. Write/reproduce the relevant test, make the smallest behavior-preserving fix, and run the related offline tests.
3. Run all affected component gates plus source/privacy/secret checks. Keep real keys out of unit tests.
4. Review the diff, source inventory and integration boundaries. `SOURCE-MANIFEST.json` is a current public structural inventory only; it must not retain private import fingerprints or operational provenance.
5. Commit small logical changes. Scan committed history with `gitleaks detect --source . --redact --exit-code 1` before pushing. Ignore baseline-only whitespace debt rather than reformatting unrelated files.
6. Push and verify remote SHA. Require successful application CI for that exact SHA. Open/review a PR; do not treat old green checks or a successful API call as proof of the new release.
7. Build the clearly synthetic staging bundle, record commit identity and artifact SHA-256, and smoke-test all six existing tabs locally.
8. Rehearse rollback between two verified static artifacts in a disposable staging release directory. Switching a staging symlink is not a production rollout.
9. Stop at staging-ready and present tests, CI URL, commit, artifact, external dependencies and limitations. Production deployment requires separate approval.

Do not add automatic commits or deployments to a cron. Do not make GitHub pushes trigger production Vercel deploys during this goal. Existing production data publishing and the dashboard application release remain separate paths.

## Public repository safeguards

Before release, verify that `main` requires a PR, an up-to-date branch, resolved review conversations, and successful GitHub Actions checks: `automation`, `dashboard-js-build`, `dashboard-python`, `disabled-execution`, and `source-safety`. Require these protections for administrators too, and block force-pushes and deletion. No second-human approval is required for this solo-maintainer repository, but independent code review remains part of the change process. Do not weaken protections to make a merge pass.

Verify that secret scanning, push protection, Dependabot alerts and security-update PRs are enabled, with automatic merging and production deployment disabled. Review affected inputs/locks, acquire hash-pinned wheels, rerun isolated tests/builds and audit the resolved versions before merging a dependency update. Functional CI passing alone is not a vulnerability scan.

Require workflow approval for outside contributors. Review proposed workflow/code changes before granting approval; hosted runners and read-only tokens are not permission to run arbitrary code against production. Actions must retain full commit SHA pins; verify the remote repository policy enforces them. Keep repository Actions secrets and deployment environments free of production credentials.

Report vulnerabilities privately using [SECURITY.md](../SECURITY.md). License and dependency notices must be preserved when distributing source or built artifacts.

## Later production approval checklist

Before a separate cutover, the operator must provide/approve the target host and release, wiki restore/mount and compatibility check, per-integration credentials, filesystem ownership/permissions, disabled-by-default job import and deliberate activation selection, deployment target/Blob origin, backup and rollback plan, and a nonduplicating scheduler handoff. Preserve paused jobs and completed one-shots. Never run two active schedulers against the same jobs/state or two publishers against the same target.

Credential-only fixes stay private. Code changes made in the legacy live directory must be explicitly reviewed into Git; they do not synchronize automatically. Until cutover, a green repo build does not mean the running production source has changed.
