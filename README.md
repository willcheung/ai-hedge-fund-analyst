# AI Hedge Fund Analyst

Public source control and **offline staging** for the analyst dashboard, custom automation and disabled execution package. Production is not automatically deployed from this repository.

## Start here

- [Staging verification and explicit limitations](docs/STAGING-VERIFICATION.md)
- [Install, test, change, release and rollback process](docs/RELEASE.md)
- [Security policy and private vulnerability reporting](SECURITY.md)
- [Dashboard/demo and configurable wiki paths](dashboard/README.md)
- [Automation support and deferred capabilities](automation/README.md)
- [Synthetic job examples and nonexecuting scratch import](deploy/jobs/README.md)
- [Disabled execution package](trading-execution/README.md)

## What is versioned

- `dashboard/`: six-tab public research UI with publication, theme and workflow views, generator/publisher source, schemas, synthetic fixtures and tests, explicit runtime/dependency locks.
- `automation/`: generic scripts, explicit private configuration, synthetic tests and capability metadata.
- `trading-execution/`: installable deterministic package, schema/resources and fake-broker tests with disabled defaults. **Code retains real order-placement capability**; never invoke operational entrypoints casually.
- `deploy/jobs/`: synthetic schema examples, private-setting placeholders and a scratch-only importer that cannot activate jobs.
- `tools/` and `.github/`: credential preflight, static source boundaries, offline isolation and separate CI suites. CI builds a synthetic artifact; it never deploys production.

`SOURCE-MANIFEST.json` lists current public relative source structure without private import hashes or provenance. `UPSTREAM.json` identifies the external Hermes dependency; no Hermes source, venv, wiki, vendor broker binaries or runtime home is copied here.

## Before changing code

```sh
python3 tools/preflight/github_readiness.py --owner willcheung --repo ai-hedge-fund-analyst --expected-login willcheung --expected-visibility public --workdir .
python3 -m unittest discover -s tools/preflight -p 'test_*.py'
git status --short
```

This repository is intentionally public. The preflight defaults to requiring a private repository; `--expected-visibility public` explicitly checks the approved public target without bypassing identity or write-permission checks.

Make reviewed changes on a focused branch. Follow the executable clean-install sequence in `.github/workflows/staging.yml`, including its network/filesystem isolation. Do not bulk-import application scripts or run tests against production HOME. Scan the diff and committed history for secrets before pushing, and verify CI for the exact remote SHA.

## Keep these boundaries

Credentials, account data, runtime state, scheduler claims/output, generated live snapshots, wiki contents and other-profile data stay outside Git. Refreshing a token is normally a private configuration change, not a code commit. Wiki relocation has synthetic interface tests; attaching a real restored wiki and enabling dependent jobs requires separate review/provisioning.

External installations are **not automatically synchronized** into this repository. Coordinate with other editors and review/capture live fixes before developing against stale source. No blind auto-commit job, automatic scheduler import or production cutover is installed.

The trade-intent example and approval metadata are synthetic fixtures, never authorization to submit an order. Archived skills and dormant scripts are not reactivated to make readiness look green. See the verification document for missing external dependencies and the difference between offline staging and full production restoration.

## License

Original repository source is available under the [MIT License](LICENSE). Third-party packages, services and external assets retain their own licenses and terms; this license does not relicense them. Hermes remains the separately pinned external dependency identified in `UPSTREAM.json`.
