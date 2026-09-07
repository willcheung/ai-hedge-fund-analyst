// SYNTHETIC regression inputs only; no research snapshot dependencies.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Chart } from 'chart.js'
import { graphGateLabel, operationalNodeState, ownerChartPalette, publicAssessmentLabel, publicSourceReference } from './App'

afterEach(() => vi.unstubAllGlobals())
describe('retained workspace presentation', () => {
  it('reports transport success without claiming live market data', () => {
    const node = { id: 'runtime_manifest', kind: 'transport', status: 'unknown' }
    expect(operationalNodeState(node, 'remote-live')).toEqual({ status: 'pass', detail: 'Latest publication verified' })
    expect(operationalNodeState(node, 'last-known-good').status).toBe('degraded')
    expect(operationalNodeState(node, 'bundled-fallback').status).toBe('fail')
    expect(graphGateLabel('pass')).toBe('Healthy')
    expect(graphGateLabel('degraded')).toBe('Update delayed')
    expect(graphGateLabel('fail')).toBe('Needs attention')
    expect(graphGateLabel('INTERNAL_NEW_STATE')).toBe('Status unavailable')
    expect(publicAssessmentLabel('INTERNAL_NEW_STATE')).toBe('Assessment unavailable')
  })
  it('does not disclose internal source locations or signed URL query strings', () => {
    for (const value of ['/root/wiki/source.md', 'tickers/SYNTHB.md', 'file:///root/job.json', 'https://user:password@example.com/log', undefined]) expect(publicSourceReference(value)).toBe('Source reference unavailable')
    expect(publicSourceReference('https://www.sec.gov/Archives/report?token=private')).toBe('www.sec.gov')
  })
  it.each(['light', 'dark'])('resolves canvas text, grid, tooltip, and legend from %s shared tokens without changing series', theme => {
    const tokens = theme === 'light' ? { foreground: '#18212b', muted: '#586473', surface: '#ffffff', border: '#d6d8d9' } : { foreground: '#e9edf2', muted: '#a7b1be', surface: '#191f27', border: '#353e4b' }
    vi.stubGlobal('document', { documentElement: {} })
    vi.stubGlobal('getComputedStyle', () => ({ getPropertyValue: (key: string) => tokens[key.replace('--markets-', '') as keyof typeof tokens] || '' }))
    expect(ownerChartPalette().text).toBe(tokens.foreground)
    const chart = { options: { scales: { x: { ticks: {}, grid: {}, title: {} }, y: { ticks: {}, grid: {}, title: {} } }, plugins: { tooltip: {}, legend: { labels: {} } } }, data: { datasets: [{ label: 'Price', data: [12, 15], backgroundColor: '#2457c5' }] } }
    const before = JSON.stringify(chart.data)
    const plugin = Chart.registry.getPlugin('owner-shared-theme')
    expect(plugin).toBeDefined()
    plugin?.beforeUpdate?.(chart as unknown as Chart, { mode: 'none', cancelable: true }, {})
    expect(chart.options.scales.x.ticks).toEqual({ color: tokens.muted })
    expect(chart.options.scales.y.grid).toEqual({ color: tokens.border })
    expect(chart.options.plugins.tooltip).toMatchObject({ backgroundColor: tokens.surface, titleColor: tokens.foreground, bodyColor: tokens.foreground })
    expect(chart.options.plugins.legend.labels).toEqual({ color: tokens.foreground })
    expect(JSON.stringify(chart.data)).toBe(before)
  })
})
