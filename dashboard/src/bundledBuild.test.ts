import { afterEach, describe, expect, it, vi } from 'vitest'
import { resolveConfig } from 'vite'

afterEach(() => vi.unstubAllEnvs())

describe('bundled startup configuration', () => {
  it.each(['serve', 'build'] as const)('selects bundled data for %s without an env file or URL override', async command => {
    const config = await resolveConfig({ mode: 'bundled', envFile: false }, command)
    expect(config.define?.['import.meta.env.VITE_MARKETS_DATA_MODE']).toBe('"bundled"')
  })

  it('leaves the production data mode unforced', async () => {
    const config = await resolveConfig({ mode: 'production', envFile: false }, 'build')
    expect(config.define?.['import.meta.env.VITE_MARKETS_DATA_MODE']).toBeUndefined()
  })

  it('requires explicit endpoints for the live consumer', async () => {
    vi.stubEnv('VITE_MARKETS_MANIFEST_URL', '')
    vi.stubEnv('VITE_MARKETS_BLOB_ORIGIN', '')
    await expect(resolveConfig({ mode: 'live', envFile: false }, 'build')).rejects.toThrow('explicit manifest URL and Blob origin')
  })

  it('builds the live consumer separately without copying staged JSON', async () => {
    vi.stubEnv('VITE_MARKETS_MANIFEST_URL', 'https://example.com/manifest.json')
    vi.stubEnv('VITE_MARKETS_BLOB_ORIGIN', 'https://example.com')
    const config = await resolveConfig({ mode: 'live', envFile: false }, 'build')
    expect(config.define?.['import.meta.env.VITE_MARKETS_DATA_MODE']).toBe('"production"')
    expect(config.publicDir).toBe('')
    expect(config.build.outDir).toBe('dist/live')
    const assets = config.plugins.find(plugin => plugin.name === 'live-static-assets')!
    const emitFile = vi.fn()
    const hook = assets.generateBundle
    if (typeof hook !== 'function') throw new Error('Missing static asset hook')
    await (hook as Function).call({ emitFile })
    const names = emitFile.mock.calls.map(([asset]) => asset.fileName)
    expect(names).toContain('fonts/inter-latin-variable.woff2')
    expect(names).toContain('favicon.svg')
    expect(names.some(name => name.endsWith('.json'))).toBe(false)
  })
})
