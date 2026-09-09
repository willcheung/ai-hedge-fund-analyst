type MeterChange = { status: 'available' | 'unavailable'; value: number | null; comparisonAsOf: string | null }
type MacroRegimePillar = { id: MeterPillarId; label: string; score: number | null; weight: number; direction: 'supportive' | 'mixed' | 'restrictive' | 'unavailable'; confidence: 'medium' | 'low' | 'unavailable'; freshnessStatus: 'current' | 'unavailable'; asOf: string | null; drivers: string[]; sourceIds: MeterSourceId[]; eligibility: boolean; reason: string | null }
type MeterPillarId = 'trend_breadth' | 'liquidity_financial_conditions' | 'credit' | 'growth_earnings' | 'inflation_policy' | 'volatility_positioning'
type MeterSourceId = 'tradermonty.market_breadth' | 'tradermonty.rsp_spy_proxy' | 'tradermonty.iwm_spy_proxy' | 'tradermonty.hyg_lqd_proxy' | 'tradermonty.shy_tlt_proxy'
type MeterBand = 'risk_off' | 'defensive' | 'neutral_mixed' | 'selective_risk_on' | 'constructive' | 'broad_risk_on' | 'unavailable'
export type MacroRegimeMeterData = { schemaVersion: 1; methodologyVersion: 'macro-regime-meter-v1'; generatedAt: string | null; asOf: string | null; score: number | null; regimeBand: MeterBand; regimeLabel: string; direction: 'improving' | 'steady' | 'deteriorating' | 'unavailable'; dailyChange: MeterChange; weeklyChange: MeterChange; confidence: 'high' | 'medium' | 'low' | 'unavailable'; freshnessStatus: 'current' | 'stale' | 'unavailable'; postureInterpretation: string; positiveDrivers: string[]; negativeDrivers: string[]; pillars: MacroRegimePillar[]; sourceHealth: { status: 'pass' | 'fail_closed'; eligibleWeight: number; minimumEligibleWeight: 55; totalWeight: 100; unavailablePillars: MeterPillarId[]; sources: { id: MeterSourceId; path: string }[]; reason?: string | null }; history: { asOf: string; score: number; regimeBand: Exclude<MeterBand, 'unavailable'>; generatedAt: string; methodologyVersion: 'macro-regime-meter-v1' }[] }

function isRecord(value: unknown): value is Record<string, any> { return typeof value === "object" && value !== null && !Array.isArray(value) }
function stringArray(value: unknown): value is string[] { return Array.isArray(value) && value.every(item => typeof item === "string") }
function exactKeys(value: Record<string, unknown>, required: string[], optional: string[] = []) {
  const allowed = new Set([...required, ...optional])
  return required.every(key => key in value) && Object.keys(value).every(key => allowed.has(key))
}
export function isMacroRegimeMeter(value: unknown): value is MacroRegimeMeterData {
  if (!isRecord(value)) return false
  const keys = ['schemaVersion', 'methodologyVersion', 'generatedAt', 'asOf', 'score', 'regimeBand', 'regimeLabel', 'direction', 'dailyChange', 'weeklyChange', 'confidence', 'freshnessStatus', 'postureInterpretation', 'positiveDrivers', 'negativeDrivers', 'pillars', 'sourceHealth', 'history']
  const pillarSpecs = [
    ['trend_breadth', 'Trend & breadth', 25], ['liquidity_financial_conditions', 'Liquidity & financial conditions', 20],
    ['credit', 'Credit', 15], ['growth_earnings', 'Growth & earnings', 15], ['inflation_policy', 'Inflation & policy', 15],
    ['volatility_positioning', 'Volatility & positioning', 10],
  ] as const
  const bandLabels: Record<string, string> = { risk_off: 'Risk off', defensive: 'Defensive', neutral_mixed: 'Neutral / mixed', selective_risk_on: 'Selective risk on', constructive: 'Constructive', broad_risk_on: 'Broad risk on', unavailable: 'Unavailable' }
  const bandIds = Object.keys(bandLabels)
  const sourceIds = new Set(['tradermonty.market_breadth', 'tradermonty.rsp_spy_proxy', 'tradermonty.iwm_spy_proxy', 'tradermonty.hyg_lqd_proxy', 'tradermonty.shy_tlt_proxy'])
  const meterDrivers = new Set(['Breadth health plus RSP/SPY and IWM/SPY participation percentiles', 'HYG/LQD percentile proxy', 'SHY/TLT percentile proxy, inverted because a rising ratio implies duration pressure'])
  const meterPostures = new Set(['Preserve risk capacity; require unusually strong proof for new exposure.', 'Keep risk constrained and favor resilience while conditions remain fragile.', 'Keep sizing selective; wait for broader confirmation before adding risk.', 'Risk is permitted selectively, with confirmation and disciplined sizing.', 'Conditions support measured risk-taking while normal controls remain in place.', 'Broad risk participation is supported; retain normal concentration controls.', 'Insufficient current structured evidence to set macro risk permission.'])
  const unavailableReasons: Record<string, string> = { trend_breadth: 'Current complete structured breadth inputs are unavailable', liquidity_financial_conditions: 'No robust current structured daily series', credit: 'Current HYG/LQD proxy is unavailable', growth_earnings: 'No robust current structured daily series', inflation_policy: 'Current SHY/TLT proxy is unavailable', volatility_positioning: 'Current structured VIX or sentiment history is unavailable' }
  const healthReasons = new Set<unknown>(["Canonical artifact failed its closed contract", "Canonical artifact failed its semantic privacy and vocabulary contract", "Canonical artifact is missing or unreadable", "Canonical artifact is not an object", "Canonical artifact was not supplied", "missing", null])
  // Exact reviewed references only; "path" is a legacy field name, not a path grant.
  const publicReferences: Record<string, readonly string[]> = {
    'tradermonty.market_breadth': ["tradermonty.market_breadth", "synthetic/inputs/market_breadth.json"],
    'tradermonty.rsp_spy_proxy': ["tradermonty.rsp_spy_proxy", "synthetic/inputs/rsp_spy_proxy.json"],
    'tradermonty.iwm_spy_proxy': ["tradermonty.iwm_spy_proxy", "synthetic/inputs/iwm_spy_proxy.json"],
    'tradermonty.hyg_lqd_proxy': ["tradermonty.hyg_lqd_proxy", "synthetic/inputs/hyg_lqd_proxy.json"],
    'tradermonty.shy_tlt_proxy': ["tradermonty.shy_tlt_proxy", "synthetic/inputs/shy_tlt_proxy.json"],
  }

  const dateOnly = (text: unknown): text is string => {
    if (typeof text !== 'string' || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(text) || text.startsWith('0000')) return false
    const parsed = new Date(`${text}T00:00:00Z`)
    return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === text
  }
  const dateTime = (text: unknown) => {
    if (typeof text !== 'string') return false
    const match = /^([0-9]{4}-[0-9]{2}-[0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.[0-9]+)?(Z|[+-]([0-9]{2}):([0-9]{2}))$/.exec(text)
    return !!match && match[0] === text && dateOnly(match[1]) && +match[2] < 24 && +match[3] < 60 && +match[4] < 60 && (match[5] === 'Z' || (+match[6] < 24 && +match[7] < 60)) && Number.isFinite(Date.parse(text))
  }
  const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
  const pillarInputs: Record<string, [string[], string[]]> = {
    trend_breadth: [['Breadth health plus RSP/SPY and IWM/SPY participation percentiles'], ['tradermonty.market_breadth', 'tradermonty.rsp_spy_proxy', 'tradermonty.iwm_spy_proxy']],
    credit: [['HYG/LQD percentile proxy'], ['tradermonty.hyg_lqd_proxy']],
    inflation_policy: [['SHY/TLT percentile proxy, inverted because a rising ratio implies duration pressure'], ['tradermonty.shy_tlt_proxy']],
  }
  const boundedTenth = (number: unknown, low: number, high: number) => typeof number === 'number' && Number.isFinite(number) && number >= low && number <= high && Math.abs(number * 10 - Math.round(number * 10)) < 1e-8
  if (typeof value.regimeBand !== 'string' || typeof value.direction !== 'string' || typeof value.confidence !== 'string' || typeof value.freshnessStatus !== 'string') return false
  if (!exactKeys(value, keys) || value.schemaVersion !== 1 || value.methodologyVersion !== 'macro-regime-meter-v1' || !bandIds.includes(String(value.regimeBand)) || value.regimeLabel !== bandLabels[String(value.regimeBand)] || !['improving', 'steady', 'deteriorating', 'unavailable'].includes(String(value.direction)) || !['high', 'medium', 'low', 'unavailable'].includes(String(value.confidence)) || !['current', 'stale', 'unavailable'].includes(String(value.freshnessStatus)) || value.postureInterpretation !== [...meterPostures][bandIds.indexOf(String(value.regimeBand))]) return false
  if (!(value.score === null || boundedTenth(value.score, 1, 10))) return false
  if (!(value.asOf === null || dateOnly(value.asOf)) || !(value.generatedAt === null || dateTime(value.generatedAt)) || !stringArray(value.positiveDrivers) || value.positiveDrivers.length > 3 || !value.positiveDrivers.every(driver => meterDrivers.has(driver)) || !stringArray(value.negativeDrivers) || value.negativeDrivers.length > 3 || !value.negativeDrivers.every(driver => meterDrivers.has(driver))) return false
  const validChange = (change: unknown) => isRecord(change) && exactKeys(change, ['status', 'value', 'comparisonAsOf']) && (
    change.status === 'available' ? boundedTenth(change.value, -9, 9) && dateOnly(change.comparisonAsOf) : change.status === 'unavailable' && change.value === null && change.comparisonAsOf === null)
  if (!validChange(value.dailyChange) || !validChange(value.weeklyChange)) return false
  if (!Array.isArray(value.pillars) || value.pillars.length !== 6 || !value.pillars.every((item, index) => {
    if (!isRecord(item) || !exactKeys(item, ['id', 'label', 'score', 'weight', 'direction', 'confidence', 'freshnessStatus', 'asOf', 'drivers', 'sourceIds', 'eligibility', 'reason'])) return false
    const [id, label, weight] = pillarSpecs[index]
    if (item.id !== id || item.label !== label || item.weight !== weight || typeof item.eligibility !== 'boolean' || !stringArray(item.drivers) || item.drivers.length > 5 || !item.drivers.every(driver => meterDrivers.has(driver)) || !stringArray(item.sourceIds) || item.sourceIds.length > 5 || !(item.sourceIds as string[]).every((source: string) => sourceIds.has(source)) || new Set(item.sourceIds as string[]).size !== item.sourceIds.length) return false
    if (item.eligibility) return item.reason === null && boundedTenth(item.score, 1, 10) && item.direction === ((item.score as number) >= 6 ? 'supportive' : (item.score as number) < 4.5 ? 'restrictive' : 'mixed') && !!pillarInputs[id] && same([item.drivers, item.sourceIds], pillarInputs[id]) && item.confidence === (id === 'trend_breadth' ? 'medium' : 'low') && item.freshnessStatus === 'current' && dateOnly(item.asOf)
    return item.reason === unavailableReasons[id] && item.score === null && item.direction === 'unavailable' && item.confidence === 'unavailable' && item.freshnessStatus === 'unavailable' && item.asOf === null && item.drivers.length === 0 && item.sourceIds.length === 0
  })) return false
  if (!isRecord(value.sourceHealth) || !exactKeys(value.sourceHealth, ['status', 'eligibleWeight', 'minimumEligibleWeight', 'totalWeight', 'unavailablePillars', 'sources'], ['reason']) || !['pass', 'fail_closed'].includes(String(value.sourceHealth.status)) || !Number.isSafeInteger(value.sourceHealth.eligibleWeight) || value.sourceHealth.minimumEligibleWeight !== 55 || value.sourceHealth.totalWeight !== 100 || !stringArray(value.sourceHealth.unavailablePillars) || !(value.sourceHealth.reason === undefined || value.sourceHealth.reason === null || healthReasons.has(value.sourceHealth.reason)) || !Array.isArray(value.sourceHealth.sources) || value.sourceHealth.sources.length > 10 || value.sourceHealth.unavailablePillars.length > 6 || !value.sourceHealth.sources.every(source => isRecord(source) && exactKeys(source, ['id', 'path']) && sourceIds.has(source.id) && typeof source.path === 'string' && publicReferences[source.id]?.includes(source.path))) return false
  const eligible = value.pillars.filter(pillar => pillar.eligibility)
  const eligibleWeight = eligible.reduce((total, pillar) => total + pillar.weight, 0)
  const unavailable = value.pillars.filter(pillar => !pillar.eligibility).map(pillar => pillar.id)
  const resolved = value.sourceHealth.sources.map(source => source.id)
  if (eligibleWeight !== value.sourceHealth.eligibleWeight || unavailable.join('|') !== value.sourceHealth.unavailablePillars.join('|') || new Set(resolved).size !== resolved.length || value.pillars.some(pillar => pillar.sourceIds.some((source: string) => !resolved.includes(source)))) return false
  if (value.score === null ? !(eligibleWeight < 55 && value.regimeBand === 'unavailable' && value.direction === 'unavailable' && value.confidence === 'unavailable' && value.freshnessStatus === 'unavailable' && value.sourceHealth.status === 'fail_closed') : !(eligibleWeight >= 55 && value.regimeBand !== 'unavailable' && value.freshnessStatus === 'current' && value.sourceHealth.status === 'pass' && value.asOf === eligible.map(pillar => pillar.asOf as string).sort()[0])) return false
  if (resolved.length !== eligible.reduce((total, pillar) => total + pillar.sourceIds.length, 0)) return false
  if (!same(value.positiveDrivers, eligible.filter(pillar => pillar.score >= 6).map(pillar => pillar.drivers[0]).slice(0, 3)) || !same(value.negativeDrivers, eligible.filter(pillar => pillar.score < 4.5).map(pillar => pillar.drivers[0]).slice(0, 3))) return false
  if (typeof value.score === 'number') {
    // Eligible weights sum to 55 in v1; integer tenths avoid floating tie drift.
    const weightedTenths = eligible.reduce((total, pillar) => total + Math.round(pillar.score * 10) * pillar.weight, 0) / eligibleWeight
    const rounded = Math.round(weightedTenths) / 10
    if (value.score !== rounded || !dateTime(value.generatedAt) || value.confidence !== (eligibleWeight >= 70 ? 'medium' : 'low')) return false
    const bounds = [[1, 2.9], [3, 4.4], [4.5, 5.9], [6, 7.4], [7.5, 8.9], [9, 10]]
    const [low, high] = bounds[bandIds.indexOf(String(value.regimeBand))]
    const daily = value.dailyChange as MeterChange
    if (value.score < low || value.score > high) {
      const prior = value.score - (daily.value as number)
      if (daily.status !== 'available' || value.score < low - .2 - 1e-8 || value.score > high + .2 + 1e-8 || prior < low - .2 - 1e-8 || prior > high + .2 + 1e-8) return false
    }
  }
  for (const change of [value.dailyChange, value.weeklyChange] as MeterChange[]) {
    if (change.status === 'available' && (typeof value.score !== 'number' || !dateOnly(value.asOf) || change.comparisonAsOf! >= value.asOf || value.score - change.value! < 1 - 1e-8 || value.score - change.value! > 10 + 1e-8)) return false
  }
  const daily = value.dailyChange as MeterChange
  const expectedDirection = daily.status === 'unavailable' ? 'unavailable' : Math.abs(daily.value as number) < .2 ? 'steady' : (daily.value as number) > 0 ? 'improving' : 'deteriorating'
  if (value.direction !== expectedDirection) return false
  const historyBandBounds: Record<string, [number, number]> = { risk_off: [1, 3.1], defensive: [2.8, 4.6], neutral_mixed: [4.3, 6.1], selective_risk_on: [5.8, 7.6], constructive: [7.3, 9.1], broad_risk_on: [8.8, 10] }
  return Array.isArray(value.history) && value.history.length <= 40 && value.history.every(row => isRecord(row) && exactKeys(row, ['asOf', 'score', 'regimeBand', 'generatedAt', 'methodologyVersion']) && dateOnly(row.asOf) && boundedTenth(row.score, 1, 10) && typeof row.regimeBand === 'string' && bandIds.slice(0, -1).includes(row.regimeBand) && (row.score as number) >= historyBandBounds[row.regimeBand][0] && (row.score as number) <= historyBandBounds[row.regimeBand][1] && dateTime(row.generatedAt) && row.methodologyVersion === 'macro-regime-meter-v1')
}
