// SYNTHETIC regression inputs only; no live snapshot dependencies.
import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { DailyBriefTimeline, isDashboardData, type DashboardData } from './App'
import snapshot from '../tests/fixtures/demo-dashboard.json'

// Exercise the shared rendering boundary: restored headers must not replace the
// meter, re-collapse mapped macro/weekly prose, or turn AI prose into a ticker.
describe('meter and cosmetics integration', () => {
  it('renders both features with the synthetic meter without mutating data', () => {
    const data = { ...structuredClone(snapshot), tickers: [{ symbol: 'AI' }, { symbol: 'SYNTHB' }], cronTimeline: [
      { id: 'macro', jobId: 'synthetic-macro', category: 'Other research job', jobName: 'Research update', runTime: '2026-09-09', summary: 'AI infrastructure; $AI and SYNTHB.', highlights: [], articleBody: 'Observed: Original macro commentary.' },
      { id: 'weekly', jobId: 'synthetic-job-0c', category: 'Other research job', jobName: 'Research update', runTime: '2026-09-08', summary: 'Original weekly research.', highlights: [], articleBody: 'Original weekly evidence.' },
    ] } as unknown as DashboardData
    const before = JSON.stringify(data)
    const html = renderToStaticMarkup(<DailyBriefTimeline data={data}/>)
    expect(html.match(/class="macro-meter"/g)).toHaveLength(1)
    expect(html).toContain(`aria-valuenow="${snapshot.macroRegimeMeter.score}"`)
    expect(html.indexOf('class="macro-meter"')).toBeLessThan(html.indexOf('class="timeline-list"'))
    expect(html).toContain('SCORE / 10')
    expect(html).toContain('class="macro-meter-line"')
    expect(html.match(/<details\b[^>]*>/g)).toEqual(['<details class="macro-meter-method">'])
    expect(html.match(/class="eyebrow timeline-category"/g)).toHaveLength(2)
    expect(html).toContain('>Macro Read</span>')
    expect(html).toContain('>Weekly Stock Analysis</span>')
    expect(html).toContain('aria-label="Combined macro commentary"')
    expect(html).toContain('aria-label="Why selected this week"')
    expect(html).toContain('AI infrastructure;')
    expect(html).toContain('href="#research/AI">$AI</a>')
    expect(html).not.toContain('href="#research/AI">AI</a>')
    expect(html).not.toContain('<h3')
    expect(html).not.toContain('Research update')
    expect(html).not.toContain('Equal-width zones; true score ranges shown.')
    expect(JSON.stringify(data)).toBe(before)
  })
  it('keeps the synthetic snapshot valid and rejects a malformed supplied meter', () => {
    expect(isDashboardData(snapshot)).toBe(true)
    expect(isDashboardData({ ...snapshot, macroRegimeMeter: { ...snapshot.macroRegimeMeter, score: 11 } })).toBe(false)
  })
})
