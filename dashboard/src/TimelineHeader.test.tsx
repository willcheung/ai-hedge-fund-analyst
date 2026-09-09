import {describe, expect, it} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import {DailyBriefTimeline, type DashboardData} from './App'
import {timelineCategory} from './briefPresentation'

// Synthetic expectations contain only synthetic producer IDs and display labels.
const expectedJobCategories = [
  ['synthetic-macro', 'Macro Read'],
  ['synthetic-job-08', 'Weekly Stock Analysis'],
  ['synthetic-job-0c', 'Weekly Stock Analysis'],
] as const;

describe('Daily Brief category header', () => {
  it.each(expectedJobCategories)('uses verified producer %s over stale categories', (id, expected) => {
    expect(timelineCategory(id, 'Other research job')).toBe(expected);
    expect(timelineCategory(` ${id} `, 'Stale category')).toBe(expected);
  });

  it.each(expectedJobCategories)('renders producer %s in one category bar without a duplicate h3', (jobId, expected) => {
    const data = {tickers: [], cronTimeline: [{
      id: 'synthetic-card', jobId, category: 'Other research job', jobName: 'Research update',
      runTime: '2026-09-09T00:30:00Z', summary: null, highlights: [],
      articleBody: 'Synthetic article content.',
    }]} as unknown as DashboardData;
    const html = renderToStaticMarkup(<DailyBriefTimeline data={data}/>);
    const header = renderToStaticMarkup(<span className="eyebrow timeline-category">{expected}</span>);
    expect([...html.matchAll(/<header class="timeline-head">(.*?)<\/header>/g)].map(match => match[1])).toEqual([header]);
    expect(html).not.toContain('<h3');
    expect(html).toContain('Synthetic article content.');
  });

  it('accepts explicit audited mappings without guessing from names', () => {
    expect(timelineCategory('verified', 'Research update', {verified: 'Earnings / catalysts'})).toBe('Earnings / catalysts');
    expect(timelineCategory('earnings-macro-weekly', null)).toBe('Uncategorized research');
  });

  it.each([undefined, null, false, 123, '', '  ', 'Research update', 'Other research job', 'Unknown'])('handles unknown category %s honestly', category => {
    expect(timelineCategory(null, category)).toBe('Uncategorized research');
  });

  it.each(['__proto__', 'prototype', 'constructor', 'toString', 'valueOf', 'hasOwnProperty', 'isPrototypeOf', 'propertyIsEnumerable', 'toLocaleString', '__defineGetter__', '__defineSetter__', '__lookupGetter__', '__lookupSetter__'])('does not resolve inherited object key %s', id => {
    expect(timelineCategory(id, null)).toBe('Uncategorized research');
    expect(timelineCategory(id, 'Supplied category')).toBe('Supplied category');
  });

  it('preserves distinct categories with one header per card and no job title h3', () => {
    const categories = ['Macro Read', 'Weekly Stock Analysis', 'Earnings / catalysts', 'Sentiment / source radar', 'Portfolio / stock decisions', 'Market brief / friday take'];
    const rows = [...categories, null].map((category, index) => ({
      id: String(index), jobId: null, category, jobName: 'Research update',
      runTime: '2026-09-09T00:30:00Z', summary: null, highlights: [],
      articleBody: '# Authored article heading\n\nEarnings, macro and weekly claims do not classify this card.',
    }));
    const data = {tickers: [], cronTimeline: rows} as unknown as DashboardData;
    const before = JSON.stringify(data);
    const html = renderToStaticMarkup(<DailyBriefTimeline data={data}/>);
    const headers = [...html.matchAll(/<header class="timeline-head">(.*?)<\/header>/g)].map(match => match[1]);
    expect(headers).toEqual([...categories, 'Uncategorized research'].map(label => `<span class="eyebrow timeline-category">${label}</span>`));
    expect(html).not.toContain('Research update');
    expect(html.match(/<h3/g)).toHaveLength(rows.length); // Only authored article headings.
    expect(html).toContain('Authored article heading');
    expect(html).toContain('2026-09-08 8:30 PM EDT');
    expect(JSON.stringify(data)).toBe(before);
  });
});
