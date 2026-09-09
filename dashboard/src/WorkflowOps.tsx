import type { DashboardData } from './App'
import type { MarketDataMode } from './useMarketData'
import type { MarketDataManifest } from './marketDataClient'
import { formatTimestamp } from './researchComponents'
import './workflowOps.css'
import { WorkflowDependencyGraph } from './WorkflowDependencyGraph'

type RecordValue = Record<string, unknown>
type OpsStatus = 'pass' | 'degraded' | 'fail' | 'blocked' | 'missing' | 'stale' | 'paused' | 'unknown'
const object = (value: unknown): RecordValue => value && typeof value === 'object' && !Array.isArray(value) ? value as RecordValue : {}
const rows = (value: unknown): RecordValue[] => Array.isArray(value) ? value.map(object) : []
const stamp = (value: unknown) => formatTimestamp(typeof value === 'string' ? value : undefined)
export const metric = (value: unknown) => typeof value === 'number' && Number.isInteger(value) && value >= 0 ? String(value) : 'Unknown'

export function opsStatus(value: unknown): OpsStatus {
  switch (typeof value === 'string' ? value.toLowerCase() : '') {
    case 'pass': case 'ok': case 'success': case 'healthy': return 'pass'
    case 'degraded': case 'warning': return 'degraded'
    case 'paused': return 'paused'
    case 'fail': case 'failed': case 'error': return 'fail'
    case 'blocked': return 'blocked'
    case 'missing': return 'missing'
    case 'stale': return 'stale'
    default: return 'unknown'
  }
}
const priority: OpsStatus[] = ['fail', 'blocked', 'missing', 'stale', 'degraded', 'paused', 'unknown', 'pass']
const worst = (statuses: OpsStatus[]) => priority.find(status => statuses.includes(status)) || 'unknown'
export function sourceStatus(section: RecordValue): OpsStatus {
  const status = opsStatus(section.status)
  const validation = opsStatus(section.validation)
  const producer = opsStatus(object(section.producer).latestStatus)
  const issues = [status, validation, producer].filter(s => s !== 'pass' && s !== 'unknown')
  return issues.length ? worst(issues) : status
}

export function graphStatus(graph: RecordValue): OpsStatus {
  const checks = rows(graph.graphNodes).filter(node => node.kind === 'source' || node.kind === 'checker')
  const statuses = checks.map(node => node.allowedIntoSynthesis === false ? 'blocked' as const : node.pipelineStale === true ? 'stale' as const : opsStatus(node.status))
  // A surviving aggregate gate alone does not establish visible source coverage.
  return worst([opsStatus(graph.finalGate), ...(checks.length ? statuses : ['unknown' as const])])
}

export function runtimeStatus(mode: MarketDataMode, isStagedPreview = false, error?: string): {status: OpsStatus; label: string; detail: string} {
  if (isStagedPreview || mode === 'bundled-fallback') return { status: 'unknown', label: isStagedPreview ? 'Bundled staged preview' : 'Bundled fallback', detail: 'This browser is reading the bundled edition. It does not verify the live publisher or scheduled jobs.' }
  if (mode === 'last-known-good') return { status: 'degraded', label: 'Last-known-good edition', detail: 'A previously verified edition is available locally. Latest publication availability is not verified.' }
  if (error) return { status: 'degraded', label: 'Refresh failed · retained edition', detail: 'The latest check failed. The displayed edition retains its original source timestamps.' }
  if (mode === 'remote-stale') return { status: 'degraded', label: 'Remote edition · source warning', detail: 'Remote transport was verified, but the manifest reports stale or degraded source coverage.' }
  if (mode === 'remote-live') return { status: 'pass', label: 'Remote snapshot verified', detail: 'The browser verified the remote edition. This is transport evidence, not live market data or proof that every producer is healthy.' }
  return { status: 'unknown', label: 'Loading · not verified', detail: 'Publication availability has not been established.' }
}

function Badge({status}: {status: OpsStatus}) { return <span className="workflow-ops-badge" data-status={status}>{status.charAt(0).toUpperCase() + status.slice(1)}</span> }

// Fixed consumer descriptions reflect the current React reads, not legacy graph edges.
const sections = [
  ['tickers', 'Company research', 'Research directory and company pages'],
  ['cronTimeline', 'Published run timeline', 'Daily Brief timeline'],
  ['dailyJournal', 'Market journal', 'Daily Brief market context'],
  ['marketPosture', 'Market posture', 'Upstream publication adaptation and legacy sources'],
  ['currentAsymmetricShortlist', 'Shortlist membership', 'Conviction List membership'],
  ['aiProjectionExhibits', 'Projection exhibits', 'Valuation analysis'],
  ['aiWarRoomCompleteData', 'Extended valuation research', 'Valuation analysis'],
  ['marketGraphs', 'Workflow checks', 'Workflow Ops only'],
] as const

function workflowName(graph: RecordValue, index: number) {
  if (graph.label === 'Market research → CIO dashboard' || graph.label === 'Market research checks') return 'Market research checks'
  if (graph.label === 'Earnings proof gate') return 'Earnings proof gate'
  return `Workflow check ${index + 1}`
}
const sourceNames = new Set(['News Calendar', 'X Signals', 'Transcripts', 'SEC Insiders', 'Macro Breadth', 'AI Projection Exhibits', 'Upcoming Earnings', 'Preview', 'Post Print Trigger', 'Press Release 8K', 'Financials', 'Guidance', 'Call Transcript', 'Price Volume', 'Peer Readthrough', 'Post Print Projection Update', 'Checker gate'])

export type WorkflowOpsProps = {
  data: DashboardData
  mode: MarketDataMode
  isStagedPreview?: boolean
  lastCheckedAt?: string
  manifest?: MarketDataManifest
  error?: string
}

export function WorkflowOps({data, mode, isStagedPreview = false, lastCheckedAt, manifest, error}: WorkflowOpsProps) {
  const runtime = runtimeStatus(mode, isStagedPreview, error)
  const health = object(data.sourceHealth)
  const sourceSections = object(health.sections)
  const graphs = rows(data.marketGraphs)
  const attention = sections.filter(([key]) => sourceStatus(object(sourceSections[key])) !== 'pass')
  return <section className="workflow-ops" aria-labelledby="workflow-ops-title">
    <header><h1 id="workflow-ops-title">Workflow Ops</h1><p>Source health, recorded workflow checks, and how this edition reached your browser.</p></header>
    <section className="workflow-ops-runtime" aria-labelledby="workflow-runtime-title"><div><h2 id="workflow-runtime-title">{runtime.label}</h2><Badge status={runtime.status}/></div><p>{runtime.detail}</p><dl className="workflow-ops-dates">
      <div><dt>Edition source as of</dt><dd>{stamp(data.dataAsOf ?? data.sourceMaxAsOf)}</dd></div>
      {(manifest?.builtAt || data.generatedAt) && <div><dt>Snapshot built</dt><dd>{stamp(manifest?.builtAt ?? data.generatedAt)}</dd></div>}
      {manifest?.publishedAt && <div><dt>Edition published</dt><dd>{stamp(manifest.publishedAt)}</dd></div>}
      {lastCheckedAt && <div><dt>Browser last checked</dt><dd>{stamp(lastCheckedAt)}</dd></div>}
    </dl></section>
    <section className="markets-section"><h2>Workflow dependency diagrams</h2><p>Actual public source/checker/synthesis dependencies, with recorded checks separated from this browser’s delivery state. Scroll sideways on smaller screens to follow the full graph.</p>
      {graphs.length ? graphs.map((graph, index) => <WorkflowDependencyGraph key={index} graph={graph} mode={mode} isStagedPreview={isStagedPreview} runtime={runtime} />) : <p className="markets-notice">No public dependency evidence available.</p>}
    </section>
    <section className="markets-section"><h2>Source health</h2><p>Recorded aggregate: <Badge status={opsStatus(health.status ?? health.overall)}/>. {attention.length ? `${attention.length} displayed source sections need attention or have incomplete evidence.` : 'All displayed source sections have recorded passing health.'} Recorded status includes validation and producer failures. Source freshness is assessed by the generator, not a second browser clock.</p>
      <p className="workflow-ops-scroll-hint">Scroll sideways to see every column.</p>
      <div className="markets-table-scroll" tabIndex={0} role="region" aria-label="Source health table"><table className="workflow-ops-table"><caption>Sources used by current dashboard views</caption><thead><tr><th scope="col">Source</th><th scope="col">Recorded status</th><th scope="col">Updated</th><th scope="col">Current consumer</th></tr></thead><tbody>{sections.map(([key,label,consumer]) => {
        const section=object(sourceSections[key]); const producer=object(section.producer)
        return <tr key={key}><th scope="row">{label}</th><td><Badge status={sourceStatus(section)}/>{producer.latestStatus && producer.latestStatus !== 'not_applicable' ? <small>Producer: <Badge status={opsStatus(producer.latestStatus)}/>{producer.lastSuccessAt ? <> · Last success {stamp(producer.lastSuccessAt)}</> : null}</small> : null}</td><td>{stamp(section.dataAsOf ?? section.artifactTimestamp)}</td><td>{consumer}</td></tr>
      })}</tbody></table></div>
      <p className="markets-metadata">Health is recorded at snapshot construction, not a scheduler heartbeat. Missing or sanitized metrics remain unknown. Publication-level health is not reported separately in this snapshot contract.</p>
    </section>
    <section className="markets-section"><h2>Recorded workflow checks</h2><p>Recorded research-workflow checks, not live scheduler status or automatic trading permission.</p>
      {!graphs.length ? <p className="markets-notice">Workflow check evidence unavailable. No healthy run can be inferred.</p> : <div className="markets-table-scroll" tabIndex={0} role="region" aria-label="Workflow check table"><table className="workflow-ops-table"><caption>Latest recorded check per workflow</caption><thead><tr><th scope="col">Workflow / run timestamp</th><th scope="col">Evidence status</th><th scope="col">Recorded gate</th><th scope="col">Passed / checked sources</th><th scope="col">Delayed sources</th><th scope="col">Source diagnostics</th></tr></thead><tbody>{graphs.map((graph,index) => {
        const nodes=rows(graph.graphNodes).filter(node=>node.kind==='source'||node.kind==='checker')
        return <tr key={index}><th scope="row">{workflowName(graph,index)}<small>{stamp(graph.generatedAt)}</small></th><td><Badge status={graphStatus(graph)}/></td><td><Badge status={opsStatus(graph.finalGate)}/></td><td>{metric(graph.passCount)} / {metric(graph.nodeCount)}</td><td>{metric(graph.pipelineStaleCount)}</td><td>{nodes.length ? <details><summary>Inspect recorded source checks</summary><ul className="workflow-ops-checks">{nodes.map((node,nodeIndex)=><li key={nodeIndex}><strong>{sourceNames.has(String(node.label)) ? String(node.label) : `Source check ${nodeIndex+1}`}</strong> <Badge status={node.allowedIntoSynthesis === false ? 'blocked' : node.pipelineStale === true ? 'stale' : opsStatus(node.status)}/><small>{node.allowedIntoSynthesis === false ? 'Excluded from that workflow synthesis' : node.allowedIntoSynthesis === true ? 'Allowed in that workflow synthesis' : 'Synthesis permission unknown'} · Sources: {metric(node.sourceCount)}</small></li>)}</ul></details> : 'Source-level detail unavailable'}</td></tr>
      })}</tbody></table></div>}
    </section>
  </section>
}
