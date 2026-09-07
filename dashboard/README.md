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
