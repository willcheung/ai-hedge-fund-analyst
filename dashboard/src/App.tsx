import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { Activity, BookOpen, CheckCircle2, Clock3, Database, RadioTower, Search, ShieldCheck, Target, TrendingUp, Zap } from 'lucide-react'
import { Bar, Bubble, Scatter } from 'react-chartjs-2'
import { BarElement, CategoryScale, Chart as ChartJS, Legend, LinearScale, LineElement, PointElement, Tooltip, type ChartData, type ChartOptions, type Plugin } from 'chart.js'
import DataTable from 'datatables.net-dt'
import { hasPublicationContract } from './publicationValidation'
import { useMarketData, isStagedPreviewBuild, type MarketDataMode } from './useMarketData'
import { WorkflowOps } from './WorkflowOps'
import { formatTimestamp, ResearchHeadline } from './researchComponents'

// Canvas cannot resolve CSS variables. Read the shared tokens at each update,
// including existing charts after an appearance change; leave data/series intact.
export function ownerChartPalette() {
  const css = typeof document === 'undefined' ? null : getComputedStyle(document.documentElement)
  const token = (name: string, fallback: string) => css?.getPropertyValue(`--markets-${name}`).trim() || fallback
  return { text: token('foreground', '#18212b'), muted: token('muted', '#586473'), surface: token('surface', '#ffffff'), border: token('border', '#d6d8d9') }
}
const ownerChartThemePlugin: Plugin = {
  id: 'owner-shared-theme',
  beforeUpdate(chart) {
    const palette = ownerChartPalette()
    for (const axis of Object.values(chart.options.scales || {})) {
      if (!axis) continue
      if (axis.ticks) axis.ticks.color = palette.muted
      if (axis.grid) axis.grid.color = palette.border
      if ('title' in axis && axis.title) axis.title.color = palette.text
    }
    const tooltip = chart.options.plugins?.tooltip
    if (tooltip) { tooltip.backgroundColor = palette.surface; tooltip.titleColor = palette.text; tooltip.bodyColor = palette.text; tooltip.borderColor = palette.border }
    const legend = chart.options.plugins?.legend
    if (legend?.labels) legend.labels.color = palette.text
  },
}
ChartJS.register(CategoryScale, LinearScale, BarElement, PointElement, LineElement, Tooltip, Legend, ownerChartThemePlugin)

function useOwnerChartTheme() {
  useEffect(() => {
    const observer = new MutationObserver(() => Object.values(ChartJS.instances).forEach(chart => chart.update('none')))
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [])
}

export function publicSourceReference(value?: string) {
  if (!value) return 'Source reference unavailable'
  try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password ? url.hostname : 'Source reference unavailable' }
  catch { return 'Source reference unavailable' }
}

type ScorePoint = { date: string; score: number; zone?: string; sourcePath?: string }
type PostureCard = { name: string; sourcePath: string; score?: number | null; zone?: string; delta?: number | null; history?: ScorePoint[]; plainTitle: string; plainEnglish: string; watch: string[]; artifactDate?: string; freshnessStatus?: string }
type DetailSection = { title: string; summary: string; bullets?: string[] }
type Ticker = {
  symbol: string; title: string; updated: string; tags: string[]; sourcePath: string; summary: string; status: string; actionBucket: string; isStub: boolean; category: string; exchange?: string; tradingViewSymbol?: string
  researchTier?: string; tierReviewed?: string; tierReason?: string
  thesis?: string
  catalyst?: string; risk?: string; shortlistGroup?: string; shortlistRank?: string; shortlistRec?: string; shortlistStatus?: string; shortlistThesis?: string; shortlistRisk?: string; trigger?: string; entryPoint?: string
  detailSections?: DetailSection[]; fullSummary?: string
}
type JournalTicker = { symbol: string; why: string; hasResearch?: boolean; changePct?: number | null; direction?: 'up' | 'down' | 'flat' }
type ActionCallout = { symbol: string; action: string; details: string[] }
type JournalItem = { title: string; sourceType: string; sourcePath: string; summary: string; highlights: string[]; goldSilver?: string[]; actionCallouts?: ActionCallout[] }
type MarketNarrative = { title: string; bullets: string[] }
type PortfolioAction = { symbol?: string; stance: string; text: string }
type JournalDay = { date: string; headline: string; summary: string; marketNarrative?: MarketNarrative; portfolioActions?: PortfolioAction[]; keyTakeaways: string[]; actionCallouts?: ActionCallout[]; goldSilver?: string[]; interestingTickers?: JournalTicker[]; items: JournalItem[]; sourceTypes: string[] }
type SourceGroup = { name: string; role: string; summary: string; examples: string[]; howUsed: string }
type CioDecision = { id: string; symbol?: string; scope: string; stance: string; decision: string; rationale: string[]; proof?: string; kill?: string; source: string; severity: 'urgent' | 'warning' | 'info' | 'success' }
type SourceSignal = { id: string; sourceType: string; title: string; sourcePath: string; signal: string; convergence: string[]; symbols: string[] }
type CronTimelineItem = { id: string; jobId: string; jobName: string; runTime: string; schedule: string; deliver: string; category: string; sourcePath: string; summary: string; highlights: string[]; articleBody?: string }
type IntradayHit = { symbol: string; action: string; trigger: string; price?: number | null; pct_today?: number | null; wiki_level?: number | null; technical_quality?: string; technical_note?: string; bucket?: string; source_lists?: string[]; context?: string; text?: string }
type IntradayEquityWatchdog = { last_check_utc: string; monitored_count: number; dashboard_hit_count: number; review_candidate_count: number; slack_policy: string; summary: string; sources: string[]; monitored_symbols: string[]; top_hits: IntradayHit[]; review_candidates: IntradayHit[]; sourcePath: string }
type GraphDecisionEvent = { id: string; workflowId: string; runId?: string; gate: string; scope: string; decision: string; proof: string[]; blockedBy: string[]; sourcePaths: string[]; slackWorthy: boolean; severity: 'urgent' | 'warning' | 'info' | 'success' | string; generatedAt?: string }
type GraphWorkflowNode = { id: string; label: string; kind: 'source' | 'checker' | 'synthesis' | string; status: string; freshness?: string; freshnessContext?: string; pipelineStale?: boolean; allowedIntoSynthesis?: boolean; reason?: string; outputPath?: string; sourceCount?: number; healActions?: string[] }
type GraphWorkflowEdge = { from: string; to: string; status?: string }
type MarketGraphWorkflow = { workflowId: string; label: string; runId?: string; generatedAt?: string; finalGate: 'pass' | 'degraded' | 'fail' | 'missing' | 'unknown' | string; recommendation?: string; allowedNodes: string[]; blockedNodes: string[]; selfHealSummary: string[]; privacyFindings: string[]; brokerSafetyFindings: string[]; contradictions: string[]; tickers: string[]; themes: string[]; nodeCount: number; passCount: number; degradedCount: number; failCount: number; marketClosedCarryCount?: number; pipelineStaleCount?: number; finalPath?: string; checkerPath?: string; decisionEventsPath?: string; decisionEvents?: GraphDecisionEvent[]; decisionEventCount?: number; slackWorthyEventCount?: number; graphNodes?: GraphWorkflowNode[]; graphEdges?: GraphWorkflowEdge[] }

type AgenticTradingReport = { lane?: string; date: string; title: string; sourcePath: string; traffic: string; status: string; summary: string; cards: { label: string; text: string }[]; learningNotes: string[] }
type AsymmetricShortlistEvent = { kind?: string; sourcePath?: string; generatedAt?: string; summary?: string }
type AsymmetricShortlistActionChange = { symbol: string; changeType?: string; fromBucket?: string; toBucket?: string; headline?: string; action?: string; freshness?: string; returnRole?: string; whyThisHelps50to100?: string; opportunityCost?: string; slackWorthy?: boolean; generatedAt?: string; expiresAt?: string }
type ShortlistMembershipChange = { symbol: string; changeType: string; fromBucket: string; toBucket: string; fromAction?: string; toAction?: string; fromFreshness?: string; toFreshness?: string; changedFields: string[] }
type ShortlistMembershipPolicy = { bucketMode: string; description: string; bucketOrder: string[] }
type ShortlistRunSummary = { builder: string; scheduledOwner: string; generatedAt: string; previousGeneratedAt?: string; status: string; rowCount: number; addedSymbols: string[]; removedSymbols: string[]; changedCount: number; unchangedCount: number }
type ShortlistAutomation = { jobName: string; schedule: string; enabled: boolean; lastStatus: string; lastRunAt?: string; nextRunAt?: string; health: string }
type ShortlistWorkflowNode = { id: string; label: string; stage: string; kind: string; status: string; schedule?: string; lastRunAt?: string; nextRunAt?: string; detail: string; artifacts: string[] }
type ShortlistWorkflowEdge = { from: string; to: string; label: string }
type ShortlistMembershipWorkflow = { generatedAt: string; status: string; coverageNote: string; nodes: ShortlistWorkflowNode[]; edges: ShortlistWorkflowEdge[] }
type AsymmetricShortlistRow = { symbol: string; bucket: string; bucketReason?: string; rank?: string; state?: string; upsideClass?: string; proofLevel?: string; entry?: string; currentPrice?: number | null; quoteAsOf?: string; entryZoneLow?: number | null; entryZoneHigh?: number | null; entryZoneCurrency?: string; entryZoneAsOf?: string; entryStatus?: string; entryReason?: string; entryEligible?: boolean; proofTrigger?: string; killTrigger?: string; whyNotNow?: string; freshness?: string; freshnessReason?: string; decisionExpiration?: string; tickerUpdated?: string; tickerAgeDays?: number | null; eventAgeDays?: number | null; priceAgeDays?: number | null; capitalEligible?: boolean; tier?: string; researchTier?: string; tierReviewed?: string; tierReason?: string; returnRole?: string; targetContribution?: string; timeToMatter?: string; actionMode?: string; whyThisHelps50to100?: string; opportunityCost?: string; capitalPriority?: number | null; latestEvent?: AsymmetricShortlistEvent | null; privateSizingHidden?: boolean }
type DecisionReceipt = { id: string; recordedAt?: string; symbol: string; decision: string; decisionState?: string; researchTier?: string; thesis?: string; entry?: string; proofTrigger?: string; killTrigger?: string; sizeClass?: string; decisionExpiration?: string; decisionQuote?: number | null; quoteAsOf?: string; fundingClass?: string; completeness?: string; missingFields?: string[]; recordReason?: string }
type DecisionLearningException = { id: string; symbol?: string; classification?: string; question: string; status?: string; sourceReceiptId?: string; nextReviewEvent?: string; lessonCandidate?: string }
type DecisionOutcome = { receiptId?: string; sourceReceiptId?: string; symbol?: string; receiptDecision?: string; priorDecision?: string; currentDecision?: string; state?: string; status?: string; classification?: string; observedAt?: string; returnPct?: number | null; reviewReason?: string; reason?: string; supersededBy?: string }
type DecisionExceptionCandidate = { id: string; symbol?: string; classification?: string; question: string; status: 'candidate'; sourceReceiptId?: string; observedAt?: string; severity?: string; priorDecision?: string; currentDecision?: string; nextReviewEvent?: string; lessonCandidate?: string; returnPct?: number | null }
type DecisionLearning = { generatedAt?: string; policy?: string; receiptCount?: number; newReceiptCount?: number; integrityGapCount?: number; openExceptionCount?: number; outcomeCount?: number; reviewDueCount?: number; candidateExceptionCount?: number; policyRuleCount?: number; adoptedPolicyRuleCount?: number; unlinkedPolicyRuleCount?: number; casebookCount?: number; casebookPolicy?: string; recentReceipts?: DecisionReceipt[]; openExceptions?: DecisionLearningException[]; recentOutcomes?: DecisionOutcome[]; exceptionCandidates?: DecisionExceptionCandidate[]; handoffs?: Record<string, string> }
type AsymmetricShortlist = { generatedAt?: string; policy?: string; summary?: Record<string, number | string>; regime?: Record<string, string>; actionChanges?: AsymmetricShortlistActionChange[]; membershipPolicy?: ShortlistMembershipPolicy; runSummary?: ShortlistRunSummary; membershipChanges?: ShortlistMembershipChange[]; automation?: ShortlistAutomation; membershipWorkflow?: ShortlistMembershipWorkflow; rows: AsymmetricShortlistRow[]; decisionLearning?: DecisionLearning | null }
export type DashboardData = {
  schemaVersion?: number; generatedAt?: string; dataAsOf?: string; sourceMaxAsOf?: string; refreshMode: string
  counts: { tickers: number; researched: number; stubs: number; reports: number; convictionItems: number; journalDays: number }
  actionBuckets: Record<string, number>; topTags: [string, number][]; categoryCounts: Record<string, number>
  marketPosture: PostureCard[]; dailyJournal: JournalDay[]; cronTimeline?: CronTimelineItem[]; intradayEquityWatchdog?: IntradayEquityWatchdog | null; marketGraphs?: MarketGraphWorkflow[]; currentAsymmetricShortlist?: AsymmetricShortlist | null; aiProjectionExhibits?: AiProjectionExhibits | null; aiWarRoomCompleteData?: AiWarRoomCompleteData | null; sources: SourceGroup[]; tickers: Ticker[]; focusTickers: Ticker[]
  agenticTradingReport?: AgenticTradingReport | null
  agenticTradingReports?: AgenticTradingReport[]
  privacy: { excluded: string[]; note: string }
  sourceHealth?: Record<string, unknown>
}
type StrategyRowTone = 'success' | 'warn' | 'danger' | 'neutral'
type AiProjectionCase = { revenueCagrPct?: number | null; terminalMultiple?: number | null; impliedPrice?: number | null; upsidePct?: number | null; proofNeeded?: string }
type AiProjectionRow = { symbol: string; companyName?: string; researchTier?: string; tierReviewed?: string; tierReason?: string; instrumentRisk?: string; archetype: string; benchmarkGroup?: string; sourcePage?: string; inclusionReason?: string; price?: number | null; marketCap?: number | null; enterpriseValue?: number | null; quoteAsOf?: string; ltmRevenue?: number | null; ntmRevenue?: number | null; ntmRevenueGrowthPct?: number | null; evNtmRevenue?: number | null; peNtm?: number | null; evEbitdaNtm?: number | null; fcfMarginPct?: number | null; sectorPercentile?: number | null; ownHistoryPercentile?: number | null; valuationSignal?: string; relativeValueScore?: number | null; dataQualityLabel?: string; dataQualityScore?: number | null; missingCriticalFields?: string[]; bear?: AiProjectionCase; base?: AiProjectionCase; bull?: AiProjectionCase; multiBagPlausibility?: string; mainBottleneck?: string; warRoomAction?: string; capitalEligibleFromProjection?: boolean; fundamentalsSource?: string; fundamentalsAsOf?: string }
type AiProjectionExhibits = { generatedAt?: string; artifactDate?: string; policy?: string; privacyClass?: string; rowCount?: number; excludedDiscoveredCount?: number; sourcePaths?: string[]; summary?: { dataQuality?: Record<string, number>; valuationSignals?: Record<string, number>; capitalEligibleCount?: number; degradedOrMissingCount?: number }; rows: AiProjectionRow[]; chartData?: Record<string, Array<Record<string, string | number | boolean | null>>>; artifactPaths?: Record<string, string> }
type AiWarRoomRow = { symbol: string; primaryTicker?: string; companyName?: string; researchTier?: string; tierReviewed?: string; tierReason?: string; instrumentRisk?: string; exchange?: string; currency?: string; price?: number | null; quoteAsOf?: string; dayChangePct?: number | null; oneMonthChangePct?: number | null; threeMonthChangePct?: number | null; ytdChangePct?: number | null; marketCap?: number | null; enterpriseValue?: number | null; ltmRevenue?: number | null; ntmRevenueEstimate?: number | null; revenueGrowthPct?: number | null; grossMarginPct?: number | null; operatingMarginPct?: number | null; fcfMarginPct?: number | null; epsNtm?: number | null; cash?: number | null; debt?: number | null; evRevenue?: number | null; evNtmRevenue?: number | null; peNtm?: number | null; evEbitda?: number | null; relativePeerValuation?: string; backlogOrdersRpo?: string; customerProof?: string; insiderFlow?: string; macroTape?: string; proofLevel?: number | null; action?: string; actionDelta?: string; starterZone?: string; addZone?: string; killZone?: string; nextCatalystCheckDate?: string; sizeFrame?: string; dataQualityLabel?: string; missingCriticalFields?: string[]; sourceFreshness?: string; sourcePaths?: string[] }
type AiWarRoomCompleteData = { generatedAt?: string; rowCount?: number; manifest?: { completed?: number; pending?: number; errors?: number; total?: number }; summary?: { actions?: Record<string, number>; dataQuality?: Record<string, number> }; sourcePaths?: string[]; rows: AiWarRoomRow[]; chartData?: Record<string, Array<Record<string, string | number | boolean | null>>> }
export type Tab = 'cio' | 'strategy' | 'market' | 'stocks' | 'ops' | 'sources'
export const dashboardTabs: ReadonlyArray<{ id: Tab; label: string }> = [
  { id: 'market', label: 'Daily brief' },
  { id: 'cio', label: 'Market outlook' },
  { id: 'strategy', label: 'Valuation' },
  { id: 'stocks', label: 'Stock research' },
  { id: 'ops', label: 'Publication availability' },
  { id: 'sources', label: 'Sources' },
]

export function tabFromHash(rawHash: string): Tab {
  if (tickerFromHash(rawHash)) return 'stocks'
  const hash = rawHash.replace(/^#/, '')
  if (hash === 'projections') return 'strategy'
  return dashboardTabs.some(tab => tab.id === hash) ? hash as Tab : 'market'
}

export function tickerFromHash(rawHash: string): string {
  return rawHash.match(/^#ticker\/([A-Z][A-Z0-9.-]{0,14})$/)?.[1] || ''
}

export function dashboardFreshnessTimestamp(data: { generatedAt?: string; dataAsOf?: string; sourceMaxAsOf?: string }) {
  return data.sourceMaxAsOf || data.dataAsOf || data.generatedAt
}


function ownerOperationsText(value?: string) {
  if (!value) return 'Detail unavailable'
  return value.replace(/\bCIO dashboard\b/g, 'Market outlook').replace(/\bCIO exceptions\b/g, 'Research alerts').replace(/\bWorkflow Ops\b/g, 'Publication availability').replace(/\bChecker gate\b/g, 'Source verification').replace(/\bDashboard synthesis\b/g, 'Research assessment').replace(/\bPublic snapshot\b/g, 'Published research').replace(/\bBlob manifest\b/g, 'Publication index').replace(/\bDTO\b/g, 'research data').replace(/\bchecker-approved\b/g, 'verified').replace(/\bpayload\b/g, 'data').replace(/\bStructural projection allowlists the graph research data and privacy-scrubs it before publication\./g, 'Only approved public research is included in the publication.').replace(/\bManifest points clients to an immutable, hash-verified public snapshot; live status is resolved in the browser\./g, 'The publication index identifies the verified research update. Availability is checked in this browser.').replace(/\bFreshness, proof-quality, privacy, contradictions, and broker-safety gate\./g, 'Checks source dates, evidence quality, privacy, conflicting findings, and trading safeguards.').replace(/\bUse synthesis as normal local decision context\./g, 'Use the verified research as decision context.')
}

function cls(...parts: Array<string | false | undefined>) { return parts.filter(Boolean).join(' ') }
function fmtDate(v?: string) { return formatTimestamp(v) }
function tierLabel(v?: string) { return publicAssessmentLabel(v) }
function TierPill({ tier, reviewed, reason }: { tier?: string; reviewed?: string; reason?: string }) {
  const tone = tier === 'core-long' ? 'tier-one' : tier === 'highly-speculative' ? 'tier-three' : tier === 'speculative' ? 'tier-two' : 'tier-unknown'
  return <span className={cls('research-tier-pill', tone)} title={[reason, reviewed ? `Reviewed ${reviewed}` : ''].filter(Boolean).join('\n')}>{tierLabel(tier)}</span>
}
const publicLabelModules = import.meta.glob('../schema/public-labels.json', { eager: true, import: 'default' })
export function publicAssessmentLabel(value?: string) {
  const document = Object.values(publicLabelModules)[0] as { labels?: Record<string, { label: string }> } | undefined
  const labels = document?.labels || {}
  const entry = value && Object.prototype.hasOwnProperty.call(labels, value) ? labels[value] : Object.values(labels).find(entry => entry.label === value)
  return entry?.label || 'Assessment unavailable'
}
function humanizeLabel(v?: string) { return publicAssessmentLabel(v) }
function displayDataQuality(v?: string) { return publicAssessmentLabel(v) }
function dataQualityTone(v?: string) {
  const label = displayDataQuality(v).toLowerCase()
  if (label.startsWith('missing')) return 'missing'
  if (label === 'degraded' || label === 'partial') return 'degraded'
  if (label === 'strong') return 'strong'
  return 'usable'
}
function searchMatch(q: string, parts: Array<string | string[] | undefined>) { const hay = parts.flatMap(p => Array.isArray(p) ? p : [p || '']).join(' ').toLowerCase(); return !q || hay.includes(q.toLowerCase()) }
function lines(text?: string, max = 8) { return (text || '').split(/\n+/).map(x => x.replace(/^[-*•]\s*/, '').trim()).filter(Boolean).slice(0, max) }

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
function hasString(row: Record<string, unknown>, key: string) { return typeof row[key] === 'string' }
function stringArray(value: unknown): value is string[] { return Array.isArray(value) && value.every(item => typeof item === 'string') }
function numberRecord(value: unknown) {
  return isRecord(value) && Object.values(value).every(item => typeof item === 'number' && Number.isFinite(item))
}
function isTickerData(value: unknown) {
  if (!isRecord(value)) return false
  return ['symbol', 'title', 'updated', 'summary', 'status', 'actionBucket', 'category'].every(key => hasString(value, key))
    && (value.sourcePath === undefined || typeof value.sourcePath === 'string')
    && stringArray(value.tags)
    && typeof value.isStub === 'boolean'
}
function isSourceData(value: unknown) {
  if (!isRecord(value)) return false
  return ['name', 'role', 'summary', 'howUsed'].every(key => hasString(value, key)) && stringArray(value.examples)
}

export function isDashboardData(value: unknown): value is DashboardData {
  if (!isRecord(value) || value.schemaVersion !== 1 || !hasString(value, 'refreshMode')) return false
  const counts = value.counts
  const privacy = value.privacy
  if (!isRecord(counts) || !['tickers', 'researched', 'stubs', 'reports', 'convictionItems', 'journalDays']
    .every(key => typeof counts[key] === 'number' && Number.isSafeInteger(counts[key]) && Number(counts[key]) >= 0)) return false
  if (!isRecord(privacy) || !stringArray(privacy.excluded) || !hasString(privacy, 'note')) return false
  if (!Array.isArray(value.tickers) || !value.tickers.every(isTickerData)) return false
  if (!Array.isArray(value.focusTickers) || !value.focusTickers.every(item => typeof item === 'string' || isTickerData(item))) return false
  if (!Array.isArray(value.sources) || !value.sources.every(isSourceData)) return false
  if (!numberRecord(value.actionBuckets) || !numberRecord(value.categoryCounts)) return false
  if (!Array.isArray(value.topTags) || !value.topTags.every(item => Array.isArray(item) && item.length === 2 && typeof item[0] === 'string' && typeof item[1] === 'number' && Number.isFinite(item[1]))) return false
  if (!Array.isArray(value.marketPosture) || !Array.isArray(value.dailyJournal)) return false
  return true
}

export function normalizeDashboardData(value: DashboardData | null): DashboardData | null {
  if (!value) return null
  const rawFocus = (value as unknown as { focusTickers?: unknown[]; focusTickerIds?: string[] }).focusTickerIds || value.focusTickers || []
  if (!rawFocus.some(item => typeof item === 'string')) return value
  const bySymbol = new Map(value.tickers.map(ticker => [ticker.symbol, ticker]))
  const focusTickers = rawFocus
    .map(item => typeof item === 'string' ? bySymbol.get(item) : item as Ticker)
    .filter((item): item is Ticker => !!item)
  return { ...value, focusTickers }
}

function dataModeLabel(mode: MarketDataMode) {
  if (mode === 'remote-live') return 'Latest publication loaded'
  if (mode === 'remote-stale') return 'Latest publication has limitations'
  if (mode === 'last-known-good') return 'Previous valid publication'
  if (mode === 'bundled-fallback') return 'Saved publication'
  return 'Loading data'
}

export function operationalNodeState(node: Pick<GraphWorkflowNode, 'id' | 'kind' | 'status' | 'reason'>, mode: MarketDataMode) {
  if (node.id === 'runtime_manifest') {
    if (mode === 'remote-live') return { status: 'pass', detail: 'Latest publication verified' }
    if (mode === 'remote-stale') return { status: 'degraded', detail: 'Publication loaded · some sources need attention' }
    if (mode === 'last-known-good') return { status: 'degraded', detail: 'Showing previous valid publication' }
    if (mode === 'bundled-fallback') return { status: 'fail', detail: 'Latest publication unavailable' }
    return { status: 'unknown', detail: 'Publication check pending' }
  }
  if (node.kind === 'consumer') return { status: 'pass', detail: 'Publication loaded' }
  if (node.id === 'public_snapshot') return { status: 'pass', detail: 'Public research loaded' }
  return { status: node.status || 'unknown', detail: node.reason || 'Detail unavailable' }
}

function MetricCard({ label, value, sub, icon, className }: { label: string; value: string | number; sub?: string; icon: React.ReactNode; className?: string }) {
  return <div className={cls('metric-card', className)}><div className="metric-icon">{icon}</div><div><div className="metric-label">{label}</div><div className="metric-value">{value}</div>{sub && <div className="metric-sub">{sub}</div>}</div></div>
}

export function findCanonicalRegimePosture(cards: PostureCard[]) {
  return cards.find(card => card.name === 'Canonical regime')
}

export function regimeStanceLabel(card: PostureCard) {
  if (/hold off|not helping|protect capital/i.test(`${card.plainTitle} ${card.plainEnglish}`)) return 'DEFENSIVE'
  if (/lean in|supports adding risk/i.test(`${card.plainTitle} ${card.plainEnglish}`)) return 'OFFENSE'
  return 'SELECTIVE'
}

function CanonicalRegimeStrip({ card }: { card: PostureCard }) {
  const fresh = (card.freshnessStatus || '').toLowerCase() === 'pass'
  const stance = regimeStanceLabel(card)
  return <section className={cls('canonical-regime-strip', !fresh ? 'degraded' : stance === 'OFFENSE' ? 'constructive' : 'selective')}>
    <div className="regime-primary">
      <span className="eyebrow">Market backdrop</span>
      <h3>{card.plainTitle}</h3>
      <small>{card.artifactDate ? `As of ${fmtDate(card.artifactDate)}` : 'Timestamp unavailable'} · {fresh ? 'Current' : 'Update needs review'}</small>
    </div>
    <div className="regime-score"><span>Stance</span><strong>{publicAssessmentLabel(stance)}</strong></div>
    <div className="regime-permission"><strong>{card.plainEnglish}</strong><div>{(card.watch || []).slice(0, 5).map(row => <span key={row}>{row}</span>)}</div></div>
  </section>
}

const tradingViewExchangeOverrides: Record<string, string> = {}
type ChartSymbolInput = string | { symbol: string; exchange?: string; tradingViewSymbol?: string }
function chartSymbolInputKey(item: ChartSymbolInput) {
  return typeof item === 'string' ? item : `${item.symbol}:${item.exchange || ''}:${item.tradingViewSymbol || ''}`
}
function cleanChartSymbol(item: ChartSymbolInput) {
  const symbol = (typeof item === 'string' ? item : item.symbol).replace(/^\$/, '').trim().toUpperCase()
  const exchange = typeof item === 'string' ? undefined : item.exchange
  const tvSymbol = typeof item === 'string' ? undefined : item.tradingViewSymbol
  return { symbol, exchange, tradingViewSymbol: tvSymbol }
}
function tradingViewSymbol(symbol: string, exchangeHint?: string) {
  const clean = symbol.replace(/^\$/, '').trim().toUpperCase()
  const exchange = exchangeHint || tradingViewExchangeOverrides[clean]
  if (!/^[A-Z0-9][A-Z0-9.-]{0,14}$/.test(clean) || !exchange || !/^[A-Z][A-Z0-9_]{0,19}$/.test(exchange)) return null
  return `${exchange}:${clean}|1D`
}
function tradingViewSymbolUrl(symbol: string, exchangeHint?: string) {
  const tv = tradingViewSymbol(symbol, exchangeHint)?.replace('|1D', '')
  return tv ? `https://www.tradingview.com/symbols/${tv.replace(':', '-')}/` : 'https://www.tradingview.com/'
}
function tradingViewSymbolForItem(item: { symbol: string; exchange?: string; tradingViewSymbol?: string }) {
  if (item.tradingViewSymbol) return /^[A-Z][A-Z0-9_]{0,19}:[A-Z0-9][A-Z0-9.-]{0,14}(?:\|1D)?$/.test(item.tradingViewSymbol) ? item.tradingViewSymbol : null
  return tradingViewSymbol(item.symbol, item.exchange)
}

export function companyChartTarget(item: { symbol: string; exchange?: string; tradingViewSymbol?: string }) {
  const symbol = tradingViewSymbolForItem(item)?.replace('|1D', '') || null
  return { symbol, url: symbol ? `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(symbol)}` : `https://www.tradingview.com/search/?query=${encodeURIComponent(item.symbol)}` }
}

// Single-company interactive chart. An unknown exchange is never guessed.
export function TradingViewChart({ symbol, exchange, tradingViewSymbol: explicitSymbol, title = 'Price history', className, height = 380 }: { symbol: string; exchange?: string; tradingViewSymbol?: string; title?: string; className?: string; height?: number }) {
  const target = companyChartTarget({ symbol, exchange, tradingViewSymbol: explicitSymbol })
  const [theme, setTheme] = useState(() => typeof document === 'undefined' ? 'light' : document.documentElement.dataset.theme || 'light')
  const [failed, setFailed] = useState(false)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    const observer = new MutationObserver(() => setTheme(document.documentElement.dataset.theme || 'light'))
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    setFailed(false)
    if (target.symbol) timeoutRef.current = setTimeout(() => setFailed(true), 12000)
    return () => { if (timeoutRef.current) clearTimeout(timeoutRef.current) }
  }, [target.symbol, theme])
  const unavailable = isStagedPreviewBuild || failed || !target.symbol
  const params = new URLSearchParams({ symbol: target.symbol || '', interval: 'D', theme, style: '1', locale: 'en', timezone: 'Etc/UTC', hide_side_toolbar: '0', allow_symbol_change: '0', save_image: '0' })
  return <section className={cls('tv-chart-card', className)}>
    <div className="tv-chart-head"><h3>{title}</h3><span>${symbol}</span></div>
    {unavailable ? <p role="status">Chart unavailable for this company.</p> : <iframe key={`${target.symbol}-${theme}`} title={`${symbol} price history — TradingView`} src={`https://www.tradingview.com/widgetembed/?${params}`} style={{ width: '100%', height: Math.max(240, Math.min(height, 500)), border: 0 }} onLoad={() => { if (timeoutRef.current) clearTimeout(timeoutRef.current) }} onError={() => setFailed(true)} />}
    <a href={target.url} target="_blank" rel="noopener noreferrer">{target.symbol ? 'Open interactive chart on TradingView' : `Search TradingView for ${symbol}`}</a>
    {!unavailable && <button type="button" className="text-link" onClick={() => setFailed(true)}>Chart not displaying? Show source link</button>}
  </section>
}
function tradingViewSymbolUrlForItem(item: { symbol: string; exchange?: string; tradingViewSymbol?: string }) {
  const tv = tradingViewSymbolForItem(item)?.replace('|1D', '')
  return tv ? `https://www.tradingview.com/symbols/${tv.replace(':', '-')}/` : tradingViewSymbolUrl(item.symbol, item.exchange)
}

export function TradingViewSymbolOverview({ symbols, title = 'Price context', className, height = 360 }: { symbols: ChartSymbolInput[]; title?: string; className?: string; height?: number }) {
  const cleanedSymbols = useMemo(() => {
    const bySymbol = new Map<string, { symbol: string; exchange?: string; tradingViewSymbol?: string }>()
    symbols.map(cleanChartSymbol).filter(item => tradingViewSymbolForItem(item)).forEach(item => {
      if (!bySymbol.has(item.symbol)) bySymbol.set(item.symbol, item)
    })
    return Array.from(bySymbol.values()).slice(0, 6)
  }, [symbols.map(chartSymbolInputKey).join('|')])
  const [chartTheme, setChartTheme] = useState(() => typeof document !== 'undefined' ? document.documentElement.dataset.theme || 'light' : 'light')
  const [unavailable, setUnavailable] = useState(false)
  useEffect(() => { const observer = new MutationObserver(() => setChartTheme(document.documentElement.dataset.theme || 'light')); observer.observe(document.documentElement, {attributes:true,attributeFilter:['data-theme']}); return () => observer.disconnect() }, [])
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    setUnavailable(false)
    if (cleanedSymbols.length) timeoutRef.current = setTimeout(() => setUnavailable(true), 20000)
    return () => { if (timeoutRef.current) clearTimeout(timeoutRef.current) }
  }, [cleanedSymbols.map(chartSymbolInputKey).join('|'), chartTheme])
  // Use the same iframe endpoint/config produced by TradingView's overview loader.
  // React owns its lifecycle, avoiding a late async script executing after theme/unmount cleanup.
  const overviewConfig = {
      lineWidth: 2,
      lineType: 0,
      chartType: 'area',
      fontColor: ownerChartPalette().text,
      gridLineColor: ownerChartPalette().border,
      volumeUpColor: 'rgba(34, 197, 94, 0.40)',
      volumeDownColor: 'rgba(248, 113, 113, 0.40)',
      backgroundColor: ownerChartPalette().surface,
      widgetFontColor: ownerChartPalette().text,
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderUpColor: '#22c55e',
      borderDownColor: '#ef4444',
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
      colorTheme: chartTheme,
      isTransparent: false,
      locale: 'en',
      chartOnly: false,
      scalePosition: 'right',
      scaleMode: 'Normal',
      fontFamily: '-apple-system, BlinkMacSystemFont, Trebuchet MS, Roboto, Ubuntu, sans-serif',
      valuesTracking: '1',
      changeMode: 'price-and-percent',
      symbols: cleanedSymbols.map(item => [item.symbol, tradingViewSymbolForItem(item)]),
      dateRanges: ['1d|1', '1m|30', '3m|60', '12m|1D', '60m|1W', 'all|1M'],
      fontSize: '10',
      headerFontSize: 'medium',
      autosize: true,
      width: '100%',
      height: '100%',
      noTimeScale: false,
      hideDateRanges: false,
      hideMarketStatus: false,
      hideSymbolLogo: false
  }
  const overviewSrc = `https://www.tradingview-widget.com/embed-widget/symbol-overview/?locale=en#${encodeURIComponent(JSON.stringify(overviewConfig))}`
  return <section className={cls('tv-chart-card', className)}>
    <div className="tv-chart-head"><div><span className="eyebrow">TradingView chart</span><h3>{title}</h3></div><span>{cleanedSymbols.map(s => `$${s.symbol}`).join(' / ')}</span></div>
    {(isStagedPreviewBuild || !cleanedSymbols.length || unavailable) && <p role="status">Chart unavailable for this company. Use the TradingView source link below.</p>}
    {!!cleanedSymbols.length && !isStagedPreviewBuild && !unavailable && <div className="tv-widget-frame" style={{ height }}><iframe key={`${cleanedSymbols.map(chartSymbolInputKey).join('|')}-${chartTheme}`} title={`${cleanedSymbols.map(s=>s.symbol).join(', ')} price overview — TradingView`} src={overviewSrc} style={{ width: '100%', height: '100%', border: 0 }} onLoad={() => { if (timeoutRef.current) clearTimeout(timeoutRef.current) }} onError={() => setUnavailable(true)} /></div>}
    <div className="markets-source-links">{symbols.map(cleanChartSymbol).map(item => { const target = companyChartTarget(item); return <a key={chartSymbolInputKey(item)} href={target.url} target="_blank" rel="noopener noreferrer">{target.symbol ? `Open ${item.symbol} on TradingView` : `Search TradingView for ${item.symbol}`}</a> })}</div>
    {!!cleanedSymbols.length && !isStagedPreviewBuild && !unavailable && <button type="button" className="text-link" onClick={() => setUnavailable(true)}>Chart not displaying? Show source link</button>}
  </section>
}

function BulletText({ text, empty = 'No detail captured yet.', symbols }: { text?: string; empty?: string; symbols?: Set<string> }) {
  const parts = lines(text, 7)
  if (!parts.length) return <p className="muted">{empty}</p>
  if (parts.length === 1) return <p><TickerAware text={parts[0]} symbols={symbols} /></p>
  return <ul className="clean-list">{parts.map(part => <li key={part}><TickerAware text={part} symbols={symbols} /></li>)}</ul>
}

function PostureCardView({ card, idx }: { card: PostureCard; idx: number }) {
  const emoji = ['🧭', '🌦️', '🎚️'][idx] || '📌'
  const delta = typeof card.delta === 'number' ? card.delta : null
  return <article className="posture-card">
    <div className="card-topline"><span className="eyebrow">{emoji} {card.name}</span><span>{typeof card.score === 'number' ? `Score ${Math.round(card.score)}` : publicAssessmentLabel(card.zone)}{delta !== null && <em className={cls('delta', delta > 0 && 'up', delta < 0 && 'down')}>{delta > 0 ? '+' : ''}{delta}</em>}</span></div>
    <h3>{card.plainTitle}</h3>
    <p>{card.plainEnglish}</p>
    {!!card.history?.length && <div className="score-trend" title="Recent daily/weekly score history">{card.history.map(point => <div key={`${card.name}-${point.date}`}><span style={{ height: `${Math.max(8, Math.min(100, point.score))}%` }} /><small>{point.score}</small></div>)}</div>}
    <ul>{(card.watch || []).filter(Boolean).slice(0, 3).map(w => <li key={w}>{w}</li>)}</ul>
  </article>
}

function cleanBullet(text: string) { return text.replace(/^•\s*/, '').trim() }
function pctFromText(text: string) { const m = text.match(/(?<![\d%])([+-]\d+(?:\.\d+)?)\s*%/); return m ? Number(m[1]) : null }
function directionFromText(text: string) { const pct = pctFromText(text); return pct === null ? 'flat' : pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat' }
function escapeRegex(text: string) { return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') }
const autoTickerSkip = new Set(['AI', 'API', 'ARR', 'BTC', 'CPI', 'CPU', 'CPO', 'DXY', 'ETF', 'ETFs', 'EV', 'FCF', 'FOMC', 'GPU', 'HBM', 'IRA', 'IRR', 'NATO', 'OFF', 'ON', 'PCE', 'PMI', 'RTH', 'SEC', 'TAM', 'USD', 'VWAP'])
function tickerRegex(symbols?: Set<string>) {
  const symbolAlternates = Array.from(symbols || [])
    .filter(symbol => /^[A-Z][A-Z0-9]{1,7}$/.test(symbol) && !autoTickerSkip.has(symbol))
    .sort((a, b) => b.length - a.length)
    .map(escapeRegex)
  const known = symbolAlternates.length ? `|\\b(?:${symbolAlternates.join('|')})\\b` : ''
  return new RegExp(`(\\$[A-Z][A-Z0-9]{1,7}\\b|(?<![\\d%])[+-]\\d+(?:\\.\\d+)?\\s*%${known})`, 'g')
}
function TickerAware({ text, symbols }: { text: string; symbols?: Set<string> }) {
  const parts = text.split(tickerRegex(symbols))
  return <>{parts.map((part, i) => {
    const key = `${i}-${part}`
    const pct = pctFromText(part)
    if (pct !== null) return <span key={key} className={cls('inline-move', pct > 0 && 'up', pct < 0 && 'down')}>{part}</span>
    if (part.match(/^\$?[A-Z][A-Z0-9]{1,7}\b$/) && !autoTickerSkip.has(part.replace(/^\$/, ''))) {
      const symbol = part.replace(/^\$/, '')
      return <span key={key} className="inline-ticker">${symbol}</span>
    }
    return <Fragment key={key}>{part}</Fragment>
  })}</>
}

function MarkdownInline({ text, symbols }: { text: string; symbols?: Set<string> }) {
  const parts = text.split(/(\[\[[^\]]+\]\]|\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\)|https?:\/\/[^\s<>]+|(?:\/?[\w.-]+\/)+[\w./-]+|[\w.-]+\.(?:md|json|csv|yaml|yml|txt))/g).filter(part => part !== '')
  return <>{parts.map((part, i) => {
    const key = `${i}-${part}`
    // Source identifiers are not prose: ticker styling must not rewrite their paths.
    if (/^(?:\[\[|https?:\/\/|(?:\/?[\w.-]+\/)+)|^[\w.-]+\.(?:md|json|csv|yaml|yml|txt)$/.test(part)) return <Fragment key={key}>{part}</Fragment>
    const bold = part.match(/^\*\*(.+)\*\*$/)
    if (bold) return <strong key={key}><TickerAware text={bold[1]} symbols={symbols} /></strong>
    const code = part.match(/^`([^`]+)`$/)
    if (code) return <code key={key}>{code[1]}</code>
    const link = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/)
    if (link) return <a key={key} href={link[2]} target="_blank" rel="noreferrer"><TickerAware text={link[1]} symbols={symbols} /></a>
    return <TickerAware key={key} text={part} symbols={symbols} />
  })}</>
}

function hasLeadingEmoji(text: string) { return /^[\u{1F300}-\u{1FAFF}\u2600-\u27BF]/u.test(text.trim()) }
function headingEmoji(text: string) {
  const s = text.toLowerCase()
  if (hasLeadingEmoji(text)) return ''
  if (/top actions|stocks worth|closer look|action posture|buy-zone|entry|scout|starter/.test(s)) return '🎯'
  if (/conviction|signal highlights|bullish|watch mentions/.test(s)) return '🔥'
  if (/regime|sentiment|macro|market setup|exposure|breadth|risk-on|risk-off/.test(s)) return '🧠'
  if (/source|cross-validated|convergence|validated|research feed/.test(s)) return '🔗'
  if (/portfolio|hedge|position|sizing/.test(s)) return '🧭'
  if (/war room|escalation|committee|decision/.test(s)) return '🏛️'
  if (/trim|kill|risk|avoid|warning|degraded|failure|fail/.test(s)) return '⚠️'
  if (/wiki|update|build|lint|research activity|verification/.test(s)) return '🛠️'
  if (/earnings|catalyst|calendar|event/.test(s)) return '📅'
  if (/gold|silver|metals/.test(s)) return '🟡'
  if (/cnbc|fast money|youtube|transcript|podcast/.test(s)) return '🎙️'
  return ''
}
function categoryEmoji(text: string) {
  const s = text.toLowerCase()
  if (/sentiment|source|radar/.test(s)) return '📡'
  if (/earnings|catalyst/.test(s)) return '📅'
  if (/portfolio|stock|decision/.test(s)) return '🎯'
  if (/market brief|research ops/.test(s)) return '🧠'
  if (/execution|trading/.test(s)) return '⚙️'
  return '📝'
}
function HeadingContent({ text, symbols, forcedEmoji }: { text: string; symbols?: Set<string>; forcedEmoji?: string }) {
  const icon = forcedEmoji || headingEmoji(text)
  return <>{icon && <span className="md-heading-icon" aria-hidden="true">{icon}</span>}<MarkdownInline text={text} symbols={symbols} /></>
}

function MarkdownOutput({ text, symbols }: { text: string; symbols?: Set<string> }) {
  const rawLines = (text || '').split('\n')
  const blocks: React.ReactNode[] = []
  let i = 0
  while (i < rawLines.length) {
    const line = rawLines[i]
    const trimmed = line.trim()
    if (!trimmed) { i += 1; continue }
    if (trimmed.startsWith('```')) {
      const codeLines: string[] = []
      i += 1
      while (i < rawLines.length && !rawLines[i].trim().startsWith('```')) { codeLines.push(rawLines[i]); i += 1 }
      i += rawLines[i]?.trim().startsWith('```') ? 1 : 0
      blocks.push(<pre className="md-code" key={`code-${i}`}>{codeLines.join('\n')}</pre>)
      continue
    }
    const heading = trimmed.match(/^(#{1,4})\s+(.+)$/)
    if (heading) {
      const level = Math.min(4, heading[1].length)
      const content = <HeadingContent text={heading[2]} symbols={symbols} />
      blocks.push(level === 1 ? <h3 className="md-heading" key={`h-${i}`}>{content}</h3> : level === 2 ? <h4 className="md-heading" key={`h-${i}`}>{content}</h4> : <h5 className="md-heading" key={`h-${i}`}>{content}</h5>)
      i += 1
      continue
    }
    const emojiBoldHeading = trimmed.match(/^([\u{1F300}-\u{1FAFF}\u2600-\u27BF][\uFE0F]?)\s+\*\*(.+?)\*\*\s*$/u)
    if (emojiBoldHeading) {
      blocks.push(<h4 className="md-heading" key={`emoji-h-${i}`}><HeadingContent text={emojiBoldHeading[2]} symbols={symbols} forcedEmoji={emojiBoldHeading[1]} /></h4>)
      i += 1
      continue
    }
    const boldHeading = trimmed.match(/^\*\*(.+?)\*\*\s*$/)
    if (boldHeading && boldHeading[1].length < 90) {
      blocks.push(<h4 className="md-heading" key={`bold-h-${i}`}><HeadingContent text={boldHeading[1]} symbols={symbols} /></h4>)
      i += 1
      continue
    }
    const isBullet = /^\s*[-*•]\s+/.test(line)
    const isNumbered = /^\s*\d+\.\s+/.test(line)
    if (isNumbered) {
      const groups: { title: string; details: string[] }[] = []
      while (i < rawLines.length) {
        while (i < rawLines.length && !rawLines[i].trim()) i += 1
        if (!/^\s*\d+\.\s+/.test(rawLines[i] || '')) break
        const title = rawLines[i].replace(/^\s*\d+\.\s+/, '').trim()
        i += 1
        const details: string[] = []
        while (i < rawLines.length) {
          const child = rawLines[i]
          const childTrim = child.trim()
          if (!childTrim) { i += 1; continue }
          if (/^\s*\d+\.\s+/.test(child) || /^#{1,4}\s+/.test(childTrim) || childTrim.startsWith('```')) break
          details.push(child.replace(/^\s*[-*•]\s+/, '').trim())
          i += 1
        }
        groups.push({ title, details })
      }
      blocks.push(<div className="md-action-list" key={`actions-${i}`}>{groups.map((group, idx) => <article className="md-action-item" key={`${idx}-${group.title}`}>
        <div className="md-action-title"><span className="md-action-number">{idx + 1}</span><strong><MarkdownInline text={group.title} symbols={symbols} /></strong></div>
        {!!group.details.length && <ul className="md-action-details">{group.details.map((detail, detailIdx) => <li key={`${detailIdx}-${detail}`}><MarkdownInline text={detail} symbols={symbols} /></li>)}</ul>}
      </article>)}</div>)
      continue
    }
    if (isBullet) {
      const items: string[] = []
      while (i < rawLines.length && /^\s*[-*•]\s+/.test(rawLines[i])) {
        items.push(rawLines[i].replace(/^\s*[-*•]\s+/, '').trim())
        i += 1
      }
      blocks.push(<ul className="md-list" key={`list-${i}`}>{items.map((item, idx) => <li key={`${idx}-${item}`}><MarkdownInline text={item} symbols={symbols} /></li>)}</ul>)
      continue
    }
    const para: string[] = [trimmed]
    i += 1
    while (i < rawLines.length) {
      const next = rawLines[i]
      const nextTrim = next.trim()
      if (!nextTrim || nextTrim.startsWith('```') || /^#{1,4}\s+/.test(nextTrim) || /^\s*[-*•]\s+/.test(next) || /^\s*\d+\.\s+/.test(next)) break
      para.push(nextTrim)
      i += 1
    }
    blocks.push(<p key={`p-${i}`}><MarkdownInline text={para.join(' ')} symbols={symbols} /></p>)
  }
  return <div className="markdown-output">{blocks}</div>
}

function trafficLight(stance: string) {
  const s = stance.toLowerCase()
  if (/urgent|breach|kill|trim|avoid|sell|cut|do not add|no chase/.test(s)) return '🔴'
  if (/add|buy|starter|scout|accumulate|new_entry_allowed/.test(s)) return '🟢'
  return '🟡'
}

function severityForText(text: string): CioDecision['severity'] {
  const s = text.toLowerCase()
  if (/urgent|breach|sell now|trim now|cash_priority|halt|fraud|thesis broken|kill trigger (?:hit|fired)/.test(s)) return 'urgent'
  if (/wait|watch|monitor|no chase|proof|selective|reduce|crowd|stale|warning|kill trigger|trim trigger|risk/.test(s)) return 'warning'
  if (/buy|add|starter|scout|new_entry_allowed|constructive|positive/.test(s)) return 'success'
  return 'info'
}

function stanceFromText(text: string) {
  const s = text.toLowerCase()
  if (/kill|sell|trim|avoid|cash_priority/.test(s)) return 'Risk off / reduce'
  if (/buy|add|starter|scout/.test(s)) return 'Actionable with guardrails'
  if (/hold|no change/.test(s)) return 'Hold / no change'
  if (/wait|watch|monitor|proof|no chase/.test(s)) return 'Watch / proof-gated'
  return 'Read-through'
}

function extractSymbols(text: string) {
  return Array.from(new Set(Array.from(text.matchAll(/\$([A-Z][A-Z0-9]{1,7})\b/g)).map(m => m[1]).filter(s => !autoTickerSkip.has(s))))
}

function splitDetails(text: string, max = 3) {
  return lines(text, max).map(x => x.replace(/^(Result|Convergence|Action posture|Tape \/ macro|X signal read|Macro \/ exposure context):\s*/i, '').trim()).filter(Boolean)
}
function fmtPrice(v?: number | null) { return typeof v === 'number' && Number.isFinite(v) ? `$${v.toFixed(v >= 100 ? 2 : 2)}` : '' }
function fmtPct(v?: number | null) { return typeof v === 'number' && Number.isFinite(v) ? `${v > 0 ? '+' : ''}${v.toFixed(1)}%` : '' }
function fmtMultiple(v?: number | null) { return typeof v === 'number' && Number.isFinite(v) ? `${v.toFixed(v >= 10 ? 1 : 2)}x` : '—' }
function fmtBig(v?: number | null) { if (typeof v !== 'number' || !Number.isFinite(v)) return '—'; const abs = Math.abs(v); if (abs >= 1_000_000_000) return `${(v / 1_000_000_000).toFixed(1)}B`; if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(0)}M`; return v.toFixed(0) }
function projectionTone(row: AiProjectionRow): StrategyRowTone { if (row.dataQualityLabel === 'strong' || row.capitalEligibleFromProjection) return 'success'; if (row.dataQualityLabel === 'missing') return 'danger'; if (row.dataQualityLabel === 'degraded') return 'warn'; return 'neutral' }
function chartNumber(v: unknown) { return typeof v === 'number' && Number.isFinite(v) ? v : null }
export function bubbleRadiusForEnterpriseValue(value: number | null | undefined, universe: number[], minRadius = 5, maxRadius = 28) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return minRadius
  const usable = universe.filter(v => Number.isFinite(v) && v > 0)
  if (!usable.length) return minRadius
  const minRoot = Math.sqrt(Math.min(...usable))
  const maxRoot = Math.sqrt(Math.max(...usable))
  if (maxRoot === minRoot) return (minRadius + maxRadius) / 2
  const normalized = (Math.sqrt(value) - minRoot) / (maxRoot - minRoot)
  return Number((minRadius + Math.max(0, Math.min(1, normalized)) * (maxRadius - minRadius)).toFixed(2))
}
export function isRelativeValueFocusPoint(growthPct: number, evNtmRevenue: number) {
  return growthPct >= -50 && growthPct <= 250 && evNtmRevenue >= 0 && evNtmRevenue <= 60
}
type BubbleLabelPoint = { symbol: string; x: number; y: number }

export function topOutlierLabelSymbols(points: BubbleLabelPoint[], maxLabels = 10) {
  const usable = points.filter(point => point.symbol && Number.isFinite(point.x) && Number.isFinite(point.y))
  if (!usable.length || maxLabels <= 0) return []
  const medianX = median(usable.map(point => point.x)) ?? 0
  const medianY = median(usable.map(point => point.y)) ?? 0
  const madX = median(usable.map(point => Math.abs(point.x - medianX))) ?? 0
  const madY = median(usable.map(point => Math.abs(point.y - medianY))) ?? 0
  const fallbackX = Math.max(...usable.map(point => Math.abs(point.x - medianX)), 1)
  const fallbackY = Math.max(...usable.map(point => Math.abs(point.y - medianY)), 1)
  const scaleX = madX > 0 ? 1.4826 * madX : fallbackX
  const scaleY = madY > 0 ? 1.4826 * madY : fallbackY
  return usable.map(point => ({
    ...point,
    robustDistance: Math.hypot((point.x - medianX) / scaleX, (point.y - medianY) / scaleY),
  })).sort((a, b) => b.robustDistance - a.robustDistance || a.symbol.localeCompare(b.symbol))
    .slice(0, Math.min(maxLabels, usable.length))
    .map(point => point.symbol)
}

function bubbleOutlierLabelPlugin(points: BubbleLabelPoint[], labeledSymbols: Set<string>, id: string): Plugin<'bubble'> {
  return {
    id,
    afterDatasetsDraw: chart => {
      const meta = chart.getDatasetMeta(0)
      const placed: Array<{ left: number; right: number; top: number; bottom: number }> = []
      chart.ctx.save()
      chart.ctx.font = '800 10px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif'
      chart.ctx.textAlign = 'center'
      chart.ctx.textBaseline = 'middle'
      chart.ctx.lineWidth = 3
      chart.ctx.strokeStyle = ownerChartPalette().surface
      chart.ctx.fillStyle = ownerChartPalette().text
      meta.data.forEach((element, index) => {
        const point = points[index]
        if (!point || !labeledSymbols.has(point.symbol)) return
        const radius = Number(element.options.radius || 5)
        const width = chart.ctx.measureText(point.symbol).width
        const halfWidth = width / 2
        const candidates = [
          { x: element.x, y: element.y - radius - 8 },
          { x: element.x, y: element.y + radius + 8 },
          { x: element.x + radius + halfWidth + 5, y: element.y },
          { x: element.x - radius - halfWidth - 5, y: element.y },
        ]
        const position = candidates.find(candidate => {
          const box = { left: candidate.x - halfWidth - 2, right: candidate.x + halfWidth + 2, top: candidate.y - 7, bottom: candidate.y + 7 }
          const inside = box.left >= chart.chartArea.left && box.right <= chart.chartArea.right && box.top >= chart.chartArea.top && box.bottom <= chart.chartArea.bottom
          const clear = placed.every(prior => box.right < prior.left || box.left > prior.right || box.bottom < prior.top || box.top > prior.bottom)
          if (inside && clear) { placed.push(box); return true }
          return false
        }) || candidates[0]
        chart.ctx.strokeText(point.symbol, position.x, position.y)
        chart.ctx.fillText(point.symbol, position.x, position.y)
      })
      chart.ctx.restore()
    },
  }
}
function chartColor(label?: string) { if (label === 'strong') return '#86efac'; if (label === 'missing') return '#fca5a5'; if (label === 'degraded') return '#fde68a'; return '#93c5fd' }
const chartTextColor = '#586473' // Shared tokens replace this before each update.
const chartGridColor = () => ownerChartPalette().border
const baseChartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  animation: false as const,
  plugins: {
    legend: { display: false },
    tooltip: { backgroundColor: 'rgba(15, 23, 42, .96)', titleColor: '#f8fafc', bodyColor: '#dbeafe', borderColor: 'rgba(148, 163, 184, .24)', borderWidth: 1 }
  },
  scales: {
    x: { ticks: { color: chartTextColor }, grid: { color: 'rgba(148, 163, 184, .08)' } },
    y: { ticks: { color: chartTextColor }, grid: { color: chartGridColor } }
  }
}

function InteractiveBarChart({ data, options }: { data: ChartData<'bar'>; options: ChartOptions<'bar'> }) {
  const [hiddenLabels, setHiddenLabels] = useState<Set<string>>(() => new Set())
  const visibleIndices = (data.labels || []).map((label, index) => ({ label: String(label), index })).filter(item => !hiddenLabels.has(item.label)).map(item => item.index)
  const visibleData: ChartData<'bar'> = {
    labels: visibleIndices.map(index => data.labels?.[index] ?? ''),
    datasets: data.datasets.map(dataset => ({
      ...dataset,
      data: visibleIndices.map(index => dataset.data[index]),
      backgroundColor: Array.isArray(dataset.backgroundColor) ? visibleIndices.map(index => (dataset.backgroundColor as unknown[])[index] as string) : dataset.backgroundColor,
      borderColor: Array.isArray(dataset.borderColor) ? visibleIndices.map(index => (dataset.borderColor as unknown[])[index] as string) : dataset.borderColor,
    })),
  }
  const interactiveOptions: ChartOptions<'bar'> = {
    ...options,
    onClick: (_event, elements) => {
      const index = elements[0]?.index
      const label = typeof index === 'number' ? String(visibleData.labels?.[index] ?? '') : ''
      if (label) setHiddenLabels(current => new Set(current).add(label))
    },
  }
  return <div className="interactive-bar-chart">
    <Bar data={visibleData} options={interactiveOptions} />
    {hiddenLabels.size ? <button type="button" className="bar-chart-reset" onClick={() => setHiddenLabels(new Set())}>Restore {hiddenLabels.size} hidden</button> : <span className="bar-chart-hint">Click bar to hide</span>}
  </div>
}
const appSoftwareSymbols = new Set<string>()
const aiCategorySymbolSets: Record<string, Set<string>> = {}
const aiCategoryColors: Record<string, string> = {
  'AI power / grid': '#f59e0b',
  'CPO / photonics': '#22d3ee',
  'AI semis / hardware': '#a78bfa',
  'Neocloud / AI infra': '#60a5fa',
  'Robotics / physical AI': '#34d399',
  'Defense / autonomy': '#f472b6',
  'Quantum / frontier': '#c084fc',
  'Other AI infra': '#94a3b8',
  'App / software layer': '#64748b',
}
type AiCategoryInput = { symbol?: unknown; archetype?: unknown; benchmarkGroup?: unknown; category?: unknown; companyName?: unknown; relativePeerValuation?: unknown; action?: unknown }
function rowSymbol(row: { symbol?: unknown }) { return String(row.symbol || '').replace(/^\$/, '').toUpperCase() }
function compareSymbols(a?: string, b?: string) { return String(a || '').localeCompare(String(b || ''), 'en', { numeric: true, sensitivity: 'base' }) }
function stableRowsBySymbol<T extends { symbol?: unknown }>(rows: T[]) { return [...rows].sort((a, b) => compareSymbols(rowSymbol(a), rowSymbol(b))) }
function stableRowsByNumberDesc<T extends { symbol?: unknown }>(rows: T[], value: (row: T) => number | null | undefined, limit?: number) {
  const sorted = [...rows].sort((a, b) => {
    const av = value(a)
    const bv = value(b)
    const an = typeof av === 'number' && Number.isFinite(av) ? av : -Infinity
    const bn = typeof bv === 'number' && Number.isFinite(bv) ? bv : -Infinity
    if (bn !== an) return bn - an
    return compareSymbols(rowSymbol(a), rowSymbol(b))
  })
  return typeof limit === 'number' ? sorted.slice(0, limit) : sorted
}
const EXTREME_MARGIN_ABS_CUTOFF = 500
function isExtremeMargin(value?: number | null) {
  return typeof value === 'number' && Number.isFinite(value) && Math.abs(value) > EXTREME_MARGIN_ABS_CUTOFF
}
function isComparableFcfMargin(row: Pick<AiWarRoomRow, 'fcfMarginPct' | 'ltmRevenue'>) {
  return typeof row.fcfMarginPct === 'number' && Number.isFinite(row.fcfMarginPct) && !isExtremeMargin(row.fcfMarginPct)
}
function ruleOf40(row: Pick<AiWarRoomRow, 'revenueGrowthPct' | 'fcfMarginPct' | 'ltmRevenue'>) {
  if (typeof row.revenueGrowthPct !== 'number' || !isComparableFcfMargin(row)) return null
  return row.revenueGrowthPct + (row.fcfMarginPct as number)
}
function CategoryPill({ category }: { category: string }) {
  return <span className="ai-category-pill"><i style={{ background: aiCategoryColor(category) }} />{category}</span>
}
function MarginValue({ value }: { value?: number | null }) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return <>—</>
  return <>{fmtPct(value)}{isExtremeMargin(value) && <small>pre-revenue outlier; excluded from margin charts</small>}</>
}
function aiCategoryForRow(row: AiCategoryInput) {
  const symbol = rowSymbol(row)
  if (appSoftwareSymbols.has(symbol)) return 'App / software layer'
  for (const [category, symbols] of Object.entries(aiCategorySymbolSets)) if (symbols.has(symbol)) return category
  const archetype = String(row.archetype || '').toLowerCase()
  const category = String(row.category || '').toLowerCase()
  const text = `${row.companyName || ''} ${row.relativePeerValuation || ''} ${row.action || ''} ${row.benchmarkGroup || ''} ${archetype} ${category}`.toLowerCase()
  if (/software|saas|app|consumer internet|streaming|advertising|fintech|crypto|insurance|insurer|brokerage/.test(text)) return 'App / software layer'
  if (/power|grid|energy|fuel|electrical|datacenter power|data-center power/.test(text)) return 'AI power / grid'
  if (/photonics|optical|cpo|transceiver|laser|glass|substrate/.test(text)) return 'CPO / photonics'
  if (/semiconductor|semis|chip|hbm|memory|advanced-packaging|metrology|wafer|quantum/.test(text)) return /quantum/.test(text) ? 'Quantum / frontier' : 'AI semis / hardware'
  if (/neocloud|gpu cloud|ai cloud|ai[- ]?infra|data center|datacenter/.test(text)) return 'Neocloud / AI infra'
  if (/robotics|autonomy|physical-ai|sensor|lidar|automation/.test(text)) return 'Robotics / physical AI'
  if (/defense|space|satellite|uas|rugged/.test(text)) return 'Defense / autonomy'
  return 'Other AI infra'
}
function isAiStockRow(row: AiCategoryInput) {
  const category = aiCategoryForRow(row)
  return category !== 'App / software layer'
}
function aiCategoryColor(rowOrCategory: AiCategoryInput | string) {
  const category = typeof rowOrCategory === 'string' ? rowOrCategory : aiCategoryForRow(rowOrCategory)
  return aiCategoryColors[category] || aiCategoryColors['Other AI infra']
}
function median(values: Array<number | null | undefined>) {
  const nums = values.filter((v): v is number => typeof v === 'number' && Number.isFinite(v)).sort((a, b) => a - b)
  if (!nums.length) return null
  const mid = Math.floor(nums.length / 2)
  return nums.length % 2 ? nums[mid] : (nums[mid - 1] + nums[mid]) / 2
}
function intradayHitDecision(hit: IntradayHit) {
  const level = fmtPrice(hit.wiki_level)
  const move = fmtPct(hit.pct_today)
  const price = fmtPrice(hit.price)
  if (/REVIEW_CANDIDATE/i.test(hit.action || '')) return `${price}${move ? ` (${move} today)` : ''} is review-ready${level ? ` near wiki level ${level}` : ''}. ${hit.technical_quality || ''}`.trim()
  return `${price}${move ? ` (${move} today)` : ''}: ${hit.trigger === 'near_level' && level ? `near wiki level ${level}` : 'dashboard-only tripwire'}. ${hit.technical_quality || ''}`.trim()
}
function normalizedText(text: string) {
  return text.toLowerCase().replace(/\$([a-z0-9]+)/g, '$1').replace(/[^a-z0-9%]+/g, ' ').replace(/\s+/g, ' ').trim()
}
function visibleRationale(decision: CioDecision) {
  const decisionNorm = normalizedText(decision.decision)
  const seen = new Set<string>()
  return decision.rationale.filter(r => {
    const norm = normalizedText(r)
    if (!norm || seen.has(norm)) return false
    seen.add(norm)
    return norm !== decisionNorm && !decisionNorm.includes(norm) && !norm.includes(decisionNorm)
  })
}

function shortlistRowSeverity(row: AsymmetricShortlistRow): CioDecision['severity'] {
  if (/kill|trim/i.test(row.actionMode || row.bucket || '')) return 'urgent'
  if (row.capitalEligible && /scout|starter|add|press/i.test(row.actionMode || '')) return 'success'
  return severityForText(`${row.freshness || ''} ${row.freshnessReason || ''} ${row.actionMode || ''}`)
}

function actionTextForShortlist(row: AsymmetricShortlistRow) {
  const action = row.actionMode || (row.capitalEligible ? 'Scout' : 'Wait')
  const ticker = row.symbol ? `$${row.symbol}` : 'Portfolio'
  if (/wait/i.test(action) && row.freshness !== 'fresh') return `${ticker}: refresh first — ${row.freshnessReason || 'data is not capital-fresh.'}`
  return `${ticker}: ${action} — ${row.whyThisHelps50to100 || row.entry || row.state || 'fresh setup under review.'}`
}

/** Availability metadata only; the investment evaluator below is unchanged. */
export function hasEntryAssessmentInputs(rows: AsymmetricShortlistRow[]) {
  return rows.length > 0 && rows.every(row =>
    typeof row.capitalEligible === 'boolean'
    && typeof row.entryEligible === 'boolean'
    && DEFAULT_MEMBERSHIP_BUCKETS.includes(row.bucket)
    && !!row.entryStatus && row.entryStatus !== 'Assessment unavailable'
    && !!row.actionMode && row.actionMode !== 'Assessment unavailable',
  )
}

export function actionableEntryRows(rows: AsymmetricShortlistRow[]) {
  return rows
    .filter(row =>
      row.capitalEligible === true
      && row.entryEligible === true
      && row.entryStatus === 'inside_zone'
      && ['Buy / Scout Now', 'Add After Proof'].includes(row.bucket)
      && /scout|starter|add|press/i.test(row.actionMode || ''),
    )
    .sort((a, b) => Number(a.capitalPriority ?? 99) - Number(b.capitalPriority ?? 99) || a.symbol.localeCompare(b.symbol))
}

function buildCioDecisions(data: DashboardData): CioDecision[] {
  const latest = data.dailyJournal[0]
  const decisions: CioDecision[] = []
  const push = (d: CioDecision) => decisions.push(d)
  const shortlist = data.currentAsymmetricShortlist
  const liveRows = (shortlist?.rows || [])
    .filter(row => row.bucket === 'Buy / Scout Now' || row.bucket === 'Add After Proof')
    .sort((a, b) => Number(a.capitalPriority || 99) - Number(b.capitalPriority || 99))
  const topLiveRows = liveRows.filter(row => row.capitalEligible).slice(0, 3)
  ;(topLiveRows.length ? topLiveRows : liveRows.slice(0, 3)).forEach(row => push({
    id: `return-engine-row-${row.rank || row.symbol}-${row.symbol}`,
    symbol: row.symbol,
    scope: 'Return engine / next dollar',
    stance: row.actionMode || stanceFromText(`${row.state || ''} ${row.freshness || ''}`),
    decision: actionTextForShortlist(row),
    rationale: [row.opportunityCost, row.proofTrigger, row.killTrigger, row.freshnessReason].filter((x): x is string => Boolean(x)).slice(0, 3),
    proof: row.proofTrigger,
    kill: row.killTrigger,
    source: 'Single live shortlist / 50-100% lens',
    severity: shortlistRowSeverity(row),
  }))
  ;(shortlist?.actionChanges || []).slice(0, 3).forEach(change => push({
    id: `return-engine-change-${change.symbol}-${change.changeType}`,
    symbol: change.symbol,
    scope: 'Return engine / what changed',
    stance: change.action || stanceFromText(`${change.headline} ${change.freshness}`),
    decision: change.headline || `$${change.symbol}: ${change.action || 'Review'}`,
    rationale: [change.whyThisHelps50to100, change.opportunityCost, change.expiresAt ? `Decision expires: ${change.expiresAt}` : ''].filter((x): x is string => Boolean(x)).slice(0, 3),
    proof: change.whyThisHelps50to100,
    source: 'Single live shortlist / actionChanges',
    severity: change.slackWorthy || /scout|starter|add|press/i.test(change.action || '') ? 'success' : severityForText(`${change.freshness} ${change.headline}`),
  }))
  ;(shortlist?.decisionLearning?.openExceptions || []).slice(0, 3).forEach(exception => push({
    id: `decision-learning-${exception.id}`,
    symbol: exception.symbol,
    scope: 'Decision learning exception',
    stance: 'Review process, not price',
    decision: exception.question,
    rationale: [exception.classification, exception.nextReviewEvent, exception.lessonCandidate].filter((x): x is string => Boolean(x)).slice(0, 3),
    proof: exception.sourceReceiptId,
    source: 'Weekly IC / curated exception queue',
    severity: 'warning',
  }))
  if (!decisions.length) push({
    id: 'return-engine-no-action',
    scope: 'Return engine / next dollar',
    stance: 'No action optimal',
    decision: 'No action today — no fresh setup beats opportunity cost.',
    rationale: ['Refresh stale candidates, wait for trigger, or keep capital in existing winners/cash.', 'Proof gates are sizing gates; they should not force mediocre buys.'],
    source: 'Single live shortlist / 50-100% lens',
    severity: 'info',
  })
  const postureText = data.marketPosture?.map(p => `${p.name}: ${p.plainTitle}`).join(' | ') || latest?.summary || ''
  if (postureText) push({ id: 'posture', scope: 'Macro / exposure', stance: stanceFromText(postureText), decision: postureText, rationale: splitDetails(postureText, 2), source: 'Exposure Coach / dashboard posture', severity: severityForText(postureText) })
  const intraday = data.intradayEquityWatchdog
  ;(intraday?.review_candidates || []).slice(0, 4).forEach(hit => push({
    id: `intraday-review-${hit.symbol}-${hit.trigger}`,
    symbol: hit.symbol,
    scope: 'Intraday tripwire',
    stance: 'Review candidate / confirmation-gated',
    decision: intradayHitDecision(hit),
    rationale: [hit.technical_note || '', hit.context || ''].filter(Boolean).slice(0, 2),
    proof: hit.context,
    source: 'Consolidated conviction + pullback tripwire',
    severity: 'success',
  }))
  // Routine tripwire health is not a front-page decision. It belongs in Ops/evidence
  // unless a name is actually review-ready.
  ;(data.marketGraphs || []).forEach(graph => {
    const interruptEvents = (graph.decisionEvents || [])
      .filter(event => event.slackWorthy || graphGateSeverity(event.gate) === 'urgent')
      .slice(0, 3)
    interruptEvents.forEach(event => push({
      id: `graph-event-${event.id}`,
      scope: `Ops exception / ${event.scope || 'checker'}`,
      stance: graphGateLabel(event.gate),
      decision: `${ownerOperationsText(graph.label)}: ${event.decision}`,
      rationale: [...(event.blockedBy || []), ...(event.proof || [])].slice(0, 3),
      proof: event.sourcePaths?.[0] || graph.checkerPath,
      source: event.slackWorthy ? 'Workflow Ops / Attention required' : 'Workflow Ops / failure',
      severity: graphGateSeverity(event.gate),
    }))
    if (!interruptEvents.length && graphGateSeverity(graph.finalGate) === 'urgent') push({
      id: `graph-${graph.workflowId}`,
      scope: 'Ops exception',
      stance: graphGateLabel(graph.finalGate),
      decision: `${ownerOperationsText(graph.label)}: ${graph.recommendation || 'checker failed'}`,
      rationale: [...(graph.blockedNodes || []), ...(graph.selfHealSummary || []), ...(graph.privacyFindings || [])].slice(0, 3),
      proof: graph.checkerPath,
      source: 'Workflow Ops / failure',
      severity: 'urgent',
    })
  })

  ;(latest?.portfolioActions || []).filter(a => a.text).slice(0, 4).forEach((a, i) => push({ id: `portfolio-${i}`, symbol: a.symbol, scope: 'Portfolio', stance: a.stance || stanceFromText(a.text), decision: a.text, rationale: splitDetails(a.text, 2), source: 'Latest daily brief', severity: severityForText(`${a.stance} ${a.text}`) }))
  ;(latest?.actionCallouts || []).slice(0, 5).forEach((a, i) => push({ id: `callout-${i}-${a.symbol}`, symbol: a.symbol, scope: 'Ticker', stance: stanceFromText(`${a.action} ${(a.details || []).join(' ')}`), decision: a.action, rationale: (a.details || []).slice(0, 3), proof: (a.details || []).find(x => /proof|trigger|why now/i.test(x)), kill: (a.details || []).find(x => /kill|risk|cut/i.test(x)), source: 'Latest action callout', severity: severityForText(`${a.action} ${(a.details || []).join(' ')}`) }))
  ;(latest?.keyTakeaways || []).filter(x => /action posture|add-size|kill trigger|proof|no chase|new_entry_allowed|cash_priority|reduce_only/i.test(x)).slice(0, 4).forEach((x, i) => push({ id: `takeaway-${i}`, scope: 'Research ops', stance: stanceFromText(x), decision: x.replace(/^[🟢🟡🔴⚪📌⚠️ ]+/, ''), rationale: splitDetails(x, 2), source: latest?.headline || 'Latest brief', severity: severityForText(x) }))
  const seen = new Set<string>()
  return decisions.filter(d => {
    const key = `${d.symbol || d.scope}|${d.decision.slice(0, 90)}`.toLowerCase()
    if (seen.has(key)) return false
    seen.add(key)
    return true
  }).slice(0, 10)
}

function buildSourceSignals(data: DashboardData): SourceSignal[] {
  const latest = data.dailyJournal[0]
  const focusSymbols = new Set([...(latest?.interestingTickers || []).map(t => t.symbol), ...data.focusTickers.map(t => t.symbol)])
  const signals: SourceSignal[] = []
  ;(latest?.keyTakeaways || []).filter(x => /x signal read|source pack|sentiment|crowding/i.test(x)).slice(0, 2).forEach((raw, idx) => {
    const signal = raw.replace(/^[🟢🟡🔴⚪📌⚠️ ]+/, '').trim()
    const symbols = extractSymbols(signal)
    signals.push({ id: `brief-signal-${idx}`, sourceType: 'X/news source pack', title: latest?.headline || 'Latest source-pack signal', sourcePath: latest?.items?.[0]?.sourcePath || 'daily brief', signal, convergence: symbols.filter(s => focusSymbols.has(s)).slice(0, 4), symbols: symbols.slice(0, 6) })
  })
  ;(latest?.items || []).filter(item => item.sourceType !== 'Daily research brief').forEach((item, idx) => {
    const candidate = [...(item.highlights || []), item.summary].map(x => (x || '').replace(/^[🟢🟡🔴⚪📌⚠️ ]+/, '').trim()).find(x => x.length > 80 && !/^(raw|source|links|command|verification):/i.test(x) && !/stale feedback|do not reply now/i.test(x))
    if (!candidate) return
    const symbols = extractSymbols(candidate)
    const convergence = symbols.filter(s => focusSymbols.has(s)).slice(0, 4)
    const meaningful = convergence.length || /macro|fed|liquidity|crowd|sentiment|short|proof|customer|order|backlog|estimate|memory|photonics|power|gold|software|ai/i.test(candidate)
    if (!meaningful) return
    signals.push({ id: `${publicSourceReference(item.sourcePath)}-${idx}`, sourceType: item.sourceType, title: item.title, sourcePath: item.sourcePath, signal: candidate, convergence, symbols: symbols.slice(0, 6) })
  })
  const seen = new Set<string>()
  return signals.filter(s => {
    const key = `${s.sourceType}|${s.signal.slice(0, 100)}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  }).slice(0, 6)
}

function DecisionPill({ severity }: { severity: CioDecision['severity'] }) {
  const label = severity === 'urgent' ? 'Action / risk' : severity === 'warning' ? 'Watch' : severity === 'success' ? 'Opportunity' : 'Info'
  return <span className={cls('decision-pill', severity)}>{label}</span>
}

function graphGateSeverity(gate?: string): CioDecision['severity'] {
  const normalized = (gate || '').toLowerCase()
  if (normalized === 'fail' || normalized === 'missing') return 'urgent'
  if (normalized === 'degraded' || normalized === 'unknown') return 'warning'
  return 'success'
}

export function graphGateLabel(gate?: string) {
  const normalized = (gate || 'unknown').toLowerCase()
  if (normalized === 'pass') return 'Healthy'
  if (normalized === 'degraded') return 'Update delayed'
  if (normalized === 'fail') return 'Needs attention'
  if (normalized === 'missing') return 'Unavailable'
  return 'Status unavailable'
}

function GraphGatePill({ gate }: { gate?: string }) {
  return <span className={cls('decision-pill', graphGateSeverity(gate))}>{graphGateLabel(gate)}</span>
}

function uniqueLines(items: Array<string | undefined>, limit = 6) {
  const seen = new Set<string>()
  return items.map(x => (x || '').trim()).filter(Boolean).filter(x => {
    const key = x.toLowerCase().replace(/\s+/g, ' ')
    if (seen.has(key)) return false
    seen.add(key)
    return true
  }).slice(0, limit)
}

function workflowIssueLines(graph: MarketGraphWorkflow) {
  return uniqueLines([
    ...groupedWarningEvents([graph]).map(group => group.decision),
    ...(graph.brokerSafetyFindings || []),
    ...(graph.selfHealSummary || []).map(x => `Self-heal: ${x}`),
  ], 5)
}

function laneFromDegradedDecision(decision: string) {
  const match = decision.match(/^([a-z0-9_\-]+) is degraded; downgrade or block synthesis for this lane\.$/i)
  return match?.[1]
}

type OpsEventGroup = {
  id: string
  graph: MarketGraphWorkflow
  gate: string
  scope: string
  generatedAt?: string
  slackWorthy: boolean
  decision: string
  proof: string[]
}

function groupedWarningEvents(graphs: MarketGraphWorkflow[]): OpsEventGroup[] {
  const groups = new Map<string, OpsEventGroup & { lanes: string[] }>()
  graphs.forEach(graph => {
    const events = graph.decisionEvents || []
    const hasSpecificWarning = events.some(event => !event.id.endsWith(':status') && (graphGateSeverity(event.gate) !== 'success' || event.slackWorthy))
    events.forEach(event => {
      if (graphGateSeverity(event.gate) === 'success' && !event.slackWorthy) return
      if (event.id.endsWith(':status') && hasSpecificWarning && graphGateSeverity(event.gate) !== 'urgent') return
    const lane = laneFromDegradedDecision(event.decision)
    const proofKey = uniqueLines(event.proof || [], 4).join('|').toLowerCase()
    const key = lane
      ? `${graph.workflowId}:${event.runId || graph.runId}:stale-lanes:${event.gate}:${event.scope}:${proofKey}`
      : `${graph.workflowId}:${event.runId || graph.runId}:${event.gate}:${event.scope}:${event.decision.toLowerCase().replace(/\s+/g, ' ')}`
    const current = groups.get(key)
    if (current) {
      if (lane && !current.lanes.includes(lane)) current.lanes.push(lane)
      current.proof = uniqueLines([...current.proof, ...(event.proof || [])], 4)
      current.slackWorthy = current.slackWorthy || event.slackWorthy
      return
    }
    groups.set(key, {
      id: key,
      graph,
      gate: event.gate,
      scope: event.scope,
      generatedAt: event.generatedAt || graph.generatedAt,
      slackWorthy: event.slackWorthy,
      decision: event.decision,
      proof: uniqueLines(event.proof || [], 4),
      lanes: lane ? [lane] : [],
    })
    })
  })
  return Array.from(groups.values()).map(group => ({
    ...group,
    decision: group.lanes.length
      ? `${group.lanes.length} degraded stale lane${group.lanes.length > 1 ? 's' : ''}: ${group.lanes.join(', ')}. Downgrade/block ${group.lanes.length > 1 ? 'these lanes' : 'this lane'} until freshness recovers.`
      : group.decision,
  }))
}

function SourceMix({ day }: { day: JournalDay }) {
  const sourceText = `${day.sourceTypes.join(' ')} ${day.items.map(i => `${i.sourceType} ${i.title} ${i.sourcePath}`).join(' ')}`.toLowerCase()
  const mix = [
    ['News / official', /daily research brief|daily note|news|fed|official|marketwatch|cnbc|yahoo/],
    ['X signal', /x signal|twitter/],
    ['Macro transcripts', /macro transcript|market media|transcript/],
    ['Blogs / web', /web\/blog|blog|last30days|feeds/],
    ['Wiki memory', /deep dive|ticker|wiki|research/],
  ].filter(([, rx]) => (rx as RegExp).test(sourceText)).map(([label]) => label as string)
  if (!mix.length) return null
  return <section className="source-mix"><span className="eyebrow">Source mix</span><div>{mix.map(x => <span key={x}>{x}</span>)}</div></section>
}

function PortfolioActions({ actions, symbols }: { actions?: PortfolioAction[]; symbols?: Set<string> }) {
  const visible = (actions || []).filter(a => a.text).slice(0, 7)
  if (!visible.length) return null
  return <section className="portfolio-actions"><h3>💼 Portfolio adjustment?</h3><div>{visible.map((a, i) => <article key={`${a.symbol || 'portfolio'}-${i}`}><div className="portfolio-action-head"><span className="traffic-light" aria-label="traffic light">{trafficLight(a.stance)}</span><strong>{a.symbol ? `$${a.symbol}` : 'Portfolio'}</strong><span className="portfolio-stance">{a.stance}</span></div><p><TickerAware text={a.text} symbols={symbols} /></p></article>)}</div></section>
}

function AgenticCardBody({ label, text, symbols }: { label: string; text: string; symbols?: Set<string> }) {
  const raw = text || ''
  const split = raw.includes('\n')
    ? raw.split(/\n+/)
    : raw.split(/(?=\s*\d+\.\s+\$?[A-Z][A-Z0-9]{1,7}\b\s+[—-])/g)
  const rows = split.map(x => x.trim()).filter(Boolean)
  const isList = rows.length > 1 || /candidate watchlist/i.test(label)
  if (isList && rows.length) {
    return <ul className="agentic-card-list">{rows.map(row => <li key={row}><TickerAware text={row} symbols={symbols} /></li>)}</ul>
  }
  return <p><TickerAware text={raw} symbols={symbols} /></p>
}

function AgenticTradingReportCard({ report, symbols }: { report?: AgenticTradingReport | null; symbols?: Set<string> }) {
  if (!report) return null
  return <section className="agentic-trading-report">
    <div className="agentic-report-head"><div><span className="eyebrow">Agentic trading report</span><h3>{report.traffic} {report.lane || 'Trading'} — {report.date}</h3></div><span>{publicAssessmentLabel(report.status)}</span></div>
    <p>{report.summary}</p>
    <div className="agentic-report-grid">{report.cards.slice(0, 6).map(card => <article key={card.label}><strong>{card.label}</strong><AgenticCardBody label={card.label} text={card.text} symbols={symbols} /></article>)}</div>
    {!!report.learningNotes?.length && <ul>{report.learningNotes.map(note => <li key={note}><TickerAware text={note} symbols={symbols} /></li>)}</ul>}
    <small>{publicSourceReference(report.sourcePath)}</small>
  </section>
}

function AgenticTradingReports({ reports, symbols }: { reports?: AgenticTradingReport[]; symbols?: Set<string> }) {
  const visible = (reports || []).filter(Boolean)
  if (!visible.length) return null
  return <div className="agentic-trading-reports">{visible.map(report => <AgenticTradingReportCard key={`${report.lane}-${report.date}`} report={report} symbols={symbols} />)}</div>
}

function MarketNarrativeCard({ day, symbols }: { day: JournalDay; symbols?: Set<string> }) {
  const bullets = (day.marketNarrative?.bullets || day.keyTakeaways || []).map(cleanBullet).filter(Boolean).slice(0, 6)
  if (!bullets.length) return null
  return <section className="market-story">
    <div><span className="eyebrow">Macro narrative</span><h3>{day.marketNarrative?.title || 'What the tape is saying'}</h3></div>
    <ul>{bullets.map((b, i) => <li key={`${i}-${b}`}><TickerAware text={b} symbols={symbols} /></li>)}</ul>
  </section>
}

function MarketBriefSupport({ day, data, symbols, onSelectTicker }: { day: JournalDay; data: DashboardData; symbols: Set<string>; onSelectTicker: (symbol: string) => void }) {
  const researchSymbols = new Set(data.tickers.map(t => t.symbol))
  return <section className="cio-card market-brief-support">
    <div className="section-header"><div><span className="eyebrow">Bridge: market brief → PM decisions</span><h3>Supporting market brief</h3><p>The brief is the tape/source/evidence layer. It supports decisions, but does not equal a buy/sell instruction by itself.</p></div></div>
    <div className="bridge-grid">
      <article><strong>Top decisions</strong><p>PM synthesis: actionable status, proof gates, sizing posture, and whether Slack should interrupt.</p></article>
      <article><strong>Capital queue</strong><p>The membership table is the single decision source; stale or proof-incomplete rows stay blocked.</p></article>
      <article><strong>Market brief</strong><p>Context layer: macro, tape, sentiment, source-pack read-throughs, and what changed today.</p></article>
      <article><strong>Brief-mentioned tickers</strong><p>Source/tape leads from the market brief. These are not another buy list unless promoted above.</p></article>
    </div>
    <div className="brief-support-grid">
      <div>
        <MarketNarrativeCard day={day} symbols={symbols} />
        <PortfolioActions actions={day.portfolioActions} symbols={symbols} />
      </div>
      <div>
        {!!day.interestingTickers?.length && <section className="ticker-watch brief-watch"><h3>👀 Brief-mentioned tickers / signals</h3><p>Opinion/sentiment/source leads from the market brief. Click only to drill down; treat as “watch/research,” not action.</p><div>{day.interestingTickers.map(t => {
          const hasResearch = t.hasResearch ?? researchSymbols.has(t.symbol)
          const dir = t.direction || 'flat'
          const label = typeof t.changePct === 'number' ? `${t.changePct > 0 ? '+' : ''}${t.changePct.toFixed(1)}%` : '•'
          return <button className={dir} title={hasResearch ? `${t.why}\n\nOpen in Stock research` : t.why} key={t.symbol} disabled={!hasResearch} onClick={() => onSelectTicker(t.symbol)}><strong>${t.symbol}</strong><small className={cls('move-pct', dir)}>{label}</small></button>
        })}</div></section>}
        <section className="takeaways brief-takeaways"><h3>🧠 Brief evidence that matters</h3><ul>{day.keyTakeaways.map(cleanBullet).filter(Boolean).slice(0, 6).map((t, i) => <li key={`${i}-${t}`}><TickerAware text={t} symbols={symbols} /></li>)}</ul></section>
      </div>
    </div>
  </section>
}

const DEFAULT_MEMBERSHIP_BUCKETS = ['Buy / Scout Now', 'Wait for Trigger', 'Add After Proof', 'Research Memory / Not Live Action', 'Kill / Do Not Average']

function membershipTone(status?: string) {
  if (/pass|ok|healthy/i.test(status || '')) return 'success'
  if (/fail|error|missing/i.test(status || '')) return 'urgent'
  if (/degrad|inactive|stale/i.test(status || '')) return 'warning'
  return 'neutral'
}

function compactReason(text?: string, max = 118) {
  const clean = (text || '').replace(/^add only after\s+/i, '').trim()
  if (clean.length <= max) return clean
  const clipped = clean.slice(0, max + 1).replace(/\s+\S*$/, '').replace(/[,:;.!?\s]+$/, '')
  return `${clipped}…`
}

function membershipAction(row: AsymmetricShortlistRow) {
  const bucket = row.bucket || ''
  let label = row.actionMode || 'Wait'
  if (/kill/i.test(bucket)) label = 'Do not average'
  else if (/research memory/i.test(bucket)) label = 'Research only'
  else if (/add after proof/i.test(bucket)) label = 'Add after proof'
  else if (/buy|scout/i.test(bucket)) label = 'Scout now'
  else if (/stale|refresh/i.test(row.freshness || '')) label = 'Refresh research'
  else if (row.entryStatus === 'above_zone') label = 'No chase'
  else if (row.entryStatus === 'below_zone') label = 'Re-underwrite'
  else if (row.entryStatus === 'zone_missing') label = 'Define entry'
  else if (/wait/i.test(bucket)) label = 'Wait for proof'
  const fullReason = row.bucketReason || row.whyNotNow || row.entryReason || row.freshnessReason || publicAssessmentLabel(row.state)
  return { label, reason: compactReason(fullReason), fullReason }
}

// Explanations paraphrase the canonical shortlist decision rules and section definitions.
// They describe bucket meaning, never infer a company's assignment from its price or reason.
export const MEMBERSHIP_BUCKET_GUIDE = [
  { bucket: 'Buy / Scout Now', label: 'Buy / Scout Now', tone: 'success', meaning: 'Candidate for an initial position. Current research, entry, freshness and risk checks still apply.' },
  { bucket: 'Wait for Trigger', label: 'Wait for Trigger', tone: 'warning', meaning: 'Wait for the stated entry condition or event. A watch item is not unconditional permission to buy.' },
  { bucket: 'Add After Proof', label: 'Add After Proof', tone: 'warning', meaning: 'Further buying is conditional on the required business evidence and entry conditions.' },
  { bucket: 'Research Memory / Not Live Action', label: 'Research only', tone: 'neutral', meaning: 'Retain the thesis for research; not a live action candidate. Revisit when the missing evidence arrives.' },
  { bucket: 'Kill / Do Not Average', label: 'Kill / Do Not Average', tone: 'urgent', meaning: 'Not a candidate for averaging down. Reopen only when the stated primary-evidence conditions are met.' },
] as const

export function ShortlistMembershipSection({ shortlist, onSelectTicker }: { shortlist?: AsymmetricShortlist | null; onSelectTicker: (symbol: string) => void }) {
  if (!shortlist) return <p className="markets-empty">Membership data is unavailable in this edition.</p>
  const rows = shortlist.rows || []
  const order = new Map<string, number>(MEMBERSHIP_BUCKET_GUIDE.map((item,index)=>[item.bucket,index]))
  const sortedRows = [...rows].sort((a,b)=>(order.get(a.bucket) ?? 99)-(order.get(b.bucket) ?? 99) || Number(a.rank || 999)-Number(b.rank || 999) || a.symbol.localeCompare(b.symbol))
  const symbols = new Set(rows.map(item=>item.symbol))
  const missing = rows.filter(row=>!order.has(row.bucket)).length
  return <section className="membership-card membership-compact">
    <div className="section-header"><div><h3>Membership buckets</h3><p>One company, one bucket, and the source reason.</p></div><small>{rows.length} companies · List updated {fmtDate(shortlist.generatedAt)}</small></div>
    {missing>0 && <p className="markets-metadata">{missing} company {missing===1?'assignment is':'assignments are'} unavailable in this staged edition. Reasons are retained; no bucket is inferred from them.</p>}
    <div className="membership-layout">
      <div className="table-scroll"><table className="membership-matrix membership-list"><thead><tr><th>Company</th><th>Membership bucket</th><th>Reason</th></tr></thead>
        <tbody>{sortedRows.map(row=>{const definition=MEMBERSHIP_BUCKET_GUIDE.find(item=>item.bucket===row.bucket);const reason=row.bucketReason || row.whyNotNow || row.entryReason || row.freshnessReason || 'Source reason unavailable.';return <tr key={row.symbol}>
          <td><button className="text-link membership-ticker" onClick={()=>onSelectTicker(row.symbol)}>${row.symbol}</button></td>
          <td><span className={cls('membership-bucket-label',definition?.tone || 'neutral')}>{definition?.label || 'Assessment unavailable'}</span></td>
          <td className="membership-reason"><TickerAware text={reason} symbols={symbols}/></td>
        </tr>})}</tbody></table></div>
      <aside className="membership-guide" aria-label="Membership bucket meanings"><h4>What each bucket means</h4><dl>{MEMBERSHIP_BUCKET_GUIDE.map(item=><div key={item.bucket}><dt className={cls('membership-bucket-label',item.tone)}>{item.label}</dt><dd>{item.meaning}</dd></div>)}</dl>{missing>0&&<p className="markets-metadata">Assessment unavailable means this edition has no usable assignment—not a buy, wait, or sell conclusion.</p>}</aside>
    </div>
  </section>
}

export function CioBrief({ data, onSelectTicker }: { data: DashboardData; onSelectTicker: (symbol: string) => void }) {
  const latest = data.dailyJournal[0]
  const knownSymbols = useMemo(() => new Set([...data.tickers.map(t => t.symbol), ...(data.intradayEquityWatchdog?.monitored_symbols || [])]), [data.tickers, data.intradayEquityWatchdog])
  const sourceSignals = useMemo(() => buildSourceSignals(data), [data])
  const shortlist = data.currentAsymmetricShortlist
  return <section className="cio-page">
    <ShortlistMembershipSection shortlist={shortlist} onSelectTicker={onSelectTicker} />

    {(!!sourceSignals.length || latest) && <details className="cio-card evidence-details">
      <summary>Supporting evidence and sources</summary>
      {!!sourceSignals.length && <div className="source-signal-panel compact">
        <div className="section-header"><div><span className="eyebrow">Commentary and corroboration</span><h3>Only matters if it changes action</h3><p>X / blogs / YouTube / TV are treated as signal, sentiment, or crowding until corroborated by primary proof.</p></div></div>
        <div className="source-signal-grid">{sourceSignals.slice(0, 3).map(signal => <article key={signal.id}>
          <div className="source-signal-head"><span>{signal.sourceType}</span>{!!signal.convergence.length && <em>Converges: {signal.convergence.map(s => `$${s}`).join(', ')}</em>}</div>
          <h4>{signal.title}</h4>
          <p><TickerAware text={signal.signal} symbols={knownSymbols} /></p>
          <small>{publicSourceReference(signal.sourcePath)}</small>
        </article>)}</div>
      </div>}
      {latest && <MarketBriefSupport day={latest} data={data} symbols={knownSymbols} onSelectTicker={onSelectTicker} />}
    </details>}
  </section>
}

function MarketUpdates({ data, onSelectTicker }: { data: DashboardData; onSelectTicker: (symbol: string) => void }) {
  const researchSymbols = new Set(data.tickers.map(t => t.symbol))
  const knownSymbols = new Set([
    ...data.tickers.map(t => t.symbol),
    ...data.dailyJournal.flatMap(day => [
      ...(day.interestingTickers || []).map(t => t.symbol),
      ...(day.portfolioActions || []).map(a => a.symbol || ''),
      ...(day.actionCallouts || []).map(a => a.symbol),
    ]),
  ].filter(Boolean))
  return <section className="tab-panel">
    <div className="journal-list">
      {data.dailyJournal.map((day, dayIdx) => <article className="journal-day" key={day.date}>
        <header><div><span className="eyebrow">{day.date}</span><h2>{day.headline}</h2></div><div className="source-pills">{day.sourceTypes.map(s => <span key={s}>{s}</span>)}</div></header>
        <SourceMix day={day} />
        <MarketNarrativeCard day={day} symbols={knownSymbols} />
        <PortfolioActions actions={day.portfolioActions} symbols={knownSymbols} />
        {dayIdx === 0 && <AgenticTradingReports reports={data.agenticTradingReports || (data.agenticTradingReport ? [data.agenticTradingReport] : [])} symbols={knownSymbols} />}
        {!!day.interestingTickers?.length && <section className="ticker-watch"><h3>👀 Brief-mentioned tickers / signals</h3><p>These are source/tape leads from the brief, not PM decisions. Use Top Decisions for actionability.</p><div>{day.interestingTickers.map(t => {
          const hasResearch = t.hasResearch ?? researchSymbols.has(t.symbol)
          const dir = t.direction || 'flat'
          const label = typeof t.changePct === 'number' ? `${t.changePct > 0 ? '+' : ''}${t.changePct.toFixed(1)}%` : '•'
          return <button className={dir} title={hasResearch ? `${t.why}\n\nOpen in Stock research` : t.why} key={t.symbol} disabled={!hasResearch} onClick={() => onSelectTicker(t.symbol)}><strong>${t.symbol}</strong><small className={cls('move-pct', dir)}>{label}</small></button>
        })}</div></section>}
        {!!day.actionCallouts?.length && <section className="action-callouts"><h3>🎯 Action callouts from the briefing</h3><div>{day.actionCallouts.slice(0, 6).map(callout => { const dir = directionFromText(`${callout.action} ${(callout.details || []).join(' ')}`); return <article className={dir} key={`${callout.symbol}-${callout.action}`}><div><strong>${callout.symbol}</strong><span className="callout-action">{callout.action}</span></div><ul>{(callout.details || []).slice(0, 3).map(detail => <li key={detail}><TickerAware text={detail} symbols={knownSymbols} /></li>)}</ul></article> })}</div></section>}
        {!!day.goldSilver?.length && <section className="metals-box"><h3>🥇 Gold / silver</h3><ul>{day.goldSilver.map(cleanBullet).filter(Boolean).slice(0, 5).map((t, i) => <li key={`${i}-${t}`}><TickerAware text={t} symbols={knownSymbols} /></li>)}</ul></section>}
        <section className="takeaways"><h3>🧠 What matters</h3><ul>{day.keyTakeaways.map(cleanBullet).filter(Boolean).slice(0, 9).map((t, i) => <li key={`${i}-${t}`}><TickerAware text={t} symbols={knownSymbols} /></li>)}</ul></section>
        <details className="source-details"><summary>Source breakdown</summary><div>{day.items.map(item => <section key={publicSourceReference(item.sourcePath)}><strong>{item.sourceType}: {item.title}</strong>{item.summary && <p>{item.summary}</p>}<small>{publicSourceReference(item.sourcePath)}</small></section>)}</div></details>
        {!!data.marketPosture?.length && dayIdx === 0 && <details className="source-details posture-details"><summary>Raw posture inputs / scores</summary><div className="posture-strip">{data.marketPosture.map((card, idx) => <PostureCardView key={card.name} card={card} idx={idx} />)}</div></details>}
      </article>)}
    </div>
  </section>
}

export function DailyBriefTimeline({ data }: { data: DashboardData }) {
  const headlineSymbols = useMemo(() => data.tickers.map(t => ({symbol: t.symbol, href: `#research/${encodeURIComponent(t.symbol)}`})), [data.tickers])
  const timeline = useMemo(() => [...(data.cronTimeline || [])].sort((a, b) => (Date.parse(b.runTime) || 0) - (Date.parse(a.runTime) || 0)), [data.cronTimeline])
  const knownSymbols = useMemo(() => new Set([
    ...data.tickers.map(t => t.symbol),
    ...timeline.flatMap(item => extractSymbols(`${item.summary} ${(item.highlights || []).join(' ')} ${item.articleBody || ''}`)),
  ]), [data.tickers, timeline])

  return <section className="daily-brief-page">
    <div className="timeline-list">
      {timeline.map(item => <article className="timeline-item" key={item.id}>
        <aside><strong>{fmtDate(item.runTime.slice(0,10))}</strong><span>{fmtDate(item.runTime)}</span></aside>
        <section className="timeline-card">
          <div className="timeline-head"><div><span className="eyebrow timeline-category"><span aria-hidden="true">{categoryEmoji(item.category)}</span>{item.category.toLowerCase() === 'other research job' ? 'Research update' : item.category}</span><h3><ResearchHeadline content={item.jobName || 'Research update'} knownSymbols={headlineSymbols}/></h3></div></div>
          <p><TickerAware text={item.summary} symbols={knownSymbols} /></p>
          {!!item.highlights?.length && <ul>{item.highlights.slice(0, 5).map((highlight, i) => <li key={`${item.id}-${i}`}><TickerAware text={highlight} symbols={knownSymbols} /></li>)}</ul>}
          {item.category === 'Weekly Stock Analysis' && item.articleBody && <section aria-label="Why selected this week"><MarkdownOutput text={item.articleBody} symbols={knownSymbols} /></section>}
          {item.category === 'Macro Read' && item.articleBody && <section aria-label="Combined macro commentary"><MarkdownOutput text={item.articleBody} symbols={knownSymbols} /></section>}
          {item.articleBody && !['Weekly Stock Analysis', 'Macro Read'].includes(item.category) && <details className="source-details"><summary>Read full Market Brief</summary><div><small>{publicSourceReference(item.sourcePath)}</small><MarkdownOutput text={item.articleBody} symbols={knownSymbols} /></div></details>}
        </section>
      </article>)}
      {!timeline.length && <div className="empty">No material market-changing events found yet.</div>}
    </div>
  </section>
}

function StockResearch({ data, selected, setSelected }: { data: DashboardData; selected: string; setSelected: (symbol: string) => void }) {
  const [category, setCategory] = useState('all')
  const [query, setQuery] = useState('')
  // Stock Research should be the full research library, not only the curated focus list.
  // Focus names still drive the dashboard metrics / daily brief, but search needs to find
  // researched pages like NOW and TEAM even when they are not on today's active shortlist.
  const focus = data.tickers.filter(t => !t.isStub)
  const knownSymbols = useMemo(() => new Set(data.tickers.map(t => t.symbol)), [data.tickers])
  const categories = Array.from(new Set(focus.map(t => t.category || 'Other research'))).sort()
  const visible = useMemo(() => {
    const q = query.trim().toUpperCase().replace(/^\$/, '')
    return focus
      .filter(t => (category === 'all' || t.category === category) && searchMatch(query, [t.symbol, t.title, t.summary, t.status, t.shortlistThesis, t.shortlistRec, t.category, t.tags]))
      .sort((a, b) => {
        if (!q) return a.symbol.localeCompare(b.symbol)
        const rank = (t: Ticker) => t.symbol === q ? 0 : t.symbol.startsWith(q) ? 1 : (`${t.title} ${t.summary}`.toUpperCase().includes(q) ? 2 : 3)
        return rank(a) - rank(b) || a.symbol.localeCompare(b.symbol)
      })
  }, [focus, category, query])
  const current = data.tickers.find(t => t.symbol === selected) || visible[0] || focus[0]
  useEffect(() => { if (!selected && visible[0]) setSelected(visible[0].symbol) }, [selected, visible])

  return <section className="stock-page">
    <div className="stock-search-row"><label className="stock-search"><Search size={20} /><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search stock research only: ticker, theme, thesis, buy/no-buy question…" /></label></div>
    <div className="stock-layout">
      <aside className="stock-sidebar">
        <div className="sidebar-head"><span className="eyebrow">Research map</span><strong>{visible.length} names</strong></div>
        <select value={category} onChange={e => setCategory(e.target.value)}><option value="all">All categories</option>{categories.map(c => <option key={c} value={c}>{c} ({focus.filter(t => t.category === c).length})</option>)}</select>
        <div className="category-chips">{categories.slice(0, 9).map(c => <button key={c} onClick={() => setCategory(c)} className={cls(category === c && 'active')}>{c}</button>)}</div>
        <div className="ticker-list">{visible.map(t => <button key={t.symbol} className={cls('ticker-row', current?.symbol === t.symbol && 'active')} onClick={() => setSelected(t.symbol)}><span>${t.symbol}</span><small>{tierLabel(t.researchTier)} · {t.category}</small><em>{publicAssessmentLabel(t.shortlistRec || t.status)}</em></button>)}</div>
      </aside>
      <article className="research-detail">
        {current ? <>
          <div className="detail-header"><div><span className="eyebrow">{current.category}</span><h2>${current.symbol} — {current.title}</h2><TierPill tier={current.researchTier} reviewed={current.tierReviewed} reason={current.tierReason} /></div><span className={cls('bucket', current.actionBucket)}>{publicAssessmentLabel(current.actionBucket)}</span></div>
          <TradingViewSymbolOverview symbols={[current]} title={`$${current.symbol}: price history`} className="stock-detail-chart" height={380} />
          <div className="answer-strip">
            <div><strong>🤔 Current view</strong><BulletText text={publicAssessmentLabel(current.shortlistRec || current.status)} empty="No current buy/avoid label. Treat as research-only until refreshed." symbols={knownSymbols} /></div>
            <div><strong>🧾 What is it?</strong><BulletText text={current.summary} empty="No factual company description captured." symbols={knownSymbols} /></div>
          </div>
          {current.shortlistStatus && <p className="why"><strong>Current read:</strong> <TickerAware text={publicAssessmentLabel(current.shortlistStatus)} symbols={knownSymbols} /></p>}
          <div className="detail-grid">
            <div className="detail-box"><strong>🧭 Research tier</strong><BulletText text={`${tierLabel(current.researchTier)}\n${current.tierReason || 'No tier rationale captured.'}`} symbols={knownSymbols} /></div>
            <div className="detail-box"><strong>💡 Thesis</strong><BulletText text={current.thesis || current.shortlistThesis} empty="No thesis captured." symbols={knownSymbols} /></div>
            <div className="detail-box"><strong>🎯 What would change the view</strong><BulletText text={[current.entryPoint, current.trigger || current.catalyst].filter(Boolean).join('\n')} empty="No entry/proof trigger captured." symbols={knownSymbols} /></div>
            <div className="detail-box"><strong>⚠️ Risks and thesis invalidation</strong><BulletText text={current.shortlistRisk || current.risk} empty="No explicit risk captured." symbols={knownSymbols} /></div>
          </div>
          <div className="tag-row">{current.tags.map(tag => <span key={tag}>{tag}</span>)}</div>
          <div className="section-header"><div><span className="eyebrow">Research summary</span><h3>Supporting research</h3></div><span className="research-source">{publicSourceReference(current.sourcePath)} · updated {current.updated}</span></div>
          <div className="detail-sections">{(current.detailSections || []).map(sec => <section key={sec.title}><h4>{sec.title}</h4>{sec.bullets && sec.bullets.length > 0 ? <ul>{sec.bullets.map(b => <li key={b}><TickerAware text={b} symbols={knownSymbols} /></li>)}</ul> : <BulletText text={sec.summary} symbols={knownSymbols} />}</section>)}</div>
          {(!current.detailSections || current.detailSections.length === 0) && <pre className="full-summary"><TickerAware text={current.fullSummary || ''} symbols={knownSymbols} /></pre>}
        </> : <div className="empty">No matching ticker.</div>}
      </article>
    </div>
  </section>
}

export function CapitalPlanTable({ shortlistRows, knownSymbols, shortlistStamp, assessmentAvailable = hasEntryAssessmentInputs(shortlistRows) }: { shortlistRows: AsymmetricShortlistRow[]; knownSymbols: Set<string>; shortlistStamp: string; assessmentAvailable?: boolean }) {
  const actionableRows = actionableEntryRows(shortlistRows)
  return <section className="strategy-card priority-stack-card">
    <div className="section-header"><div><span className="eyebrow">Strict entry discipline</span><h3>Entries meeting the research criteria</h3><p>Only names inside the ideal price band and passing every research, proof, freshness, and portfolio gate appear here. Above-zone names are not chased; below-zone names are re-underwritten.</p></div>{shortlistStamp && <small>Research list updated: {shortlistStamp}</small>}</div>
    {!assessmentAvailable ? <div className="empty"><strong>Entry assessment unavailable.</strong><p>This public edition does not contain the inputs needed to evaluate entries. This is not a conclusion that no opportunities qualify.</p></div> : actionableRows.length ? <div className="table-scroll"><table className="strategy-table">
      <thead><tr><th>Rank</th><th>Stock</th><th>Tier</th><th>Action</th><th>Price / ideal entry</th><th>Why now</th><th>Proof before adding</th><th>Kill / reassess</th></tr></thead>
      <tbody>{actionableRows.map((row, index) => <tr key={`capital-${row.bucket}-${row.symbol}`}>
        <td>{index + 1}</td>
        <td><ResearchTickerLink symbol={row.symbol} /></td>
        <td><TierPill tier={row.researchTier} reviewed={row.tierReviewed} reason={row.tierReason} /></td>
        <td>{publicAssessmentLabel(row.actionMode)}</td>
        <td>{fmtPrice(row.currentPrice)} / {fmtPrice(row.entryZoneLow)}–{fmtPrice(row.entryZoneHigh)}</td>
        <td><TickerAware text={row.entryReason || publicAssessmentLabel(row.state)} symbols={knownSymbols} /></td>
        <td><TickerAware text={row.proofTrigger || ''} symbols={knownSymbols} /></td>
        <td><TickerAware text={row.killTrigger || ''} symbols={knownSymbols} /></td>
      </tr>)}</tbody>
    </table></div> : <div className="empty"><strong>No entries meet all criteria in this assessment.</strong><br />The evaluated conditions are not all satisfied; this does not invalidate the underlying business research.</div>}
  </section>
}

function DecisionLearningPanel({ learning, knownSymbols }: { learning?: DecisionLearning | null; knownSymbols: Set<string> }) {
  if (!learning || (!learning.receiptCount && !learning.outcomeCount && !learning.candidateExceptionCount && !learning.openExceptionCount && !learning.policyRuleCount && !learning.integrityGapCount)) return null
  const receipts = (learning.recentReceipts || []).slice(0, 4)
  const candidates = (learning.exceptionCandidates || []).filter(row => row.status === 'candidate').slice(0, 3)
  const outcomes = (learning.recentOutcomes || []).slice(0, 6)
  return <section className="strategy-card decision-learning-card">
    <div className="section-header"><div><span className="eyebrow">Decision review</span><h3>Decision discipline</h3><p>{learning.policy || 'Decision records preserve what was known at the time. Material exceptions are raised for strategy review.'}</p></div><small>{learning.generatedAt ? `Updated ${fmtDate(learning.generatedAt)}` : ''}</small></div>
    <div className="ops-summary-strip"><span>{learning.receiptCount || 0} receipts</span><span>{learning.candidateExceptionCount || 0} candidates</span><span>{learning.reviewDueCount || 0} review-due</span><span>{learning.openExceptionCount || 0} open exceptions</span><span>{learning.adoptedPolicyRuleCount || 0} adopted rules</span><span>{learning.integrityGapCount || 0} integrity gaps</span></div>
    {!!candidates.length && <div className="table-scroll"><table className="strategy-table"><caption>Strategy review queue · dashboard-only candidates, not urgent alerts</caption><thead><tr><th>Candidate</th><th>Process question</th><th>Decision change</th><th>Next review</th></tr></thead><tbody>{candidates.map(row => <tr key={row.id}><td><TickerAware text={row.symbol ? `$${row.symbol} · ${publicAssessmentLabel(row.classification)}` : publicAssessmentLabel(row.classification)} symbols={knownSymbols} /></td><td>{row.question}</td><td>{[row.priorDecision, row.currentDecision].filter(Boolean).map(publicAssessmentLabel).join(' → ') || '—'}</td><td>{row.nextReviewEvent || 'Strategy review'}</td></tr>)}</tbody></table></div>}
    {!!outcomes.length && <details className="source-details"><summary>Recent observed outcomes ({outcomes.length})</summary><div>{outcomes.map((row, index) => <section key={row.receiptId || row.sourceReceiptId || `${row.symbol || 'portfolio'}-${index}`}><strong><TickerAware text={`${row.symbol ? `$${row.symbol} · ` : ''}${publicAssessmentLabel(row.classification || row.status)}`} symbols={knownSymbols} /></strong><p>{[row.priorDecision || row.receiptDecision, row.currentDecision].filter(Boolean).map(publicAssessmentLabel).join(' → ') || row.reviewReason || row.reason || 'Decision outcome recorded.'}{typeof row.returnPct === 'number' ? ` · ${row.returnPct >= 0 ? '+' : ''}${row.returnPct.toFixed(1)}%` : ''}</p><small>{row.observedAt ? fmtDate(row.observedAt) : ''}{row.reviewReason || row.reason ? ` · ${row.reviewReason || row.reason}` : ''}</small></section>)}</div></details>}
    {!!receipts.length && <details className="source-details"><summary>Recent decision records ({receipts.length})</summary><div>{receipts.map(row => <section key={row.id}><strong><TickerAware text={`$${row.symbol} · ${publicAssessmentLabel(row.decision)}`} symbols={knownSymbols} /></strong><p>{row.thesis || row.proofTrigger || row.killTrigger || 'Capital decision snapshot.'}</p><small>{row.recordedAt ? fmtDate(row.recordedAt) : ''}{row.completeness === 'incomplete' ? ` · incomplete: ${(row.missingFields || []).map(publicAssessmentLabel).join(', ')}` : ''}</small></section>)}</div></details>}
  </section>
}

function StrategyWarRoom({ data }: { data: DashboardData }) {
  const knownSymbols = useMemo(() => new Set(data.tickers.map(t => t.symbol)), [data.tickers])
  const entryInputsAvailable = hasEntryAssessmentInputs(data.currentAsymmetricShortlist?.rows || [])
  const liveShortlistRows = (data.currentAsymmetricShortlist?.rows || []).filter(row => {
    const isLiveBucket = ['Buy / Scout Now', 'Wait for Trigger', 'Add After Proof'].includes(row.bucket)
    const decisionText = `${row.state || ''} ${row.actionMode || ''}`.toLowerCase()
    const isKillOrExit = /kill|do not average|exit\/trim/.test(decisionText)
    return isLiveBucket && !isKillOrExit
  }).slice(0, 14)
  const shortlistStamp = data.currentAsymmetricShortlist?.generatedAt ? fmtDate(data.currentAsymmetricShortlist.generatedAt) : ''
  return <section className="strategy-page">
    <CapitalPlanTable shortlistRows={liveShortlistRows} knownSymbols={knownSymbols} shortlistStamp={shortlistStamp} assessmentAvailable={entryInputsAvailable} />
    <DecisionLearningPanel learning={data.currentAsymmetricShortlist?.decisionLearning} knownSymbols={knownSymbols} />
  </section>
}

function WorkflowNodeCard({ node, mode }: { node: GraphWorkflowNode; mode: MarketDataMode }) {
  const runtime = operationalNodeState(node, mode)
  const tone = graphGateSeverity(runtime.status || node.freshness || 'unknown')
  const sourceDetail = node.freshnessContext === 'market_closed_carry_forward'
    ? 'Market closed — latest session carried'
    : node.freshnessContext === 'pipeline_stale'
      ? 'Update delayed — refresh needed'
      : `${node.sourceCount || 0} sources`
  return <div className={cls('ops-node', node.kind !== 'source' && 'ops-core-node', node.kind, tone, !node.allowedIntoSynthesis && 'blocked')}>
    <strong>{ownerOperationsText(node.label)}</strong>
    <span>{graphGateLabel(runtime.status)}{node.kind === 'source' ? ` / ${graphGateLabel(node.freshness)}` : ''}</span>
    <small>{node.kind === 'source' ? sourceDetail : ownerOperationsText(runtime.detail)}</small>
    {!!node.healActions?.length && <em>Recovered automatically</em>}
  </div>
}

function WorkflowGraphVisual({ graph, mode }: { graph: MarketGraphWorkflow; mode: MarketDataMode }) {
  const nodes = graph.graphNodes || []
  const sourceNodes = nodes.filter(n => n.kind === 'source')
  const checker = nodes.find(n => n.kind === 'checker')
  const synthesis = nodes.find(n => n.kind === 'synthesis')
  const deliveryNodes = nodes.filter(n => n.kind === 'publish' || n.kind === 'transport')
  const consumerNodes = nodes.filter(n => n.kind === 'consumer')
  const nodeTone = (node: GraphWorkflowNode) => graphGateSeverity(operationalNodeState(node, mode).status || node.freshness || 'unknown')
  const severity = graphGateSeverity(graph.finalGate)
  const issueLines = workflowIssueLines(graph)
  const attentionNodeCount = sourceNodes.filter(node => nodeTone(node) !== 'success' || !node.allowedIntoSynthesis).length
  const fanInCount = graph.graphEdges?.filter(e => e.to === 'checker').length || sourceNodes.length
  const fanOutCount = graph.graphEdges?.filter(e => e.from === 'runtime_manifest').length || consumerNodes.length
  return <article className={cls('ops-workflow-card', severity)}>
    <div className="ops-workflow-head"><div><span className="eyebrow">Publication process</span><h3>{ownerOperationsText(graph.label)}</h3><p>{ownerOperationsText(graph.recommendation)}</p></div><div className="ops-status-stack"><GraphGatePill gate={graph.finalGate} /><small>Last run: {fmtDate(graph.generatedAt)}</small></div></div>
    <div className="ops-summary-strip"><span>{graph.passCount}/{graph.nodeCount} source checks healthy</span><span>{attentionNodeCount} checks need attention</span><span>{graph.marketClosedCarryCount || 0} carried from the latest market session</span><span>{graph.pipelineStaleCount || 0} updates delayed</span><span>{graph.slackWorthyEventCount || 0} Attention required</span></div>
    {severity !== 'success' && <div className={cls('ops-issue-strip', severity)}><strong>Needs attention</strong>{issueLines.length ? <ul>{issueLines.map(issue => <li key={issue}>{issue}</li>)}</ul> : <p>No warning detail captured.</p>}</div>}
    <div className="ops-graph-flow">
      <div className="ops-stage"><span className="ops-stage-label">Sources</span><div className="ops-node-column source-column">{sourceNodes.map(node => <WorkflowNodeCard key={node.id} node={node} mode={mode} />)}</div></div>
      <div className="ops-edge-bundle"><span /> <b>{fanInCount} inputs</b> <span /></div>
      <div className="ops-stage ops-stage-stack"><span className="ops-stage-label">Checks and assessment</span>{checker && <WorkflowNodeCard node={checker} mode={mode} />}<div className="ops-stage-arrow">checked ↓</div>{synthesis && <WorkflowNodeCard node={synthesis} mode={mode} />}</div>
      <div className="ops-edge-bundle single"><span /> <b>publish</b> <span /></div>
      <div className="ops-stage ops-stage-stack"><span className="ops-stage-label">Publication</span>{deliveryNodes.map((node, index) => <Fragment key={node.id}><WorkflowNodeCard node={node} mode={mode} />{index < deliveryNodes.length - 1 && <div className="ops-stage-arrow">verified ↓</div>}</Fragment>)}</div>
      <div className="ops-edge-bundle"><span /> <b>{fanOutCount} views</b> <span /></div>
      <div className="ops-stage"><span className="ops-stage-label">Connected views</span><div className="ops-node-column consumer-column">{consumerNodes.map(node => <WorkflowNodeCard key={node.id} node={node} mode={mode} />)}</div></div>
    </div>
    <details className="ops-diagnostics"><summary>Source checks</summary><div>{nodes.map(node => <section key={`${graph.workflowId}-${node.id}`}><strong>{ownerOperationsText(node.label)}</strong><p>{ownerOperationsText(node.reason)}</p>{node.outputPath && <small>{publicSourceReference(node.outputPath)}</small>}</section>)}</div></details>
  </article>
}

function ChartCategoryKey({ rows }: { rows: AiCategoryInput[] }) {
  const categories = Array.from(new Set(rows.map(aiCategoryForRow))).filter(category => category !== 'App / software layer').sort()
  if (!categories.length) return null
  return <div className="chart-category-key" aria-label="AI category color key">{categories.map(category => <span key={category}><i style={{ background: aiCategoryColor(category) }} />{category}</span>)}</div>
}

function AiProjectionBarChart({ title, rows, valueKey, yLabel }: { title: string; rows: Array<Record<string, string | number | boolean | null>>; valueKey: string; yLabel: string }) {
  const usable = stableRowsByNumberDesc(rows.filter(row => typeof row[valueKey] === 'number'), row => row[valueKey] as number)
  if (!usable.length) return <article className="chart-js-card empty-chart"><strong>{title}</strong><p>No usable numeric rows yet.</p></article>
  return <article className="chart-js-card">
    <div><strong>{title}</strong><small>{yLabel} · sorted by value, then ticker · color = AI category</small></div>
    <div className="chart-js-frame"><InteractiveBarChart data={{ labels: usable.map(row => String(row.symbol || '')), datasets: [{ label: yLabel, data: usable.map(row => row[valueKey] as number), backgroundColor: usable.map(aiCategoryColor), borderColor: usable.map(aiCategoryColor), borderWidth: 1 }] }} options={baseChartOptions} /></div>
    <ChartCategoryKey rows={usable} />
  </article>
}

function AiProjectionScatterChart({ rows }: { rows: Array<Record<string, string | number | boolean | null>> }) {
  const points = stableRowsBySymbol(rows.map(row => ({ symbol: String(row.symbol || ''), x: chartNumber(row.ntmRevenueGrowthPct), y: chartNumber(row.evNtmRevenue), category: aiCategoryForRow(row) })))
    .filter(point => point.x !== null && point.y !== null)
  return <article className="chart-js-card">
    <div><strong>Growth vs valuation</strong><small>NTM revenue growth vs EV/NTM revenue · color = AI category</small></div>
    {points.length ? <><div className="chart-js-frame"><Scatter data={{ datasets: [{ label: 'Growth / valuation', data: points.map(point => ({ x: point.x as number, y: point.y as number })), pointBackgroundColor: points.map(point => aiCategoryColor(point.category)), pointBorderColor: () => ownerChartPalette().surface, pointRadius: 6, pointHoverRadius: 8 }] }} options={{ ...baseChartOptions, scales: { x: { ticks: { color: chartTextColor, callback: value => `${value}%` }, grid: { color: chartGridColor }, title: { display: true, text: 'NTM revenue growth %', color: chartTextColor } }, y: { ticks: { color: chartTextColor }, grid: { color: chartGridColor }, title: { display: true, text: 'EV / NTM revenue', color: chartTextColor } } }, plugins: { ...baseChartOptions.plugins, tooltip: { ...baseChartOptions.plugins.tooltip, callbacks: { label: ctx => `${points[ctx.dataIndex]?.symbol || 'Name'} (${points[ctx.dataIndex]?.category || 'AI'}): ${Number(ctx.parsed.x || 0).toFixed(1)}% growth / ${Number(ctx.parsed.y || 0).toFixed(2)}x EV/Rev` } } } }} /></div><ChartCategoryKey rows={points} /></> : <p className="muted">No AI rows currently have both growth and EV/Revenue.</p>}
  </article>
}

function AiProjectionFootballChart({ rows }: { rows: Array<Record<string, string | number | boolean | null>> }) {
  const usable = stableRowsBySymbol(rows.filter(row => typeof row.currentPrice === 'number' && typeof row.bear === 'number' && typeof row.base === 'number' && typeof row.bull === 'number'))
  if (!usable.length) return null
  return <article className="chart-js-card wide">
    <div><strong>Projection football field</strong><small>{usable.length} tickers with current + bear/base/bull support · ticker order</small></div>
    <div className="chart-js-frame"><InteractiveBarChart data={{ labels: usable.map(row => String(row.symbol || '')), datasets: [
      { label: 'Current', data: usable.map(row => row.currentPrice as number), backgroundColor: '#94a3b8' },
      { label: 'Bear', data: usable.map(row => row.bear as number), backgroundColor: '#fca5a5' },
      { label: 'Base', data: usable.map(row => row.base as number), backgroundColor: '#7dd3fc' },
      { label: 'Bull', data: usable.map(row => row.bull as number), backgroundColor: '#86efac' },
    ] }} options={baseChartOptions} /></div>
  </article>
}

function AiProjectionQualityChart({ summary }: { summary?: AiProjectionExhibits['summary'] }) {
  const dataQuality = summary?.dataQuality || {}
  const labels = Object.keys(dataQuality).sort()
  const total = labels.reduce((acc, label) => acc + (dataQuality[label] || 0), 0)
  if (!labels.length || !total) return null
  if (labels.length === 1) {
    const label = labels[0]
    return <article className="chart-js-card quality-single">
      <div><span className="eyebrow">Coverage diagnostic</span><strong>Data quality</strong><small>Out of {total} projection rows</small></div>
      <div className="quality-single-value"><span className={cls('projection-dq', label)}>{displayDataQuality(label)}</span><strong>{dataQuality[label]}/{total}</strong></div>
    </article>
  }
  return <article className="chart-js-card">
    <div><span className="eyebrow">Coverage diagnostic</span><strong>Data quality mix</strong><small>Rows by data-quality label · out of {total}</small></div>
    <div className="chart-js-frame compact"><InteractiveBarChart data={{ labels: labels.map(displayDataQuality), datasets: [{ label: 'Rows', data: labels.map(label => dataQuality[label]), backgroundColor: labels.map(chartColor) }] }} options={{ ...baseChartOptions, indexAxis: 'y' as const }} /></div>
  </article>
}

function ProjectionDataTable({ rows, knownSymbols }: { rows: AiProjectionRow[]; knownSymbols: Set<string> }) {
  const tableRef = useRef<HTMLTableElement>(null)
  useEffect(() => {
    if (!tableRef.current || !rows.length) return undefined
    const table = new DataTable(tableRef.current, {
      paging: true,
      pageLength: 10,
      lengthMenu: [10, 20, 50],
      searching: true,
      order: [[9, 'desc'], [0, 'asc']],
      autoWidth: false,
    })
    return () => { table.destroy() }
  }, [rows.length])
  if (!rows.length) return null
  return <section className="strategy-card priority-stack-card"><div className="section-header"><div><h3>Base/bull implied upside by data quality</h3><p>Sortable/searchable table view. Sort favors base upside, but table rank is not a buy/add instruction.</p></div></div><div className="table-scroll datatable-shell"><table ref={tableRef} className="strategy-table ai-projection-table display compact"><thead><tr><th title="Stock ticker symbol">Ticker</th><th title="Primary AI exposure category">Category</th><th title="Business or investment archetype used for valuation comparisons">Archetype</th><th title="Data quality: completeness and reliability of the inputs used in the projection">DQ</th><th title="Latest stock price at the dashboard refresh">Price</th><th title="Market capitalization: share price multiplied by diluted shares outstanding">Market cap</th><th title="Next-twelve-month consensus revenue estimate">NTM revenue</th><th title="Expected next-twelve-month revenue growth rate">Growth</th><th title="Relative valuation assessment and peer benchmark group">Valuation</th><th title="Base-case implied share price and upside or downside versus the current price">Base upside</th><th title="Bull-case implied share price and upside versus the current price">Bull upside</th><th title="Current research view or next step">Action</th></tr></thead><tbody>{rows.map(row => <tr className={projectionTone(row)} key={row.symbol}><td><ResearchTickerLink symbol={row.symbol} /></td><td><CategoryPill category={aiCategoryForRow(row)} /></td><td>{row.archetype}</td><td><span className={cls('projection-dq', row.dataQualityLabel)}>{displayDataQuality(row.dataQualityLabel)}</span></td><td data-order={row.price ?? undefined}>{fmtPrice(row.price)}</td><td data-order={row.marketCap ?? undefined}>{fmtBig(row.marketCap)}</td><td data-order={row.ntmRevenue ?? undefined}>{fmtBig(row.ntmRevenue)}</td><td data-order={row.ntmRevenueGrowthPct ?? undefined}>{fmtPct(row.ntmRevenueGrowthPct) || '—'}</td><td>{publicAssessmentLabel(row.valuationSignal)}{row.benchmarkGroup ? ` · Benchmark: ${row.benchmarkGroup}` : ''}</td><td data-order={row.base?.upsidePct ?? undefined}><strong>{fmtPrice(row.base?.impliedPrice) || '—'}</strong><small>{fmtPct(row.base?.upsidePct)}</small></td><td data-order={row.bull?.upsidePct ?? undefined}><strong>{fmtPrice(row.bull?.impliedPrice) || '—'}</strong><small>{fmtPct(row.bull?.upsidePct)}</small></td><td><TickerAware text={row.warRoomAction || 'context only'} symbols={knownSymbols} /></td></tr>)}</tbody></table></div></section>
}


function AiWarRoomGrowthScatter({ rows }: { rows: AiWarRoomRow[] }) {
  const completePoints = rows.map(row => ({
    symbol: row.symbol,
    x: chartNumber(row.revenueGrowthPct),
    y: chartNumber(row.evNtmRevenue),
    enterpriseValue: chartNumber(row.enterpriseValue),
    category: aiCategoryForRow(row),
    action: row.action,
    proofLevel: row.proofLevel,
    fcfMarginPct: row.fcfMarginPct,
    nextGate: row.nextCatalystCheckDate,
  })).filter(point => point.x !== null && point.y !== null && point.enterpriseValue !== null)
    .sort((a, b) => (b.enterpriseValue as number) - (a.enterpriseValue as number) || a.symbol.localeCompare(b.symbol))
  const points = completePoints.filter(point => isRelativeValueFocusPoint(point.x as number, point.y as number))
  const outliers = completePoints.filter(point => !isRelativeValueFocusPoint(point.x as number, point.y as number))
  const enterpriseValues = points.map(point => point.enterpriseValue as number)
  const labelPoints = points.map(point => ({ symbol: point.symbol, x: point.x as number, y: point.y as number }))
  const labeledSymbols = new Set(topOutlierLabelSymbols(labelPoints, 10))
  const outlierLabelPlugin = bubbleOutlierLabelPlugin(labelPoints, labeledSymbols, 'relative-value-outlier-labels')
  return <article className="chart-js-card">
    <div><strong>AI relative value map</strong><small>Latest quarterly revenue growth YoY vs EV/NTM revenue (EV ÷ NTM consensus revenue) · focus window: -50% to 250% / 0x to 60x · bubble area = bounded enterprise value · labels = top 10 robust 2D outliers</small></div>
    {points.length ? <><div className="chart-js-frame"><Bubble data={{ datasets: [{
      label: 'AI relative value',
      data: points.map(point => ({ x: point.x as number, y: point.y as number, r: bubbleRadiusForEnterpriseValue(point.enterpriseValue, enterpriseValues) })),
      backgroundColor: points.map(point => aiCategoryColor(point.category)),
      borderWidth: 0,
      hoverBorderWidth: 0,
      hoverRadius: 2,
    }] }} options={{ ...baseChartOptions, scales: {
      x: { ticks: { color: chartTextColor, callback: value => `${value}%` }, grid: { color: chartGridColor }, title: { display: true, text: 'Latest reported revenue growth YoY %', color: chartTextColor } },
      y: { ticks: { color: chartTextColor, callback: value => `${value}x` }, grid: { color: chartGridColor }, title: { display: true, text: 'EV / NTM revenue', color: chartTextColor } },
    }, plugins: { ...baseChartOptions.plugins, tooltip: { ...baseChartOptions.plugins.tooltip, callbacks: {
      label: ctx => `${points[ctx.dataIndex]?.symbol || 'Name'}: ${Number(ctx.parsed.x || 0).toFixed(1)}% growth / ${Number(ctx.parsed.y || 0).toFixed(2)}x EV/Rev`,
      afterLabel: ctx => {
        const point = points[ctx.dataIndex]
        return point ? [`EV: ${fmtBig(point.enterpriseValue)}`, `FCF margin: ${fmtPct(point.fcfMarginPct) || '—'}`, `Proof: ${point.proofLevel ?? '—'}`, `Action: ${humanizeLabel(point.action || 'context only')}`, `Next gate: ${point.nextGate || 'not captured'}`] : []
      },
    } } } }} plugins={[outlierLabelPlugin]} /></div><ChartCategoryKey rows={points} />{outliers.length > 0 && <div className="chart-outlier-note"><strong>{outliers.length} extreme outlier{outliers.length === 1 ? '' : 's'} outside focus window</strong><span>{outliers.map(point => `$${point.symbol} (${fmtPct(point.x)} / ${fmtMultiple(point.y)})`).join(' · ')}</span><small>Outliers remain visible in the sortable table above.</small></div>}</> : <p className="muted">No complete growth, valuation, and enterprise-value rows yet.</p>}
  </article>
}

function AiWarRoomProofChart({ rows }: { rows: AiWarRoomRow[] }) {
  const usable = stableRowsByNumberDesc(rows.filter(row => typeof row.proofLevel === 'number'), row => row.proofLevel, 30)
  if (!usable.length) return null
  const proofBySymbol = new Map(usable.map(row => [row.symbol, row]))
  return <article className="chart-js-card">
    <div><strong>Business-proof maturity</strong><small>Analyst-assigned 0-5 evidence ladder · not a composite opportunity or buy score</small></div>
    <div className="chart-js-frame"><InteractiveBarChart data={{ labels: usable.map(r => r.symbol), datasets: [{ label: 'Proof level', data: usable.map(r => r.proofLevel as number), backgroundColor: usable.map(aiCategoryColor), borderColor: usable.map(aiCategoryColor), borderWidth: 1 }] }} options={{ ...baseChartOptions, scales: { ...baseChartOptions.scales, y: { ...baseChartOptions.scales.y, min: 0, max: 5 } }, plugins: { ...baseChartOptions.plugins, tooltip: { ...baseChartOptions.plugins.tooltip, callbacks: { label: ctx => `${ctx.label}: Level ${Number(ctx.parsed.y).toFixed(2).replace(/\.00$/, '')}`, afterLabel: ctx => { const row = proofBySymbol.get(String(ctx.label)); return row ? [`Action: ${publicAssessmentLabel(row.action)}`, `Next gate: ${row.nextCatalystCheckDate || 'not captured'}`] : [] } } } } }} /></div>
    <div className="proof-methodology" aria-label="Business proof methodology">
      <div className="proof-boundaries">
        <section><strong>What it measures</strong><p>Customer/order evidence, backlog conversion, revenue and estimate validation, margins, FCF, and repeatability.</p></section>
        <section><strong>What it does not reflect</strong><p>Valuation, mispricing, crowding, entry/technical R:R, catalyst timing, portfolio fit, position size, or freshness.</p></section>
      </div>
      <ol className="proof-ladder">
        <li><b>0</b><span>Story only</span></li>
        <li><b>1</b><span>Claimed exposure</span></li>
        <li><b>2</b><span>Product, pilot, or design win</span></li>
        <li><b>3</b><span>Named customer, order, or backlog</span></li>
        <li><b>4</b><span>Revenue, guide, estimate, or margin conversion</span></li>
        <li><b>5</b><span>Repeatable growth plus durable margin/FCF</span></li>
      </ol>
      <p className="proof-methodology-note">Decimals are analyst judgment between adjacent levels. Use proof with valuation, crowding, entry, and portfolio fit to determine Scout / Add / Wait—not by itself.</p>
    </div>
    <ChartCategoryKey rows={usable} />
  </article>
}

function AiWarRoomCompleteDataTable({ rows, knownSymbols }: { rows: AiWarRoomRow[]; knownSymbols: Set<string> }) {
  const tableRef = useRef<HTMLTableElement>(null)
  useEffect(() => {
    if (!tableRef.current || !rows.length) return undefined
    const table = new DataTable(tableRef.current, { paging: true, pageLength: 15, lengthMenu: [15, 30, 69, 100], searching: true, order: [[11, 'desc'], [0, 'asc']], autoWidth: false })
    return () => { table.destroy() }
  }, [rows.length])
  if (!rows.length) return null
  return <section className="strategy-card priority-stack-card"><div className="section-header"><div><h3>Complete AI research data</h3><p>Search and sort the full company research table. Figures come from the published research update; missing values are shown explicitly.</p></div></div><div className="table-scroll datatable-shell"><table ref={tableRef} className="strategy-table ai-war-room-table display compact"><thead><tr><th title="Stock ticker symbol">Ticker</th><th title="Research tier reflects business and thesis fragility">Research tier</th><th title="Primary AI exposure category">Category</th><th title="Current research view or next step">Action</th><th title="Evidence scale from 0 (unproven) to 5 (repeatable financial results)">Proof</th><th title="Latest stock price at the dashboard refresh">Price</th><th className="one-month-change" title="Stock-price percentage change over the prior one month">1M</th><th title="Market capitalization: share price multiplied by diluted shares outstanding">MCap</th><th title="Enterprise value: market cap plus debt and preferred claims, minus cash">EV</th><th title="Revenue reported over the latest twelve months">LTM rev</th><th title="Consensus revenue estimate for the next twelve months">NTM rev</th><th title="Latest reported quarterly revenue growth versus the same quarter one year earlier">Rev growth YoY</th><th title="Gross margin: gross profit divided by revenue">GM</th><th title="Free-cash-flow margin: free cash flow divided by revenue; pre-revenue values can be distorted">FCF margin</th><th title="Enterprise value divided by next-twelve-month revenue">EV/Rev</th><th title="Next-twelve-month price-to-earnings multiple">P/E</th><th title="Upcoming evidence or catalyst required to confirm, upgrade, or invalidate the thesis">Next gate</th></tr></thead><tbody>{rows.map(row => <tr key={`war-${row.symbol}`}><td><ResearchTickerLink symbol={row.symbol} /><small>{row.exchange || row.primaryTicker}</small></td><td><TierPill tier={row.researchTier} reviewed={row.tierReviewed} reason={row.tierReason} /></td><td><CategoryPill category={aiCategoryForRow(row)} /></td><td><TickerAware text={publicAssessmentLabel(row.action)} symbols={knownSymbols} /></td><td data-order={row.proofLevel ?? undefined}>{row.proofLevel ?? '—'}</td><td data-order={row.price ?? undefined}>{fmtPrice(row.price)}</td><td className="one-month-change" data-order={row.oneMonthChangePct ?? undefined}>{fmtPct(row.oneMonthChangePct) || '—'}</td><td data-order={row.marketCap ?? undefined}>{fmtBig(row.marketCap)}</td><td data-order={row.enterpriseValue ?? undefined}>{fmtBig(row.enterpriseValue)}</td><td data-order={row.ltmRevenue ?? undefined}>{fmtBig(row.ltmRevenue)}</td><td data-order={row.ntmRevenueEstimate ?? undefined}>{fmtBig(row.ntmRevenueEstimate)}</td><td data-order={row.revenueGrowthPct ?? undefined}>{fmtPct(row.revenueGrowthPct) || '—'}</td><td data-order={row.grossMarginPct ?? undefined}>{fmtPct(row.grossMarginPct) || '—'}</td><td data-order={row.fcfMarginPct ?? undefined}><MarginValue value={row.fcfMarginPct} /></td><td data-order={row.evNtmRevenue ?? undefined}>{fmtMultiple(row.evNtmRevenue)}</td><td data-order={row.peNtm ?? undefined}>{fmtMultiple(row.peNtm)}</td><td><TickerAware text={row.nextCatalystCheckDate || row.addZone || 'review'} symbols={knownSymbols} /></td></tr>)}</tbody></table></div></section>
}

function CloudedJudgementGrowthProfitabilityScatter({ rows }: { rows: AiWarRoomRow[] }) {
  const points = rows.filter(isComparableFcfMargin).map(row => ({
    symbol: row.symbol,
    x: chartNumber(row.revenueGrowthPct),
    y: chartNumber(row.fcfMarginPct),
    enterpriseValue: chartNumber(row.enterpriseValue),
    category: aiCategoryForRow(row),
  })).filter(point => point.x !== null && point.y !== null && point.enterpriseValue !== null)
    .sort((a, b) => (b.enterpriseValue as number) - (a.enterpriseValue as number) || a.symbol.localeCompare(b.symbol))
  const enterpriseValues = points.map(point => point.enterpriseValue as number)
  const labelPoints = points.map(point => ({ symbol: point.symbol, x: point.x as number, y: point.y as number }))
  const labeledSymbols = new Set(topOutlierLabelSymbols(labelPoints, 10))
  const outlierLabelPlugin = bubbleOutlierLabelPlugin(labelPoints, labeledSymbols, 'growth-fcf-outlier-labels')
  return <article className="chart-js-card">
    <div><strong>Growth vs FCF margin</strong><small>Latest quarterly revenue growth YoY vs FCF margin (free cash flow ÷ LTM revenue) · bubble area = bounded enterprise value · labels = top 10 robust 2D outliers · excludes |FCF margin| &gt; 500% denominator distortions</small></div>
    {points.length ? <><div className="chart-js-frame"><Bubble data={{ datasets: [{
      label: 'Growth / FCF margin',
      data: points.map(point => ({ x: point.x as number, y: point.y as number, r: bubbleRadiusForEnterpriseValue(point.enterpriseValue, enterpriseValues) })),
      backgroundColor: points.map(point => aiCategoryColor(point.category)),
      borderWidth: 0,
      hoverBorderWidth: 0,
      hoverRadius: 2,
    }] }} options={{ ...baseChartOptions, scales: {
      x: { ticks: { color: chartTextColor, callback: value => `${value}%` }, grid: { color: chartGridColor }, title: { display: true, text: 'Latest reported revenue growth YoY %', color: chartTextColor } },
      y: { ticks: { color: chartTextColor, callback: value => `${value}%` }, grid: { color: chartGridColor }, title: { display: true, text: 'FCF margin % (FCF / LTM revenue)', color: chartTextColor } },
    }, plugins: { ...baseChartOptions.plugins, tooltip: { ...baseChartOptions.plugins.tooltip, callbacks: {
      label: ctx => `${points[ctx.dataIndex]?.symbol || 'Name'}: ${Number(ctx.parsed.x || 0).toFixed(1)}% growth / ${Number(ctx.parsed.y || 0).toFixed(1)}% FCF margin`,
      afterLabel: ctx => { const point = points[ctx.dataIndex]; return point ? [`EV: ${fmtBig(point.enterpriseValue)}`, 'FCF margin = free cash flow / LTM revenue'] : [] },
    } } } }} plugins={[outlierLabelPlugin]} /></div><ChartCategoryKey rows={points} /></> : <p className="muted">No comparable rows with growth, FCF margin, and enterprise value yet.</p>}
  </article>
}


function AiFcfMarginLeaderboard({ rows }: { rows: AiWarRoomRow[] }) {
  const usable = stableRowsByNumberDesc(rows.filter(isComparableFcfMargin), row => row.fcfMarginPct, 30)
  if (!usable.length) return null
  return <article className="chart-js-card">
    <div><strong>FCF margin leaderboard</strong><small>Sorted by free-cash-flow margin · excludes |FCF margin| &gt; 500% pre-revenue outliers</small></div>
    <div className="chart-js-frame"><InteractiveBarChart data={{ labels: usable.map(r => r.symbol), datasets: [{ label: 'FCF margin %', data: usable.map(r => r.fcfMarginPct as number), backgroundColor: usable.map(aiCategoryColor), borderColor: usable.map(aiCategoryColor), borderWidth: 1 }] }} options={baseChartOptions} /></div>
    <ChartCategoryKey rows={usable} />
  </article>
}

function AiRevenueLeaderboard({ rows }: { rows: AiWarRoomRow[] }) {
  const usable = stableRowsByNumberDesc(rows.filter(row => typeof row.ntmRevenueEstimate === 'number' || typeof row.ltmRevenue === 'number'), row => row.ntmRevenueEstimate ?? row.ltmRevenue, 30)
  if (!usable.length) return null
  return <article className="chart-js-card">
    <div><strong>Revenue leaderboard</strong><small>NTM estimate when available, otherwise LTM revenue · color = AI category</small></div>
    <div className="chart-js-frame"><InteractiveBarChart data={{ labels: usable.map(r => r.symbol), datasets: [{ label: 'Revenue', data: usable.map(r => (r.ntmRevenueEstimate ?? r.ltmRevenue) as number), backgroundColor: usable.map(aiCategoryColor), borderColor: usable.map(aiCategoryColor), borderWidth: 1 }] }} options={{ ...baseChartOptions, scales: { ...baseChartOptions.scales, y: { ...baseChartOptions.scales.y, ticks: { color: chartTextColor, callback: value => fmtBig(Number(value)) } } } }} /></div>
    <ChartCategoryKey rows={usable} />
  </article>
}

function CloudedJudgementRuleOf40Chart({ rows }: { rows: AiWarRoomRow[] }) {
  const scored = stableRowsByNumberDesc(rows.map(row => ({ ...row, rule40: ruleOf40(row) })).filter(row => typeof row.rule40 === 'number'), row => row.rule40, 25)
  if (!scored.length) return null
  return <article className="chart-js-card">
    <div><strong>Rule of 40 stack</strong><small>Revenue growth + comparable FCF margin; extreme pre-revenue margins excluded</small></div>
    <div className="chart-js-frame"><InteractiveBarChart data={{ labels: scored.map(r => r.symbol), datasets: [{ label: 'Rule of 40', data: scored.map(r => r.rule40 as number), backgroundColor: scored.map(aiCategoryColor), borderColor: scored.map(aiCategoryColor), borderWidth: 1 }] }} options={baseChartOptions} /></div>
    <ChartCategoryKey rows={scored} />
  </article>
}

function CloudedJudgementCompsTable({ rows, knownSymbols }: { rows: AiWarRoomRow[]; knownSymbols: Set<string> }) {
  const tableRef = useRef<HTMLTableElement>(null)
  useEffect(() => {
    if (!tableRef.current || !rows.length) return undefined
    const table = new DataTable(tableRef.current, { paging: true, pageLength: 12, lengthMenu: [12, 25, 50], searching: true, order: [[6, 'desc'], [0, 'asc']], autoWidth: false })
    return () => { table.destroy() }
  }, [rows.length])
  if (!rows.length) return null
  return <section className="strategy-card priority-stack-card"><div className="section-header"><div><h3>AI company comparisons</h3><p>Compare reported revenue growth, profitability, valuation, price performance, and the evidence needed for the next research decision.</p></div></div><div className="table-scroll datatable-shell"><table ref={tableRef} className="strategy-table ai-war-room-table display compact"><thead><tr><th title="Stock ticker symbol">Ticker</th><th title="Primary AI exposure category">Category</th><th title="Latest reported quarterly revenue growth versus the same quarter one year earlier">Rev growth YoY</th><th title="Gross margin: gross profit divided by revenue">GM</th><th title="Free-cash-flow margin: free cash flow divided by revenue; pre-revenue values can be distorted">FCF margin</th><th title="Revenue growth plus free-cash-flow margin; 40 or higher is the classic benchmark">Rule 40</th><th title="Enterprise value divided by next-twelve-month consensus revenue">EV/NTM rev</th><th title="Market capitalization: share price multiplied by diluted shares outstanding">MCap</th><th className="one-month-change" title="Stock-price percentage change over the prior one month">1M</th><th title="Current capital posture plus the next evidence required before changing it">Action gate</th></tr></thead><tbody>{stableRowsBySymbol(rows).map(row => { const r40 = ruleOf40(row); return <tr key={`cj-${row.symbol}`}><td><ResearchTickerLink symbol={row.symbol} /><small>{row.companyName}</small></td><td><CategoryPill category={aiCategoryForRow(row)} /></td><td data-order={row.revenueGrowthPct ?? undefined}>{fmtPct(row.revenueGrowthPct) || '—'}</td><td data-order={row.grossMarginPct ?? undefined}>{fmtPct(row.grossMarginPct) || '—'}</td><td data-order={row.fcfMarginPct ?? undefined}><MarginValue value={row.fcfMarginPct} /></td><td data-order={r40 ?? undefined}>{fmtPct(r40) || '—'}</td><td data-order={row.evNtmRevenue ?? undefined}>{fmtMultiple(row.evNtmRevenue)}</td><td data-order={row.marketCap ?? undefined}>{fmtBig(row.marketCap)}</td><td className="one-month-change" data-order={row.oneMonthChangePct ?? undefined}>{fmtPct(row.oneMonthChangePct) || '—'}</td><td><TickerAware text={publicAssessmentLabel(row.action)} symbols={knownSymbols} /><small>{row.nextCatalystCheckDate || publicAssessmentLabel(row.sourceFreshness)}</small></td></tr> })}</tbody></table></div></section>
}

export function publishedValuationAction(symbol: string, shortlist?: AsymmetricShortlist | null) {
  const source = shortlist?.rows?.find(row => row.symbol === symbol)
  const bucket = MEMBERSHIP_BUCKET_GUIDE.find(item => item.bucket === source?.bucket)
  return {label: bucket?.label || 'No published action', tone: bucket?.tone || 'neutral', reason: bucket ? source?.bucketReason || bucket.meaning : 'No published CIO action for this company; this is not a buy or sell conclusion.'}
}

function ResearchTickerLink({ symbol }: { symbol: string }) {
  return <a className="inline-ticker research-ticker-link" href={`#research/${encodeURIComponent(symbol)}`}>${symbol}</a>
}

function AiCapitalAllocationTable({ rows, projections, knownSymbols, shortlist }: { rows: AiWarRoomRow[]; projections: AiProjectionRow[]; knownSymbols: Set<string>; shortlist?: AsymmetricShortlist | null }) {
  const tableRef = useRef<HTMLTableElement>(null)
  const projectionBySymbol = useMemo(() => new Map(projections.map(row => [row.symbol, row])), [projections])
  const comparableRows = stableRowsBySymbol(rows.filter(isAiStockRow))
  useEffect(() => {
    if (!tableRef.current || !comparableRows.length) return undefined
    const table = new DataTable(tableRef.current, { paging: true, pageLength: 15, lengthMenu: [15, 30, 69, 100], searching: true, order: [[3, 'desc'], [0, 'asc']], autoWidth: false })
    return () => { table.destroy() }
  }, [comparableRows.length])
  if (!comparableRows.length) return null
  return <section className="strategy-card priority-stack-card"><div className="section-header"><div><span className="eyebrow">Combined proof + valuation table</span><h3>AI company financials and evidence</h3><p>Each company row combines the current view, evidence, price changes, operating quality, valuation, and projection scenarios. Sortable evidence — not a standalone buy list.</p><p className="markets-metadata">Action uses published CIO membership. No published action is not a buy or sell conclusion.{shortlist?.generatedAt ? ` Source updated ${fmtDate(shortlist.generatedAt)}.` : ''}</p></div></div><div className="table-scroll datatable-shell"><table ref={tableRef} className="strategy-table ai-war-room-table display compact"><thead><tr><th title="Stock ticker and company name">Company</th><th title="Primary AI exposure category">Theme</th><th title="Published CIO membership classification; not automatic trading permission">Action</th><th title="Evidence scale from 0 (unproven) to 5 (repeatable financial results)">Proof</th><th className="one-month-change" title="Stock-price percentage change over the prior one month">1M</th><th title="Latest reported quarterly revenue growth versus the same quarter one year earlier">Rev growth YoY</th><th title="Free-cash-flow margin: free cash flow divided by revenue; pre-revenue values can be distorted">FCF margin</th><th title="Enterprise value divided by next-twelve-month consensus revenue">EV/NTM rev</th><th title="Base-case implied share price and upside or downside versus the current price">Base case</th><th title="Bull-case implied share price and upside versus the current price">Bull case</th><th title="Upcoming evidence or catalyst required to confirm, upgrade, or invalidate the thesis">Next gate</th></tr></thead><tbody>{comparableRows.map(row => {
    const projection = projectionBySymbol.get(row.symbol)
    const action = publishedValuationAction(row.symbol, shortlist)
    return <tr key={`allocation-${row.symbol}`}><td><ResearchTickerLink symbol={row.symbol} /><small>{row.companyName}</small></td><td><CategoryPill category={aiCategoryForRow(row)} /></td><td className="valuation-action"><span className={cls("valuation-action-label",action.tone)} title={action.reason}>{action.label}</span></td><td data-order={row.proofLevel ?? undefined}>{row.proofLevel ?? '—'}</td><td className="one-month-change" data-order={row.oneMonthChangePct ?? undefined}>{fmtPct(row.oneMonthChangePct) || '—'}</td><td data-order={row.revenueGrowthPct ?? undefined}>{fmtPct(row.revenueGrowthPct) || '—'}</td><td data-order={row.fcfMarginPct ?? undefined}><MarginValue value={row.fcfMarginPct} /></td><td data-order={row.evNtmRevenue ?? projection?.evNtmRevenue ?? undefined}>{fmtMultiple(row.evNtmRevenue ?? projection?.evNtmRevenue)}</td><td data-order={projection?.base?.upsidePct ?? undefined}><strong>{fmtPrice(projection?.base?.impliedPrice) || '—'}</strong><small>{fmtPct(projection?.base?.upsidePct)}</small></td><td data-order={projection?.bull?.upsidePct ?? undefined}><strong>{fmtPrice(projection?.bull?.impliedPrice) || '—'}</strong><small>{fmtPct(projection?.bull?.upsidePct)}</small></td><td><TickerAware text={row.nextCatalystCheckDate || row.addZone || projection?.base?.proofNeeded || 'Review details unavailable'} symbols={knownSymbols} /></td></tr>
  })}</tbody></table></div></section>
}

function CloudedJudgementCompsSection({ rows, knownSymbols, showTable = true }: { rows: AiWarRoomRow[]; knownSymbols: Set<string>; showTable?: boolean }) {
  const comparableRows = stableRowsBySymbol(rows.filter(isAiStockRow))
  if (!comparableRows.length) return null
  const medMultiple = median(comparableRows.map(row => row.evNtmRevenue))
  const medGrowth = median(comparableRows.map(row => row.revenueGrowthPct))
  const medRule = median(comparableRows.map(ruleOf40))
  return <section className="ai-war-room-section">
    <section className="strategy-card ai-projection-policy"><div className="section-header"><div><span className="eyebrow">AI-only comps</span><h3>AI infrastructure quality, growth, and valuation</h3><p>Only AI infrastructure, hardware, power, photonics, neocloud, robotics, defense/autonomy, and frontier names are plotted here. App/software-layer comps are excluded so the visuals do not turn into a generic software screen.</p></div></div></section>
    <section className="strategy-metrics ai-projection-metrics">
      <MetricCard label="Plotted AI rows" value={comparableRows.length} sub="Software/app layer excluded" icon={<Database size={22} />} />
      <MetricCard label="Median EV/NTM rev" value={fmtMultiple(medMultiple)} sub="Multiple sanity check" icon={<TrendingUp size={22} />} />
      <MetricCard label="Median growth" value={fmtPct(medGrowth) || '—'} sub="Latest reported revenue YoY" icon={<Activity size={22} />} />
      <MetricCard className={(medRule || 0) >= 40 ? 'success' : 'warning'} label="Median Rule 40" value={fmtPct(medRule) || '—'} sub="Growth + FCF margin" icon={<ShieldCheck size={22} />} />
    </section>
    <section className="strategy-card ai-chart-gallery"><div className="section-header"><div><h3>AI stock visuals</h3><p>Colors identify AI category on each chart. Margin charts exclude pre-revenue denominator blowups beyond ±500%, while tables still show the raw value.</p></div></div><div className="ai-chart-grid">{showTable && <AiWarRoomGrowthScatter rows={comparableRows} />}<CloudedJudgementGrowthProfitabilityScatter rows={comparableRows} /><AiFcfMarginLeaderboard rows={comparableRows} /><AiRevenueLeaderboard rows={comparableRows} /><CloudedJudgementRuleOf40Chart rows={comparableRows} /></div></section>
    {showTable && <CloudedJudgementCompsTable rows={comparableRows} knownSymbols={knownSymbols} />}
  </section>
}

function AiWarRoomCompleteDataSection({ warRoom, knownSymbols, projectionRows, shortlist }: { warRoom: AiWarRoomCompleteData; knownSymbols: Set<string>; projectionRows?: AiProjectionRow[]; shortlist?: AsymmetricShortlist | null }) {
  const rows = warRoom.rows || []
  const aiRows = rows.filter(isAiStockRow)
  const completed = warRoom.manifest?.completed ?? rows.length
  const errors = warRoom.manifest?.errors ?? 0
  const excludedRows = rows.length - aiRows.length
  const fcfRows = aiRows.filter(isComparableFcfMargin).length
  const rule40Rows = aiRows.filter(row => ruleOf40(row) !== null).length
  return <section className="ai-war-room-section">
    {projectionRows && <AiCapitalAllocationTable rows={aiRows} projections={projectionRows} knownSymbols={knownSymbols} shortlist={shortlist} />}
    <section className="strategy-metrics ai-projection-metrics">
      <MetricCard className={errors ? 'urgent' : 'success'} label="AI rows plotted" value={`${aiRows.length}/${completed}`} sub={`${excludedRows} software/app-layer rows excluded · ${errors} errors`} icon={<Database size={22} />} />
      <MetricCard label="Category colors" value={Array.from(new Set(aiRows.map(aiCategoryForRow))).length} sub="Power, photonics, semis, infra, robotics, defense" icon={<Target size={22} />} />
      <MetricCard className={fcfRows ? 'success' : 'warning'} label="FCF margin rows" value={fcfRows} sub={`${rule40Rows} rows support comparable Rule of 40; |FCF margin| &gt; 500% excluded`} icon={<Zap size={22} />} />
      <MetricCard label="Freshness" value={fmtDate(warRoom.generatedAt).split(',')[0]} sub="Latest research update" icon={<Clock3 size={22} />} />
    </section>
    <section className="strategy-card ai-chart-gallery"><div className="section-header"><div><h3>Financial and evidence charts</h3><p>Growth/valuation and proof ranking, with category keys repeated on each chart.</p></div></div><div className="ai-chart-grid"><AiWarRoomGrowthScatter rows={aiRows} /><AiWarRoomProofChart rows={aiRows} /></div></section>
    <CloudedJudgementCompsSection rows={aiRows} knownSymbols={knownSymbols} showTable={!projectionRows} />
    {!projectionRows && <AiWarRoomCompleteDataTable rows={aiRows} knownSymbols={knownSymbols} />}
    <section className="strategy-card"><div className="section-header"><div><span className="eyebrow">Research sources</span><h3>Research source references</h3><p>Public source references supporting these tables. Internal source locations are not published.</p></div></div><div className="ops-artifact-chips">{(warRoom.sourcePaths || []).map(path => <span key={path}>{publicSourceReference(path)}</span>)}</div></section>
  </section>
}

function AiProjectionDashboard({ data, combined = false }: { data: DashboardData; combined?: boolean }) {
  const exhibit = data.aiProjectionExhibits
  const warRoom = data.aiWarRoomCompleteData
  const rawRows = exhibit?.rows || []
  const rows = rawRows.filter(isAiStockRow)
  const warRows = warRoom?.rows || []
  const knownSymbols = useMemo(() => new Set([...data.tickers.map(t => t.symbol), ...rows.map(r => r.symbol), ...warRows.map(r => r.symbol)]), [data.tickers, rows, warRows])
  const topBase = [...rows].filter(r => typeof r.base?.upsidePct === 'number').sort((a, b) => (b.base?.upsidePct || -9999) - (a.base?.upsidePct || -9999))
  const chartData = exhibit?.chartData || {}
  const projectionChartRows = (key: string) => ((chartData[key] || []) as Array<Record<string, string | number | boolean | null>>).filter(isAiStockRow)
  const football = projectionChartRows('projection_football_field')
  if (!exhibit) return <section className="ai-projection-page"><div className="empty">Valuation inputs are unavailable. Other published research remains accessible.</div></section>
  return <section className="ai-projection-page">
    {warRoom && <AiWarRoomCompleteDataSection warRoom={warRoom} knownSymbols={knownSymbols} projectionRows={combined ? rows : undefined} shortlist={data.currentAsymmetricShortlist} />}

    <section className="strategy-card ai-chart-gallery"><div className="section-header"><div><h3>Interactive AI visuals</h3><p>Charts render from public JSON in the browser. Each chart carries its own category key so the color meaning is visible locally.</p></div></div><div className="ai-chart-grid">
      <AiProjectionBarChart title="Base implied upside" rows={projectionChartRows('base_implied_upside_bar')} valueKey="baseUpsidePct" yLabel="Base upside %" />
      <AiProjectionBarChart title="Bull implied upside" rows={projectionChartRows('bull_implied_upside_bar')} valueKey="bullUpsidePct" yLabel="Bull upside %" />
      {!combined && <AiProjectionScatterChart rows={projectionChartRows('growth_vs_valuation_scatter')} />}
      {!combined && <AiProjectionQualityChart summary={exhibit.summary} />}
      <AiProjectionFootballChart rows={football} />
    </div></section>

    {!combined && <ProjectionDataTable rows={topBase} knownSymbols={knownSymbols} />}

    {!combined && <section className="strategy-card"><div className="section-header"><div><span className="eyebrow">Universe detail</span><h3>All included AI names</h3><p>Shows why each ticker is in the AI projection universe and what field gaps block better valuation work.</p></div></div><div className="ai-universe-grid">{rows.map(row => <article className={cls('ai-universe-card', projectionTone(row))} key={`universe-${row.symbol}`}><div><strong><ResearchTickerLink symbol={row.symbol} /></strong><span>{row.archetype}</span></div><p>{row.inclusionReason}</p><ul><li>Base: {fmtPct(row.base?.upsidePct) || 'not supported'} / Bull: {fmtPct(row.bull?.upsidePct) || 'not supported'}</li><li>Multiple: EV/Rev {fmtMultiple(row.evNtmRevenue)}, P/E {fmtMultiple(row.peNtm)}, EV/EBITDA {fmtMultiple(row.evEbitdaNtm)}</li><li>Missing: {(row.missingCriticalFields || []).join(', ') || 'none flagged'}</li></ul><small>{row.sourcePage}</small></article>)}</div></section>}

    {!combined && !!football.length && <section className="strategy-card"><div className="section-header"><div><span className="eyebrow">Readable chart data</span><h3>Projection football field rows</h3><p>Exact values behind the football-field chart for the tickers with full bear/base/bull support.</p></div></div><div className="table-scroll"><table className="strategy-table"><thead><tr><th>Ticker</th><th>Current</th><th>Bear</th><th>Base</th><th>Bull</th></tr></thead><tbody>{football.map(row => <tr key={`football-${row.symbol}`}><td>{typeof row.symbol === 'string' ? <ResearchTickerLink symbol={row.symbol} /> : 'Ticker unavailable'}</td><td>{fmtPrice(row.currentPrice as number)}</td><td>{fmtPrice(row.bear as number)}</td><td>{fmtPrice(row.base as number)}</td><td>{fmtPrice(row.bull as number)}</td></tr>)}</tbody></table></div></section>}

    <section className="strategy-card"><div className="section-header"><div><span className="eyebrow">Research sources</span><h3>Source files</h3><p>Source references supporting the valuation scenarios. A scenario is not a recommendation.</p></div></div><div className="ops-artifact-chips">{Object.entries(exhibit.artifactPaths || {}).map(([k, v]) => <span key={k}>{publicSourceReference(v)}</span>)}</div></section>
  </section>
}

export function ValuationDashboard({ data }: { data: DashboardData }) {
  useOwnerChartTheme()
  const knownSymbols = useMemo(() => new Set(data.tickers.map(t => t.symbol)), [data.tickers])
  return <section className="strategy-page valuation-page">
    <AiProjectionDashboard data={data} combined />
    <DecisionLearningPanel learning={data.currentAsymmetricShortlist?.decisionLearning} knownSymbols={knownSymbols} />
  </section>
}

function Sources({ data }: { data: DashboardData }) {
  return <section className="sources-page">
    <div className="section-header command-intro"><div><span className="eyebrow">Information supply chain</span><h2>Where the dashboard gets its signal</h2><p>No file dump here — just the human-readable map of sources and how each source should be weighted.</p></div></div>
    <div className="sources-grid">{data.sources.map(group => <article className="source-card" key={group.name}><div className="card-topline"><span className="eyebrow">{group.role}</span></div><h3>{group.name}</h3><p>{group.summary}</p><div className="example-cloud">{group.examples.map(e => <span key={e}>{e}</span>)}</div><p className="why"><strong>How to use:</strong> {group.howUsed}</p></article>)}</div>
  </section>
}

export const isPublishedDashboard = (value: unknown): value is DashboardData => isDashboardData(value) && hasPublicationContract(value)
export default function App() {
  useOwnerChartTheme()
  const marketData = useMarketData<DashboardData>(isPublishedDashboard)
  const data = useMemo(() => normalizeDashboardData(marketData.data), [marketData.data])
  const [tab, setTab] = useState<Tab>(() => tabFromHash(window.location.hash))
  const [selectedTicker, setSelectedTicker] = useState(() => tickerFromHash(window.location.hash))
  const selectTab = (next: Tab) => {
    setTab(next)
    const baseUrl = `${window.location.pathname}${window.location.search}`
    window.history.replaceState(null, '', next === 'market' ? baseUrl : `${baseUrl}#${next}`)
  }
  useEffect(() => {
    const onHash = () => {
      setTab(tabFromHash(window.location.hash))
      const symbol = tickerFromHash(window.location.hash)
      if (symbol) setSelectedTicker(symbol)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  if (!data && marketData.error) return <main className="shell"><div className="empty">Research is unavailable. Please try again later.</div></main>
  if (!data) return <main className="shell"><div className="empty">Loading market research…</div></main>
  return <main className="shell">
    <nav className="tabs">{dashboardTabs.map(item => <button key={item.id} className={cls(tab === item.id && 'active')} onClick={() => selectTab(item.id)}>{item.label}</button>)}</nav>
    {tab === 'cio' && <CioBrief data={data} onSelectTicker={(symbol) => { setSelectedTicker(symbol); selectTab('stocks') }} />}{tab === 'strategy' && <ValuationDashboard data={data} />}{tab === 'market' && <DailyBriefTimeline data={data} />}{tab === 'stocks' && <StockResearch data={data} selected={selectedTicker} setSelected={setSelectedTicker} />}{tab === 'ops' && <WorkflowOps data={data} mode={marketData.mode} isStagedPreview={isStagedPreviewBuild} lastCheckedAt={marketData.lastCheckedAt} manifest={marketData.manifest} error={marketData.error} />}{tab === 'sources' && <Sources data={data} />}
    <footer><p><strong>Data mode:</strong> {dataModeLabel(marketData.mode)}{marketData.lastCheckedAt ? ` · checked ${fmtDate(marketData.lastCheckedAt)}` : ''}</p>{marketData.error && <p>The latest update could not be loaded. Showing the last available publication.</p>}<p>{data.privacy.note}</p><p>Excluded: {data.privacy.excluded.join(', ')}</p></footer>
  </main>
}
