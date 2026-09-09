// SYNTHETIC regression inputs only; no research snapshot dependencies.
import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { formatTimestamp, Quote } from './researchComponents'

describe('source timestamp precision', () => {
  it('preserves unzoned source wall-clock values without inventing an instant', () => {
    expect(formatTimestamp('2026-09-06 21:18:28')).toBe('2026-09-06 21:18:28')
    expect(formatTimestamp('2026-09-06T21:18:28')).toBe('2026-09-06T21:18:28')
    expect(formatTimestamp('2026-09-06T21:18:28Z')).toBe('2026-09-06 17:18:28 EDT')
    expect(formatTimestamp('2026-02-31 25:18:28')).toBe('Timestamp unavailable')
  })
  it('does not accept an unzoned source time as a trusted price instant', () => {
    const html=renderToStaticMarkup(<Quote quote={{symbol:'AAA',price:100,currency:'USD',asOf:'2026-09-06 21:18:28'}} trusted/>)
    expect(html).toContain('Timestamp unavailable')
    expect(html).not.toContain(' UTC')
  })
})
