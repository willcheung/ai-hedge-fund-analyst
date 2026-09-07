# Public staging verification scope

Offline verification uses synthetic data, disabled execution defaults and the shared `tools/staging/offline.sh` launcher. See `RELEASE.md` for dependency installation and isolation boundaries. Historical private import, job/skill audit and deployment receipts have been removed; this document does not carry forward their test counts or live coverage claims.

The source gate combines path/syntax checks with `tools/staging/privacy_scan.py`. It enumerates current source without Git or index access and reports paths/categories only. `python3 tools/staging/privacy_scan.py` scans every component. Dependency/tool metadata and generated build output are excluded from source enumeration; generated dashboard output must pass the separate byte-exact demo gate. The manifest gate checks that the current file inventory is exact. The documented [privacy policy](../tools/staging/PRIVACY-POLICY.md) covers exact synthetic exceptions, forbidden private inputs and permitted public metadata. Pattern scanning requires human review and cannot prove arbitrary prose contains no private associations.

Application tests must use a clean environment and the isolation wrapper. Namespace creation failure blocks application validation; never bypass it. No broker, external wiki, scheduler, publishing, remote GitHub or credentials are needed for source review. Optional vendor/media integrations and external runtime contracts remain unverified.

The repository remains public. Current-source cleanup does not sanitize Git history, remove previously published data or establish a production migration. Real deployment configuration and financial inputs belong outside the public checkout.

No historical test receipt certifies this integrated tree. Run every current CI
suite and the synthetic build in successful isolation before release; browser
smoke checks and remote release checks remain separate gates.
