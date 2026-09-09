// All market values and article examples in this file are synthetic.
import {describe, expect, it} from 'vitest'
import css from './theme.css?raw'

describe('financial change cascade contract', () => {
  const rules = [...css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/([^{}]+)\{([^{}]*)\}/g)]
  const foregroundRules = rules.filter(([, , declarations]) =>
    /\bcolor:\s*var\(--markets-(?:foreground|muted|primary|caution)\)/.test(declarations),
  )

  it.each(['positive', 'negative', 'neutral'])('keeps %s semantics above shared foreground rules', direction => {
    const selector = `.financial-change[data-direction='${direction}']`
    const contract = rules.find(([, selectors]) => selectors.split(',').map(s => s.trim()).includes(selector))
    expect(contract).toBeDefined()
    const selectors = contract![1].split(',').map(s => s.trim())
    // The unscoped selector preserves legacy consumers; the shell selector has
    // specificity (0,3,0), tying the broad :is() rule's strongest branch
    // (.markets-app .datatable-shell .dt-container), even for outlier spans.
    expect(selectors).toEqual([selector, `.markets-app ${selector}`])
    expect(contract![2].trim()).toBe(`color: var(--markets-${direction});`)
    // Source order must break that tie in favor of the semantic contract.
    // Cover all shared foreground rules, not just the reported outlier case.
    expect(foregroundRules.length).toBeGreaterThan(0)
    for (const rule of foregroundRules) {
      expect(contract!.index, rule[1].trim()).toBeGreaterThan(rule.index!)
    }
  })
})
