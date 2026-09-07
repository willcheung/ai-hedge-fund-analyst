// SYNTHETIC regression inputs only; no research snapshot dependencies.
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  LAST_KNOWN_GOOD_MAX_AGE_MS,
  loadLastKnownGood,
  loadRemote,
  MARKET_DATA_BLOB_ORIGIN,
  MARKET_DATA_MAX_BYTES,
  sha256Hex,
  snapshotRoute,
  validateManifest,
} from './marketDataClient'

vi.hoisted(() => { vi.stubEnv('VITE_MARKETS_BLOB_ORIGIN', 'https://demo.invalid') })

const originalFetch = globalThis.fetch
const originalCaches = globalThis.caches
const jsonHeaders = { 'content-type': 'application/json' }

function manifestFor(hash: string, byteLength: number) {
  const snapshotPath = `marketwiki/snapshots/${hash}.json`
  return {
    schemaVersion: 1,
    snapshotId: `sha256:${hash}`,
    snapshotPath,
    snapshotUrl: `${MARKET_DATA_BLOB_ORIGIN}/${snapshotPath}`,
    objectSha256: hash,
    byteLength,
  }
}

afterEach(() => {
  globalThis.fetch = originalFetch
  Object.defineProperty(globalThis, 'caches', { value: originalCaches, configurable: true })
  vi.restoreAllMocks()
})

describe('market data contract', () => {
  it('accepts only the fixed snapshot prefix, configured origin, and matching ID/hash', () => {
    const hash = 'a'.repeat(64)
    const manifest = validateManifest(manifestFor(hash, 100))
    expect(snapshotRoute(manifest)).toBe(`/market-data/snapshots/${hash}.json`)
    expect(() => validateManifest({ ...manifest, snapshotPath: 'https://evil.example/payload.json' })).toThrow(/fixed prefix/)
    expect(() => validateManifest({ ...manifest, snapshotId: `sha256:${'b'.repeat(64)}` })).toThrow(/mismatch/)
    expect(() => validateManifest({ ...manifest, snapshotUrl: `https://attacker.public.blob.vercel-storage.com/${manifest.snapshotPath}` })).toThrow(/configured Blob origin/)
    expect(() => validateManifest({ ...manifest, snapshotUrl: undefined })).toThrow(/required/)
    expect(() => validateManifest({ ...manifest, byteLength: MARKET_DATA_MAX_BYTES + 1 })).toThrow(/byte length/)
  })

  it('uses a unique cache-busting same-origin URL for every manifest request', async () => {
    const hash = 'c'.repeat(64)
    const manifest = manifestFor(hash, 100)
    globalThis.fetch = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(manifest), { status: 200, headers: jsonHeaders }))
      .mockResolvedValueOnce(new Response(JSON.stringify(manifest), { status: 200, headers: jsonHeaders })) as typeof fetch
    await loadRemote(undefined, manifest.snapshotId)
    await loadRemote(undefined, manifest.snapshotId)
    const urls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.map(call => String(call[0]))
    expect(urls[0]).toMatch(/^\.\/market-data\/manifest\.json\?request=/)
    expect(urls[1]).toMatch(/^\.\/market-data\/manifest\.json\?request=/)
    expect(urls[0]).not.toBe(urls[1])
    for (const url of urls) {
      const resolved = new URL(url, 'https://demo.invalid/preview/')
      expect(resolved.origin).toBe('https://demo.invalid')
      expect(resolved.pathname).toBe('/preview/market-data/manifest.json')
      expect(resolved.searchParams.get('request')).toBeTruthy()
    }
  })

  it('verifies exact bytes before returning and persists a verifiable LKG envelope', async () => {
    const snapshot = new TextEncoder().encode('{"privacy":{"excluded":[],"note":"safe"},"sources":[],"tickers":[]}\n')
    const bytes = snapshot.buffer.slice(snapshot.byteOffset, snapshot.byteOffset + snapshot.byteLength)
    const hash = await sha256Hex(bytes)
    const manifest = manifestFor(hash, snapshot.byteLength)
    let cachedResponse: Response | undefined
    const cache = {
      put: vi.fn(async (_key: string, response: Response) => { cachedResponse = response.clone() }),
      match: vi.fn(async () => cachedResponse?.clone()),
      delete: vi.fn(async () => true),
    }
    Object.defineProperty(globalThis, 'caches', { value: { open: vi.fn().mockResolvedValue(cache) }, configurable: true })
    globalThis.fetch = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(manifest), { status: 200, headers: jsonHeaders }))
      .mockResolvedValueOnce(new Response(snapshot, { status: 200, headers: { ...jsonHeaders, 'content-length': String(snapshot.byteLength) } })) as typeof fetch

    const validator = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object'
    const loaded = await loadRemote<Record<string, unknown>>(undefined, undefined, validator)
    expect(loaded?.source).toBe('remote')
    expect(cache.put).toHaveBeenCalledOnce()
    expect((await loadLastKnownGood(validator))?.manifest?.snapshotId).toBe(manifest.snapshotId)
    expect(cache.delete).not.toHaveBeenCalled()
  })

  it('rejects non-JSON snapshot content before parsing or caching', async () => {
    const snapshot = new TextEncoder().encode('{}')
    const hash = await sha256Hex(snapshot.buffer)
    const cachePut = vi.fn()
    Object.defineProperty(globalThis, 'caches', { value: { open: vi.fn().mockResolvedValue({ put: cachePut }) }, configurable: true })
    globalThis.fetch = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(manifestFor(hash, snapshot.byteLength)), { status: 200, headers: jsonHeaders }))
      .mockResolvedValueOnce(new Response(snapshot, { status: 200, headers: { 'content-type': 'text/html' } })) as typeof fetch
    await expect(loadRemote()).rejects.toThrow(/not JSON/)
    expect(cachePut).not.toHaveBeenCalled()
  })

  it('cancels a streamed response immediately after crossing the hard 6MB cap despite dishonest length', async () => {
    const hash = 'd'.repeat(64)
    let cancelled = false
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new Uint8Array(3_500_000))
        controller.enqueue(new Uint8Array(2_500_001))
      },
      cancel() { cancelled = true },
    })
    globalThis.fetch = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(manifestFor(hash, MARKET_DATA_MAX_BYTES)), { status: 200, headers: jsonHeaders }))
      .mockResolvedValueOnce(new Response(stream, { status: 200, headers: { ...jsonHeaders, 'content-length': '10' } })) as typeof fetch
    await expect(loadRemote()).rejects.toThrow(/size budget/)
    expect(cancelled).toBe(true)
  })

  it('rejects and deletes corrupt, schema-invalid, and expired cached LKG entries', async () => {
    const snapshot = new TextEncoder().encode('{"valid":true}')
    const bytes = snapshot.buffer.slice(snapshot.byteOffset, snapshot.byteOffset + snapshot.byteLength)
    const hash = await sha256Hex(bytes)
    const manifest = manifestFor(hash, snapshot.byteLength)
    const now = Date.now()
    const envelope = (cachedAt: string) => encodeURIComponent(JSON.stringify({ schemaVersion: 1, cachedAt, manifest }))
    const responses = [
      new Response('{"tampered":true}', { headers: { ...jsonHeaders, 'x-marketwiki-lkg-envelope': envelope(new Date(now).toISOString()) } }),
      new Response(snapshot, { headers: { ...jsonHeaders, 'x-marketwiki-lkg-envelope': envelope(new Date(now).toISOString()) } }),
      new Response(snapshot, { headers: { ...jsonHeaders, 'x-marketwiki-lkg-envelope': envelope(new Date(now - LAST_KNOWN_GOOD_MAX_AGE_MS - 1).toISOString()) } }),
    ]
    const cache = { match: vi.fn(async () => responses.shift()), delete: vi.fn(async () => true) }
    Object.defineProperty(globalThis, 'caches', { value: { open: vi.fn().mockResolvedValue(cache) }, configurable: true })
    const validShape = (value: unknown): value is { valid: true } => !!value && typeof value === 'object' && (value as { valid?: unknown }).valid === true
    expect(await loadLastKnownGood(validShape, now)).toBeNull()
    const rejectsValidData = (_value: unknown): _value is { valid: true } => false
    expect(await loadLastKnownGood(rejectsValidData, now)).toBeNull()
    expect(await loadLastKnownGood(validShape, now)).toBeNull()
    expect(cache.delete).toHaveBeenCalledTimes(3)
  })

  it('rejects a byte-level hash mismatch without caching it', async () => {
    const snapshot = new TextEncoder().encode('{"tickers":[]}\n')
    const manifest = manifestFor('e'.repeat(64), snapshot.byteLength)
    const cachePut = vi.fn()
    Object.defineProperty(globalThis, 'caches', { value: { open: vi.fn().mockResolvedValue({ put: cachePut }) }, configurable: true })
    globalThis.fetch = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(manifest), { status: 200, headers: jsonHeaders }))
      .mockResolvedValueOnce(new Response(snapshot, { status: 200, headers: jsonHeaders })) as typeof fetch
    await expect(loadRemote()).rejects.toThrow(/hash verification failed/)
    expect(cachePut).not.toHaveBeenCalled()
  })
})
