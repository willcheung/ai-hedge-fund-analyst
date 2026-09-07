import { createContext, useCallback, useContext, useEffect, useId, useLayoutEffect, useMemo, useState, type ReactNode } from 'react'

// Keep the tiny synchronous index.html prepaint script in sync (tested).
export const THEME_STORAGE_KEY = 'markets-theme'
export type ThemePreference = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'
const SYSTEM_QUERY = '(prefers-color-scheme: dark)'

export function resolvePreference(value: unknown): ThemePreference {
  return value === 'light' || value === 'dark' || value === 'system' ? value : 'system'
}

export function resolveTheme(preference: ThemePreference, systemDark: boolean): ResolvedTheme {
  return preference === 'system' ? (systemDark ? 'dark' : 'light') : preference
}

function readPreference(): ThemePreference {
  try { return resolvePreference(window.localStorage.getItem(THEME_STORAGE_KEY)) }
  catch { return 'system' }
}

function systemIsDark(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(SYSTEM_QUERY).matches
}

type ThemeContextValue = {
  preference: ThemePreference
  resolvedTheme: ResolvedTheme
  setPreference: (preference: ThemePreference) => void
}
const ThemeContext = createContext<ThemeContextValue | null>(null)
const useClientLayoutEffect = typeof window === 'undefined' ? useEffect : useLayoutEffect

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, updatePreference] = useState<ThemePreference>(readPreference)
  const [systemDark, updateSystemDark] = useState(systemIsDark)
  const resolvedTheme = resolveTheme(preference, systemDark)
  const setPreference = useCallback((next: ThemePreference) => {
    const valid = resolvePreference(next)
    updatePreference(valid)
    // Storage may be unavailable in private browsing; the control still works.
    try { window.localStorage.setItem(THEME_STORAGE_KEY, valid) } catch { /* in-memory preference */ }
  }, [])

  useClientLayoutEffect(() => {
    document.documentElement.dataset.theme = resolvedTheme
    document.documentElement.style.colorScheme = resolvedTheme
  }, [resolvedTheme])

  useEffect(() => {
    const media = typeof window.matchMedia === 'function' ? window.matchMedia(SYSTEM_QUERY) : null
    const update = () => updateSystemDark(media?.matches ?? false)
    update()
    media?.addEventListener?.('change', update)
    // Support older embedded WebKit without modern MediaQueryList listeners.
    if (media && !media.addEventListener) media.addListener(update)
    const syncStorage = (event: StorageEvent) => {
      if (event.key === THEME_STORAGE_KEY || event.key === null) updatePreference(readPreference())
    }
    window.addEventListener('storage', syncStorage)
    return () => {
      media?.removeEventListener?.('change', update)
      if (media && !media.removeEventListener) media.removeListener(update)
      window.removeEventListener('storage', syncStorage)
    }
  }, [])

  const value = useMemo(() => ({ preference, resolvedTheme, setPreference }), [preference, resolvedTheme, setPreference])
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext)
  if (!context) throw new Error('useTheme must be used within ThemeProvider')
  return context
}

export function ThemeControl({ className = '' }: { className?: string }) {
  const { preference, setPreference } = useTheme()
  const id = useId()
  return <div className={`markets-theme-control ${className}`.trim()}>
    <label htmlFor={id}>Appearance</label>
    <select aria-label="Appearance" id={id} value={preference} onChange={event => setPreference(resolvePreference(event.target.value))}>
      <option value="light">Light</option>
      <option value="dark">Dark</option>
      <option value="system">System</option>
    </select>
  </div>
}
