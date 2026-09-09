import {describe, expect, it} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import {DailyBriefTimeline, type DashboardData} from './App'

describe('Daily Brief left date label', () => {
  it.each([
    ['2026-09-09T14:30:00Z', '2026-09-09', '2026-09-09 10:30 AM EDT'],
    ['2026-09-09T00:30:00Z', '2026-09-08', '2026-09-08 8:30 PM EDT'],
    ['2026-01-09T00:30:00Z', '2026-01-08', '2026-01-08 7:30 PM EST'],
    ['2026-09-09T02:30:00+02:00', '2026-09-08', '2026-09-08 8:30 PM EDT'],
    ['2026-09-09 02:10:38', '2026-09-08', '2026-09-08 10:10 PM EDT'],
    ['2026-03-08T06:59:00Z', '2026-03-08', '2026-03-08 1:59 AM EST'],
    ['2026-03-08T07:00:00Z', '2026-03-08', '2026-03-08 3:00 AM EDT'],
    ['2026-11-01T05:30:00Z', '2026-11-01', '2026-11-01 1:30 AM EDT'],
    ['2026-11-01T06:30:00Z', '2026-11-01', '2026-11-01 1:30 AM EST'],
    ['2026-09-09', '2026-09-09', '2026-09-09'],
  ])('renders a prominent date above a separate smaller timestamp for %s', (runTime, day, timestamp) => {
    const data = {tickers: [], cronTimeline: [{
      id: 'synthetic-date', category: 'Research', runTime, summary: '', highlights: [],
    }]} as unknown as DashboardData;
    const html = renderToStaticMarkup(<DailyBriefTimeline data={data}/>);
    const instant = runTime === '2026-09-09 02:10:38' ? '2026-09-09T02:10:38Z' : runTime;

    // Direct siblings reuse the existing aside grid and prominent strong style.
    expect(html).toContain(`<aside><strong>${day}</strong><time dateTime="${instant}">${timestamp}</time></aside>`);
    expect(html).toContain(`data-publication-day="${day}"`);
  });
});
