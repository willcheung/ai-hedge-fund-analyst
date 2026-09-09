// SYNTHETIC regression inputs only; no research snapshot dependencies.
import { describe, expect, it } from 'vitest'
import html from '../index.html?raw'
import themeCss from './theme.css?raw'

function runInNewContext(script: string, context: Record<string, unknown>) {
  // Execute only the repository-owned initialization script with isolated browser doubles.
  new Function(...Object.keys(context), script)(...Object.values(context))
}
import { resolvePreference, resolveTheme, THEME_STORAGE_KEY } from './theme'

describe('Markets markdown headings', () => {
  it('overrides legacy heading colors with the current shell foreground token', () => {
    // Include h4/h5: legacy CSS gives these explicit pale colors of their own.
    expect(themeCss).toMatch(/\.markets-app \.markdown-output :is\(h3, h4, h5\)\s*\{\s*color:\s*var\(--markets-foreground\);\s*\}/)
  })
})

describe('theme preference', () => {
  it.each([null, undefined, '', 'auto', 'DARK', {}, 1])('defaults invalid preference %s to system', value => {
    expect(resolvePreference(value)).toBe('system')
  })
  it.each(['light', 'dark', 'system'] as const)('preserves explicit %s', value => {
    expect(resolvePreference(value)).toBe(value)
  })
  it('follows system only when system is selected', () => {
    expect(resolveTheme('system', true)).toBe('dark')
    expect(resolveTheme('system', false)).toBe('light')
    expect(resolveTheme('light', true)).toBe('light')
    expect(resolveTheme('dark', false)).toBe('dark')
  })
})

describe('prepaint theme script', () => {
  const script = html.match(/<script id="markets-theme-init">([\s\S]*?)<\/script>/)?.[1]
  it.each([
    [null, true, 'dark'], [null, false, 'light'], ['light', true, 'light'],
    ['dark', false, 'dark'], ['system', true, 'dark'], ['invalid', false, 'light'],
  ])('resolves saved %s and dark system %s before paint', (stored, dark, expected) => {
    expect(script).toBeTruthy()
    const root = { dataset: {} as Record<string, string>, style: {} as Record<string, string> }
    runInNewContext(script!, {
      document: { documentElement: root },
      localStorage: { getItem: (key: string) => { expect(key).toBe(THEME_STORAGE_KEY); return stored } },
      window: { matchMedia: () => ({ matches: dark }) },
    })
    expect(root.dataset.theme).toBe(expected)
    expect(root.style.colorScheme).toBe(expected)
  })
  it('survives blocked storage and unavailable matchMedia', () => {
    const root = { dataset: {}, style: {} }
    runInNewContext(script!, {
      document: { documentElement: root }, window: {},
      localStorage: { getItem: () => { throw new Error('blocked') } },
    })
    expect(root).toEqual({ dataset: { theme: 'light' }, style: { colorScheme: 'light' } })
  })
})
