import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe('synthetic default network boundary', () => {
  it.each([undefined, '', 'bundled', 'unknown'])('defaults mode %s to bundled only', async mode => {
    vi.resetModules()
    vi.stubEnv('VITE_MARKETS_DATA_MODE', mode)
    expect((await import('./useMarketData')).isStagedPreviewBuild).toBe(true)
  })
  it('requires the explicit production mode to enable the remote runtime', async () => {
    vi.resetModules()
    vi.stubEnv('VITE_MARKETS_DATA_MODE', 'production')
    expect((await import('./useMarketData')).isStagedPreviewBuild).toBe(false)
  })
  it('loads bundled bytes from a relative URL only', async () => {
    const payload = { synthetic: true }
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify(payload), { headers: { 'content-type': 'application/json' } }))
    vi.stubGlobal('fetch', fetcher)
    const { loadBundled } = await import('./marketDataClient')
    await loadBundled(undefined, (v): v is typeof payload => !!v && (v as typeof payload).synthetic === true)
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(fetcher.mock.calls[0][0]).toBe('./wiki-data.json')
  })
  it('never embeds external charts in demo even when exchange metadata is available', async () => {
    vi.resetModules()
    vi.stubEnv('VITE_MARKETS_DATA_MODE', undefined)
    const { TradingViewChart, TradingViewSymbolOverview } = await import('./App')
    for (const node of [<TradingViewChart symbol="SYNTHA" exchange="NASDAQ" />, <TradingViewSymbolOverview symbols={[{ symbol: 'SYNTHA', exchange: 'NASDAQ' }]} />]) {
      const html = renderToStaticMarkup(node)
      expect(html).not.toContain('<iframe')
      expect(html).not.toContain('<script')
      expect(html).toContain('Chart unavailable')
    }
  })
})
