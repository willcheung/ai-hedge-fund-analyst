// SYNTHETIC regression inputs only; no research snapshot dependencies.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { startMarketDataRuntime, type MarketDataState, MARKET_DATA_POLL_MS } from './useMarketData'
import type { MarketDataLoad } from './marketDataClient'

type Data = { value: string }
const valid = (value: unknown): value is Data => !!value && typeof value === 'object' && typeof (value as Data).value === 'string'
const load = (value: string, source: MarketDataLoad<Data>['source']): MarketDataLoad<Data> => ({ data: { value }, source, detail: source })
const manifest = { schemaVersion: 1, snapshotId: 'sha256:test', snapshotPath: 'marketwiki/snapshots/test.json', objectSha256: 'test', byteLength: 10 }

class FakeDocument {
  visibilityState = 'visible'
  listener?: () => void
  addEventListener(_type: 'visibilitychange', listener: () => void) { this.listener = listener }
  removeEventListener(_type: 'visibilitychange', listener: () => void) { if (this.listener === listener) this.listener = undefined }
  setVisibility(state: 'visible' | 'hidden') { this.visibilityState = state; this.listener?.() }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

function harness(overrides: Partial<Parameters<typeof startMarketDataRuntime<Data>>[0]> = {}) {
  let state: MarketDataState<Data> = { data: null, mode: 'loading', detail: 'loading' }
  const applied: MarketDataState<Data>[] = []
  const documentRef = new FakeDocument()
  const options: Parameters<typeof startMarketDataRuntime<Data>>[0] = {
    validateData: valid,
    getState: () => state,
    applyState: next => { state = next; applied.push(next) },
    patchState: patch => { state = patch(state); applied.push(state) },
    loadLastKnownGoodFn: vi.fn(async () => null),
    loadBundledFn: vi.fn(async () => load('bundle', 'bundled')),
    loadRemoteFn: vi.fn(async () => null),
    documentRef,
    random: () => 0.5,
    ...overrides,
  }
  const runtime = startMarketDataRuntime(options)
  return { runtime, options, documentRef, applied, getState: () => state }
}

async function settle() {
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
}

afterEach(() => vi.restoreAllMocks())

describe('market data runtime', () => {
  it.each(['missing', 'corrupt'])('live mode never loads a leftover bundle with a %s cache, including remote failure and recovery', async cache => {
    const remote = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(load('live', 'remote'))
    const h = harness({
      bundledOnly: false,
      loadLastKnownGoodFn: vi.fn(async () => {
        if (cache === 'corrupt') throw new Error('corrupt')
        return null
      }),
      loadRemoteFn: remote,
    })
    await settle()
    expect(h.getState().data).toBeNull()
    expect(h.getState().error).toBe('offline')
    expect(h.options.loadBundledFn).not.toHaveBeenCalled()
    await h.runtime.refresh()
    expect(h.getState().data).toEqual({ value: 'live' })
    expect(h.getState().error).toBeUndefined()
    expect(h.options.loadBundledFn).not.toHaveBeenCalled()
    h.runtime.dispose()
  })

  it('explicit staged mode bypasses remote manifests and cached live data on load and refresh', async () => {
    const remote = vi.fn(async () => { throw new Error('No manifest on static preview') })
    const cached = vi.fn(async () => load('live cached data', 'last-known-good'))
    const h = harness({ bundledOnly: true, loadRemoteFn: remote, loadLastKnownGoodFn: cached })
    await settle()
    await h.runtime.refresh()
    expect(h.getState().data).toEqual({ value: 'bundle' })
    expect(h.getState().error).toBeUndefined()
    expect(remote).not.toHaveBeenCalled()
    expect(cached).not.toHaveBeenCalled()
    h.runtime.dispose()
  })

  it('staged mode still surfaces real bundled data failures rather than hiding warnings', async () => {
    const h = harness({ bundledOnly: true, loadBundledFn: vi.fn(async () => { throw new Error('Staged data invalid') }) })
    await settle()
    await h.runtime.refresh()
    expect(h.getState().data).toBeNull()
    expect(h.getState().error).toBe('Staged data invalid')
    expect(h.options.loadRemoteFn).not.toHaveBeenCalled()
    h.runtime.dispose()
  })

  it('adopts a verified LKG before remote work and never flashes the bundle', async () => {
    const calls: string[] = []
    const pendingRemote = deferred<MarketDataLoad<Data> | null>()
    const h = harness({
      bundledOnly: false,
      loadLastKnownGoodFn: vi.fn(async () => { calls.push('lkg'); return { ...load('cached', 'last-known-good'), manifest } }),
      loadBundledFn: vi.fn(async () => { calls.push('bundle'); return load('bundle', 'bundled') }),
      loadRemoteFn: vi.fn(async () => { calls.push('remote'); return pendingRemote.promise }),
    })
    await settle()
    expect(calls).toEqual(['lkg', 'remote'])
    expect(h.applied[0]?.data).toEqual({ value: 'cached' })
    expect(h.options.loadBundledFn).not.toHaveBeenCalled()
    pendingRemote.resolve(null)
    await settle()
    expect(h.getState().mode).toBe('remote-live')
    expect(h.getState().detail).toBe('Live manifest verified; current snapshot unchanged')
    h.runtime.dispose()
  })

  it('falls back to the bundle when the cache is corrupt or unavailable', async () => {
    const h = harness({ loadLastKnownGoodFn: vi.fn(async () => { throw new Error('corrupt') }) })
    await settle()
    expect(h.applied[0]?.mode).toBe('bundled-fallback')
    expect(h.getState().data).toEqual({ value: 'bundle' })
    h.runtime.dispose()
  })

  it('aborts overlapping requests and ignores an older completion by token order', async () => {
    const requests: Array<{ signal: AbortSignal; deferred: ReturnType<typeof deferred<MarketDataLoad<Data> | null>> }> = []
    const remote = vi.fn((signal?: AbortSignal) => {
      const request = { signal: signal!, deferred: deferred<MarketDataLoad<Data> | null>() }
      requests.push(request)
      return request.deferred.promise
    })
    const h = harness({ loadRemoteFn: remote })
    await settle()
    expect(requests).toHaveLength(1)
    const secondRefresh = h.runtime.refresh()
    expect(requests[0].signal.aborted).toBe(true)
    expect(requests).toHaveLength(2)
    requests[0].deferred.resolve(load('old', 'remote'))
    requests[1].deferred.resolve(load('new', 'remote'))
    await secondRefresh
    await settle()
    expect(h.getState().data).toEqual({ value: 'new' })
    expect(h.applied.some(item => item.data?.value === 'old')).toBe(false)
    h.runtime.dispose()
  })

  it('aborts and stops scheduling while hidden, then refreshes immediately on recovery', async () => {
    const first = deferred<MarketDataLoad<Data> | null>()
    const second = deferred<MarketDataLoad<Data> | null>()
    let firstSignal: AbortSignal | undefined
    const remote = vi.fn()
      .mockImplementationOnce((signal?: AbortSignal) => { firstSignal = signal; return first.promise })
      .mockImplementationOnce(() => second.promise)
    const h = harness({ loadRemoteFn: remote })
    await settle()
    h.documentRef.setVisibility('hidden')
    expect(firstSignal?.aborted).toBe(true)
    expect(remote).toHaveBeenCalledTimes(1)
    h.documentRef.setVisibility('visible')
    expect(remote).toHaveBeenCalledTimes(2)
    second.resolve(null)
    await settle()
    h.runtime.dispose()
  })

  it('backs off after failure and resets to the normal poll interval after recovery', async () => {
    const delays: number[] = []
    const clearTimeoutFn = vi.fn()
    const setTimeoutFn = ((handler: TimerHandler, delay?: number) => {
      delays.push(Number(delay))
      return 1
    }) as typeof setTimeout
    const remote = vi.fn()
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(load('recovered', 'remote'))
    const h = harness({ loadRemoteFn: remote, setTimeoutFn, clearTimeoutFn })
    await settle()
    expect(delays).toEqual([MARKET_DATA_POLL_MS * 2])
    expect(h.getState().data).toEqual({ value: 'bundle' })
    expect(h.getState().error).toBe('offline')
    await h.runtime.refresh()
    expect(h.getState().data).toEqual({ value: 'recovered' })
    expect(h.getState().error).toBeUndefined()
    expect(delays).toEqual([MARKET_DATA_POLL_MS * 2, MARKET_DATA_POLL_MS])
    expect(clearTimeoutFn).toHaveBeenCalled()
    h.runtime.dispose()
  })
})
