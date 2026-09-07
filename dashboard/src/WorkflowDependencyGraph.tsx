import { useId } from 'react'
import { formatTimestamp } from './researchComponents'
import type { MarketDataMode } from './useMarketData'
import './workflowDependencyGraph.css'

type Row = Record<string, unknown>
type Node = Row & {id: string; kind: string; label: string}
type Edge = {from: string; to: string; status?: unknown}
const catalog: Record<string, [string, string]> = {
  'news-calendar': ['source', 'News Calendar'], 'x-signals': ['source', 'X Signals'],
  transcripts: ['source', 'Transcripts'], 'sec-insiders': ['source', 'SEC Insiders'],
  'macro-breadth': ['source', 'Macro Breadth'], 'ai-projection-exhibits': ['source', 'AI Projection Exhibits'],
  'upcoming-earnings': ['source', 'Upcoming Earnings'], preview: ['source', 'Preview'],
  'post-print-trigger': ['source', 'Post Print Trigger'], 'press-release-8k': ['source', 'Press Release 8K'],
  financials: ['source', 'Financials'], guidance: ['source', 'Guidance'],
  'call-transcript': ['source', 'Call Transcript'], 'price-volume': ['source', 'Price Volume'],
  'peer-readthrough': ['source', 'Peer Readthrough'], 'post-print-projection-update': ['source', 'Post Print Projection Update'],
  checker: ['checker', 'Checker gate'], synthesis: ['synthesis', 'Recorded synthesis'],
  'public-snapshot': ['publish', 'Public snapshot'], 'runtime-manifest': ['transport', 'Blob manifest'],
  'workflow-ops': ['consumer', 'Workflow Ops'],
}
const row = (v: unknown): Row => v && typeof v === 'object' && !Array.isArray(v) ? v as Row : {}
const status = (v: unknown) => typeof v === 'string' && ['pass', 'fail', 'failed', 'error', 'degraded', 'warning', 'pending', 'unknown', 'missing', 'blocked', 'stale', 'paused'].includes(v) ? v : 'unknown'

/** Draw only the public DTO's exact identities and edges. Never repair blanks. */
export function dependencyTopology(graph: Row): {nodes: Node[]; edges: Edge[]} | null {
  if (!Array.isArray(graph.graphNodes) || !Array.isArray(graph.graphEdges) || !graph.graphNodes.length) return null
  const nodes: Node[] = [], edges: Edge[] = [], ids = new Set<string>(), pairs = new Set<string>()
  for (const value of graph.graphNodes) {
    const n = row(value), id = n.id
    if (typeof id !== 'string' || !Object.prototype.hasOwnProperty.call(catalog, id) || ids.has(id) || n.kind !== catalog[id][0]) return null
    ids.add(id)
    nodes.push({...n, id, kind: catalog[id][0], label: catalog[id][1]})
  }
  for (const value of graph.graphEdges) {
    const e = row(value), a = e.from, b = e.to
    if (typeof a !== 'string' || typeof b !== 'string' || !ids.has(a) || !ids.has(b) || a === b || pairs.has(`${a}:${b}`)) return null
    // This visual encodes the known stage layout, not arbitrary cyclic graphs.
    const allowed = catalog[a][0] === 'source' && b === 'checker' ||
      a === 'checker' && b === 'synthesis' || a === 'synthesis' && b === 'public-snapshot' ||
      a === 'public-snapshot' && b === 'runtime-manifest' || a === 'runtime-manifest' && b === 'workflow-ops'
    if (!allowed) return null
    pairs.add(`${a}:${b}`)
    edges.push({from: a, to: b, status: e.status})
  }
  return {nodes, edges}
}

type Props = {graph: Row; mode: MarketDataMode; isStagedPreview?: boolean; runtime: {status: string; label: string; detail: string}}
export function WorkflowDependencyGraph({graph, mode, isStagedPreview = false, runtime}: Props) {
  const marker = `dependency-arrow-${useId().replace(/[^a-zA-Z0-9]/g, '')}`
  const topology = dependencyTopology(graph)
  const name = graph.label === 'Earnings proof gate' ? 'Earnings proof gate' : graph.label === 'Market research checks' || graph.label === 'Market research → CIO dashboard' ? 'Market research checks' : 'Recorded workflow'
  if (!topology) return <article className="ops-workflow-card workflow-dependency-card"><h3>{name}</h3><p className="markets-notice">Dependency diagram unavailable: public node identities or edges are incomplete. Recorded status remains available in the checks table.</p></article>
  const {nodes, edges} = topology
  const sources = nodes.filter(n => n.kind === 'source')
  const height = Math.max(410, sources.length * 86 + 48)
  const center = height / 2
  const positions: Record<string, {x: number; y: number}> = {}
  sources.forEach((n, i) => { positions[n.id] = {x: 16, y: 42 + i * 86} })
  const corePositions: Record<string, {x: number; y: number}> = {
    checker: {x: 330, y: center - 128}, synthesis: {x: 330, y: center + 32},
    'public-snapshot': {x: 645, y: center - 128}, 'runtime-manifest': {x: 645, y: center + 32},
    'workflow-ops': {x: 960, y: center - 48},
  }
  Object.assign(positions, corePositions)
  const bundled = isStagedPreview || mode === 'bundled-fallback'
  function nodeState(n: Node) {
    if (n.kind === 'source' || n.kind === 'checker' || n.kind === 'synthesis') return {
      status: n.allowedIntoSynthesis === false ? 'blocked' : status(n.status),
      detail: n.pipelineStale === true ? 'Recorded update delayed' : n.allowedIntoSynthesis === false ? 'Excluded from recorded synthesis' : n.kind === 'source' ? 'Recorded source check' : 'Recorded workflow result',
    }
    if (n.kind === 'publish') return {status: 'unknown', detail: 'Snapshot construction; publisher health not verified'}
    if (n.kind === 'transport') return {status: bundled ? 'unknown' : runtime.status, detail: bundled ? 'Not used by this bundled edition' : mode === 'last-known-good' ? 'Cached edition; latest remote not verified' : runtime.label}
    return {status: 'unknown', detail: `Current graph consumer · ${runtime.label}`}
  }
  const edgePath = (e: Edge) => {
    const a = positions[e.from], b = positions[e.to]
    if (a.x === b.x) return `M ${a.x + 112} ${a.y + 70} L ${b.x + 112} ${b.y}`
    const x = a.x + 225, y = a.y + 35, targetY = b.y + 35, mid = (x + b.x) / 2
    return `M ${x} ${y} C ${mid} ${y}, ${mid} ${targetY}, ${b.x} ${targetY}`
  }
  return <article className="ops-workflow-card workflow-dependency-card">
    <div className="ops-workflow-head"><div><span className="eyebrow">Recorded dependencies</span><h3>{name}</h3><p>Recorded run: {formatTimestamp(typeof graph.generatedAt === 'string' ? graph.generatedAt : undefined)}</p></div><div className="ops-summary-strip"><span>{sources.length} source nodes</span><span>{edges.length} declared dependencies</span></div></div>
    <p className="workflow-dependency-explainer">Solid arrows are recorded research dependencies. Dashed arrows show the configured publication route, not proof of live delivery. Workflow Ops is the sole current graph-status consumer.</p>
    <div className="workflow-dependency-scroll" tabIndex={0} role="region" aria-label={`${name} dependency diagram; scroll horizontally on smaller screens`}>
      <div className="workflow-dependency-canvas" style={{height}}>
        <div className="workflow-dependency-stage" style={{left:16}}>Sources · recorded</div><div className="workflow-dependency-stage" style={{left:330}}>Checks and assessment</div><div className="workflow-dependency-stage" style={{left:645}}>Publication · conditional route</div><div className="workflow-dependency-stage" style={{left:960}}>Current consumer</div>
        <svg width="1205" height={height} aria-hidden="true"><defs><marker id={marker} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" /></marker></defs>{edges.map(e => <path key={`${e.from}:${e.to}`} data-from={e.from} data-to={e.to} className={catalog[e.from][0] === 'source' || e.from === 'checker' ? 'research-edge' : 'delivery-edge'} d={edgePath(e)} markerEnd={`url(#${marker})`} />)}</svg>
        {nodes.map(n => {const s = nodeState(n); return <div key={n.id} className={`workflow-dependency-node ops-workflow-node ${n.kind}`} data-node={n.id} data-status={s.status} style={{left: positions[n.id].x, top: positions[n.id].y}}><strong>{n.label}</strong><span className="workflow-ops-badge" data-status={s.status}>{s.status}</span><small>{s.detail}</small></div>})}
      </div>
    </div>
    <p className="markets-metadata">{runtime.detail} Recovery: last-known-good is used only when a valid cached edition is available; otherwise the browser can use the bundled edition. Recorded checks do not establish publisher or scheduler health.</p>
    <details className="ops-diagnostics"><summary>Inspect exact dependencies ({edges.length})</summary><ul>{edges.map(e => <li key={`${e.from}:${e.to}`}>{catalog[e.from][1]} → {catalog[e.to][1]}{catalog[e.from][0] === 'source' || e.from === 'checker' ? ` · recorded ${status(e.status)}` : ' · configured route'}</li>)}</ul></details>
  </article>
}
