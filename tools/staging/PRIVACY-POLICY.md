# Public source privacy policy

`privacy_scan.py` is a deterministic regression guard, not semantic review of
financial prose. Diagnostics contain relative paths and categories, never matches.
It does not invoke Git, import application code, or read private configuration.

All source components, tests, licenses and documentation are scanned. Enumeration
omits Git/tool metadata, installed dependencies, Python caches and generated build
output. It does not apply broad ignore rules that could hide credentials. Symlinks
are reported without following them. `check_source.py` also requires an exact
current `SOURCE-MANIFEST.json` inventory. Generated dashboard JSON is checked by
`dashboard/scripts/validate_demo_privacy.py` against fresh synthetic bytes.

The deny patterns cover private home roots, opaque deployment/account identifiers,
operational endpoints, personal email, financial associations and embedded private
configuration. Python AST checks additionally reject nonempty holdings/account
constants and financial `.get()` defaults. Reserved example email domains are
permitted. No file, owner word, regex class, dashboard directory or test directory
is exempt. Public author attribution and third-party license notices are preserved.

`privacy-policy.json` contains exact source-path/category/full-line SHA-256 receipts
for reviewed adversarial synthetic inputs, synthetic normalization prefixes,
public economic/SEC identifiers and one generic social-media-account description.
These hashes identify current synthetic source lines, not private source history.
They avoid repeating detectable negative fixtures in a second file. A receipt
only suppresses that category on that exact line in that exact file. No automatic
learning or receipt generation is part of the gate. A future authorized license
email may receive the same narrowly reviewed treatment; licenses are not exempt.

Adding or changing a receipt requires reading the source and documenting why it
is public or invented. Real embedded personal, operational or financial facts must
be removed or externalized. Do not hide data through string concatenation.

Tests require every receipt to match a current detectable source line. Copied
literals, changed lines, appended values, new lines and real-shaped synthetic
negatives in every exception-bearing file must still fail. Python AST checks are
never suppressed by line receipts. Human review of unrecognized facts and separate
secret/history checks remain required before publication.
