# Synthetic dashboard

The default app is an offline, clearly labeled demonstration built entirely from
`tests/fixtures/demo-dashboard.json`. Its companies, publications and dated events
are fictional. It uses relative bundled JSON, local fonts and no analytics. Demo
HTML blocks external connections and frames. Company chart embeds are disabled.

The UI includes publication contracts, theme and workflow views, and synthetic
regression suites. No real research snapshot or source history is included.

Use Node 22.23.2, npm 10.9.8 and Python 3.12. Existing exact npm versions and the
hash-locked Python requirements (including Pillow 12.3.0) are preserved. The optional
analytics SDK is pinned to `@vercel/analytics` 2.0.1.

All application tests, generation, builds and artifact validation must run through
`../tools/staging/offline.sh` in a disposable checkout. Changing HOME alone does
not provide filesystem or network isolation. Do not relax namespaces if the host
cannot run that entry point. See [staging verification](../docs/STAGING-VERIFICATION.md) and the
[CI workflow](../.github/workflows/staging.yml) for the required gates.

Within that isolation:

- `npm test` generates the deterministic demo, validates local contracts, and runs
  all Python unittest and JavaScript Vitest suites.
- `npm run build` generates/reuses only identical synthetic data, validates it,
  checks TypeScript, builds static output and checks source and artifact privacy.
- `npm run validate:privacy` checks source defaults and requires public/dist JSON
  to match freshly generated synthetic bytes. Unexpected JSON and source maps fail.
- `npm run dev` serves the synthetic demo on loopback.
- `python3 scripts/stage_demo.py --output-dir /tmp/fresh-demo --scenario missing`
  creates the empty-input scenario. Existing different datasets and symlinks fail.

`public/wiki-data.json`, `public/market-data/`, `dist/`, dependencies, and install
caches are generated and ignored. The checked-in fixture is hand-authored test
input, not a copied research snapshot. Python tests use temporary directories and
mocked transports; real Blob smoke remains explicitly opt-in and is excluded by
the staging environment.

Production runtime data requires all three explicit environment settings:
`VITE_MARKETS_DATA_MODE=production`, `VITE_MARKETS_MANIFEST_URL`, and
`VITE_MARKETS_BLOB_ORIGIN`. The build fails if production mode lacks either URL.
There is no bundled owner origin or deployment rewrite. Production integrations
must arrange their own manifest/snapshot routes. Analytics additionally requires
an explicit `VITE_ENABLE_ANALYTICS=true` in a production build (`import.meta.env.PROD`).
It stays off in dev, default tests and every synthetic/bundled mode, even with that
opt-in. Enabled analytics strips URL queries and fragments before sending events;
invalid or non-HTTP(S) URLs are dropped. Default demo build validation requires
zero analytics transport in emitted artifacts. These settings do not authorize
publication or deployment.

The optional generator requires explicit `--wiki-root`, `--cron-root`, `--output`
and `--offline`. It fails on absent input directories and never falls back to a
host wiki. `MARKETWIKI_CACHE_ROOT`, `MARKETWIKI_STATE_ROOT` and
`MARKETWIKI_ENV_FILE` configure external cache/state/credential paths; unset paths
stay inside this checkout, with the credential path disabled. No credential file
is loaded at import. The auxiliary AI validator accepts `MARKETWIKI_WIKI_ROOT`.

Schema validation uses both checked-in snapshot contracts. External comparison
requires `--wiki-schema PATH` or `MARKETS_WIKI_SCHEMA`; `--integration` requires
one of those inputs and fails closed. Historical weekly report lineage is empty
by default; regression tests inject scoped synthetic mappings. No historical
research is embedded in the helper.

Job identities in demonstration helpers use `synthetic-job-*` tokens. Private
installations must supply their own reviewed job mappings; these tokens identify
fixtures and are not deployment identities.
# Meter and consumer builds

Daily Brief includes a six-band macro meter, Eastern publication times, complete
macro and weekly commentary, and shared theme styling. Meter scores are supplied
by the publication contract; the browser only positions and labels them. Missing
scores remain unavailable. The optional offline generator accepts `--macro-meter`
with an explicit JSON artifact and validates it without rewriting its numeric DTO.

The demo meter is fictional: 5.5, dated January 2000, with synthetic input paths.
The shared meter observation fixtures contain synthetic boundary and invalid
cases, not recorded market observations. Contract source identifiers are stable
public vocabulary; they do not refer to installed jobs. Timeline mappings cover
only synthetic demo producers; other publishers supply their category metadata.

`npm run build` remains the synthetic offline build. `npm run build:live` builds
the manifest consumer into `dist/live`, requires explicit
`VITE_MARKETS_MANIFEST_URL` and `VITE_MARKETS_BLOB_ORIGIN`, and copies only the
reviewed icons and fonts. It includes no bundled JSON dataset. Remote failures
use the existing validated cache behavior, or show unavailable data when no
cached edition exists. Neither build publishes anything.

Use a fresh disposable source copy at `/tmp/analyst-ci` and the tool versions in
the staging workflow. Dependency acquisition is separate setup (no lifecycle
scripts); run these from that copy after installing Bubblewrap:

```sh
python3 -m venv .venv
python3 -m pip download --index-url https://pypi.org/simple --only-binary=:all: --require-hashes -r dashboard/requirements.txt -d .wheelhouse
env -i PATH="$PATH" HOME=/tmp/analyst-install-home npm ci --ignore-scripts --prefix dashboard
env -i PATH="/tmp/analyst-ci/.venv/bin:$PATH" STAGING_ROOT=/tmp/analyst-ci bash tools/staging/offline.sh python -m pip install --no-index --find-links .wheelhouse --require-hashes -r dashboard/requirements.txt
```

Then, from `/tmp/analyst-ci/dashboard`, run application validation only through
the unchanged isolation entry point:

```sh
env -i PATH="/tmp/analyst-ci/.venv/bin:$PATH" STAGING_ROOT=/tmp/analyst-ci bash ../tools/staging/offline.sh bash -c 'python scripts/validate_demo_privacy.py --source-only && npm test && npm run build && npm run validate:public && npm run validate:privacy'
env -i PATH="/tmp/analyst-ci/.venv/bin:$PATH" STAGING_ROOT=/tmp/analyst-ci bash ../tools/staging/offline.sh bash -c 'VITE_MARKETS_MANIFEST_URL=https://example.com/manifest.json VITE_MARKETS_BLOB_ORIGIN=https://example.com npm run build:live && python scripts/validate_public_assets.py dist/live'
```

The second command uses inert example endpoints to verify the consumer build;
it does not fetch a manifest. Namespace failures block application validation
and must be handled by running the same entry point on a compatible host.
