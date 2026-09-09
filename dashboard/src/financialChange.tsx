import type {ReactNode} from 'react'

export type Direction = 'positive' | 'negative' | 'neutral'
export function changeDirection(value: number | null | undefined): Direction {
  return typeof value !== 'number' || !Number.isFinite(value) || value === 0 ? 'neutral' : value > 0 ? 'positive' : 'negative'
}
export function FinancialChange({children, direction}: {children: ReactNode; direction: Direction}) {
  return <span className="financial-change financial-value" data-direction={direction}>{children}</span>
}
/** Structured changes use one decimal; source-authored prose retains its precision. */
export function percentChangeText(value?: number | null, missing = '—'): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${value > 0 ? '+' : ''}${Object.is(value, -0) ? '-0.0' : value.toFixed(1)}%` : missing
}
export function PercentChange({value, missing = '—'}: {value?: number | null; missing?: string}) {
  return <FinancialChange direction={changeDirection(value)}>{percentChangeText(value, missing)}</FinancialChange>
}
type Part = {text: string; direction?: Direction; range?: boolean}
/** Only explicit signed percentages or adjacent, affirmative movement phrases.
 * Consume ranges whole so their endpoints cannot be mistaken for changes.
 * Protected markdown is removed by the caller before this plain-text scanner.
 */
export function financialParts(text: string): Part[] {
  const number = '[+−-]?(?:\\d+(?:\\.\\d+)?|\\.\\d+)'
  const between = `\\bbetween\\s+${number}\\s*%?\\s+and\\s+${number}\\s*%`
  const movement = '\\b(?:up|gained|rose|increased|down|fell|declined|dropped|lost|decreased)\\s+(?:(?:by|roughly|approximately|about|around)\\s+){0,2}'
  // Without a first percent unit, whitespace before an attached minus starts a
  // change ("500 -0.58%"); compact or spaced separators still form ranges.
  const rangeSeparator = '(?:\\s*%\\s*(?:[-−–—]|to)\\s*|[-−]\\s*|\\s+[-−]\\s+|\\s*(?:[–—]|to)\\s*)'
  const rangePattern = `${number}${rangeSeparator}${number}\\s*%`
  const pattern = new RegExp(`${between}|(?:${movement})?${rangePattern}|\\b(up|gained|rose|increased|down|fell|declined|dropped|lost|decreased)\\s+(?:(?:by|roughly|approximately|about|around)\\s+){0,2}(\\d+(?:\\.\\d+)?)\\s*%|[+−-](?:\\d+(?:\\.\\d+)?|\\.\\d+)\\s*%`, 'gi')
  const parts: Part[] = []
  let cursor = 0
  for (const match of text.matchAll(pattern)) {
    const start = match.index!, end = start + match[0].length
    const before = text.slice(0, start), after = text.slice(end)
    const boundary = !/[\p{L}\p{N}_.%+−-]$/u.test(before) && !/^[\p{L}\p{N}_%]/u.test(after)
    const range = /^between\b/i.test(match[0]) || new RegExp(`^(?:${movement})?${rangePattern}$`, 'i').test(match[0])
    // Opaque inline qualifiers cannot erase negation or supply movement context.
    const negated = /\b(?:not|never|hardly|no|without|(?:is|are|was|were|do|does|did|has|have|had|ca|could|would|should|wo)n['’]t)(?:[ \t]+(?:\$?\w+|\uFFFC)){0,2}[ \t]+$/i.test(before)
    if (start > cursor) parts.push({text: text.slice(cursor, start)})
    const value = match[1] ? Number(match[2]) * (/^(down|fell|declined|dropped|lost|decreased)$/i.test(match[1]) ? -1 : 1) : Number(match[0].replace('−', '-').replace(/\s*%$/, ''))
    parts.push({text: match[0], ...(range ? {range: true} : boundary && !negated ? {direction: changeDirection(value)} : {})})
    cursor = end
  }
  if (cursor < text.length) parts.push({text: text.slice(cursor)})
  return parts
}
