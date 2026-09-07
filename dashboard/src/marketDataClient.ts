export const MARKET_DATA_MANIFEST_URL = import.meta.env.VITE_MARKETS_MANIFEST_URL || './market-data/manifest.json'
export const MARKET_DATA_MAX_BYTES = 6_000_000
export const MARKET_DATA_BLOB_ORIGIN = import.meta.env.VITE_MARKETS_BLOB_ORIGIN || ''
export const LAST_KNOWN_GOOD_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000
const CACHE_NAME = 'marketwiki-data-v2'
const CACHE_KEY = '/market-data/last-known-good.json'
const LKG_ENVELOPE_HEADER = 'x-marketwiki-lkg-envelope'
let manifestRequestSequence = 0

export type MarketDataManifest = {
  schemaVersion: number
  snapshotId: string
  snapshotPath: string
  snapshotUrl?: string
  objectSha256: string
  byteLength: number
  builtAt?: string
  publishedAt?: string
  sourceMaxAsOf?: string
  previousSnapshotId?: string | null
  sourceHealth?: Record<string, unknown>
}

type LastKnownGoodEnvelope = {
  schemaVersion: 1
  cachedAt: string
  manifest: MarketDataManifest
}

export type MarketDataLoad<T> = {
  data: T
  manifest?: MarketDataManifest
  source: 'remote' | 'last-known-good' | 'bundled'
  detail: string
}

export class MarketDataError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'MarketDataError'
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isJsonContentType(response: Response): boolean {
  const mime = response.headers.get('content-type')?.split(';', 1)[0].trim().toLowerCase() ?? ''
  return mime === 'application/json' || (mime.startsWith('application/') && mime.endsWith('+json'))
}

function requireJsonResponse(response: Response, label: string): void {
  if (!response.ok) throw new MarketDataError(`${label} fetch failed: ${response.status}`)
  if (!isJsonContentType(response)) throw new MarketDataError(`${label} response is not JSON`)
}

export function validateManifest(value: unknown): MarketDataManifest {
  if (!isObject(value)) throw new MarketDataError('Manifest must be an object')
  const hash = typeof value.objectSha256 === 'string' ? value.objectSha256.toLowerCase() : ''
  const snapshotId = typeof value.snapshotId === 'string' ? value.snapshotId.toLowerCase() : ''
  const snapshotPath = typeof value.snapshotPath === 'string' ? value.snapshotPath : ''
  if (value.schemaVersion !== 1) throw new MarketDataError('Unsupported manifest schema')
  if (!/^[a-f0-9]{64}$/.test(hash)) throw new MarketDataError('Invalid manifest object hash')
  if (snapshotId !== `sha256:${hash}`) throw new MarketDataError('Manifest snapshot ID/hash mismatch')
  if (snapshotPath !== `marketwiki/snapshots/${hash}.json`) throw new MarketDataError('Manifest snapshot path is outside the fixed prefix')
  if (!Number.isInteger(value.byteLength) || Number(value.byteLength) <= 0 || Number(value.byteLength) > MARKET_DATA_MAX_BYTES) {
    throw new MarketDataError('Manifest byte length is invalid')
  }
  if (typeof value.snapshotUrl !== 'string') throw new MarketDataError('Manifest snapshot URL is required')
  let snapshotUrl: URL
  try {
    snapshotUrl = new URL(value.snapshotUrl)
  } catch {
    throw new MarketDataError('Manifest snapshot URL is invalid')
  }
  const expectedUrl = `${MARKET_DATA_BLOB_ORIGIN}/${snapshotPath}`
  if (snapshotUrl.href !== expectedUrl) throw new MarketDataError('Manifest snapshot URL does not match the configured Blob origin and path')
  return { ...value, objectSha256: hash, snapshotId } as MarketDataManifest
}

export function snapshotRoute(manifest: MarketDataManifest): string {
  return `/market-data/${manifest.snapshotPath.slice('marketwiki/'.length)}`
}

export async function sha256Hex(bytes: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('')
}

async function readBoundedBytes(response: Response, label: string): Promise<ArrayBuffer> {
  const declaredHeader = response.headers.get('content-length')
  if (declaredHeader !== null) {
    const declaredLength = Number(declaredHeader)
    if (!Number.isSafeInteger(declaredLength) || declaredLength < 0) throw new MarketDataError(`${label} has an invalid Content-Length`)
    if (declaredLength > MARKET_DATA_MAX_BYTES) {
      await response.body?.cancel().catch(() => undefined)
      throw new MarketDataError(`${label} exceeds the browser size budget`)
    }
  }
  if (!response.body) throw new MarketDataError(`${label} response has no body`)
  const reader = response.body.getReader()
  const chunks: Uint8Array[] = []
  let total = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      if (!value) continue
      total += value.byteLength
      if (total > MARKET_DATA_MAX_BYTES) {
        await reader.cancel('size limit exceeded').catch(() => undefined)
        throw new MarketDataError(`${label} exceeds the browser size budget`)
      }
      chunks.push(value)
    }
  } catch (error) {
    await reader.cancel().catch(() => undefined)
    throw error
  }
  const bytes = new Uint8Array(total)
  let offset = 0
  for (const chunk of chunks) {
    bytes.set(chunk, offset)
    offset += chunk.byteLength
  }
  return bytes.buffer
}

function decodeJson(bytes: ArrayBuffer, label: string): unknown {
  try {
    return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)) as unknown
  } catch {
    throw new MarketDataError(`${label} contains invalid JSON`)
  }
}

async function parseJsonResponse(response: Response, label: string): Promise<unknown> {
  requireJsonResponse(response, label)
  return decodeJson(await readBoundedBytes(response, label), label)
}

export async function loadBundled<T>(
  signal?: AbortSignal,
  validateData: (value: unknown) => value is T = ((value: unknown): value is T => isObject(value)) as (value: unknown) => value is T,
): Promise<MarketDataLoad<T>> {
  const response = await fetch('./wiki-data.json', { signal, cache: 'no-store', headers: { Accept: 'application/json' } })
  const data = await parseJsonResponse(response, 'Bundled snapshot')
  if (!validateData(data)) throw new MarketDataError('Bundled snapshot schema validation failed')
  return { data, source: 'bundled', detail: 'Bundled fallback; may be stale' }
}

async function discardCachedResponse(cache: Cache): Promise<null> {
  await cache.delete(CACHE_KEY).catch(() => false)
  return null
}

export async function loadLastKnownGood<T>(
  validateData: (value: unknown) => value is T = ((value: unknown): value is T => isObject(value)) as (value: unknown) => value is T,
  now = Date.now(),
): Promise<MarketDataLoad<T> | null> {
  if (!('caches' in globalThis)) return null
  const cache = await caches.open(CACHE_NAME)
  const response = await cache.match(CACHE_KEY)
  if (!response) return null
  try {
    if (!isJsonContentType(response)) return await discardCachedResponse(cache)
    const encoded = response.headers.get(LKG_ENVELOPE_HEADER)
    if (!encoded) return await discardCachedResponse(cache)
    const envelope = JSON.parse(decodeURIComponent(encoded)) as unknown
    if (!isObject(envelope) || envelope.schemaVersion !== 1 || typeof envelope.cachedAt !== 'string') return await discardCachedResponse(cache)
    const cachedAt = Date.parse(envelope.cachedAt)
    if (!Number.isFinite(cachedAt) || cachedAt > now || now - cachedAt > LAST_KNOWN_GOOD_MAX_AGE_MS) return await discardCachedResponse(cache)
    const manifest = validateManifest(envelope.manifest)
    const bytes = await readBoundedBytes(response, 'Cached snapshot')
    if (bytes.byteLength !== manifest.byteLength) return await discardCachedResponse(cache)
    if (await sha256Hex(bytes) !== manifest.objectSha256) return await discardCachedResponse(cache)
    const data = decodeJson(bytes, 'Cached snapshot')
    if (!validateData(data)) return await discardCachedResponse(cache)
    return { data, manifest, source: 'last-known-good', detail: 'Verified browser last-known-good snapshot' }
  } catch {
    return await discardCachedResponse(cache)
  }
}

async function persistLastKnownGood(bytes: ArrayBuffer, manifest: MarketDataManifest): Promise<void> {
  if (!('caches' in globalThis)) return
  const cache = await caches.open(CACHE_NAME)
  const envelope: LastKnownGoodEnvelope = { schemaVersion: 1, cachedAt: new Date().toISOString(), manifest }
  const headers = new Headers({
    'content-type': 'application/json',
    [LKG_ENVELOPE_HEADER]: encodeURIComponent(JSON.stringify(envelope)),
  })
  await cache.put(CACHE_KEY, new Response(bytes.slice(0), { status: 200, headers }))
}

function uniqueManifestUrl(): string {
  manifestRequestSequence += 1
  return `${MARKET_DATA_MANIFEST_URL}?request=${Date.now().toString(36)}-${manifestRequestSequence.toString(36)}`
}

export async function loadRemote<T>(
  signal?: AbortSignal,
  currentSnapshotId?: string,
  validateData: (value: unknown) => value is T = ((value: unknown): value is T => isObject(value)) as (value: unknown) => value is T,
): Promise<MarketDataLoad<T> | null> {
  const manifestResponse = await fetch(uniqueManifestUrl(), {
    signal,
    cache: 'no-store',
    headers: { Accept: 'application/json' },
  })
  const manifest = validateManifest(await parseJsonResponse(manifestResponse, 'Manifest'))
  if (manifest.snapshotId === currentSnapshotId) return null

  const snapshotResponse = await fetch(`${snapshotRoute(manifest)}?snapshot=${encodeURIComponent(manifest.snapshotId)}`, {
    signal,
    cache: 'force-cache',
    headers: { Accept: 'application/json' },
  })
  requireJsonResponse(snapshotResponse, 'Snapshot')
  const bytes = await readBoundedBytes(snapshotResponse, 'Snapshot')
  if (bytes.byteLength !== manifest.byteLength) throw new MarketDataError('Snapshot byte length does not match manifest')
  if (await sha256Hex(bytes) !== manifest.objectSha256) throw new MarketDataError('Snapshot hash verification failed')
  const value = decodeJson(bytes, 'Snapshot')
  if (!validateData(value)) throw new MarketDataError('Snapshot schema validation failed')
  await persistLastKnownGood(bytes, manifest)
  return { data: value, manifest, source: 'remote', detail: 'Live immutable snapshot' }
}
