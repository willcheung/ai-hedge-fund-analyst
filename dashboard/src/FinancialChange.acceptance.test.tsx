// All market values and article examples in this file are synthetic.
import {renderToStaticMarkup as render} from 'react-dom/server'
import {describe, it, expect, vi} from 'vitest'
import {Narrative, ResearchHeadline} from './researchComponents'
import {PublicationArticle} from './MarketsApp'
import type {Publication} from './publicationTypes'
import {morningBriefProse} from './morningBriefPresentation'
import {DailyBriefTimeline, LatestMarketContextEvidence, ValuationDashboard, type DashboardData} from './App'

vi.mock('react-chartjs-2', () => ({
  Bubble: ({options}: any) => <div>{options.plugins.tooltip.callbacks.afterLabel({dataIndex: 0}).join(' | ')}</div>,
  Bar: () => null, Scatter: () => null, Line: () => null, Doughnut: () => null,
}))
for (const Renderer of [Narrative, ResearchHeadline]) for (const knownSymbols of [[], ['BTC', 'ETH']]) {
  describe(`${Renderer.name}, symbols=${knownSymbols.join(',')}`, () => {
    it.each(['BTC up roughly **1.2%**', 'semiconductors gained approximately **1.2%**'])('bold affirmative %s', content => {
      expect(render(<Renderer content={content} knownSymbols={knownSymbols}/>)).toContain('data-direction="positive">1.2%</span>')
    })
    it.each(['BTC not **up 1.2%**', 'BTC isn’t up 1.2%', "BTC can't be up 1.2%", "BTC won't be up 1.2%", "BTC isn't up 1.2%", "BTC wasn't up 1.2%", '**+1%** to **+2%**', 'up 1.2% to 2%', 'down 0.4%–0.8%'])('neutral %s', content => {
      expect(render(<Renderer content={content} knownSymbols={knownSymbols}/>)).not.toContain('data-direction')
    })
    it.each(['reports/market_setup_example.md', '[[market_setup_example]]'])('preserves the original source identifier %s', content => {
      const html = render(<Renderer content={content} knownSymbols={knownSymbols}/>)
      expect(html.replace(/<[^>]*>/g, '')).toBe(content)
      expect(html).not.toMatch(/<(?:em|a|span)\b/)
    })
    it.each([
      ['BTC not `currently` up 1.2%', '<code>currently</code>'],
      ['BTC not [currently](https://example.com) up 1.2%', '<a href="https://example.com" rel="noopener noreferrer">currently</a>'],
    ])('retains negation across the protected qualifier in %s', (content, qualifier) => {
      const html = render(<Renderer content={content} knownSymbols={knownSymbols}/>)
      expect(html).not.toContain('data-direction')
      expect(html).toContain(qualifier)
      expect(html).toContain(' up 1.2%')
    })
    it.each(['BTC up 1%, not ETH up 2%', 'BTC up 1%, not $ETH up 2%'])('retains negation across tickers: %s', content => {
      const html = render(<Renderer content={content} knownSymbols={knownSymbols}/> )
      expect(html.match(/data-direction/g)).toHaveLength(1)
      expect(html).toContain('up 2%')
    })
  })
}
it('retains bold synthetic snapshot while dropping the complete routine sentence', () => {
  expect(morningBriefProse('**Premarket snapshot: approximately 08:10–08:12 ET / 05:10–05:12 PT. Cash trading opens at 09:30 ET.**')).toBe('**Premarket snapshot: approximately 08:10–08:12 ET / 05:10–05:12 PT.**')
})
it.each([
  ['Cash trading opens at 09:30 ET.', ''],
  ['U.S. cash trading opens 09:30 ET.', ''],
  ['Snapshot 08:15 ET. Cash trading opens 09:30 ET.', 'Snapshot 08:15 ET. '],
  ['Snapshot 08:15 ET. Cash trading opens at 09:30 ET.\nMaterial evidence.', 'Snapshot 08:15 ET. \nMaterial evidence.'],
])('removes the plain EOL routine reminder in %s', (source, expected) => {
  expect(morningBriefProse(source)).toBe(expected)
})
it.each([
  '`Cash trading opens at 09:30 ET.`',
  '[Cash trading opens at 09:30 ET.](https://example.com)',
  '```text\nCash trading opens at 09:30 ET.\n```',
  '~~~text\nCash trading opens at 09:30 ET.\n~~~',
  'Cash trading opens at 09:30 ET; holiday hours apply.',
  'Holiday exception: Cash trading opens at 09:30 ET.',
])('preserves protected and exceptional EOL reminders in %s', source => {
  expect(morningBriefProse(source)).toBe(source)
})
it.each(['Holiday exception: U.S. cash trading opens 09:30 ET.', 'Example holiday: U.S. cash markets are closed.', 'Cash trading opens 09:30 ET, but holiday hours apply.', '````\n~~~\n## Market Setup\nCash trading opens 09:30 ET.\n````', '~~~~\n```\n## Market Setup\nCash trading opens 09:30 ET.\n~~~~'])('preserves exceptional or fenced text %s', text => {
  expect(morningBriefProse(text)).toBe(text)
})
it('renders actual chart strings and neutral Rule40 score, with directional 1M cells', () => {
  const row = {symbol: 'AAA', category: 'Semiconductor', companyName: 'Fixture', oneMonthChangePct: 1.2345, revenueGrowthPct: 28, fcfMarginPct: 12, enterpriseValue: 1000000000, evNtmRevenue: 5}
  const data = {tickers: [], aiProjectionExhibits: {rows: []}, aiWarRoomCompleteData: {rows: [row, {...row, symbol: 'BBB', revenueGrowthPct: 300}]}}
  const html = render(<ValuationDashboard data={data as unknown as DashboardData}/>)
  expect(html).toContain('FCF margin: 12%')
  expect(html.replace(/<[^>]*>/g, '')).toContain('$BBB (+300.0% / 5.00x)')
  expect(html).not.toContain('$&lt;PercentChange')
  expect(html).toMatch(/class="one-month-change"[^>]*><span[^>]*data-direction="positive">\+1.2%/)
  expect(html).not.toMatch(/<th[^>]*>[^<]*<span[^>]*data-direction/)
  const single = render(<ValuationDashboard data={{...data, aiWarRoomCompleteData: {rows: [row]}} as unknown as DashboardData}/>)
  expect(single).toMatch(/Median Rule 40<\/div><div class="metric-value">40<\/div>/)
})

for (const Renderer of [Narrative, ResearchHeadline]) {
  it.each([
    ['S&P 500 -0.58%', '-0.58%'],
    ['S&P **500** **-0.58%**', '-0.58%'],
    ['**S&P 500 -0.58%**', '-0.58%'],
    ['S&P 500\t−0.580%', '−0.580%'],
    ['Price $123.45 -0.58%', '-0.58%'],
    ['Price **$1,234.50** **−0.580%**', '−0.580%'],
  ])(`${Renderer.name} colors the negative change after a level: %s`, (content, delta) => {
    const html = render(<Renderer content={content}/>)
    expect(html).toContain(`data-direction="negative">${delta}</span>`)
    expect(html.match(/data-direction/g)).toHaveLength(1)
    expect(html.replace(/<[^>]*>/g, '').replace(/&amp;/g, '&')).toBe(content.replace(/\*\*/g, ''))
  })
  it.each(['1-2%', '1 - 2%', '1%–2%', '+7%-8%', '**1**-**2%**', '**1** - **2%**', '**1%**–**2%**', '**+7%**-**8%**', '**1 - 2%**'])(`${Renderer.name} keeps the range neutral: %s`, content => {
    const html = render(<Renderer content={content}/>)
    expect(html).not.toContain('data-direction')
    expect(html.replace(/<[^>]*>/g, '')).toBe(content.replace(/\*\*/g, ''))
  })
  it(`${Renderer.name} preserves precision and protected markup`, () => {
    const html = render(<Renderer knownSymbols={['BTC', 'ETH']} content={'BTC **+1.200%**, ETH **−2.300%**; yield 4.806%, margin 12%. [+9%](https://example.com/a_(b)) **`+8%`** <img src=x onerror=alert(1)> [bad](javascript:alert(1))'}/>)
    expect(html).toContain('data-direction="positive">+1.200%</span>')
    expect(html).toContain('data-direction="negative">−2.300%</span>')
    expect(html.match(/data-direction/g)).toHaveLength(2)
    expect(html).toContain('href="https://example.com/a_(b)"')
    expect(html).toContain('<code>+8%</code>')
    expect(html).not.toContain('<img')
    expect(html).not.toContain('href="javascript:')
  })
  it(`${Renderer.name} does not borrow movement context across code`, () => {
    expect(render(<Renderer content={'up `context` **1.2%**'}/>)).not.toContain('data-direction')
  })
}
it('does not trim literal fence content', () => {
  const source = '````\n~~~\nCash trading opens 09:30 ET.\ncontent ** \ncontent **\n````'
  expect(morningBriefProse(source)).toBe(source)
})
it('preserves the exact snapshot and Example holiday closure in both article paths', () => {
  const snapshot = 'Premarket snapshot: approximately 08:10–08:12 ET / 05:10–05:12 PT.'
  const markdown = `**${snapshot} Cash trading opens at 09:30 ET.**\n\nExample holiday: U.S. cash markets are closed.\n\nHoliday exception: U.S. cash trading opens 09:30 ET.`
  const item = {id: 'fixture', jobId: 'synthetic-morning', title: 'Morning Market Briefing', summary: '', sources: [], sections: [{heading: 'Market Setup', markdown}]} as unknown as Publication
  const data = {tickers: [], cronTimeline: [{id: 'fixture', jobId: 'synthetic-morning', category: 'Morning Market Briefing', runTime: '2000-01-03T12:07:00Z', summary: '', articleBody: '## Market Setup\n\n' + markdown}]}
  for (const html of [render(<PublicationArticle item={item} symbols={['BTC', 'ETH']}/>), render(<DailyBriefTimeline data={data as unknown as DashboardData}/>)]) {
    expect(html).toContain(`<strong>${snapshot}</strong>`)
    expect(html).not.toContain('Cash trading opens at')
    expect(html).toContain('Example holiday: U.S. cash markets are closed.')
    expect(html).toContain('Holiday exception: U.S. cash trading opens 09:30 ET.')
    expect(html).not.toContain('Market Setup')
  }
})
it.each(['Literal `Snapshot. Cash trading opens 09:30 ET. Keep literal.`', '[Snapshot. Cash trading opens 09:30 ET. Keep label.](https://example.com)'])('does not edit protected inline source %s', text => {
  expect(morningBriefProse(text)).toBe(text)
})

it.each(['Premarket AAA -0.25% BBB +0.05%', undefined])('renders market narrative heading %s through shared financial markup', title => {
  const data = {tickers: [{symbol: 'AAA'}, {symbol: 'BBB'}], dailyJournal: [{
    date: '2000-01-03', headline: 'Morning Market Briefing', items: [], keyTakeaways: [],
    marketNarrative: {title, bullets: ['AAA -0.25% BBB +0.05%']},
  }]} as unknown as DashboardData
  const html = render(<LatestMarketContextEvidence data={data} onSelectTicker={() => {}} />)
  const heading = html.match(/<h3>(.*?)<\/h3>/)![1]
  expect(heading.replace(/<[^>]*>/g, '')).toBe(title || 'What the tape is saying')
  if (title) {
    expect(heading).toContain('data-direction="negative">-0.25%</span>')
    expect(heading).toContain('data-direction="positive">+0.05%</span>')
    expect(heading).toContain('class="ticker">AAA</span>')
    expect(heading).toContain('class="ticker">BBB</span>')
  } else expect(heading).not.toContain('data-direction')
  const bullet = html.match(/<li[^>]*>(.*?)<\/li>/)![1]
  expect(bullet).toContain('data-direction="negative">-0.25%</span>')
  expect(bullet).toContain('data-direction="positive">+0.05%</span>')
})

it('renders all valuation outliers with signed changes, intact tickers and neutral multiples', () => {
  const base = {category: 'Semiconductor', enterpriseValue: 1000000000, fcfMarginPct: 12}
  const rows = [
    {...base, symbol: 'AAA', revenueGrowthPct: 28, evNtmRevenue: 5},
    {...base, symbol: 'CCC', revenueGrowthPct: 320.5, evNtmRevenue: 7.50},
    {...base, symbol: 'DDD', revenueGrowthPct: 610.2, evNtmRevenue: 15.5},
    {...base, symbol: 'EEE', revenueGrowthPct: -75.4, evNtmRevenue: 160.2},
  ]
  const data = {tickers: [], aiProjectionExhibits: {rows: []}, aiWarRoomCompleteData: {rows}} as unknown as DashboardData
  const html = render(<ValuationDashboard data={data}/>)
  const note = html.match(/<div class="chart-outlier-note">(.*?)<\/div>/)![1]
  expect(note.replace(/<[^>]*>/g, '')).toBe('3 extreme outliers outside focus window$CCC (+320.5% / 7.50x) · $DDD (+610.2% / 15.5x) · $EEE (-75.4% / 160.2x)Outliers remain visible in the sortable table above.')
  for (const change of ['+320.5%', '+610.2%']) expect(note).toContain(`data-direction="positive">${change}</span>`)
  expect(note).toContain('data-direction="negative">-75.4%</span>')
  expect(note.match(/data-direction/g)).toHaveLength(3)
  expect(html).not.toMatch(/\[object Object\]|&lt;(?:PercentChange|TickerAware|FinancialChange)/)
})
