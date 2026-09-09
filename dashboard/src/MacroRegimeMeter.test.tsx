// SYNTHETIC regression inputs only; no live snapshot dependencies.
import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MacroRegimeMeter, meterPosition, METER_ZONES } from './MacroRegimeMeter'
import { isMacroRegimeMeter } from './macroRegimeContract'
import { isDashboardData } from './App'
import snapshot from '../tests/fixtures/demo-dashboard.json'
import cases from '../tests/fixtures/meter-observation-cases.json'
import invalid from '../tests/fixtures/meter-invalid-cases.json'

describe('piecewise presentation preserves all six score bands', () => {
  it.each([1, 3, 4.5, 6, 7.5, 9, 10])('maps exact edge %s', score => {
    const index = [1, 3, 4.5, 6, 7.5, 9, 10].indexOf(score)
    expect(meterPosition(score)).toBeCloseTo(index * 100 / 6)
  })
  it.each(METER_ZONES)('keeps both decimal boundaries in $label', zone => {
    const index = METER_ZONES.indexOf(zone)
    const end = [2.9, 4.4, 5.9, 7.4, 8.9, 10][index]
    expect(meterPosition(zone.start)).toBeCloseTo(index * 100 / 6)
    expect(meterPosition(end)!).toBeGreaterThan(index * 100 / 6)
    expect(meterPosition(end)!).toBeLessThanOrEqual((index + 1) * 100 / 6)
  })
  it('is monotonic for every legal tenth, clamps endpoints and rejects nonfinite values', () => {
    for (let n = 11; n <= 100; n++) expect(meterPosition(n / 10)!).toBeGreaterThan(meterPosition((n - 1) / 10)!)
    expect(meterPosition(-5)).toBe(0)
    expect(meterPosition(20)).toBe(100)
    for (const value of [NaN, Infinity, -Infinity]) expect(meterPosition(value)).toBeNull()
  })
})

describe('producer-owned meter contract', () => {
  it.each(cases)('$name', example => {
    expect(isMacroRegimeMeter(example.value)).toBe(example.valid)
    expect(isDashboardData({ ...snapshot, macroRegimeMeter: example.value })).toBe(example.valid)
  })
  it.each(invalid)('rejects $name', mutation => {
    const value = structuredClone(snapshot.macroRegimeMeter)
    let target: any = value
    for (const key of mutation.path.slice(0, -1)) target = target[key]
    target[mutation.path[mutation.path.length - 1]] = mutation.value
    expect(isMacroRegimeMeter(value)).toBe(false)
    expect(isDashboardData({ ...snapshot, macroRegimeMeter: value })).toBe(false)
  })
  it('accepts the synthetic edition and rejects a malformed extension at transport validation', () => {
    expect(isMacroRegimeMeter(snapshot.macroRegimeMeter)).toBe(true)
    expect(isDashboardData(snapshot)).toBe(true)
    expect(isDashboardData({...snapshot, macroRegimeMeter: {score: 5.7}})).toBe(false)
  })
  it('renders accessible true score and collapsed methodology without changing the snapshot', () => {
    const before = JSON.stringify(snapshot)
    const meter = snapshot.macroRegimeMeter
    if (!isMacroRegimeMeter(meter)) throw new Error('Invalid public fixture')
    const html = renderToStaticMarkup(<MacroRegimeMeter meter={meter}/>)
    expect(html).toContain('role="meter"')
    expect(html).toContain(`aria-valuenow="${meter.score}"`)
    expect(html).toContain('How this is calculated</summary>')
    expect(html).not.toMatch(/<details[^>]*\sopen[\s=>]/)
    expect(html).not.toContain('Equal-width zones; true score ranges shown.')
    const descriptionId = html.match(/aria-describedby="([^"]+)"/)![1]
    expect(html).toContain(`class="macro-meter-sr-only" id="${descriptionId}">Six equal-width zones with different score ranges, listed below.`)
    expect(html).toContain(`style="--meter-position:${meterPosition(meter.score!)}%"`)
    expect(html).toContain('class="macro-meter-pointer"')
    expect(html).toContain('class="macro-meter-line"')
    expect(html).not.toContain('▼')
    expect(html).toContain(`Observation as of ${meter.asOf}`)
    expect(html).not.toMatch(/direction|confidence|Daily:|Weekly:|macro-meter-deltas|no compatible comparison/i)
    expect(html).not.toMatch(/\stitle=|role="tooltip"/)
    expect(html).not.toContain('Source status:')
    expect(html).not.toContain('Macro context only; not a trade or leverage recommendation.')
    const disclosure = html.split('</summary>')[1].split('</details>')[0].trim()
    expect(disclosure).toMatch(/^<table .*<\/table>$/)
    expect(disclosure).not.toMatch(/<(p|ul|li)\b/)
    expect(disclosure).toContain('aria-label="Macro regime pillars"')
    expect(disclosure.match(/scope="col"/g)).toHaveLength(4)
    for (const label of ['PILLAR', 'SCORE / 10', 'TREND', 'WEIGHT']) expect(disclosure).toContain(`>${label}</th>`)
    const rows = disclosure.split('<tbody>')[1].split('</tbody>')[0].match(/<tr>.*?<\/tr>/g)!
    expect(rows).toHaveLength(6)
    expect(disclosure).not.toMatch(/<tfoot|>total|>sum/i)
    expect(meter.pillars.map(p => p.score)).toEqual([5.5, null, 5.5, null, 5.5, null])
    expect(meter.pillars.map(p => p.weight)).toEqual([25, 20, 15, 15, 15, 10])
    rows.forEach((row, index) => {
      const pillar = meter.pillars[index]
      expect(row).toContain(`<th scope="row">${pillar.label.replace(/&/g, '&amp;')}</th>`)
      expect(row).toContain(pillar.score === null ? 'Score unavailable' : `<td>${pillar.score.toFixed(1)}</td>`)
      expect(row).toContain('<span aria-hidden="true">—</span><span class="macro-meter-sr-only">Trend unavailable</span>')
      expect(row).toContain(`<td>${pillar.weight}%</td>`)
    })
    expect(JSON.stringify(snapshot)).toBe(before)
  })
  it('leads with plain confirmed labels and retains true ranges', () => {
    const meter = structuredClone(snapshot.macroRegimeMeter)
    if (!isMacroRegimeMeter(meter)) throw new Error('Invalid public fixture')
    // Confirmed band can differ from the score band near a hysteresis boundary.
    meter.score = 6.1
    const html = renderToStaticMarkup(<MacroRegimeMeter meter={meter}/>)
    const outside = html.split('<details')[0]
    expect(outside).toContain('6.1 / 10</strong> · Neutral / Mixed')
    const labels = ['Bearish / Cash focus', 'Cautious', 'Neutral / Mixed', 'Mildly bullish', 'Bullish', 'Strongly bullish / Risk on']
    for (const label of labels) expect(outside).toContain(`<strong>${label}</strong>`)
    for (const zone of METER_ZONES) expect(outside).toContain(zone.range)
    expect(outside).not.toContain('margin')
    expect(outside).not.toContain(meter.postureInterpretation)
    expect(outside).not.toContain('<strong>Defensive</strong>')
    expect(html).not.toContain(meter.postureInterpretation)
  })
  it('retains the selective canonical identity when backend direction is unavailable', () => {
    const meter = structuredClone(snapshot.macroRegimeMeter)
    if (!isMacroRegimeMeter(meter)) throw new Error('Invalid public fixture')
    meter.score = 6.5
    meter.regimeBand = 'selective_risk_on'
    meter.regimeLabel = 'Selective risk on'
    meter.direction = 'unavailable'
    const html = renderToStaticMarkup(<MacroRegimeMeter meter={meter}/>)
    expect(html).toContain('6.5 / 10</strong> · Mildly bullish')
    expect(html).not.toMatch(/direction|confidence/i)
    expect(html).not.toContain('Score withheld')
    expect(html).not.toContain('Selectively bullish')
    expect(html.match(/Trend unavailable/g)).toHaveLength(6)
  })
  it.each(['improving', 'steady', 'deteriorating', 'unavailable'] as const)('never substitutes global %s direction for pillar trends', direction => {
    const meter = structuredClone(snapshot.macroRegimeMeter)
    if (!isMacroRegimeMeter(meter)) throw new Error('Invalid public fixture')
    meter.direction = direction
    const html = renderToStaticMarkup(<MacroRegimeMeter meter={meter}/>)
    expect(html).not.toMatch(/direction|confidence|\stitle=|role="tooltip"/i)
    const table = html.split('<tbody>')[1].split('</tbody>')[0]
    expect(table.match(/Trend unavailable/g)).toHaveLength(6)
    expect(table).not.toMatch(/↑|↓|→|↔|improving|steady|deteriorating|supportive|restrictive|mixed/)
  })
  it.each(cases.filter(example => example.valid))('keeps history and deltas backend-only for $name', example => {
    if (!isMacroRegimeMeter(example.value)) throw new Error('Invalid contract fixture')
    const before = JSON.stringify(example.value)
    const html = renderToStaticMarkup(<MacroRegimeMeter meter={example.value}/> )
    expect(html).not.toMatch(/direction|confidence|Daily:|Weekly:|macro-meter-deltas|no compatible comparison|\stitle=|role="tooltip"/i)
    expect(html).toContain(`Observation as of ${example.value.asOf ?? 'unavailable'}`)
    expect(JSON.stringify(example.value)).toBe(before)
  })
  it('does not draw a neutral marker for an absent meter', () => {
    const html = renderToStaticMarkup(<MacroRegimeMeter/>)
    expect(html).toContain('Score withheld')
    expect(html).not.toContain('role="meter"')
    expect(html.match(/scope="row"/g)).toHaveLength(6)
    expect(html.match(/Score unavailable/g)).toHaveLength(6)
    expect(html.match(/Trend unavailable/g)).toHaveLength(6)
    for (const weight of [25, 20, 15, 10]) expect(html).toContain(`<td>${weight}%</td>`)
  })
})
