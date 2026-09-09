import {renderToStaticMarkup} from 'react-dom/server'
import {describe, expect, it} from 'vitest'
import {DailyBriefTimeline, type DashboardData} from './App'

// Producer-shaped metadata, with synthetic prose and a complete article tail.
const summary = '📋 MORNING BRIEFING — Tuesday, September 8, 2026'
const articleBody = `${summary}\n\n## Market setup\n\n- 🟡 Evidence pending\n- Ordinary market detail\n\n## Watch points\n\n${Array.from({length: 8}, (_, i) => `- Watch point ${i + 1}`).join('\n')}\n\n## Sources\n\n[Primary source](https://example.com/filing)\n\nFinal caveat: these observations remain uncertain.`
const item = {
  id: 'synthetic-edition', jobId: 'synthetic-publisher',
  category: 'Morning Market Briefing', jobName: '', runTime: '2026-09-08 12:11:31',
  summary, highlights: ['⚪ Synthetic premarket highlight'], articleBody,
}
const draw = (overrides: Partial<typeof item> = {}) => renderToStaticMarkup(
  <DailyBriefTimeline data={{tickers: [], cronTimeline: [{...item, ...overrides}]} as unknown as DashboardData}/>,
).match(/<article class="timeline-item"[\s\S]*?<\/article>/)![0]

describe('Morning Market Briefing inline article', () => {
  it.each([
    ['synthetic publisher', {}],
    ['explicit category without job', {jobId: '', category: 'Morning Market Briefing'}],
    ['explicit category with unknown job', {jobId: 'unknown-producer', category: 'Morning Market Briefing'}],
  ])('renders the complete body inline for %s', (_, overrides) => {
    const html = draw(overrides)
    expect(html).toContain('<section aria-label="Morning Market Briefing full article">')
    expect(html).not.toContain('<details')
    expect(html).not.toContain('Read full article')
    expect(html).toContain('Watch point 8')
    expect(html).toContain('Final caveat: these observations remain uncertain.')
    expect(html).toContain('href="https://example.com/filing"')
    expect(html.split(summary)).toHaveLength(2)
    expect(html).toContain('<li class="authored-list-marker">🟡 Evidence pending</li>')
    expect(html.split('🟡')).toHaveLength(2)
    expect(html).toContain('Synthetic premarket highlight')
    expect(html.split('⚪')).toHaveLength(2)
    expect(html).toContain('<aside><strong>2026-09-08</strong><time dateTime="2026-09-08T12:11:31Z">2026-09-08 8:11 AM EDT</time></aside>')
  })

  it('keeps a distinct summary and handles an absent body', () => {
    expect(draw({summary: 'Distinct overview.'})).toContain('Distinct overview.')
    const html = draw({articleBody: ''})
    expect(html).toContain(summary)
    expect(html).not.toContain('Morning Market Briefing full article')
    expect(html).not.toContain('<details')
  })

  it.each([
    {jobId: 'unknown-producer', category: 'Market brief / research ops'},
    {jobId: 'synthetic-publisher', category: 'Earnings / catalysts'},
  ])('preserves disclosure and summary for a nonmorning resolved category: %j', overrides => {
    const html = draw(overrides)
    expect(html).toContain('<details class="source-details"><summary>Read full article</summary>')
    expect(html).not.toContain('aria-label="Morning Market Briefing full article"')
    expect(html.split(summary)).toHaveLength(3)
    expect(html).toContain('Final caveat: these observations remain uncertain.')
  })
})
