// SYNTHETIC regression inputs only; no research snapshot dependencies.
import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { companyChartTarget, isDashboardData, isPublishedDashboard, publicAssessmentLabel, TradingViewChart } from './App'

vi.mock('./useMarketData', () => ({ useMarketData: vi.fn(), isStagedPreviewBuild: false }))

const legacy = {
  schemaVersion: 1, refreshMode: 'snapshot', counts: { tickers: 0, researched: 0, stubs: 0, reports: 0, convictionItems: 0, journalDays: 0 },
  actionBuckets: {}, categoryCounts: {}, topTags: [], marketPosture: [], dailyJournal: [], sources: [], tickers: [], focusTickers: [], privacy: { excluded: [], note: '' },
}
describe('publicly reachable research workspace', () => {
  it('rejects legacy cached snapshots without the publication contract', () => {
    expect(isDashboardData(legacy)).toBe(true)
    expect(isPublishedDashboard(legacy)).toBe(false)
    expect(isPublishedDashboard({ ...legacy, publications: [] })).toBe(true)
    expect(isPublishedDashboard({ ...legacy, publications: [{}] })).toBe(false)
  })
  it('uses only verified shared assessment labels, including in tooltip helpers', () => {
    expect(publicAssessmentLabel('OWNABLE')).toBe('Differentiated business thesis supported')
    expect(publicAssessmentLabel('Established business thesis')).toBe('Established business thesis')
    for (const value of ['WAIT_FOR_PROOF', 'NO_CHASE', 'unmapped_code', 'toString', undefined]) expect(publicAssessmentLabel(value)).toBe('Assessment unavailable')
  })
})
describe('company chart integration', () => {
  it('uses known exchange metadata, supports international symbols, and never guesses NASDAQ', () => {
    expect(companyChartTarget({ symbol: 'SYNTHA', exchange: 'NASDAQ' }).symbol).toBe('NASDAQ:SYNTHA')
    expect(companyChartTarget({ symbol: 'AIR', exchange: 'EURONEXT' }).symbol).toBe('EURONEXT:AIR')
    expect(companyChartTarget({ symbol: 'SYNTH.N', exchange: 'NYSE' }).symbol).toBe('NYSE:SYNTH.N')
    const unknown = companyChartTarget({ symbol: 'UNMAPPED' })
    expect(unknown.symbol).toBeNull()
    expect(unknown.url).toBe('https://www.tradingview.com/search/?query=UNMAPPED')
    expect(companyChartTarget({ symbol: 'SYNTHA', tradingViewSymbol: '<script>' }).symbol).toBeNull()
  })
  it('renders a real single-company chart and a bounded unsupported-symbol fallback', () => {
    const known = renderToStaticMarkup(<TradingViewChart symbol="SYNTHA" exchange="NASDAQ" />)
    expect(known).toContain('widgetembed/?symbol=NASDAQ%3ASYNTHA')
    expect(known).toContain('SYNTHA price history')
    expect(known).toContain('height:380px')
    const unknown = renderToStaticMarkup(<TradingViewChart symbol="UNMAPPED" />)
    expect(unknown).not.toContain('<iframe')
    expect(unknown).not.toContain('height:')
    expect(unknown).toContain('Chart unavailable')
    expect(unknown).toContain('search/?query=UNMAPPED')
  })
})
