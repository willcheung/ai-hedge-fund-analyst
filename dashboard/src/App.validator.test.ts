// SYNTHETIC regression inputs only; no research snapshot dependencies.
import { describe, expect, it } from 'vitest'
import { actionableEntryRows, bubbleRadiusForEnterpriseValue, dashboardFreshnessTimestamp, dashboardTabs, findCanonicalRegimePosture, isDashboardData, isRelativeValueFocusPoint, operationalNodeState, regimeStanceLabel, tabFromHash, topOutlierLabelSymbols } from './App'

const ticker = {
  symbol: 'TEST', title: 'Test', updated: '2026-08-09', tags: ['test'], sourcePath: 'tickers/test.md',
  summary: 'Summary', status: 'watch', actionBucket: 'wait_watch', isStub: false, category: 'Test',
}
const valid = {
  schemaVersion: 1,
  refreshMode: 'remote-snapshot',
  counts: { tickers: 1, researched: 1, stubs: 0, reports: 0, convictionItems: 0, journalDays: 0 },
  actionBuckets: { wait_watch: 1 },
  categoryCounts: { Test: 1 },
  topTags: [['test', 1]],
  marketPosture: [],
  dailyJournal: [],
  sources: [{ name: 'Source', role: 'signal', summary: 'Summary', examples: [], howUsed: 'Carefully' }],
  tickers: [ticker],
  focusTickers: [ticker],
  privacy: { excluded: ['private'], note: 'Public only' },
}

describe('dashboard navigation and freshness', () => {
  it('keeps Daily brief first/default and Market outlook second without advertising stock research', () => {
    expect(dashboardTabs.slice(0, 2).map(tab => [tab.id, tab.label])).toEqual([
      ['market', 'Daily brief'],
      ['cio', 'Market outlook'],
    ])
    expect(dashboardTabs.map(tab => tab.id)).not.toContain('stocks')
    expect(dashboardTabs.map(tab => tab.label)).not.toContain('Stock research')
    expect(tabFromHash('')).toBe('market')
    expect(tabFromHash('#market')).toBe('market')
    expect(tabFromHash('#cio')).toBe('cio')
    expect(tabFromHash('#projections')).toBe('strategy')
    expect(tabFromHash('#not-a-page')).toBe('market')
  })

  it('uses the public snapshot timestamp when generatedAt is not projected', () => {
    expect(dashboardFreshnessTimestamp({ dataAsOf: '2026-09-03T02:23:08Z' })).toBe('2026-09-03T02:23:08Z')
    expect(dashboardFreshnessTimestamp({ generatedAt: '2026-09-01T10:00:00Z', dataAsOf: '2026-09-02T10:00:00Z', sourceMaxAsOf: '2026-09-03T10:00:00Z' })).toBe('2026-09-03T10:00:00Z')
  })
})

describe('asymmetric entry discipline', () => {
  const base = {
    bucket: 'Buy / Scout Now', actionMode: 'Scout', capitalEligible: true,
    entryEligible: true, entryStatus: 'inside_zone', capitalPriority: 2,
  }

  it('shows only names inside the ideal entry band that pass every capital gate', () => {
    const rows = actionableEntryRows([
      { ...base, symbol: 'GOOD' },
      { ...base, symbol: 'CHASE', capitalPriority: 1, entryEligible: false, entryStatus: 'above_zone' },
      { ...base, symbol: 'KNIFE', entryEligible: false, entryStatus: 'below_zone' },
      { ...base, symbol: 'STALE', capitalEligible: false },
      { ...base, symbol: 'WAIT', bucket: 'Wait for Trigger', actionMode: 'Wait' },
    ])

    expect(rows.map(row => row.symbol)).toEqual(['GOOD'])
  })
})

describe('dashboard production validator', () => {
  it('accepts the complete core structure', () => {
    expect(isDashboardData(valid)).toBe(true)
  })

  it.each([
    ['wrong schema', { ...valid, schemaVersion: 2 }],
    ['malformed counts', { ...valid, counts: { ...valid.counts, tickers: '1' } }],
    ['malformed ticker', { ...valid, tickers: [{ symbol: 'TEST' }] }],
    ['malformed source', { ...valid, sources: [{ name: 'Source' }] }],
    ['malformed privacy', { ...valid, privacy: { excluded: 'private', note: 'unsafe' } }],
    ['malformed tag tuple', { ...valid, topTags: [['test', 'one']] }],
  ])('rejects %s', (_label, candidate) => {
    expect(isDashboardData(candidate)).toBe(false)
  })
})

describe('canonical macro regime surface', () => {
  it('selects only the canonical posture card', () => {
    const card = {
      name: 'Canonical regime', sourcePath: 'data/automation/macro_regime_snapshot_latest.json',
      score: 58, zone: 'Broadening · selective risk-on', plainTitle: 'More stocks are working, but stay selective',
      plainEnglish: 'Small new positions are okay. Wait for stronger proof before adding size.', watch: ['Main risk: the flow of money into markets is becoming less supportive'],
    }
    expect(findCanonicalRegimePosture([card])).toEqual(card)
    expect(findCanonicalRegimePosture([{ ...card, name: 'Macro Regime' }])).toBeUndefined()
    expect(regimeStanceLabel(card)).toBe('SELECTIVE')
  })
})

describe('growth versus valuation bubble sizing', () => {
  it('uses bounded deterministic radii while preserving enterprise-value ordering', () => {
    const values = [100_000_000, 10_000_000_000, 5_000_000_000_000]
    const radii = values.map(value => bubbleRadiusForEnterpriseValue(value, values))
    expect(radii[0]).toBe(5)
    expect(radii[2]).toBe(28)
    expect(radii[1]).toBeGreaterThan(radii[0])
    expect(radii[1]).toBeLessThan(radii[2])
    expect(bubbleRadiusForEnterpriseValue(null, values)).toBe(5)
  })

  it('keeps a readable deterministic focus window and separates extreme outliers', () => {
    expect(isRelativeValueFocusPoint(25, 8)).toBe(true)
    expect(isRelativeValueFocusPoint(-50, 60)).toBe(true)
    expect(isRelativeValueFocusPoint(251, 8)).toBe(false)
    expect(isRelativeValueFocusPoint(25, 61)).toBe(false)
  })

  it('labels the top 10 robust two-dimensional outliers deterministically', () => {
    const centers = Array.from({ length: 12 }, (_, index) => ({ symbol: `CENTER_${index}`, x: index - 6, y: (index % 3) - 1 }))
    const extremes = [
      { symbol: 'X_POS', x: 1000, y: 0 },
      { symbol: 'X_NEG', x: -900, y: 0 },
      { symbol: 'Y_POS', x: 0, y: 800 },
      { symbol: 'Y_NEG', x: 0, y: -700 },
      { symbol: 'NE', x: 600, y: 600 },
      { symbol: 'SW', x: -500, y: -500 },
      { symbol: 'SE', x: 400, y: -400 },
      { symbol: 'NW', x: -300, y: 300 },
      { symbol: 'X_MID', x: 250, y: 0 },
      { symbol: 'Y_MID', x: 0, y: -200 },
    ]
    const selected = topOutlierLabelSymbols([...centers, ...extremes], 10)
    expect(selected).toHaveLength(10)
    expect(new Set(selected)).toEqual(new Set(extremes.map(point => point.symbol)))
    expect(topOutlierLabelSymbols([...centers, ...extremes], 10)).toEqual(selected)
  })
})

describe('workflow ops runtime transport state', () => {
  const manifestNode = { id: 'runtime_manifest', label: 'Runtime manifest', kind: 'transport', status: 'configured' }

  it('distinguishes verified publications from fallback without claiming live quotes', () => {
    expect(operationalNodeState(manifestNode, 'remote-live')).toMatchObject({ status: 'pass', detail: 'Latest publication verified' })
    expect(operationalNodeState(manifestNode, 'last-known-good')).toMatchObject({ status: 'degraded', detail: 'Showing previous valid publication' })
    expect(operationalNodeState(manifestNode, 'bundled-fallback')).toMatchObject({ status: 'fail', detail: 'Latest publication unavailable' })
  })

  it('marks the currently rendered dashboard consumers as loaded', () => {
    const consumer = { id: 'workflow_ops', label: 'Workflow Ops', kind: 'consumer', status: 'configured' }
    expect(operationalNodeState(consumer, 'last-known-good')).toMatchObject({ status: 'pass', detail: 'Publication loaded' })
  })
})
