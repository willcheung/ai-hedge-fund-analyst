import { formatTimestamp, publicationDay } from './researchComponents';

/** Optional snapshot prose must be text before it reaches string operations. */
export function briefText(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

/** Exact producer identities from audited job provenance, including the verified
 * historical macro producer. Extend only with audited provenance. */
export const timelineJobCategories: Readonly<Record<string, string>> = Object.freeze({
  'synthetic-macro': 'Macro Read',
  'synthetic-job-08': 'Weekly Stock Analysis',
  'synthetic-job-0c': 'Weekly Stock Analysis',
});

/** Resolve metadata only: financial claims and article titles are not evidence
 * of a publishing job. Unknown producers retain their supplied category. */
export function timelineCategory(jobId: unknown, category: unknown, knownMappings: Readonly<Record<string, string>> = timelineJobCategories): string {
  const id = briefText(jobId).trim();
  const mapped = Object.prototype.hasOwnProperty.call(knownMappings, id) ? briefText(knownMappings[id]).trim() : '';
  const label = mapped || briefText(category).trim();
  return !label || ['research update', 'other research job', 'unknown'].includes(label.toLowerCase())
    ? 'Uncategorized research' : label;
}

/** Suppress scheduler/category placeholders, never original research prose. */
export function briefHeadline(title: unknown, category: unknown = ''): string | null {
  const text = briefText(title).trim();
  const normalized = text.toLowerCase();
  return !normalized || normalized === briefText(category).trim().toLowerCase()
    || ['research update', 'other research job', 'macro read'].includes(normalized) ? null : text;
}

/** Only timeline cron records attest that this exact legacy clock is UTC. */
export function timelineInstant(value: string): string {
  if (!/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(value)) return value;
  const utc = value.replace(' ', 'T') + 'Z';
  const parsed = Date.parse(utc);
  return Number.isFinite(parsed) && new Date(parsed).toISOString().slice(0, 19) === utc.slice(0, 19) ? utc : value;
}

export function timelineTimestamp(value: string): string {
  const stamp = timelineInstant(value);
  if (!/(?:Z|[+-]\d{2}:\d{2})$/.test(stamp) || !Number.isFinite(Date.parse(stamp))) return formatTimestamp(stamp);
  const clock = new Intl.DateTimeFormat('en-US', {timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit', hour12: true, timeZoneName: 'short'}).format(new Date(stamp));
  return `${publicationDay(stamp)} ${clock}`;
}

/** Remove evidence labels, preserving substantive language and fenced literals. */
export function cleanObservedPrefixes(text: string): string {
  let fence: string | undefined;
  return text.split('\n').map(line => {
    const marker = /^ {0,3}(`{3,}|~{3,})/.exec(line)?.[1];
    if (marker) {
      if (!fence) fence = marker;
      else if (marker[0] === fence[0] && marker.length >= fence.length) fence = undefined;
      return line;
    }
    if (fence) return line;
    const start = /^(\s*(?:(?:[-+*]|\d+[.)])\s+)?(?:[🟢🟡🔴⚪📌⚠]\uFE0F?\s+)?)/u.exec(line)![0];
    let body = line.slice(start.length);
    const label = /^(\*\*|__)?Observed(\*\*|__)?[ \t]*[:–—][ \t]*(\*\*|__)?[ \t]*/i;
    while (label.test(body)) {
      body = body.replace(label, (_, open, closeBefore, closeAfter) => open && !closeBefore && !closeAfter ? open : '');
    }
    return start + body;
  }).join('\n');
}

export function macroProse(text: string): string {
  return cleanObservedPrefixes(text).replace(/^\s*#\s+Macro Read\s*[—–:-]\s*\d{4}-\d{2}-\d{2}[ \t]*(?:\n|$)/i, '').trim();
}

// Compare whole prose blocks, ignoring only presentation markers. Never fuzzy-match
// research claims, case, punctuation, URLs, or uncertainty qualifiers.
function comparable(text: string): string {
  return cleanObservedPrefixes(text).replace(/^\s*(?:[-+*]|\d+[.)])\s+/gm, '')
    .replace(/^\s*[🟢🟡🔴⚪📌⚠]\uFE0F?\s*/gmu, '')
    .replace(/\*\*|__/g, '').replace(/\s+/g, ' ').trim();
}
export function uniqueMacroHighlights(highlights: string[], body: string): string[] {
  const blocks = body.split(/\n\s*\n/).map(comparable);
  return highlights.filter(highlight => {
    const full = comparable(highlight);
    if (!full) return false;
    const prefix = full.replace(/(?:…|\.{3})$/, '').trimEnd();
    return !blocks.some(block => block === full || (prefix.length > 0 && block.startsWith(prefix)
      && (prefix !== full || highlight.length >= 280)));
  });
}

/** Preserve sourced company identity as prose only when absent from the content. */
export function timelineIdentity(title: unknown, category: unknown, content: string, companyNames: string[] = []): string | null {
  const source = briefHeadline(title, category);
  // Keep the publisher's 8–170 character, single-line source-title boundary.
  if (!source || source.length < 8 || source.length > 170 || /[\r\n]/.test(source) || source.split(/\s+/).length < 2) return null;
  if (/^(?:scheduled|automated|automation)\b|\b(?:cron|job|prompt|pipeline|scheduler|skill)\b/i.test(source)
    || ['market setup', 'bottom line', 'regime map', 'research', 'response', 'summary'].includes(source.toLowerCase())
    || /^(?:(?:daily|weekly|monthly|hourly)\s+)?(?:(?:macro|market|stock|company|earnings)\s+)?(?:research|commentary|analysis|scan|read|update|job|brief|monitor|report)(?:\s+(?:job|scan|update|run))?$/i.test(source)) return null;
  if (comparable(content).includes(comparable(source))) return null;
  const symbols = source.match(/\$[A-Z][A-Z0-9.-]*/g) || [];
  const identities = [...symbols, ...companyNames.filter(name => name && source.includes(name))];
  // Unknown issuers still have sourced context. Do not infer a symbol from the
  // financial prose or require an entry in the research directory to retain it.
  return identities.length ? (identities.some(identity => !content.includes(identity)) ? source : null) : source;
}
