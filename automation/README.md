# Automation source and offline tests

Generic data collection, formatting and analysis helpers are preserved. Optional network, publishing, scheduler, broker, media and external-wiki capabilities remain disabled for staging; consult `capabilities.json`. Do not bulk-import legacy modules: some initialize SDKs or perform operations at module scope. Configuration does not establish operational readiness.

## Private inputs

- `ANALYST_HOLDINGS_FILE`: absolute JSON path outside the checkout, containing `{"holdings": ["SYNTH"]}` (synthetic symbol). Unset means empty holdings. Invalid or unreadable explicit input fails closed. Market prefetch adds configured holdings to public benchmark earnings coverage; market_data fetches only configured holdings. Feed tagging uses the same helper.
- `ANALYST_WATCHLIST_CONFIG`: optional private external JSON containing `exclude_symbols`; no personal sale history or symbol exclusion list is bundled. `ANALYST_JOB_TARGETS_FILE` supplies private job ID-to-label mappings for the optional pilot stopper.
- `ANALYST_METALS_OPTIONS_FILE` (or explicit `load_metals_options(path)` / trader `--metals-options-cache`): private external JSON with optional `positions`, `summary.by_underlying`, `generated_at` and `account_value`. Missing configuration returns no exposure. An explicitly selected missing/invalid file raises a value-free error. No account summary is discovered implicitly. Missing account value prints allocation unavailable; a supplied denominator must be finite and positive. Optional trader sizing limits are explicit CLI inputs.
- `NEWSLETTER_TARGET_EMAIL`, `NEWSLETTER_TOKEN_FILE`, `NEWSLETTER_CLIENT_SECRETS_FILE`: required environment-only configuration, checked before SDK initialization or credentials. `NEWSLETTER_PRIORITY_SENDERS` optionally supplies comma-separated sender addresses. No personal recipient fallback exists.
- Optional legacy operations use `ANALYST_WIKI_ROOT`, `ANALYST_DASHBOARD_ROOT`, `ANALYST_EXECUTION_ROOT`, `ANALYST_HERMES_HOME`, `ANALYST_DASHBOARD_URL`, `ANALYST_BLOB_ORIGIN`, `ANALYST_SAFE_DEPLOYMENT_ID`, or `ANALYST_JOBS_FILE` as required by the selected source. `X_SOURCE_LIST_ID` and `ANALYST_SLACK_CHANNEL` are private delivery/collection targets. No deployment root or ID is embedded. Paths interpolated into legacy shell commands must use simple paths without shell metacharacters; these scripts remain deferred pending operational review.
- Shell launchers additionally require explicit `ANALYST_ENABLE_LEGACY_OPS`. Existing client state/secret helpers support `ANALYST_STATE_DIR` and `ANALYST_SECRETS_DIR`; tests use disposable homes. These environment inputs are not credentials or account values to commit.

## Verification

Follow [RELEASE.md](../docs/RELEASE.md) for hash-pinned wheel acquisition and offline installation into a fresh environment under a dedicated `/tmp` staging root. From this directory, run:

```sh
env -i PATH="$PATH" STAGING_ROOT="$(pwd -P)/.." bash ../tools/staging/offline.sh python -m unittest discover -p 'test_*.py' -v
```

Use the same wrapper for every application test. Isolation failure is fatal; no unsandboxed fallback is permitted. Optional heavy/vendor integrations are not installed by the offline lock or validated by source parsing. Public inventories describe current relative source structure only, with no original private import hashes or operational provenance.
