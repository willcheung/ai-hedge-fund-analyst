// SYNTHETIC regression inputs only; no research snapshot dependencies.
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { WorkflowOps, opsStatus, graphStatus, sourceStatus, runtimeStatus, metric } from './WorkflowOps'
import type { DashboardData } from './App'

const data = (value: object = {}) => ({ sourceHealth: {}, marketGraphs: [], ...value }) as unknown as DashboardData

describe('Workflow Ops evidence boundaries', () => {
  it('never maps missing or sanitized status to pass or missing metrics to zero', () => {
    for (const value of [undefined, null, '', 'Assessment unavailable', 'configured']) expect(opsStatus(value)).toBe('unknown')
    for (const value of [undefined, null, NaN, -1, '0']) expect(metric(value)).toBe('Unknown')
    expect(metric(0)).toBe('0')
  })
  it('preserves failed, blocked and missing graph gates, including a blocked source under a pass gate', () => {
    expect(graphStatus({finalGate:'pass'})).toBe('unknown')
    expect(graphStatus({finalGate:'pass',graphNodes:[{kind:'source',status:'Assessment unavailable'}]})).toBe('unknown')
    expect(graphStatus({finalGate:'fail'})).toBe('fail')
    expect(graphStatus({finalGate:'missing'})).toBe('missing')
    expect(graphStatus({finalGate:'blocked'})).toBe('blocked')
    expect(graphStatus({finalGate:'pass',graphNodes:[{kind:'source',status:'pass',allowedIntoSynthesis:false}]})).toBe('blocked')
    expect(graphStatus({finalGate:'pass',graphNodes:[{kind:'source',status:'failed'}]})).toBe('fail')
  })
  it('surfaces source failures, validation failures and producer failure independently of aggregate pass', () => {
    expect(sourceStatus({status:'fail'})).toBe('fail')
    expect(sourceStatus({status:'pass',validation:'fail'})).toBe('fail')
    expect(sourceStatus({status:'pass',producer:{latestStatus:'error'}})).toBe('fail')
    expect(sourceStatus({})).toBe('unknown')
    expect(sourceStatus({status:'pass',dataAsOf:'2026-09-01T00:00:00Z',stalenessThresholdSeconds:60})).toBe('pass')
    expect(sourceStatus({status:'stale'})).toBe('stale')
    expect(opsStatus('paused')).toBe('paused')
    expect(sourceStatus({status:'degraded',producer:{latestStatus:'paused'}})).toBe('degraded')
  })
  it('distinguishes bundled staging, LKG, stale remote and live transport without asserting scheduler health', () => {
    expect(runtimeStatus('bundled-fallback',true).label).toBe('Bundled staged preview')
    expect(runtimeStatus('bundled-fallback').status).not.toBe('pass')
    expect(runtimeStatus('last-known-good').status).toBe('degraded')
    expect(runtimeStatus('remote-stale').status).toBe('degraded')
    expect(runtimeStatus('remote-live').label).toBe('Remote snapshot verified')
    expect(runtimeStatus('remote-live',false,'private fetch detail').status).toBe('degraded')
  })
  it('renders unavailable evidence explicitly and excludes stale consumer claims and private metadata', () => {
    const html=renderToStaticMarkup(<WorkflowOps data={data({sourceHealth:{sections:{tickers:{status:'fail',producer:{jobId:'secret-job',latestStatus:'error'}}}},marketGraphs:[{label:'Market research → CIO dashboard',finalGate:'missing',runId:'secret-run',workflowId:'secret-workflow',graphNodes:[{kind:'consumer',label:'CIO exceptions',reason:'/root/private/account'}]}]})} mode="bundled-fallback" isStagedPreview error="secret-error" />)
    expect(html).toContain('Bundled staged preview')
    expect(html).toContain('Missing')
    expect(html).toContain('Fail')
    expect(html).toContain('Timestamp unavailable')
    expect(html).toContain('Unknown')
    for(const text of ['CIO exceptions','→ CIO dashboard','secret-job','secret-run','secret-workflow','secret-error','/root/private','No priority alerts','0 source checks']) expect(html).not.toContain(text)
  })
  it('keeps the current consumers explicit and omits absent runtime metadata', () => {
    const html=renderToStaticMarkup(<WorkflowOps data={data()} mode="bundled-fallback" />)
    expect(html).toContain('Published run timeline')
    expect(html).toContain('Daily Brief timeline')
    expect(html).toContain('CIO supporting evidence')
    expect(html).toContain('Upstream publication adaptation')
    expect(html).not.toContain('Artifact timestamp')
    for (const label of ['Snapshot built', 'Edition published', 'Browser last checked']) expect(html).not.toContain(label)
  })
  it('shows source/run/publication timestamps separately without inferring a date-only clock', () => {
    const html=renderToStaticMarkup(<WorkflowOps data={data({dataAsOf:'2026-09-06',marketGraphs:[{label:'Earnings proof gate',finalGate:'degraded',generatedAt:'2026-09-04T23:20:02Z'}]})} mode="last-known-good" lastCheckedAt="2026-09-07T01:02:03Z" manifest={{publishedAt:'2026-09-06T04:05:06Z'} as never} />)
    expect(html).toContain('2026-09-04 23:20:02 UTC')
    expect(html).toContain('2026-09-06 04:05:06 UTC')
    expect(html).toContain('2026-09-07 01:02:03 UTC')
    expect(html).not.toContain('(date only)')
    expect(html).not.toContain('(timezone unspecified)')
    expect(html).not.toContain('2026-09-06 00:00:00')
  })
})
