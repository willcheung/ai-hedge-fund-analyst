// All market values and article examples in this file are synthetic.
import {renderToStaticMarkup as render} from 'react-dom/server'
import {describe, expect, it} from 'vitest'
import {Narrative, Quote, ResearchHeadline} from './researchComponents'
import {DailyBriefTimeline, ValuationDashboard, type DashboardData} from './App'
import {PercentChange} from './financialChange'
import {PublicationArticle} from './MarketsApp'
import type {Publication} from './publicationTypes'
import css from './theme.css?raw'

describe('shared financial change presentation', () => {
  it('formats structured changes to one decimal and gives flat and missing values neutral semantics', () => {
    expect(render(<PercentChange value={-1.234567}/>)).toContain('data-direction="negative">-1.2%</span>')
    expect(render(<PercentChange value={7.113464932293789}/>)).toContain('data-direction="positive">+7.1%</span>')
    expect(render(<PercentChange value={0}/>)).toContain('data-direction="neutral">0.0%</span>')
    expect(render(<PercentChange value={-0}/>)).toContain('data-direction="neutral">-0.0%</span>')
    for (const value of [null, undefined, NaN, Infinity, -Infinity]) {
      expect(render(<PercentChange value={value}/>)).toContain('data-direction="neutral">—</span>')
      expect(render(<PercentChange value={value} missing="•"/>)).toContain('data-direction="neutral">•</span>')
    }
  })
  it('keeps the Quote percentage formatter at two decimals', () => {
    const quote = {price: 100, currency: 'USD', asOf: '2000-01-02T16:00:00Z', change: {percent: 7.113464932293789, trusted: true, period: 'day' as const, asOf: '2000-01-02T16:00:00Z'}}
    expect(render(<Quote quote={quote}/>)).toContain('data-direction="positive">+7.11%</span>')
  })
  it('renders valuation changes independently of neutral margin levels', () => {
    const data = {tickers: [], aiProjectionExhibits: {rows: []}, aiWarRoomCompleteData: {rows: [{symbol: 'AAA', category: 'Semiconductor', companyName: 'Fixture', oneMonthChangePct: -1.2345, revenueGrowthPct: 2.3456, fcfMarginPct: -4.8}]}}
    const html = render(<ValuationDashboard data={data as unknown as DashboardData}/>)
    expect(html).toContain('data-direction="negative">-1.2%</span>')
    expect(html).toContain('data-direction="positive">+2.3%</span>')
    expect(html).toContain('>-4.8%</td>')
  })
  it('shares financial color tokens across themes', () => {
    for (const direction of ['positive', 'negative', 'neutral']) {
      expect(css).toContain(`.financial-change[data-direction='${direction}'] { color: var(--markets-${direction}); }`)
      expect(css.match(new RegExp(`--markets-${direction}:`, 'g'))).toHaveLength(2)
    }
  })
  it('projects the Morning Brief publication heading without removing its section body', () => {
    const item = {id: 'fixture', jobId: 'synthetic-morning', title: 'Morning Market Briefing', summary: '', sources: [], sections: [{heading: 'Market Setup', markdown: 'Snapshot 08:15 ET. Cash trading opens 09:30 ET. Material evidence −1.200%.'}]} as unknown as Publication
    const html = render(<PublicationArticle item={item} symbols={[]}/>)
    expect(html).not.toContain('Market Setup')
    expect(html).not.toContain('Cash trading opens')
    expect(html).toContain('Snapshot 08:15 ET.')
    expect(html).toContain('data-direction="negative">−1.200%</span>')
  })
  it('styles structured observed returns with one decimal', () => {
    const data = {tickers: [], currentAsymmetricShortlist: {decisionLearning: {outcomeCount: 1, recentOutcomes: [{symbol: 'AAA', returnPct: -1.2345}]}}}
    expect(render(<ValuationDashboard data={data as unknown as DashboardData}/>)).toContain('data-direction="negative">-1.2%</span>')
  })
  it.each([['+1.200%', 'positive'], ['-1.20%', 'negative'], ['−1.200%', 'negative'], ['+0.00%', 'neutral'], ['−0.000%', 'neutral']])('preserves %s with %s semantics', (text, direction) => {
    expect(render(<Narrative content={text}/>)).toContain(`data-direction="${direction}">${text}</span>`)
    expect(render(<ResearchHeadline content={text}/>)).toContain(`data-direction="${direction}">${text}</span>`)
  })
  it.each([['BTC up roughly 1.2%', 'positive'], ['semiconductors gained approximately 1.2%', 'positive'], ['BTC down about 1.20%', 'negative'], ['shares fell by 1.2%', 'negative'], ['shares declined 0.0%', 'neutral']])('recognizes %s', (text, direction) => {
    expect(render(<Narrative content={text}/>)).toContain(`data-direction="${direction}"`)
  })
  it.each(['yield 4.806%, margin 12%, weight 3%', '1-2%', '1%–2%', '+1% to +2%', 'between +1% and +2%', '**+1%** to **+2%**', 'down 1–2%', 'not up 1.2%', 'up to 1.2%', 'fell to 1.2%'])('does not infer direction from %s', content => {
    expect(render(<Narrative content={content}/>)).not.toContain('data-direction')
  })
  it('protects authored links, code, URLs and raw HTML from rewriting or execution', () => {
    const html = render(<Narrative content={'[+1.2%](https://example.com/a_(b)) `−2%`\n\n```\n+3%\n```\n\n<img src=x onerror=alert(1)> [bad](javascript:alert(1)) https://example.com/+4%'}/>)
    expect(html).not.toContain('data-direction')
    expect(html).toContain('href="https://example.com/a_(b)"')
    expect(html).not.toContain('href="javascript:')
    expect(html).not.toContain('<img')
  })
  it('uses the same semantics in markdown tables', () => {
    const html = render(<Narrative content={'| Change | Yield |\n| --- | --- |\n| −1.200% | 4.806% |'}/>)
    expect(html).toContain('data-direction="negative">−1.200%</span>')
    expect(html).toMatch(/<td[^>]*>4\.806%<\/td>/)
  })
  it('simplifies only routine morning intro copy and keeps body and exceptional clauses', () => {
    const articleBody = '## Market Setup\n\nSnapshot 08:15 ET. Cash trading opens 09:30 ET. Material takeaway: BTC up roughly 1.2%.\n\nCash trading opens 09:30 ET, but holiday hours apply.\n\n## Risks\n\nFinal evidence.'
    const html = render(<DailyBriefTimeline data={{tickers: [], cronTimeline: [{id: 'morning', jobId: 'synthetic-morning', category: 'Morning Market Briefing', runTime: '2000-01-02T12:15:00Z', summary: '', articleBody}]} as unknown as DashboardData}/>)
    expect(html).not.toContain('Market Setup')
    expect(html).not.toContain('Cash trading opens 09:30 ET. ')
    expect(html).toContain('Snapshot 08:15 ET.')
    expect(html).toContain('Material takeaway:')
    expect(html).toContain('Cash trading opens 09:30 ET, but holiday hours apply.')
    expect(html).toContain('Final evidence.')
    expect(html).toContain('data-direction="positive"')
  })
  it('protects legacy article tilde code fences and renders shared markdown tables', () => {
    const articleBody = '~~~\n−2.300%\n~~~\n\n| Change | Yield |\n| --- | --- |\n| +1.200% | 4.806% |'
    const data = {tickers: [], cronTimeline: [{id: 'fixture', jobId: 'synthetic-morning', category: 'Morning Market Briefing', runTime: '2000-01-02T12:15:00Z', summary: '', articleBody}]}
    const html = render(<DailyBriefTimeline data={data as unknown as DashboardData}/>)
    expect(html).not.toContain('data-direction="negative"')
    expect(html).toContain('<table>')
    expect(html).toContain('data-direction="positive">+1.200%</span>')
  })
})
