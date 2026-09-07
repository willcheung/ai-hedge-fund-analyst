// SYNTHETIC regression inputs only; no research snapshot dependencies.
import type { ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { sanitizeAnalyticsEvent } from './analytics'

const { analytics, render } = vi.hoisted(() => ({
  analytics: vi.fn((_props: { beforeSend: typeof sanitizeAnalyticsEvent }) => null),
  render: vi.fn(),
}))
vi.mock('@vercel/analytics/react', () => ({ Analytics: analytics }))
vi.mock('react-dom/client', () => ({ createRoot: () => ({ render }) }))
vi.mock('./MarketsApp', () => ({ default: () => <main>Dashboard</main> }))
vi.mock('./theme', () => ({ ThemeProvider: ({ children }: { children: ReactNode }) => children }))

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

describe('analytics URL privacy', () => {
  it.each([
    ['https://example.com/research?query=private#company/ABC', 'https://example.com/research'],
    ['https://example.com/?query=private', 'https://example.com/'],
    ['https://example.com/#valuation', 'https://example.com/'],
    ['https://example.com/public/path', 'https://example.com/public/path'],
  ])('sanitizes %s without mutating the event', (url, expected) => {
    const event = { type: 'pageview' as const, url }
    expect(sanitizeAnalyticsEvent(event)).toEqual({ type: 'pageview', url: expected })
    expect(event.url).toBe(url)
  })

  it.each(['not a URL', 'https://[invalid', 'javascript:alert(1)'])('drops unsafe URL %s without throwing', url => {
    expect(sanitizeAnalyticsEvent({ type: 'pageview', url })).toBeNull()
  })
})

describe('root analytics integration', () => {
  const cases = [true, false].flatMap(production =>
    [undefined, '', 'bundled', 'unknown', 'production'].flatMap(dataMode =>
      [undefined, '', 'false', 'TRUE', '1', 'true'].map(optIn => ({
        production, dataMode, optIn,
        count: production && dataMode === 'production' && optIn === 'true' ? 1 : 0,
      }))))
  it.each(cases)('production=$production, data mode=$dataMode, opt-in=$optIn mounts $count tracker(s)', async ({ production, dataMode, optIn, count }) => {
    vi.resetModules()
    vi.stubEnv('PROD', production)
    vi.stubEnv('VITE_ENABLE_ANALYTICS', optIn)
    vi.stubEnv('VITE_MARKETS_DATA_MODE', dataMode)
    vi.stubGlobal('document', { getElementById: () => ({}) })
    render.mockImplementation((node: ReactNode) => renderToStaticMarkup(node))

    await import('./main')

    expect(render).toHaveBeenCalledTimes(1)
    expect(render.mock.results[0].value).toBe('<main>Dashboard</main>')
    expect(analytics).toHaveBeenCalledTimes(count)
    if (count) {
      const props = analytics.mock.calls[0][0]
      expect(props.beforeSend({ type: 'pageview', url: 'https://example.com/?private=1#research' }))
        .toEqual({ type: 'pageview', url: 'https://example.com/' })
    }
  })
})
