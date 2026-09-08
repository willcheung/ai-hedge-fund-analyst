# Public dashboard verification scope

Verification covers only the public dashboard source and its synthetic offline demo. Private automations, Hermes jobs, trading execution, wiki contents, credentials, live snapshots, and portfolio/account data are separate and are never synchronized or imported. No public automation source is present.

`tools/staging/check_source.py` combines path and syntax checks, an exact `SOURCE-MANIFEST.json` comparison, and `tools/staging/privacy_scan.py`. Enumeration does not consult Git, so tracked and untracked source are both covered. Tool metadata, installed dependencies, caches, and generated build output are excluded; generated dashboard JSON has a separate byte-exact synthetic demo gate.

The path gate explicitly rejects the removed `automation/`, `deploy/jobs/`, and `trading-execution/` trees. Privacy scanning retains strict patterns and AST checks for private paths, identifiers, endpoints, personal email, financial associations, account values, portfolio values, and embedded private account configuration. Exact line receipts remain limited to reviewed synthetic adversarial fixtures and public metadata; there are no directory-wide exemptions.

Application tests run with `tools/staging/offline.sh`. Bubblewrap must establish its filesystem, process, environment, and network boundaries; failure to create namespaces blocks application validation and must not be bypassed. Source review needs no broker, external wiki, scheduler, publisher, remote GitHub access, or credentials.

The current workflow has exactly three jobs:

- `source-safety`: history secret scan plus preflight, source, privacy, and isolation regressions.
- `dashboard-python`: locked Python dependencies and dashboard tests inside isolation.
- `dashboard-js-build`: locked dependencies, dashboard tests/build/privacy checks inside isolation, then a synthetic artifact.

Static pattern scanning cannot prove arbitrary prose is public, and current-source cleanup does not rewrite Git history. Human diff/history review and remote branch protections remain required before merging.
