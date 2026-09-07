# Read-only GitHub preflight

This is a **Git source-control start gate**, not a deployment authorization. It does not create repositories, push, change Git configuration, install packages or validate Vercel/Blob/broker credentials.

From the repository root:

```sh
python3 -m unittest discover -s tools/preflight -p 'test_*.py'
python3 tools/preflight/github_readiness.py --owner willcheung --repo ai-hedge-fund-analyst --expected-login willcheung --expected-visibility public --workdir .
```

The owner, repository and expected login must be explicit. `--expected-visibility` accepts `private` (the safe default) or `public`. This repository's owner approved public visibility, so its command explicitly selects `public`; the helper never infers approval from the repository's current setting. A missing or mismatched check exits nonzero. It verifies stored gh authentication, API identity, exact target and expected visibility, consistent GitHub privacy metadata, write permission, configured Git identity and actual read-only Git transport. The initial push is verified separately by comparing the remote commit SHA.

Subprocesses remove stale GH_TOKEN/GITHUB_TOKEN/GITHUB_PAT and debugging variables; provider stderr and credentials are not printed. Git transport uses the gh credential helper for that command only. An expired global URL rewrite can still interfere; fix the narrowly scoped auth configuration separately and rerun, rather than treating API auth as proof of working Git.

Unit tests cover fail-closed behavior in both visibility modes and CLI option handling. SOURCE-MANIFEST.json is a public structural inventory, without original private source hashes.

Before a goal or release, recheck source stability, secret scans, workflow permission, applicable integration credentials and the full docs/RELEASE.md. This helper does not enforce all of those checks or install an OS sandbox.
