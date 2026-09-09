import css from './styles.css?raw'
import {describe, expect, it} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import {DailyBriefTimeline, type DashboardData} from './App'
import {Narrative} from './researchComponents'

const draw = (highlights: string[], articleBody = '', summary = '') => renderToStaticMarkup(
  <DailyBriefTimeline data={{tickers: [], cronTimeline: [{
    id: 'synthetic-markers', category: 'Research', runTime: '2026-09-09',
    jobName: 'Research', summary, highlights, articleBody,
  }]} as unknown as DashboardData}/>,
)
const count = (html: string, text: string) => html.split(text).length - 1

describe('Daily Brief authored list markers', () => {
  it.each(['🟡 Evidence pending', '📌 **Evidence:** synthetic finding', '**⚠️ Caution** remains', '• Evidence marker'])('keeps the authored marker once: %s', highlight => {
    const html = draw([highlight])
    expect(html).toContain('<li class="authored-list-marker"><div class="research-narrative"><p>')
    const marker = highlight.match(/🟡|📌|⚠️|•/)![0]
    expect(count(html, marker)).toBe(1)
    if (marker === '📌') expect(html).toContain('role="img" aria-label="Important evidence"')
  })

  it('preserves ordinary highlights, Markdown bullets, and ordered markers', () => {
    const html = draw(['Ordinary highlight', '- Ordinary bullet\n- Another bullet', '3. 🟡 Ranked evidence\n4. Next step'])
    expect(html).toContain('<li><div class="research-narrative"><p>Ordinary highlight</p>')
    expect(html).toContain('<ul><li>Ordinary bullet</li><li>Another bullet</li></ul>')
    expect(html).toContain('<ol start="3"><li><span class="research-item">')
    expect(html).not.toContain('class="authored-list-marker"')
  })

  it('targets the wrapper around a nested Markdown list without hiding its ordinary items', () => {
    const html = draw(['- 🟡 Parent evidence\n  - Ordinary child\n  - 📌 Child evidence\n- Ordinary sibling'])
    expect(html).toContain('<ul><li><div class="research-narrative"><ul><li class="authored-list-marker">')
    expect(html).toContain('<li>Ordinary child</li>')
    expect(html).toContain('<li>Ordinary sibling</li>')
    expect(count(html, 'class="authored-list-marker"')).toBe(2)
    expect(count(html, '🟡')).toBe(1)
    expect(count(html, '📌')).toBe(1)
  })

  it('handles summary lists and full article bullets, including numbered action details', () => {
    const html = draw([], '## Evidence\n\n- 🟡 Article evidence\n- Ordinary article bullet\n\n1. First action\n  - 📌 Action evidence\n  - Ordinary action detail', '- 📌 Summary evidence\n- Ordinary summary bullet')
    expect(html).toContain('<details class="source-details"><summary>Read full article</summary>')
    expect(html).toContain('<ul class="md-list"><li class="authored-list-marker">🟡 Article evidence</li><li>Ordinary article bullet</li></ul>')
    expect(html).toContain('<span class="md-action-number">1</span>')
    expect(html).toContain('<ul class="md-action-details"><li class="authored-list-marker">📌 Action evidence</li><li>Ordinary action detail</li></ul>')
    expect(html).toContain('<li>Ordinary summary bullet</li>')
    expect(count(html, 'class="authored-list-marker"')).toBe(3)
  })

  it('scopes marker suppression to direct unordered items in Daily Brief cards', () => {
    const rule = css.match(/\.daily-brief-page \.timeline-card ul > li\.authored-list-marker::marker,[\s\S]*?\}/)![0]
    expect(rule).toBe(".daily-brief-page .timeline-card ul > li.authored-list-marker::marker,\n.daily-brief-page .timeline-card ul > li:has(> .research-narrative > :is(ul, ol):first-child)::marker { content: ''; }")
    // Shared Narrative output keeps semantic lists and has no inline suppression.
    const html = renderToStaticMarkup(<Narrative content={'- 📌 Evidence\n- Ordinary bullet\n\n1. Ordered item'}/>)
    expect(html).toContain('<ul>')
    expect(html).toContain('<ol start="1"><li>Ordered item</li></ol>')
    expect(html).not.toContain('style=')
    expect(html).not.toContain('aria-hidden')
  })
})
