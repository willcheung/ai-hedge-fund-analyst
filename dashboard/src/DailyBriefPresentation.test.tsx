// SYNTHETIC regression inputs only; no live snapshot dependencies.
import {afterEach, describe, expect, it, vi} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import {DailyBriefTimeline, type DashboardData} from './App'
import MarketsApp, {PublicationArticle} from './MarketsApp'
import {ThemeProvider} from './theme'
import {formatTimestamp, publicationDay} from './researchComponents'
import {cleanObservedPrefixes, macroProse, timelineInstant, timelineTimestamp, uniqueMacroHighlights} from './briefPresentation'
import bundled from '../tests/fixtures/demo-dashboard.json'
import type {Publication} from './publicationTypes'

const macroBody = '## Original commentary\n\nObserved: Observed: Demand was observed to improve, but confirmation is unavailable.\n\nInference: Gains may reverse.\n\nObserved uncertainty remains.\n\nFinal caveat.';
const fixture = {...bundled, cronTimeline: [
  {id: 'macro', jobId: 'synthetic-macro', category: 'Macro Read', jobName: 'Macro Read', runTime: '2026-09-09T00:30:00Z', summary: 'Commentary, not independent confirmation.', highlights: [], articleBody: macroBody},
  {id: 'research', category: 'Other research job', jobName: 'Research update', runTime: '2026-09-08', summary: 'Original research summary.', highlights: Array.from({length: 6}, (_, i) => `Evidence ${i + 1}`), articleBody: '# Original research title\n\nComplete article ending.'},
]};
vi.mock('./useMarketData', () => ({useMarketData: () => ({data: fixture, error: null}), isStagedPreviewBuild: true}));
afterEach(() => vi.unstubAllGlobals());

describe('Eastern publication dates', () => {
  it.each([
    ['2026-09-09T00:30:00Z', '2026-09-08 20:30:00 EDT'],
    ['2026-01-09T00:30:00Z', '2026-01-08 19:30:00 EST'],
    ['2026-03-08T06:59:00Z', '2026-03-08 01:59:00 EST'],
    ['2026-03-08T07:00:00Z', '2026-03-08 03:00:00 EDT'],
    ['2026-11-01T05:30:00Z', '2026-11-01 01:30:00 EDT'],
    ['2026-11-01T06:30:00Z', '2026-11-01 01:30:00 EST'],
    ['2026-09-09T02:30:00+02:00', '2026-09-08 20:30:00 EDT'],
    ['2026-09-09', '2026-09-09'],
  ])('formats %s without changing source precision', (input, expected) => {
    expect(formatTimestamp(input)).toBe(expected);
    expect(publicationDay(input)).toBe(expected.slice(0, 10));
  });
});

describe('actual MarketsApp Daily Brief route and publication adapter', () => {
  it('groups by Eastern day, drops generic headings, and preserves complete research', () => {
    vi.stubGlobal('window', {location: {hash: '#brief'}});
    const before = JSON.stringify(fixture);
    const html = renderToStaticMarkup(<ThemeProvider><MarketsApp/></ThemeProvider>);
    expect(html.match(/data-publication-day="2026-09-08"/g)).toHaveLength(2);
    expect(html).toMatch(/datetime="2026-09-09T00:30:00Z"/i);
    expect(html).toContain('2026-09-08 8:30 PM EDT');
    expect(html).toContain('class="timeline-head"');
    expect(html).not.toContain('Research update');
    expect(html.match(/>Macro Read</g)).toHaveLength(1);
    expect(html).not.toContain('Read full Market Brief');
    expect(html).toContain('Read full article');
    for (const text of ['Original commentary', 'Demand was observed to improve', 'confirmation is unavailable', 'Inference: Gains may reverse.', 'Observed uncertainty remains.', 'Final caveat.', 'Original research title', 'Evidence 6', 'Complete article ending.']) expect(html).toContain(text);
    expect(html).not.toContain('Observed: Observed:');
    expect(JSON.stringify(fixture)).toBe(before);
  });
  it('applies the same dates and safe macro cleanup to publication articles', () => {
    const item: Publication = {schemaVersion: 1, id: 'macro', jobId: 'synthetic-macro', type: 'brief', title: 'Macro Read', summary: 'Opinions remain uncertain.', publishedAt: '2026-09-09T00:30:00Z', informationAt: null, informationDate: '2026-09-09', tickers: [], sections: [{heading: 'Research', markdown: macroBody}], sources: []};
    const html = renderToStaticMarkup(<PublicationArticle item={item} symbols={[]}/>);
    expect(html).toContain('Published 2026-09-08 20:30:00 EDT');
    expect(html).toContain('Information updated 2026-09-09');
    expect(html).not.toContain('Macro Read');
    expect(html).not.toContain('Observed: Observed:');
    expect(html).toContain('Inference: Gains may reverse.');
    expect(item.sections[0].markdown).toBe(macroBody);
    const lead = renderToStaticMarkup(<PublicationArticle item={item} symbols={[]} lead/>);
    expect(lead).toContain('Read full article');
    expect(lead).toContain('href="#briefs/macro"');
    const titled = renderToStaticMarkup(<PublicationArticle item={{...item, title: 'Original research title', summary: 'Original research title'}} symbols={[]}/>);
    expect(titled.match(/Original research title/g)).toHaveLength(1);
  });
});

describe('bounded evidence prefix cleaning', () => {
  it('removes leading labels while retaining substantive language', () => {
    expect(cleanObservedPrefixes('- Observed: Observed: Observed: Demand improved.')).toBe('- Demand improved.');
    expect(cleanObservedPrefixes('Observed: Inference: demand may improve.')).toBe('Inference: demand may improve.');
    expect(cleanObservedPrefixes('**Observed:** demand improved.')).toBe('demand improved.');
    for (const text of ['Observed demand improved.', 'We observed: Observed: uncertainty.', 'Inference: Observed: demand may improve.', '```\nObserved: Observed: literal\n```']) expect(cleanObservedPrefixes(text)).toBe(text);
  });
});


describe('audited legacy timeline shapes with synthetic research', () => {
  const evidence = 'Synthetic freight volumes rose. ' + 'Confirmation remains unavailable; this is a preliminary reading. '.repeat(6);
  const body = `# Macro Read — 2026-09-09\n\n## Transport commentary\n\n1. **Observed — ${evidence}**\n\n2. **Observed – Inventory fell.** Inference: restocking may slow.\n\n3. **Observed: Financing tightened.** Uncertainty remains.`;
  it('assigns only the exact legacy cron format to UTC, including DST', () => {
    expect(timelineInstant('2026-09-09 02:10:38')).toBe('2026-09-09T02:10:38Z');
    expect(timelineTimestamp('2026-09-09 02:10:38')).toBe('2026-09-08 10:10 PM EDT');
    expect(timelineTimestamp('2026-01-09 02:10:38')).toBe('2026-01-08 9:10 PM EST');
    expect(timelineTimestamp('2026-03-08 07:00:00')).toBe('2026-03-08 3:00 AM EDT');
    expect(timelineInstant('2026-09-09T02:10:38')).toBe('2026-09-09T02:10:38');
    expect(timelineInstant('2026-02-30 02:10:38')).toBe('2026-02-30 02:10:38');
    expect(formatTimestamp('2026-09-09 02:10:38')).toBe('2026-09-09 02:10:38');
  });
  it('cleans numbered bold and emoji labels without deleting qualifications', () => {
    expect(cleanObservedPrefixes('1. **Observed — Synthetic demand rose.**')).toBe('1. **Synthetic demand rose.**');
    expect(cleanObservedPrefixes('⚪ Observed – Inference: orders may recover.')).toBe('⚪ Inference: orders may recover.');
    expect(macroProse(body)).not.toContain('Macro Read');
    expect(macroProse('# Substantive research — 2026-09-09')).toContain('Substantive research');
  });
  it('omits only verified duplicates and truncated prefixes, retaining unique older highlights', () => {
    const prefix = `⚪ Observed — ${evidence}`.slice(0, 280);
    expect(uniqueMacroHighlights([prefix, '⚪ Observed – Inventory fell. Inference: restocking may slow.', 'Older survey evidence remains unique.', 'Inventory fell. Inference: restocking will accelerate.'], macroProse(body))).toEqual(['Older survey evidence remains unique.', 'Inventory fell. Inference: restocking will accelerate.']);
  });
  it('preserves missing company identity as prose and suppresses redundant job names', () => {
    const data = {tickers: [{symbol: 'SYN', title: 'Synthetic Company'}], cronTimeline: [
      {id: 'identity', jobName: '$SYN — Synthetic Company research', category: 'Research', runTime: '2026-09-08', summary: 'Demand improved.', highlights: []},
      {id: 'redundant', jobName: '$SYN — Duplicate scheduler headline', category: 'Research', runTime: '2026-09-07', summary: '$SYN Synthetic Company demand improved.', highlights: []},
    ]} as unknown as DashboardData;
    const html = renderToStaticMarkup(<DailyBriefTimeline data={data}/>);
    expect(html).toContain('Synthetic Company research');
    expect(html).toContain('href="#research/SYN"');
    expect(html).not.toContain('Duplicate scheduler headline');
    expect(html).not.toContain('<h3');
  });
  it('renders legacy cards once with safe markdown and no scheduler heading or empty paragraphs', () => {
    const rows = [
      {id: 'latest', jobName: 'Scheduled macro commentary job', category: 'Macro Read', runTime: '2026-09-09 02:10:38', summary: '', highlights: [`⚪ Observed — ${evidence}`.slice(0, 280)], articleBody: body},
      {id: 'older', jobName: 'Scheduled earnings scan', category: 'Earnings', runTime: '2026-09-09T02:00:00Z', summary: '', highlights: ['⚪ Observed — Older evidence remains unique.', '⚪ **[Synthetic report](https://example.com/research) — Preliminary…', '[Unsafe](javascript:alert(1))', '<script>example</script>'], articleBody: 'Synthetic research only.'},
    ];
    const data = {tickers: [], cronTimeline: rows} as unknown as DashboardData;
    const before = JSON.stringify(data);
    const html = renderToStaticMarkup(<DailyBriefTimeline data={data}/>);
    expect(html).toContain('2026-09-08 10:10 PM EDT');
    expect(html.indexOf('10:10 PM')).toBeLessThan(html.indexOf('10:00 PM'));
    expect(html.match(/Synthetic freight volumes rose/g)).toHaveLength(1);
    for (const removed of ['Scheduled macro', 'Scheduled earnings', 'Observed', '<p></p>', 'href="javascript:', '<script>']) expect(html).not.toContain(removed);
    expect(html).toContain('href="https://example.com/research"');
    expect(html).toContain('Inference: restocking may slow.');
    expect(html).toContain('Uncertainty remains.');
    expect(html).toContain('Older evidence remains unique.');
    expect(html.match(/datetime="2026-09-09T02:10:38Z"/gi)).toHaveLength(1);
    expect(JSON.stringify(data)).toBe(before);
  });
});

describe('Daily Brief optional prose and source identity regressions', () => {
  const metrics = 'Revenue $1.2B; net income $240M; diluted EPS $2.40; margin 20%.';
  const evidence = 'Free cash flow $180M; guidance remains uncertain.';
  const renderRow = (fields: Record<string, unknown>, category = 'Earnings') => {
    const data = {tickers: [], cronTimeline: [{
      id: 'synthetic', runTime: '2026-09-09T00:30:00Z', category,
      highlights: [evidence], articleBody: metrics, ...fields,
    }]} as unknown as DashboardData;
    const before = JSON.stringify(data);
    const html = renderToStaticMarkup(<DailyBriefTimeline data={data}/>);
    expect(JSON.stringify(data)).toBe(before);
    expect(html).toContain(metrics);
    expect(html).toContain(evidence);
    expect(html).toContain('class="timeline-head"');
    expect(html).not.toContain('<h3');
    expect(html).not.toContain('href="#research/');
    for (const text of ['<p></p>', '>undefined<', '>null<', '>false<']) expect(html).not.toContain(text);
    return html;
  };

  describe.each(['Earnings', 'Macro Read'])('%s', category => {
    it.each<[string, Record<string, unknown>]>([
      ['omitted fields', {}],
      ['null summary', {summary: null, jobName: 'Research update'}],
      ['null job name', {summary: 'Revenue grew 12%.', jobName: null}],
      ['both null', {summary: null, jobName: null}],
      ['non-text scalar fields', {summary: false, jobName: 123}],
    ])('renders the actual timeline with %s and retains financial evidence', (_, fields) => {
      const html = renderRow(fields, category);
      if (typeof fields.summary === 'string') expect(html).toContain(fields.summary);
      expect(html).not.toContain('Research update');
    });
  });

  it.each(['SYN — Synthetic Company earnings', 'Synthetic Company earnings'])('retains unmapped issuer context from %s as prose', jobName => {
    const html = renderRow({jobName});
    expect(html).toContain(`<p>${jobName}</p>`);
    expect(html.match(/Synthetic Company earnings/g)).toHaveLength(1);
  });

  it('omits a source title already present in the body', () => {
    const jobName = 'SYN — Synthetic Company earnings';
    const html = renderRow({jobName, articleBody: `${jobName}\n\n${metrics}`});
    expect(html.match(/Synthetic Company earnings/g)).toHaveLength(1);
  });

  it.each(['Research update', 'Other research job', 'Macro Read', 'Earnings', 'Scheduled earnings scan', 'Weekly stock analysis', 'Cron research run', 'Daily market brief', 'Original job', 'Market setup'])('drops generic scheduler title %s', jobName => {
    const html = renderRow({jobName});
    expect(html).not.toContain(`<p>${jobName}</p>`);
    expect(html).not.toContain('<h3');
  });

  it.each(['Synthetic Company '.repeat(20), 'SYN — Synthetic Company earnings\nExtra scheduler payload'])('bounds fallback source prose', jobName => {
    expect(renderRow({jobName})).not.toContain('Synthetic Company');
  });
});
