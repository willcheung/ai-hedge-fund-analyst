// SYNTHETIC regression inputs only; no research snapshot dependencies.
import { describe, expect, it } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { DailyBriefTimeline, tabFromHash, tickerFromHash } from './App'

describe('Daily Brief without retired annotation feature', () => {
  it('renders the unchanged base even when an old snapshot contains feature data', () => {
    const data = { tickers: [], counts: { journalDays: 1 }, cronTimeline: [{ id: 'event', category: 'Earnings', runTime: '2026-09-05T12:00:00Z', jobName: 'Original job', summary: 'Original event', highlights: ['Original highlight'], articleBody: 'Original full research article.' }] }
    const draw = (extra: object) => renderToStaticMarkup(createElement(DailyBriefTimeline, { data: { ...data, ...extra } as never }))
    const base = draw({})
    expect(draw({ convictionChange: { status: 'initial', reason: 'RETIRED_SENTINEL', item: { now: 'RETIRED_SENTINEL' } } })).toBe(base)
    for (const text of ['timeline-list', 'Original event', 'Original full research article.']) expect(base).toContain(text)
    for (const text of ['daily-brief-metrics', 'Market lanes', 'Noise policy', 'conviction-change', 'Conviction change', 'No annotation supplied', 'RETIRED_SENTINEL']) expect(base).not.toContain(text)
  })

  it('retains generic literal ticker navigation and existing tab routes', () => {
    expect(tickerFromHash('#ticker/SYNTHL')).toBe('SYNTHL')
    expect(tickerFromHash('#ticker/SYNTH.N')).toBe('SYNTH.N')
    expect(tickerFromHash('#ticker/synthl')).toBe('')
    expect(tickerFromHash('#ticker/SYNTHL/invalid')).toBe('')
    expect(tabFromHash('#stocks')).toBe('stocks')
    expect(tabFromHash('#ticker/SYNTHL')).toBe('stocks')
    for (const tab of ['market', 'cio', 'stocks', 'strategy', 'ops', 'sources']) expect(tabFromHash(`#${tab}`)).toBe(tab)
    expect(tabFromHash('#projections')).toBe('strategy')
  })
})
