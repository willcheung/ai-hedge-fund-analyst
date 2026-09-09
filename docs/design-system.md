# Financial change presentation contract

This contract extends the [dashboard design system](../dashboard/docs/design-system.md) for public, synthetic dashboard examples.

## Shared semantics

`dashboard/src/financialChange.tsx` owns `FinancialChange`, `PercentChange`, and the plain-text financial scanner. Changes use `data-direction="positive"`, `"negative"`, or `"neutral"` with the corresponding `--markets-*` token in both themes. Keep these rules after broad foreground rules in `theme.css`, including the Markets shell selector so semantic colors win the cascade. Signs and movement words remain visible; color is supplementary.

Structured percentage changes use one decimal and an explicit positive sign. Zero and negative zero are neutral; negative zero retains its sign. Missing and non-finite values use a neutral placeholder. Quote formatting retains its existing two-decimal default and trust, timestamp, and sign-consistency checks.

Revenue growth, price changes, observed returns, and projected upside use change semantics. Yield, margin, weight, valuation multiples, and Rule 40 scores remain levels or scores, without inferred change coloring. Table sorting retains the underlying numeric values. Chart tooltip strings use text formatters, never React elements.

## Authored prose and Markdown

`Narrative` and `ResearchHeadline` share classification before emphasis and ticker rendering. Preserve authored precision, signs (including Unicode minus), and text. Recognize explicit signed percentages and adjacent affirmative movement phrases. Keep ranges, negated movements, and ambiguous unsigned levels uncolored. Protected code, links, URLs, source identifiers, and raw HTML must not acquire financial markup or execute as HTML. Negation can cross a protected qualifier; movement context cannot.

Legacy article rendering shares code-fence and Markdown-table handling with `Narrative`. Ticker identity and styling remain independent of nearby changes.

## Morning briefing projection

`morningBriefPresentation.ts` applies only to morning briefing presentation. Omit the redundant “Market Setup” heading while retaining its body. Remove only a complete routine 09:30 ET cash-opening reminder. Preserve snapshot timestamps, bold formatting, substantive evidence, holiday or exceptional-hours clauses, and protected source text. Other publication categories retain their existing presentation.

## Verification

The `FinancialChange` unit, acceptance, and CSS tests use synthetic examples for structured values, prose precision, Markdown protection, both article paths, valuation outliers, and cascade specificity. Run application checks through the required [offline launcher](RELEASE.md). Source safety and the exact `SOURCE-MANIFEST.json` inventory remain mandatory; full isolated gates and final release review are separate from a focused port check.
