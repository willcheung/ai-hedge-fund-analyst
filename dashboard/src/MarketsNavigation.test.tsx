// SYNTHETIC regression inputs only; no research snapshot dependencies.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import MarketsApp, { ResearchDirectory } from './MarketsApp'
import { DailyBriefTimeline, LatestMarketContextEvidence, selectLatestMarketBriefDay, TradingViewSymbolOverview, type DashboardData } from './App'
import { ThemeProvider } from './theme'
import { publicRoute, type CompanyRow } from './publicationTypes'
import { siteConfig } from './siteConfig'
import bundled from '../tests/fixtures/demo-dashboard.json'

let dashboardData = bundled as unknown as DashboardData
vi.mock('./useMarketData', () => ({ useMarketData: () => ({ data: dashboardData, error: null }), isStagedPreviewBuild: true }))
afterEach(() => {
  vi.unstubAllGlobals()
  dashboardData = bundled as unknown as DashboardData
})
const renderRoute = (hash: string) => {
  vi.stubGlobal('window', { location: { hash } })
  return renderToStaticMarkup(<ThemeProvider><MarketsApp/></ThemeProvider>)
}
describe('restored public navigation', () => {
  it('keeps Daily Brief first and default, Conviction List second on the unchanged CIO route, and Valuation visible', () => {
    expect(siteConfig.navigation.slice(0, 3).map(n => n.label)).toEqual(['Daily Brief', 'Conviction List', 'Valuation'])
    for (const hash of ['', '#brief', '#market']) expect(publicRoute(hash).page).toBe('brief')
    expect(publicRoute('#cio').page).toBe('cio')
    expect(renderRoute('#cio')).toContain('<h1>Conviction List</h1>')
    for (const hash of ['#evaluation', '#strategy', '#projections', '#valuation']) expect(publicRoute(hash).page).toBe('evaluation')
    expect(publicRoute('#briefs').page).toBe('briefs')
  })
  it('omits Research and Themes from navigation while retaining their direct routes', () => {
    expect(siteConfig.navigation.map(n => n.label)).not.toContain('Research')
    expect(siteConfig.navigation.map(n => n.label)).not.toContain('Themes')
    const html = renderRoute('#brief')
    const nav = html.match(/<nav\b[^>]*aria-label="Main navigation"[\s\S]*?<\/nav>/)?.[0] || ''
    expect(nav).not.toBe('')
    expect(nav).not.toContain('href="#research"')
    expect(nav).not.toContain('href="#themes"')
    expect(renderRoute('#research')).toContain('aria-label="Research categories"')
    expect(publicRoute('#themes').page).toBe('themes')
    const item = bundled.publications.find(p => p.type === 'theme')!
    const article = renderRoute(`#themes/${encodeURIComponent(item.id)}`)
    expect(article).toContain(`data-publication-id="${item.id}"`)
    expect(article).toContain(item.title)
  })
  it('provides one mobile menu control and one shared navigation list', () => {
    const html=renderRoute('#cio')
    expect(html).toContain('id="markets-menu-toggle"')
    expect(html).toContain('aria-expanded="false"')
    expect(html).toContain('aria-controls="markets-navigation-panel"')
    expect(html).toContain('aria-label="Open navigation menu"')
    expect(html).toContain('id="markets-navigation-panel"')
    expect(html.match(/aria-label="Main navigation"/g)).toHaveLength(1)
  })
  it('describes ticker research as contextual in the workspace', () => {
    const html=renderRoute('#owner')
    expect(html).toContain('Ticker research opens contextually from ticker links.')
  })
  it('keeps the Conviction List concise and limited to the exact active source buckets', () => {
    const html=renderRoute('#cio')
    expect(html).not.toContain('cio-context-details')
    expect(html).not.toContain('membership-update-details')
    expect(html).not.toContain('class="cio-metrics"')
    expect(html).not.toContain('Market backdrop and entry checks')
    expect(html).not.toContain('Capital freshness')
    expect(html).not.toContain('Supporting evidence and sources')
    expect(html).not.toContain('Bridge: market brief → PM decisions')
    expect(html).not.toContain('class="bridge-grid"')
    expect(html).not.toContain('Selected theses classified as Buy / Scout Now or Add After Proof appear here')
    expect(html).not.toContain('Source updated')
    const headingOrder=['<h1>Conviction List</h1>','<h2>Current picks</h2>','<h3>How picks qualify</h3>']
    for(const heading of headingOrder) expect(html).toContain(heading)
    expect(headingOrder.map(heading=>html.indexOf(heading))).toEqual([...headingOrder.map(heading=>html.indexOf(heading))].sort((a,b)=>a-b))
    expect(html).not.toContain('What each pick status means')
    expect(html).not.toContain('aria-label="Pick status meanings"')
    expect([...html.matchAll(/data-top-pick-symbol="([^"]+)"/g)].map(match=>match[1])).toEqual([])
    expect(html).toContain('No qualified Conviction List theses')
  })
  it('selects the newest canonical market brief regardless of journal order instead of a newer weekly earnings preview', () => {
    const olderBrief: DashboardData['dailyJournal'][number] = {
      date: '2026-09-03', headline: 'Morning Market Briefing', summary: '',
      keyTakeaways: ['Older canonical evidence'], items: [], sourceTypes: [],
    }
    const newestBrief: DashboardData['dailyJournal'][number] = {
      date: '2026-09-04', headline: 'Daily research brief', summary: '',
      marketNarrative: { title: 'Canonical macro context', bullets: ['Regular session already open at capture'] },
      keyTakeaways: ['Newest canonical evidence'], interestingTickers: [{ symbol: 'TEST', why: 'Canonical brief signal' }],
      items: [{ title: 'Daily research brief', sourceType: 'Daily research brief', sourcePath: '', summary: '', highlights: [] }],
      sourceTypes: ['Daily research brief'],
    }
    const weeklyPreview: DashboardData['dailyJournal'][number] = {
      date: '2026-09-07', headline: 'Weekly Earnings Preview', summary: '',
      marketNarrative: { title: 'Weekly Earnings Preview', bullets: ['Q4 FY2026 consensus normalized EPS'] },
      keyTakeaways: ['Q4 FY2026 consensus normalized EPS'], items: [], sourceTypes: ['Weekly Earnings Preview'],
    }
    // The weekly entry is newer than both canonical briefs; neither input position
    // nor the first canonical match should determine the selected context.
    const journal = [weeklyPreview, olderBrief, newestBrief]
    const originalJournal = structuredClone(journal)
    dashboardData = { ...dashboardData, dailyJournal: journal }
    const html=renderRoute('#brief')
    const latest=selectLatestMarketBriefDay(journal)
    expect(html).toContain('<section class="markets-section latest-market-context">')
    const context=html.slice(html.indexOf('<section class="markets-section latest-market-context">'))
    expect(latest).toBe(newestBrief)
    expect(selectLatestMarketBriefDay([...journal].reverse())).toBe(newestBrief)
    expect(journal).toEqual(originalJournal)
    expect(latest).not.toBe(journal[0])
    expect(latest?.items.some(item=>item.sourceType==='Daily research brief')).toBe(true)
    expect(html).not.toContain('Recently updated research')
    expect(context).toContain('Market Brief context')
    expect(context).toContain('Macro narrative')
    expect(context).toContain('Brief evidence that matters')
    expect(context).toContain('$TEST')
    expect(context).toContain('Newest canonical evidence')
    expect(context).not.toContain('Older canonical evidence')
    expect(context).toContain('Regular session already open at capture')
    expect(context).not.toContain('Weekly Earnings Preview')
    expect(context).not.toContain('Q4 FY2026 consensus normalized EPS')
    expect(context).not.toContain('separate from the chronological Daily Brief')
    expect(html.indexOf('latest-market-context')).toBeGreaterThan(html.indexOf('timeline-list'))
    expect(html).not.toContain('Bridge: market brief → PM decisions')
    expect(html).not.toContain('class="bridge-grid"')
  })
  it('returns no market context day when the journal has no canonical brief and reaches the empty state', () => {
    const nonCanonical: DashboardData['dailyJournal'] = [{date:'2026-09-07',headline:'Weekly Earnings Preview',summary:'',keyTakeaways:[],items:[],sourceTypes:[]}]
    expect(selectLatestMarketBriefDay(nonCanonical)).toBeUndefined()
    const html=renderToStaticMarkup(<LatestMarketContextEvidence data={{dailyJournal:nonCanonical,tickers:[]} as unknown as DashboardData} onSelectTicker={()=>{}}/>)
    expect(html).toContain('Market context is not available in this edition.')
    expect(html).not.toContain('Weekly Earnings Preview')
  })
  it('returns no market context day for an empty journal', () => {
    expect(selectLatestMarketBriefDay([])).toBeUndefined()
  })
  it('renders latest market context only on the Daily Brief route', () => {
    expect(renderRoute('#brief').match(/latest-market-context/g)).toHaveLength(1)
    for (const hash of ['#briefs', `#briefs/${encodeURIComponent(bundled.publications.find(p=>p.type==='brief')!.id)}`, '#themes']) {
      expect(renderRoute(hash)).not.toContain('latest-market-context')
    }
  })
  it('restores standalone Workflow Ops with real source health and no owner shell', () => {
    expect(publicRoute('#ops').page).toBe('ops')
    expect(siteConfig.navigation.some(n=>n.id==='ops'&&n.label==='Workflow Ops')).toBe(true)
    const html=renderRoute('#ops')
    expect(html).toContain('id="workflow-ops-title"')
    expect(html).toContain('Bundled staged preview')
    expect(html).toContain('Source health')
    expect(html).not.toContain('markets-owner')
    expect(html.match(/<main\b/g)).toHaveLength(1)
  })
  it('removes decorative header cards and the research quote column, not data or charts', () => {
    for(const hash of ['#brief','#cio','#valuation']) {
      const html=renderRoute(hash)
      expect(html).not.toContain('daily-brief-hero')
      expect(html).not.toContain('cio-hero')
      expect(html).not.toContain('valuation-status-bar')
      expect(html).not.toContain('valuation-data-status')
      expect(html).not.toContain('(date only)')
      expect(html).not.toContain('(timezone unspecified)')
    }
    const html=renderRoute('#research')
    expect([...html.matchAll(/<th\b[^>]*>(.*?)<\/th>/g)].map(m=>m[1])).toEqual(['Company','Theme','Research stance','Latest research','Information updated'])
    expect(html).not.toContain('quote-unavailable')
    expect(renderRoute('#brief')).toContain('timeline-list')
    expect(renderRoute('#valuation')).toContain('strategy-table')
  })
  it('renders actual timeline updates by timestamp without mutating source order', () => {
    const item = { jobId: 'test', jobName: 'Test update', schedule: '', deliver: '', category: 'Earnings', sourcePath: '', highlights: [] }
    const timeline = [{ ...item, id: 'old', runTime: '2026-09-01T10:00:00Z', summary: 'OLDER_EVIDENCE' }, { ...item, id: 'new', runTime: '2026-09-02T10:00:00Z', summary: 'NEWER_EVIDENCE' }]
    const html = renderToStaticMarkup(<DailyBriefTimeline data={{ tickers: [], cronTimeline: timeline } as unknown as DashboardData}/>)
    expect(html.indexOf('NEWER_EVIDENCE')).toBeLessThan(html.indexOf('OLDER_EVIDENCE'))
    expect(timeline[0].id).toBe('old')
  })
  it('renders standalone restored views with one main navigation, not an owner shell', () => {
    for (const [hash, marker] of [['', 'timeline-list'], ['#cio', 'cio-page'], ['#strategy', 'valuation-page']]) {
      const html = renderRoute(hash)
      expect(html).toContain(marker)
      expect(html).not.toContain('dashboard-topbar')
      expect(html).toContain('SYNTHETIC DEMO · fictional data')
      expect(html.match(/<main\b/g)).toHaveLength(1)
    }
    expect(renderRoute('')).not.toContain('Browse all brief publications')
    expect(renderRoute('')).not.toContain('Chronological market updates, newest first.')
    expect(renderRoute('#briefs')).toContain('data-content-type="brief"')
  })
  it('places original overview chart above company evidence and keeps its source link', () => {
    const row = bundled.tickers[0]
    const html = renderRoute(`#research/${encodeURIComponent(row.symbol)}`)
    expect(html).not.toContain('<iframe')
    expect(html).toContain('Chart unavailable')
    expect(html.indexOf('tv-chart-card')).toBeLessThan(html.indexOf('markets-publication'))
    expect(html).not.toContain('widgetembed')
  })
  it('shares Company/Theme and uses meaningful Valuation actions without dropping financial metrics', () => {
    const headers=(html:string)=>[...html.matchAll(/<th\b[^>]*>(.*?)<\/th>/g)].map(m=>m[1].replace(/<[^>]+>/g,''))
    const research=headers(renderRoute('#research'))
    const valuation=headers(renderRoute('#valuation'))
    expect(research.slice(0,3)).toEqual(['Company','Theme','Research stance'])
    expect(valuation.slice(0,2)).toEqual(research.slice(0,2))
    expect(valuation).not.toContain('Research stance')
    expect(valuation).not.toContain('Research tier')
    expect(valuation).toEqual(['Company','Theme','Action','Proof','1M','Rev growth YoY','FCF margin','EV/NTM rev','Base case','Bull case','Next gate'])
    expect(renderRoute('#valuation')).toContain('<h1>Valuation</h1>')
    expect(renderRoute('#evaluation')).toContain('<h1>Valuation</h1>')
  })
  it('omits the four valuation summary cards while retaining the comparison table and evidence charts', () => {
    const html=renderRoute('#valuation')
    for(const label of ['AI rows plotted','Category colors','FCF margin rows','Freshness']) expect(html).not.toContain(`<div class="metric-label">${label}</div>`)
    expect(html).toContain('Financial and evidence charts')
    expect(html).toContain('AI company financials and evidence')
    expect(html).toContain('class="strategy-table ai-war-room-table display compact"')
  })
  it('offers an honest fallback for unmapped exchange symbols', () => {
    const html = renderToStaticMarkup(<TradingViewSymbolOverview symbols={[{ symbol: 'UNKNOWN' }]}/>)
    expect(html).toContain('Chart unavailable for this company')
    expect(html).toContain('Search TradingView for UNKNOWN')
  })
  it('limits category controls to high-level assignments with counts, never raw tags', () => {
    const rows = [{ symbol: 'AAA', title: 'Alpha', category: 'Hardware', tags: ['internal-tag'], summary: '', status: '', updated: '', actionBucket: '' }, { symbol: 'BBB', title: 'Beta', category: 'Hardware', tags: ['raw-tag'], summary: '', status: '', updated: '', actionBucket: '' }] satisfies CompanyRow[]
    const html = renderToStaticMarkup(<ResearchDirectory rows={rows} publications={[]} symbols={[]}/>)
    expect(html).toContain('markets-category-grid')
    expect(html).toContain('aria-pressed="true"')
    expect(html).toContain('Hardware <span>2</span>')
    expect(html).not.toContain('internal-tag')
    expect(html).not.toContain('raw-tag')
  })
})
