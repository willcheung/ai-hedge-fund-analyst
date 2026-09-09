import { useEffect, useRef, useState } from 'react'
import { loadBundled, loadLastKnownGood, loadRemote, type MarketDataLoad, type MarketDataManifest } from './marketDataClient'

export type MarketDataMode = 'loading' | 'remote-live' | 'remote-stale' | 'last-known-good' | 'bundled-fallback'
export type MarketDataState<T> = {
  data: T | null
  mode: MarketDataMode
  detail: string
  manifest?: MarketDataManifest
  lastCheckedAt?: string
  error?: string
}

export const MARKET_DATA_POLL_MS = 120_000
export const MARKET_DATA_MAX_BACKOFF_MS = 600_000
const jitter = (base: number, random: () => number) => Math.round(base * (0.85 + random() * 0.30))

function manifestIsStale(manifest?: MarketDataManifest): boolean {
  if (!manifest?.sourceHealth || typeof manifest.sourceHealth !== 'object') return false
  const health = manifest.sourceHealth as Record<string, unknown>
  const overall = String(health.overall ?? health.status ?? '').toLowerCase()
  if (['degraded', 'fail', 'failed', 'stale'].includes(overall)) return true
  const sections = health.sections
  if (sections && typeof sections === 'object') {
    return Object.values(sections as Record<string, unknown>).some(section => {
      if (!section || typeof section !== 'object') return false
      const row = section as Record<string, unknown>
      return row.critical === true && ['degraded', 'fail', 'failed', 'stale'].includes(String(row.status ?? '').toLowerCase())
    })
  }
  return false
}

export function stateFromLoad<T>(load: MarketDataLoad<T>, now = () => new Date()): MarketDataState<T> {
  if (load.source === 'remote') {
    const stale = manifestIsStale(load.manifest)
    return {
      data: load.data,
      manifest: load.manifest,
      mode: stale ? 'remote-stale' : 'remote-live',
      detail: stale ? 'Remote snapshot loaded; one or more critical sections are stale or degraded' : load.detail,
      lastCheckedAt: now().toISOString(),
    }
  }
  return {
    data: load.data,
    manifest: load.manifest,
    mode: load.source === 'last-known-good' ? 'last-known-good' : 'bundled-fallback',
    detail: load.detail,
    lastCheckedAt: now().toISOString(),
  }
}

type VisibilityDocument = {
  visibilityState: string
  addEventListener(type: 'visibilitychange', listener: () => void): void
  removeEventListener(type: 'visibilitychange', listener: () => void): void
}

type RuntimeOptions<T> = {
  validateData: (value: unknown) => value is T
  /** True selects staged data; false permits only remote or validated cached data. */
  bundledOnly?: boolean
  getState: () => MarketDataState<T>
  applyState: (state: MarketDataState<T>) => void
  patchState: (patch: (state: MarketDataState<T>) => MarketDataState<T>) => void
  loadRemoteFn?: typeof loadRemote<T>
  loadLastKnownGoodFn?: typeof loadLastKnownGood<T>
  loadBundledFn?: typeof loadBundled<T>
  documentRef?: VisibilityDocument
  setTimeoutFn?: typeof setTimeout
  clearTimeoutFn?: typeof clearTimeout
  random?: () => number
  now?: () => Date
}

export type MarketDataRuntime = {
  refresh: () => Promise<void>
  dispose: () => void
}

/** Runtime is separated from React so request ordering, visibility and retry behavior are deterministic to test. */
export function startMarketDataRuntime<T>(options: RuntimeOptions<T>): MarketDataRuntime {
  const bundledLoader = options.loadBundledFn ?? loadBundled<T>
  const remoteLoader = options.bundledOnly
    ? (signal?: AbortSignal) => bundledLoader(signal, options.validateData)
    : options.loadRemoteFn ?? loadRemote<T>
  const lkgLoader = options.bundledOnly ? async () => null : options.loadLastKnownGoodFn ?? loadLastKnownGood<T>
  const documentRef = options.documentRef ?? document
  const setTimer = options.setTimeoutFn ?? setTimeout
  const clearTimer = options.clearTimeoutFn ?? clearTimeout
  const random = options.random ?? Math.random
  const now = options.now ?? (() => new Date())
  let disposed = false
  let timer: ReturnType<typeof setTimeout> | undefined
  let failures = 0
  let requestToken = 0
  let controller: AbortController | undefined

  const apply = (next: MarketDataState<T>) => {
    if (!disposed) options.applyState(next)
  }

  const schedule = () => {
    if (disposed || documentRef.visibilityState === 'hidden') return
    const delay = failures
      ? Math.min(MARKET_DATA_MAX_BACKOFF_MS, MARKET_DATA_POLL_MS * 2 ** Math.min(failures, 3))
      : MARKET_DATA_POLL_MS
    timer = setTimer(() => { void refresh() }, jitter(delay, random))
  }

  const refresh = async () => {
    if (disposed || documentRef.visibilityState === 'hidden') return
    if (timer) {
      clearTimer(timer)
      timer = undefined
    }
    controller?.abort()
    const token = ++requestToken
    const requestController = new AbortController()
    controller = requestController
    try {
      const currentId = options.getState().manifest?.snapshotId
      const load = await remoteLoader(requestController.signal, currentId, options.validateData)
      if (disposed || requestController.signal.aborted || token !== requestToken) return
      failures = 0
      if (load) apply(stateFromLoad(load, now))
      else options.patchState(previous => {
        const verifiedCurrent = previous.mode === 'last-known-good' && previous.manifest
        return {
          ...previous,
          mode: verifiedCurrent ? (manifestIsStale(previous.manifest) ? 'remote-stale' : 'remote-live') : previous.mode,
          detail: verifiedCurrent ? 'Live manifest verified; current snapshot unchanged' : previous.detail,
          lastCheckedAt: now().toISOString(),
          error: undefined,
        }
      })
    } catch (error) {
      if (disposed || requestController.signal.aborted || token !== requestToken) return
      failures += 1
      const message = error instanceof Error ? error.message : String(error)
      options.patchState(previous => ({ ...previous, lastCheckedAt: now().toISOString(), error: message }))
    } finally {
      if (!disposed && !requestController.signal.aborted && token === requestToken) schedule()
    }
  }

  const initialLoad = async () => {
    let hasFallback = false
    try {
      const lastKnownGood = await lkgLoader(options.validateData)
      if (!disposed && lastKnownGood) {
        apply(stateFromLoad(lastKnownGood, now))
        hasFallback = true
      }
    } catch {
      // A missing or corrupt cache may use a bundle only outside explicit live mode.
    }
    if (!hasFallback && !disposed && options.bundledOnly !== false) {
      try {
        const bundled = await bundledLoader(undefined, options.validateData)
        if (!disposed) apply(stateFromLoad(bundled, now))
      } catch (error) {
        if (!disposed) options.patchState(previous => ({ ...previous, error: error instanceof Error ? error.message : String(error) }))
      }
    }
    await refresh()
  }

  const onVisibility = () => {
    if (documentRef.visibilityState === 'hidden') {
      if (timer) {
        clearTimer(timer)
        timer = undefined
      }
      controller?.abort()
    } else {
      void refresh()
    }
  }

  documentRef.addEventListener('visibilitychange', onVisibility)
  void initialLoad()
  return {
    refresh,
    dispose: () => {
      disposed = true
      requestToken += 1
      if (timer) clearTimer(timer)
      controller?.abort()
      documentRef.removeEventListener('visibilitychange', onVisibility)
    },
  }
}

export function isLocalDataPreview(hostname: string, search: string): boolean {
  return ['localhost', '127.0.0.1', '[::1]', '::1'].includes(hostname) && new URLSearchParams(search).get('localData') === '1'
}

export const isStagedPreviewBuild = import.meta.env.VITE_MARKETS_DATA_MODE !== 'production'

export function useMarketData<T>(validateData: (value: unknown) => value is T): MarketDataState<T> {
  const [state, setState] = useState<MarketDataState<T>>({ data: null, mode: 'loading', detail: 'Loading market data…' })
  const latestRef = useRef<MarketDataState<T>>(state)
  useEffect(() => { latestRef.current = state }, [state])

  useEffect(() => {
    const localPreview = isLocalDataPreview(window.location.hostname, window.location.search)
    const runtime = startMarketDataRuntime({
      bundledOnly: isStagedPreviewBuild || localPreview,
      validateData,
      getState: () => latestRef.current,
      applyState: next => {
        latestRef.current = next
        setState(next)
      },
      patchState: patch => {
        setState(previous => {
          const next = patch(previous)
          latestRef.current = next
          return next
        })
      },
    })
    return runtime.dispose
  }, [validateData])

  return state
}
