// SYNTHETIC regression inputs only; no research snapshot dependencies.
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { dependencyTopology, WorkflowDependencyGraph } from './WorkflowDependencyGraph'
import { runtimeStatus } from './WorkflowOps'

const graph = () => ({label:'Earnings proof gate', generatedAt:'2026-09-04T23:20:02Z', graphNodes:[
  {id:'financials',kind:'source',status:'degraded',pipelineStale:true},
  {id:'checker',kind:'checker',status:'degraded'}, {id:'synthesis',kind:'synthesis',status:'degraded'},
  {id:'public-snapshot',kind:'publish',status:'pass'}, {id:'runtime-manifest',kind:'transport',status:'pass'},
  {id:'workflow-ops',kind:'consumer',status:'pass'},
],graphEdges:[{from:'financials',to:'checker',status:'degraded'}, {from:'checker',to:'synthesis',status:'degraded'}, {from:'synthesis',to:'public-snapshot'}, {from:'public-snapshot',to:'runtime-manifest'}, {from:'runtime-manifest',to:'workflow-ops'}]})

describe('public dependency diagrams', () => {
  it('uses exact edge endpoints, not order or display labels', () => {
    const g = graph(); g.graphNodes.reverse(); g.graphEdges.reverse()
    expect(dependencyTopology(g)?.edges).toHaveLength(5)
    const html=renderToStaticMarkup(<WorkflowDependencyGraph graph={g} mode="bundled-fallback" runtime={runtimeStatus('bundled-fallback',true)} isStagedPreview />)
    expect(html).toContain('data-from="financials" data-to="checker"')
    expect(html).toContain('data-from="runtime-manifest" data-to="workflow-ops"')
    expect(html).toContain('Recorded update delayed')
    expect(html).toContain('Not used by this bundled edition')
    expect(html).toContain('publisher health not verified')
    expect(html).not.toContain('Remote snapshot verified')
    expect(html).toContain('last-known-good is used only when a valid cached edition is available')
    expect((html.match(/data-node=/g)||[])).toHaveLength(6)
    expect((html.match(/data-from=/g)||[])).toHaveLength(5)
  })
  it('fails closed for blank, unknown, duplicate or dangling identities and unsupported edges', () => {
    for (const mutate of [
      (g:ReturnType<typeof graph>)=>{g.graphNodes[0].id=''},
      (g:ReturnType<typeof graph>)=>{g.graphNodes[0].id='/root/private'},
      (g:ReturnType<typeof graph>)=>{g.graphNodes.push(g.graphNodes[0])},
      (g:ReturnType<typeof graph>)=>{g.graphEdges[0].from='missing'},
      (g:ReturnType<typeof graph>)=>{g.graphEdges.push(g.graphEdges[0])},
      (g:ReturnType<typeof graph>)=>{g.graphEdges[0].to='workflow-ops'},
    ]) { const g=graph(); mutate(g); expect(dependencyTopology(g)).toBeNull() }
  })
  it('does not synthesize absent source edges', () => {
    const g=graph(); g.graphEdges.shift()
    expect(dependencyTopology(g)?.edges).toHaveLength(4)
    const html=renderToStaticMarkup(<WorkflowDependencyGraph graph={g} mode="last-known-good" runtime={runtimeStatus('last-known-good')}/>)
    expect(html).not.toContain('data-from="financials"')
    expect(html).toContain('Cached edition; latest remote not verified')
  })
  it('never renders untrusted labels, paths, reasons or IDs', () => {
    const g=graph(); Object.assign(g.graphNodes[0], {label:'/root/private',reason:'secret-run',outputPath:'private-file'})
    const html=renderToStaticMarkup(<WorkflowDependencyGraph graph={g} mode="remote-live" runtime={runtimeStatus('remote-live')}/>)
    for(const text of ['/root/private','secret-run','private-file','CIO exceptions']) expect(html).not.toContain(text)
    expect(html).toContain('Financials')
    expect(html).toContain('Remote snapshot verified')
  })
})
