// SYNTHETIC regression inputs only; no research snapshot dependencies.
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { DailyBriefTimeline } from './App'

const item = { id: 'note', category: 'Market brief / deep dive', runTime: '2026-09-06T12:00:00Z', jobName: '$SYNTHB proof', summary: 'Short overview', highlights: ['First point'], sourcePath: 'daily/briefs/market_brief_deep_dive_2026-09-06.md' }
const draw = (extra: object) => renderToStaticMarkup(createElement(DailyBriefTimeline, { data: { tickers: [], counts: { journalDays: 1 }, cronTimeline: [{ ...item, ...extra }] } as never }))

describe('Market Brief full article', () => {
  it('preserves legacy cards without an empty expander', () => {
    const html = draw({})
    expect(html).toContain('Short overview')
    expect(html).toContain('First point')
    expect(html).not.toContain('Read full article')
  })

  it('renders the complete article, sixth name, provenance and caveat in a native expander', () => {
    const body = '# $SYNTHB evidence\n\nHistorical note dated September 4; not current advice.\n\n## Key points\n' + Array.from({ length: 6 }, (_, i) => `- $SYNTHB evidence item ${i + 1}`).join('\n') + '\n\n## Sources\n- [Primary filing](https://example.com/filing)\n- https://example.com/SYNTHB\n\nFinal caveat after the summary and bullet limit.'
    const html = draw({ articleBody: body })
    expect(html).toContain('<details class="source-details"><summary>Read full article</summary>')
    expect(html).not.toContain(item.sourcePath)
    expect(html).toContain('Source reference unavailable')
    expect(html).toContain('evidence item 6')
    expect(html).toContain('Historical note dated September 4; not current advice.')
    expect(html).toContain('Final caveat after the summary and bullet limit.')
    expect(html).toContain('href="https://example.com/filing"')
    expect(html).toContain('https://example.com/SYNTHB')
    expect(html).not.toContain('$$SYNTHB')
  })
})
