# AI Hedge Fund Analyst Dashboard

**Version:** 0.1.0

This public repository contains only the dashboard source and a synthetic, offline demo. It is not a production system and does not deploy or publish anything automatically. See it in action at https://market-analyst.vibecodingdad.com/.

## Privacy boundary

The repository contains no personal financial data, portfolio holdings, account identifiers, credentials, runtime state, or live dashboard snapshots. Private automations, Hermes jobs, trading execution, wiki contents, and portfolio/account data are maintained separately. They are never synchronized or imported into this public repository, and no automation source is included here.

Contributions must preserve that boundary. Source checks reject private material and prevent the removed `automation/`, `deploy/jobs/`, and `trading-execution/` trees from returning.

## Public source

- `dashboard/`: the public research UI, synthetic demo generator, schemas, fixtures, and tests.
- `tools/`: source/privacy validation, credential preflight, and strict offline isolation tooling.
- `.github/workflows/staging.yml`: read-only CI for source safety, dashboard Python tests, dashboard JavaScript tests/build, and a synthetic artifact only.
- `SOURCE-MANIFEST.json`: exact current public source inventory, including untracked source files.
- `UPSTREAM.json`: metadata for Hermes as a separate external dependency; no Hermes source, environment, jobs, or runtime data is present.

See [dashboard/README.md](dashboard/README.md), [staging verification](docs/STAGING-VERIFICATION.md), [release guidance](docs/RELEASE.md), and [SECURITY.md](SECURITY.md).

## Verify locally

```sh
python3 -m unittest discover -s tools/preflight -p 'test_*.py' -v
python3 -m unittest discover -s tools/staging -p 'test_*.py' -v
python3 tools/staging/check_source.py
```

Application tests must run through the Bubblewrap launcher described in the release guide. If namespace creation is unavailable, report the blocked isolated tests; do not bypass isolation. The workflow acquires locked dependencies before entering the network-isolated sandbox and produces only a synthetic dashboard artifact.

## License

Original repository source is available under the [MIT License](LICENSE). Third-party packages, services, and assets retain their own terms. Hermes remains separately licensed and pinned only as metadata in `UPSTREAM.json`.
