import { useId, type CSSProperties } from 'react'
import type { MacroRegimeMeterData } from './macroRegimeContract'
import './macroRegimeMeter.css'

export const METER_ZONES = [
  { start: 1, range: '1.0–2.9', band: 'risk_off', label: 'Bearish / Cash focus', technical: 'Risk off' },
  { start: 3, range: '3.0–4.4', band: 'defensive', label: 'Cautious', technical: 'Defensive' },
  { start: 4.5, range: '4.5–5.9', band: 'neutral_mixed', label: 'Neutral / Mixed', technical: 'Neutral / mixed' },
  { start: 6, range: '6.0–7.4', band: 'selective_risk_on', label: 'Mildly bullish', technical: 'Selective risk on' },
  { start: 7.5, range: '7.5–8.9', band: 'constructive', label: 'Bullish', technical: 'Constructive' },
  { start: 9, range: '9.0–10.0', band: 'broad_risk_on', label: 'Strongly bullish / Risk on', technical: 'Broad risk on' },
] as const

// Canonical rows also remain visible in editions without a supplied meter.
const EMPTY_PILLARS = [
  { id: 'trend_breadth', label: 'Trend & breadth', weight: 25, score: null },
  { id: 'liquidity_financial_conditions', label: 'Liquidity & financial conditions', weight: 20, score: null },
  { id: 'credit', label: 'Credit', weight: 15, score: null },
  { id: 'growth_earnings', label: 'Growth & earnings', weight: 15, score: null },
  { id: 'inflation_policy', label: 'Inflation & policy', weight: 15, score: null },
  { id: 'volatility_positioning', label: 'Volatility & positioning', weight: 10, score: null },
] as const

function Unavailable({ label }: { label: string }) {
  return <><span aria-hidden="true">—</span><span className="macro-meter-sr-only">{label} unavailable</span></>
}

// Presentation only: each canonical band gets one sixth of the track. Scores
// have one decimal; transition edges are the next band's entry score.
export function meterPosition(score: number): number | null {
  if (!Number.isFinite(score)) return null
  const bounded = Math.min(10, Math.max(1, score))
  const index = METER_ZONES.reduce((found, zone, i) => bounded >= zone.start ? i : found, 0)
  const low = METER_ZONES[index].start
  const high = METER_ZONES[index + 1]?.start ?? 10
  return (index + (bounded - low) / (high - low)) * 100 / 6
}

export function MacroRegimeMeter({ meter }: { meter?: MacroRegimeMeterData }) {
  const id = useId()
  const score = meter?.score ?? null
  const position = score === null ? null : meterPosition(score)
  const confirmedLabel = METER_ZONES.find(zone => zone.band === meter?.regimeBand)?.label ?? meter?.regimeLabel ?? 'No meter in this edition'
  return <section className="macro-meter" aria-labelledby={`${id}-title`}>
    <header className="macro-meter-head"><div><h2 id={`${id}-title`}>Macro Regime Meter</h2>
      <p className="macro-meter-reading"><strong>{score === null ? 'Unavailable' : `${score.toFixed(1)} / 10`}</strong> · {confirmedLabel}</p></div>
      {meter && <p className="macro-meter-meta">Observation as of {meter.asOf ?? 'unavailable'}</p>}
    </header>
    {position !== null ? <>
      <div className="macro-meter-track" role="meter" aria-label="Macro regime score" aria-valuemin={1} aria-valuemax={10} aria-valuenow={score!} aria-valuetext={`${score!.toFixed(1)} out of 10; confirmed regime ${confirmedLabel}`} aria-describedby={`${id}-scale`}>
        <div className="macro-meter-colors" aria-hidden="true">{METER_ZONES.map(zone => <span key={zone.start} />)}</div>
        <span className="macro-meter-marker" style={{ '--meter-position': `${position}%` } as CSSProperties} aria-hidden="true"><span className="macro-meter-pointer" /><span className="macro-meter-line" /></span>
      </div>
      <ol className="macro-meter-labels">{METER_ZONES.map(zone => <li key={zone.start}><strong>{zone.label}</strong><span>{zone.range}</span></li>)}</ol>
    </> : <p role="status">Score withheld: {meter ? `eligible input weight ${meter.sourceHealth.eligibleWeight}%; at least 55% required.` : 'The snapshot does not supply the meter.'}</p>}
    <p className="macro-meter-sr-only" id={`${id}-scale`}>Six equal-width zones with different score ranges, listed below. The pointer is positioned proportionally within each zone.</p>
    <details className="macro-meter-method"><summary>How this is calculated</summary>
      <table className="macro-meter-pillars" aria-label="Macro regime pillars">
        <thead><tr><th scope="col">PILLAR</th><th scope="col">SCORE / 10</th><th scope="col">TREND</th><th scope="col">WEIGHT</th></tr></thead>
        <tbody>{(meter?.pillars ?? EMPTY_PILLARS).map(pillar => <tr key={pillar.id}>
          <th scope="row">{pillar.label}</th>
          <td>{pillar.score === null ? <Unavailable label="Score" /> : pillar.score.toFixed(1)}</td>
          {/* The contract supplies pillar stance, not per-pillar trend/history. */}
          <td><Unavailable label="Trend" /></td>
          <td>{pillar.weight}%</td>
        </tr>)}</tbody>
      </table>
    </details>
  </section>
}
