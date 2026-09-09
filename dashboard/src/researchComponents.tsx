import React, { type ReactNode } from 'react';

/** Percent inputs are percentage points (1.93 means 1.93%), not fractions. */
export type FinancialValue = number | null | undefined;
export type Direction = 'positive' | 'negative' | 'neutral';
const finite = (value: FinancialValue): value is number => typeof value === 'number' && Number.isFinite(value);
const digits = (precision: number) => Number.isFinite(precision) ? Math.min(8, Math.max(0, Math.trunc(precision))) : 2;
const cleanZero = (value: number, precision: number) => Number(value.toFixed(digits(precision))) === 0 ? 0 : value;
const decimal = (value: number, precision = 2) => new Intl.NumberFormat('en-US', { minimumFractionDigits: digits(precision), maximumFractionDigits: digits(precision) }).format(cleanZero(value, precision));

export function formatPrice(value: FinancialValue, currency = 'USD', precision = 2): string {
  if (!finite(value)) return '—';
  const normalized = cleanZero(value, precision);
  if (!/^[A-Z]{3}$/.test(currency)) return decimal(normalized, precision);
  return new Intl.NumberFormat('en-US', { style: 'currency', currency, minimumFractionDigits: digits(precision), maximumFractionDigits: digits(precision) }).format(normalized);
}
export function formatPercent(value: FinancialValue, precision = 2): string {
  return finite(value) ? `${decimal(value, precision)}%` : '—';
}
export function formatChange(value: FinancialValue, currency = 'USD', precision = 2): string {
  if (!finite(value)) return '—';
  const normalized = cleanZero(value, precision);
  return `${normalized > 0 ? '+' : normalized < 0 ? '−' : ''}${formatPrice(Math.abs(normalized), currency, precision)}`;
}
export function formatPercentChange(value: FinancialValue, precision = 2): string {
  if (!finite(value)) return '—';
  const normalized = cleanZero(value, precision);
  return `${normalized > 0 ? '+' : normalized < 0 ? '−' : ''}${formatPercent(Math.abs(normalized), precision)}`;
}
export function financialDirection(value: FinancialValue, precision = 2): Direction {
  if (!finite(value)) return 'neutral';
  const normalized = cleanZero(value, precision);
  return normalized > 0 ? 'positive' : normalized < 0 ? 'negative' : 'neutral';
}

/** Only an explicit timezone-bearing timestamp can establish a quote instant. */
function instant(value: string | null | undefined): number | null {
  if (!value || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}
const easternTimestamp = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23', timeZoneName: 'short',
});
function easternParts(value: number) {
  return Object.fromEntries(easternTimestamp.formatToParts(value).map(part => [part.type, part.value]));
}
/** Calendar dates have no instant; unknown source timezones must not be guessed. */
export function publicationDay(value: string | null | undefined): string {
  const parsed = instant(value);
  if (parsed !== null) {
    const p = easternParts(parsed);
    return `${p.year}-${p.month}-${p.day}`;
  }
  return formatTimestamp(value) === 'Timestamp unavailable' ? 'Date unavailable' : value!.slice(0, 10);
}
export function formatTimestamp(value: string | null | undefined): string {
  if (value && /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}$/.test(value)) {
    const wallClock = value.replace(' ', 'T');
    // UTC is used only to validate calendar fields, never to assign the source a timezone.
    const validFields = Date.parse(`${wallClock}Z`);
    if (Number.isFinite(validFields) && new Date(validFields).toISOString().slice(0,19) === wallClock) return value;
  }
  if (value && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0,10) === value) return value;
  const parsed = instant(value);
  if (parsed === null) return 'Timestamp unavailable';
  const p = easternParts(parsed);
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second} ${p.timeZoneName}`;
}
export interface QuoteChange {
  absolute?: FinancialValue;
  percent?: FinancialValue;
  /** Provenance attestation by the adapter, never inferred from a price. */
  trusted: boolean;
  period: string;
  asOf: string;
}
export interface QuoteData {
  symbol?: string;
  price?: FinancialValue;
  currency?: string;
  asOf?: string | null;
  stale?: boolean;
  change?: QuoteChange | FinancialValue;
  changePct?: FinancialValue;
  period?: string;
  previousAsOf?: string;
}
export interface QuoteProps {
  quote?: QuoteData | null;
  precision?: number;
  /** Set only for a quote from the validated publication DTO, not raw feeds. */
  trusted?: boolean;
}
export function Quote({ quote, precision = 2, trusted = false }: QuoteProps) {
  if (!quote || !finite(quote.price)) return <span className="quote quote-unavailable">Quote unavailable</span>;
  const stamp = instant(quote.asOf);
  const previous = instant(quote.previousAsOf);
  // Mirrors the publisher's day-period compatibility guard (weekends allowed).
  // Never calculate a change from two unrelated prices or guess provenance.
  const dtoCompatible = trusted && stamp !== null && previous !== null && stamp > previous && stamp - previous <= 4 * 86400 * 1000;
  const change: QuoteChange | null = typeof quote.change === 'object' && quote.change !== null ? quote.change : {
    absolute: quote.change, percent: quote.changePct, trusted: dtoCompatible,
    period: quote.period || '', asOf: quote.asOf || '',
  };
  const compatible = change?.trusted === true && change.period === 'day' && stamp !== null && instant(change.asOf) === stamp;
  const signsAgree = !finite(change?.absolute) || !finite(change?.percent) || Math.sign(change.absolute) === Math.sign(change.percent);
  return <div className="quote">
    <span className="quote-price financial-value">{formatPrice(quote.price, quote.currency, precision)}</span>
    {compatible && signsAgree && (finite(change?.absolute) || finite(change?.percent)) ? <span className="quote-daily-change">{' '}
      {finite(change?.absolute) && <span className="quote-change financial-value" data-direction={financialDirection(change.absolute, precision)}>{formatChange(change.absolute, quote.currency, precision)}</span>}
      {finite(change?.percent) && <span className="quote-change financial-value" data-direction={financialDirection(change.percent)}>{finite(change?.absolute) ? ' (' : ''}{formatPercentChange(change.percent)}{finite(change?.absolute) ? ')' : ''}</span>}
      <span className="quote-period"> daily change</span>
    </span> : <span className="quote-change-unavailable"> Daily change unavailable</span>}
    <div className="quote-timestamp">{quote.stale ? 'Stale quote · ' : stamp !== null && Date.now() - stamp > 72 * 3600 * 1000 ? 'Earlier quote snapshot · ' : ''}{stamp !== null ? <>As of <time dateTime={quote.asOf!}>{formatTimestamp(quote.asOf)}</time></> : 'Timestamp unavailable'}</div>
  </div>;
}

/** No implicit research destinations: callers supply links that actually exist. */
export interface KnownSymbol { symbol: string; companyName?: string; exchange?: string; aliases?: readonly string[]; href?: string; }
export type KnownSymbols = readonly (string | KnownSymbol)[];
export interface TickerProps { symbol: string; companyName?: string; href?: string; dollarPrefix?: boolean; }
export function safeHref(value: string | null | undefined): string | undefined {
  if (!value || value !== value.trim() || /[\u0000-\u0020\u007f\\]/.test(value)) return undefined;
  if (value.startsWith('#') || (value.startsWith('/') && !value.startsWith('//'))) return value;
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? value : undefined; } catch { return undefined; }
}
export function Ticker({ symbol, companyName, href, dollarPrefix = true }: TickerProps) {
  const canonical = symbol.replace(/^\$+/, '');
  const label = `${dollarPrefix ? '$' : ''}${canonical}`;
  const safe = safeHref(href);
  return <span className="ticker-group">{safe ? <a className="ticker" href={safe}>{label}</a> : <span className="ticker">{label}</span>}{companyName && <span className="ticker-company"> {companyName}</span>}</span>;
}
export type TickerToken = { type: 'text'; text: string } | { type: 'ticker'; text: string; symbol: string; href?: string; companyName?: string };
const currencies = new Set(['USD', 'EUR', 'GBP', 'JPY', 'CNY', 'CNH', 'HKD', 'SGD', 'AUD', 'CAD', 'CHF', 'INR', 'KRW', 'TWD', 'NZD', 'SEK', 'NOK', 'DKK', 'BRL', 'ZAR', 'MXN', 'RUB']);
function symbolIndex(knownSymbols: KnownSymbols): Map<string, KnownSymbol> {
  const index = new Map<string, KnownSymbol>();
  for (const item of knownSymbols) {
    const info = typeof item === 'string' ? { symbol: item } : item;
    const symbol = info.symbol.replace(/^\$/, '');
    if (!/^[A-Z0-9][A-Z0-9.:-]{0,39}$/.test(symbol) || (currencies.has(symbol) && symbol !== 'NOK')) continue;
    const record = { ...info, symbol };
    for (const alias of [symbol, ...(info.aliases || []), ...(info.exchange ? [`${info.exchange}:${symbol}`] : [])]) index.set(alias, record);
  }
  return index;
}

interface MarkdownLink { end: number; label: string; destination: string; image: boolean; }
/** A bounded balanced scanner avoids truncating URLs at their first parenthesis. */
function markdownLink(text: string, start: number): MarkdownLink | null {
  const image = text.startsWith('![', start);
  const open = image ? start + 1 : start;
  if (text[open] !== '[') return null;
  let depth = 1, close = open + 1;
  for (; close < text.length && depth; close++) {
    if (text[close] === '\\') { close++; continue; }
    if (text[close] === '[') depth++;
    if (text[close] === ']') depth--;
  }
  if (depth || text[close] !== '(') return null;
  const label = text.slice(open + 1, close - 1);
  const urlStart = close + 1;
  depth = 1;
  for (close = urlStart; close < text.length && depth; close++) {
    if (text[close] === '\\') { close++; continue; }
    if (text[close] === '(') depth++;
    if (text[close] === ')') depth--;
  }
  return depth ? null : { end: close, label, destination: text.slice(urlStart, close - 1), image };
}
interface ProtectedPart { end: number; kind: 'code' | 'link' | 'literal'; body?: string; link?: MarkdownLink; }
function protectedAt(text: string, start: number): ProtectedPart | null {
  const rest = text.slice(start);
  if (rest[0] === '`' || rest.startsWith('~~~')) {
    const delimiter = /^(?:`+|~{3,})/.exec(rest)![0];
    const end = text.indexOf(delimiter, start + delimiter.length);
    if (end >= 0) return { end: end + delimiter.length, kind: 'code', body: text.slice(start + delimiter.length, end) };
    return { end: text.length, kind: 'literal' };
  }
  if (rest[0] === '[' || rest.startsWith('![')) {
    const link = markdownLink(text, start);
    if (link) return { end: link.end, kind: 'link', link };
    // Reference syntax is retained literally rather than guessed or relinked.
    const reference = /^!?\[[^\]\n]*\](?:\[[^\]\n]*\]|:[^\n]*)/.exec(rest);
    if (reference) return { end: start + reference[0].length, kind: 'literal' };
  }
  if (rest[0] === '<') {
    const html = /^(?:<a\b[^>]*>[\s\S]*?<\/a\s*>|<[^>]*>)/i.exec(rest);
    if (html) return { end: start + html[0].length, kind: 'literal' };
  }
  // URL/email matching only starts at a token boundary; long plain words must
  // not trigger a quadratic suffix scan at every character.
  if (start > 0 && /[A-Za-z0-9._%+@-]/.test(text[start - 1])) return null;
  const literal = /^(?:(?:[a-z][a-z0-9+.-]*:\/\/|www\.)[^\s<>]+|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})/i.exec(rest);
  return literal ? { end: start + literal[0].length, kind: 'literal' } : null;
}
function parsePlainTickers(text: string, index: Map<string, KnownSymbol>): TickerToken[] {
  const result: TickerToken[] = [];
  const pattern = /\$?(?:[A-Z][A-Z0-9_-]{0,14}:)?[A-Z0-9](?:[A-Z0-9.-]{0,23}[A-Z0-9])?/g;
  let cursor = 0;
  for (const match of text.matchAll(pattern)) {
    const start = match.index!;
    const end = start + match[0].length;
    const key = match[0].replace(/^\$/, '');
    const info = index.get(key);
    // AI is usually prose; only an explicitly marked $AI may match this bare symbol.
    if (match[0] === 'AI') continue;
    if (currencies.has(key) && (!match[0].startsWith('$') || /^\s*\d/.test(text.slice(end)))) continue;
    if (!info || /[\p{L}\p{N}_$@/.:\-]/u.test(text[start - 1] || '') || /[\p{L}\p{N}_$@/:\-]/u.test(text[end] || '') || /^\d+$/.test(key)) continue;
    if (start > cursor) result.push({ type: 'text', text: text.slice(cursor, start) });
    result.push({ type: 'ticker', text: match[0], symbol: info.symbol, href: info.href, companyName: info.companyName });
    cursor = end;
  }
  if (cursor < text.length) result.push({ type: 'text', text: text.slice(cursor) });
  return result;
}
export function parseTickerMentions(text: string, knownSymbols: KnownSymbols = []): TickerToken[] {
  const index = symbolIndex(knownSymbols);
  const result: TickerToken[] = [];
  let cursor = 0, start = 0;
  while (cursor < text.length) {
    const protectedPart = protectedAt(text, cursor);
    if (!protectedPart) { cursor++; continue; }
    result.push(...parsePlainTickers(text.slice(start, cursor), index), { type: 'text', text: text.slice(cursor, protectedPart.end) });
    cursor = protectedPart.end; start = cursor;
  }
  result.push(...parsePlainTickers(text.slice(start), index));
  return result;
}
function tickerNodes(text: string, known: KnownSymbols): ReactNode[] {
  return parseTickerMentions(text, known).map((token, key) => token.type === 'text' ? token.text : <Ticker key={key} symbol={token.symbol} href={token.href} dollarPrefix={token.text.startsWith('$')} />);
}
function inline(text: string, known: KnownSymbols, allowLinks = true, depth = 0): ReactNode[] {
  if (depth > 12) return [text];
  const nodes: ReactNode[] = [];
  let cursor = 0, start = 0;
  const flush = () => { if (cursor > start) nodes.push(...(allowLinks ? tickerNodes(text.slice(start, cursor), known) : [text.slice(start, cursor)])); };
  while (cursor < text.length) {
    if (text[cursor] === '\\' && /[\\`*_[\]{}()#+.!>|~-]/.test(text[cursor + 1] || '')) {
      flush(); nodes.push(text[cursor + 1]); cursor += 2; start = cursor; continue;
    }
    const protectedPart = protectedAt(text, cursor);
    if (protectedPart) {
      flush();
      if (protectedPart.kind === 'code') nodes.push(<code key={nodes.length}>{protectedPart.body}</code>);
      else if (protectedPart.kind === 'link' && protectedPart.link) {
        const link = protectedPart.link;
        const href = safeHref(link.destination);
        const label = inline(link.label, known, false, depth + 1);
        nodes.push(href && allowLinks && !link.image ? <a key={nodes.length} href={href} rel="noopener noreferrer">{label}</a> : <React.Fragment key={nodes.length}>{label}</React.Fragment>);
      } else { const literal=text.slice(cursor, protectedPart.end); const href=safeHref(literal); nodes.push(allowLinks && /^https?:\/\//.test(literal) && href ? <a key={nodes.length} href={href} rel="noopener noreferrer">{literal}</a> : literal); }
      cursor = protectedPart.end; start = cursor; continue;
    }
    const delimiter = text.startsWith('**', cursor) ? '**' : text.startsWith('__', cursor) ? '__' : (text[cursor] === '*' || text[cursor] === '_') ? text[cursor] : null;
    if (delimiter) {
      const end = text.indexOf(delimiter, cursor + delimiter.length);
      if (end > cursor + delimiter.length) {
        flush(); const body = inline(text.slice(cursor + delimiter.length, end), known, allowLinks, depth + 1);
        nodes.push(delimiter.length === 2 ? <strong key={nodes.length}>{body}</strong> : <em key={nodes.length}>{body}</em>);
        cursor = end + delimiter.length; start = cursor; continue;
      }
    }
    cursor++;
  }
  flush();
  return nodes;
}

/** Inline-only shared renderer for semantic headlines, without nested paragraphs. */
export function ResearchHeadline({content,knownSymbols=[]}:{content:string;knownSymbols?:KnownSymbols}) {return <>{inline(content,knownSymbols)}</>}

/** Preserve leading evidence markers without assigning a market direction. */
export function ResearchItem({marker,children}:{marker:string;children:ReactNode}) {
 return <span className="research-item"><span className="research-marker" role="img" aria-label={({'📌':'Important evidence','⚠️':'Caution','🟢':'Green marker','🟡':'Yellow marker','🔴':'Red marker','⚪':'Neutral marker','🧠':'Analysis','🎯':'Focus','📡':'Monitoring','📅':'Date'} as Record<string,string>)[marker] || 'Research marker'}>{marker}</span><span>{children}</span></span>
}
export interface NarrativeProps { content?: string | null; knownSymbols?: KnownSymbols; }
// Inline emphasis can wrap a source-authored marker without changing its meaning.
export function hasAuthoredListMarker(text: string) {
  return /^(?:\*\*|__|\*|_)*(?:[\u{1F300}-\u{1FAFF}\u2600-\u27BF]|[•●▪◦])/u.test(text.trim());
}
const tableCells = (line: string) => line.trim().replace(/^\|/, '').replace(/\|$/, '').split(/(?<!\\)\|/).map(cell => cell.trim().replace(/\\\|/g, '|'));
const tableSeparator = (line: string) => line.includes('|') && tableCells(line).every(cell => /^:?-{3,}:?$/.test(cell));
/** Deliberately limited Markdown, built as React nodes. Raw HTML is always text. */
export function Narrative({ content, knownSymbols = [] }: NarrativeProps) {
  if (!content) return null;
  const lines = content.replace(/\r\n?/g, '\n').split('\n');
  const blocks: ReactNode[] = [];
  let i = 0;
  const render = (text: string) => inline(text, knownSymbols);
  const finding = (text: string) => {const marker=/^(🟢|🟡|🔴|📌|⚪|⚠️?|🧠|🎯|📡|📅)\s+(.+)$/s.exec(text);return marker ? <ResearchItem marker={marker[1]}>{render(marker[2])}</ResearchItem> : render(text)};
  const blockStart = (line: string) => /^(?:\s*$| {0,3}#{1,6}\s| {0,3}(?:`{3,}|~{3,})| {0,3}>|\s*[-+*]\s|\s*\d+[.)]\s)/.test(line);
  while (i < lines.length) {
    const line = lines[i];
    const key = i;
    if (!line.trim()) { i++; continue; }
    const fence = /^ {0,3}(`{3,}|~{3,})[^`]*$/.exec(line);
    if (fence) {
      const body: string[] = []; i++;
      const end = new RegExp(`^ {0,3}${fence[1][0]}{${fence[1].length},}\\s*$`);
      while (i < lines.length && !end.test(lines[i])) body.push(lines[i++]);
      if (i < lines.length) i++;
      blocks.push(<pre key={key}><code>{body.join('\n')}</code></pre>); continue;
    }
    const heading = /^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$/.exec(line);
    if (heading) { const Tag = `h${heading[1].length}` as 'h1'; blocks.push(<Tag key={key}>{render(heading[2])}</Tag>); i++; continue; }
    if (i + 1 < lines.length && line.includes('|') && tableSeparator(lines[i + 1])) {
      const headers = tableCells(line), alignments = tableCells(lines[i + 1]); i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) rows.push(tableCells(lines[i++]));
      const alignment = (column: number) => /^:.*:$/.test(alignments[column] || '') ? 'center' : /:$/.test(alignments[column] || '') ? 'right' : 'left';
      blocks.push(<div className="narrative-table-scroll" key={key}><table><thead><tr>{headers.map((cell, col) => <th key={col} scope="col" style={{ textAlign: alignment(col) }}>{render(cell)}</th>)}</tr></thead><tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>{headers.map((_, col) => <td key={col} style={{ textAlign: alignment(col) }}>{render(row[col] || '')}</td>)}</tr>)}</tbody></table></div>); continue;
    }
    if (/^ {0,3}>/.test(line)) {
      const body: string[] = [];
      while (i < lines.length && /^ {0,3}>/.test(lines[i])) body.push(lines[i++].replace(/^ {0,3}> ?/, ''));
      blocks.push(<blockquote key={key}><Narrative content={body.join('\n')} knownSymbols={knownSymbols} /></blockquote>); continue;
    }
    const list = /^\s*([-+*]|\d+[.)])\s+(.+)$/.exec(line);
    if (list) {
      const ordered = /^\d/.test(list[1]);
      const items: ReactNode[] = [];
      while (i < lines.length) {
        const item = /^\s*([-+*]|\d+[.)])\s+(.+)$/.exec(lines[i]);
        if (!item || /^\d/.test(item[1]) !== ordered) break;
        i++; const body = [item[2]];
        while (i < lines.length && /^ {2,}\S/.test(lines[i]) && !/^\s*([-+*]|\d+[.)])\s/.test(lines[i])) body.push(lines[i++].trim());
        items.push(<li className={!ordered && hasAuthoredListMarker(body[0]) ? 'authored-list-marker' : undefined} key={items.length}>{finding(body.join('\n'))}</li>);
      }
      blocks.push(ordered ? <ol key={key} start={parseInt(list[1], 10)}>{items}</ol> : <ul key={key}>{items}</ul>); continue;
    }
    if (/^ {0,3}(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)) { blocks.push(<hr key={key} />); i++; continue; }
    const paragraph = [line]; i++;
    while (i < lines.length && !blockStart(lines[i]) && !(i + 1 < lines.length && tableSeparator(lines[i + 1]))) paragraph.push(lines[i++]);
    blocks.push(<p key={key}>{finding(paragraph.join('\n'))}</p>);
  }
  return <div className="research-narrative">{blocks}</div>;
}
export const MarkdownNarrative = Narrative;

// Optional while the shared publication contract is being introduced. No local
// code-to-label fallback: the producer and renderer must use the same vocabulary.
const labelModules = import.meta.glob('../schema/public-labels.json', { eager: true, import: 'default' });
export interface PublicLabel { label: string; explanation?: string; }
function publicLabel(value: string | null | undefined): PublicLabel | undefined {
  if (!value) return undefined;
  const document = Object.values(labelModules)[0] as Record<string, unknown> | undefined;
  const labels = (document?.labels ?? document) as Record<string, unknown> | undefined;
  if (!labels) return undefined;
  const entry = Object.prototype.hasOwnProperty.call(labels, value) ? labels[value] : Object.values(labels).find(candidate =>
    candidate && typeof candidate === 'object' && 'label' in candidate && candidate.label === value);
  if (typeof entry === 'string') return { label: entry };
  if (entry && typeof entry === 'object' && 'label' in entry && typeof entry.label === 'string') return { label: entry.label, explanation: 'explanation' in entry && typeof entry.explanation === 'string' ? entry.explanation : undefined };
  return undefined;
}
export interface StatusProps { value?: string | null; marker?: string | null; markerLabel?: string; }
export function Status({ value, marker, markerLabel }: StatusProps) {
  const approved = publicLabel(value);
  return <span className="research-status">{marker && <span className="research-marker" {...(markerLabel ? { role: 'img', 'aria-label': markerLabel } : { 'aria-hidden': true as const })}>{marker}</span>}<span>{approved?.label || 'Assessment unavailable'}{approved?.explanation && <span className="status-explanation"> — {approved.explanation}</span>}</span></span>;
}
export interface ResearchSource { label: string; url: string; }
export function SourceLink({ label, url }: ResearchSource) {
  const href = safeHref(url);
  return href ? <a className="research-source" href={href} rel="noopener noreferrer">{label}</a> : <span className="research-source-unavailable">{label} (link unavailable)</span>;
}
export interface ThesisUpdateProps {
  previousView?: string | null;
  newEvidence?: string | null;
  currentView?: string | null;
  date?: string | null;
  sources?: readonly ResearchSource[];
  knownSymbols?: KnownSymbols;
}
export function ThesisUpdate({ previousView, newEvidence, currentView, date, sources = [], knownSymbols = [] }: ThesisUpdateProps) {
  if (!previousView && !newEvidence && !currentView) return null;
  return <section className="thesis-update" aria-label="Thesis update">
    {date && <div className="thesis-update-date">{instant(date) !== null ? <time dateTime={date}>{formatTimestamp(date)}</time> : /^\d{4}-\d{2}-\d{2}$/.test(date) ? <time dateTime={date}>{date}</time> : 'Date unavailable'}</div>}
    {([[previousView, 'Previous view'], [newEvidence, 'New evidence'], [currentView, 'Current view']] as const).map(([content, title]) => content ? <div key={title}><h3>{title}</h3><Narrative content={content} knownSymbols={knownSymbols} /></div> : null)}
    {sources.length > 0 && <div className="thesis-sources"><h3>Sources</h3><ul>{sources.map((source, key) => <li key={key}><SourceLink {...source} /></li>)}</ul></div>}
  </section>;
}
