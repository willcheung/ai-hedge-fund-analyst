# Dashboard design system

This document defines the small, shared visual contract for the public dashboard. It describes the system already implemented by the application; it is not a separate component library.

## Foundation and ownership

[`src/theme.css`](../src/theme.css) is the canonical source for design tokens and shared primitives. It is loaded after the retained legacy stylesheet so its accessible, theme-aware rules apply consistently across public routes.

[`src/styles.css`](../src/styles.css) is grandfathered legacy code. Its existing hardcoded values are accepted debt, but it is not a template for new work and should not receive new design primitives. New shared rules belong in `theme.css`; a feature that cannot reasonably use a shared primitive may have a small feature stylesheet whose visual values come from `--markets-*` tokens.

## Tokens

Use the semantic token whose name matches the role of the value. Do not copy a token's current literal color into feature CSS: every color token can change between light and dark themes.

### Surfaces, text, and interaction

- Page and content surfaces: `--markets-background`, `--markets-surface`, and `--markets-hover`.
- Primary text and secondary text: `--markets-foreground` and `--markets-muted`.
- Boundaries: `--markets-border` and `--markets-border-strong`.
- Primary actions and selection: `--markets-primary`, `--markets-primary-foreground`, `--markets-selected`, and `--markets-focus`.
- Ticker links and labels: `--markets-ticker`, `--markets-ticker-background`, and `--markets-ticker-hover`.
- Destructive actions: `--markets-destructive` and `--markets-destructive-foreground`.
- Overlays: `--markets-overlay-shadow`.

Four states communicate research and operational meaning:

| State | Foreground | Background | Meaning |
| --- | --- | --- | --- |
| Positive | `--markets-positive` | `--markets-positive-background` | Successful, healthy, or constructive |
| Caution | `--markets-caution` | `--markets-caution-background` | Degraded, delayed, or needs attention |
| Negative | `--markets-negative` | `--markets-negative-background` | Failed, blocked, or adverse |
| Neutral | `--markets-neutral` | `--markets-hover` when a surface is needed | Informational or unavailable without a positive/negative conclusion |

Color is supporting information, never the only status signal. Pair it with visible text such as “Pass,” “Degraded,” “Failed,” or “Assessment unavailable.” Icons and emoji that carry meaning need an accessible label or accompanying text.

The four `--markets-chart-*` tokens provide the fixed chart palette. Data-derived chart colors may remain dynamic when categories are labeled in the chart or an adjacent key.

### Typography and dimensions

- Interface text uses `--markets-font-body`: Inter with system fallbacks.
- Editorial headings use `--markets-font-editorial`: Source Serif 4 with serif fallbacks.
- Spacing uses `--markets-space-1` through `--markets-space-8`, representing 4, 8, 12, 16, 24, 32, 48, and 64 pixels.
- Corners use `--markets-radius` or `--markets-radius-lg`.
- Content width uses `--markets-width`; long-form reading width uses `--markets-reading-width`.

The short unprefixed custom properties in `theme.css` are compatibility aliases for retained components. New modular CSS should use the `--markets-*` names directly.

## Accessibility and interaction

Interactive controls must have at least a 44px target in the context where they are used. Keep the shared `:focus-visible` outline visible; do not remove it unless the replacement is at least as clear in light, dark, and forced-color modes.

Use semantic elements and accessible names before adding ARIA. Status updates should remain understandable in text, keyboard navigation must reach every action, and reduced-motion preferences must be respected.

Tables belong in a contained horizontal-scroll region at narrow widths. Headers and financial values must not wrap mid-value; use tabular numerals for numeric comparisons. The page itself must not gain horizontal overflow.

## Themes and responsive behavior

Light, dark, and system preferences are required. `ThemeProvider` resolves the preference and sets `data-theme` on the document root. Any new semantic color must be defined for both the default light theme and `:root[data-theme='dark']`; system mode then follows the operating-system preference automatically.

Design mobile-first within the existing layout. The shared breakpoints currently adapt dense layouts around 900px, collapse navigation below 768px, and stack compact layouts around 540px. Prefer fluid grids, wrapping controls, and contained scrolling over adding page-specific breakpoints. Check representative routes at desktop and mobile widths in both themes.

## Contribution rules

For a visual change:

1. Reuse an existing shared primitive or semantic `--markets-*` token.
2. Add a token to `theme.css` only when no existing token expresses the required semantic role, and define its light and dark values together.
3. Put generally reusable CSS in `theme.css`. Keep unavoidable feature CSS small and token-based.
4. Do not add raw hex, `rgb()`/`rgba()`, or `hsl()`/`hsla()` colors to modular CSS. `theme.css` owns palette literals, while existing `styles.css` is explicitly grandfathered.
5. Inline styles may express dynamic or numeric geometry such as a calculated height or position. Literal inline `color`, `background`, `backgroundColor`, `borderColor`, or `outlineColor` values are prohibited. Existing data-derived chart colors remain allowed.
6. Run `npm test` and `npm run build` from `dashboard/`; both include the lightweight design-system check.

These rules apply only to the public dashboard source and its synthetic demo. They must not introduce or document private data, production configuration, or external operational workflows.
