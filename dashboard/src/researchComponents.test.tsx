// SYNTHETIC regression inputs only; no research snapshot dependencies.
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { formatPrice, formatPercent, formatChange, parseTickerMentions, Quote, Ticker, Narrative, ResearchHeadline, Status, ThesisUpdate, type KnownSymbols } from './researchComponents';

const known: KnownSymbols = [{ symbol: 'SYNTHA', href: '#research/SYNTHA' }, { symbol: '0000.HK', exchange: 'HKEX' }, { symbol: 'SYNTHI', exchange: 'AMS' }];
const aiKnown: KnownSymbols = [{ symbol: 'AI', href: '#research/AI' }, { symbol: 'SYNTHB', href: '#research/SYNTHB' }];
const html = (node: React.ReactNode) => renderToStaticMarkup(<>{node}</>);

describe('financial formatting', () => {
  it('handles finite, absent and signed zero values without inventing data', () => {
    expect(formatPrice(null)).toBe('—');
    expect(formatPrice(Infinity)).toBe('—');
    expect(formatPrice(NaN)).toBe('—');
    expect(formatPrice(-0)).toBe('$0.00');
    expect(formatPrice(1234.5)).toBe('$1,234.50');
    expect(formatChange(2.34)).toBe('+$2.34');
    expect(formatChange(-2.34)).toBe('−$2.34');
    expect(formatChange(-0.001)).toBe('$0.00');
    expect(formatPercent(1.93)).toBe('1.93%');
    expect(formatPercent(-0)).toBe('0.00%');
  });
  it('accepts the publication quote DTO only with explicit trust and compatible period clocks', () => {
    const quote = { symbol: 'SYNTHA', price: 100, currency: 'USD', asOf: '2026-01-05T16:00:00Z', change: 2, changePct: 2.04, period: 'day', previousAsOf: '2026-01-02T16:00:00Z' };
    expect(html(<Quote quote={quote} />)).not.toContain('+$2.00');
    expect(html(<Quote quote={quote} trusted />)).toContain('+$2.00');
    expect(html(<Quote quote={{ ...quote, previousAsOf: '2025-12-02T16:00:00Z' }} trusted />)).not.toContain('+$2.00');
  });
  it('keeps prices neutral and only shows explicitly trusted compatible changes', () => {
    const quote = { price: 123.45, asOf: '2026-01-02T16:00:00Z', currency: 'USD', stale: true, change: { absolute: 2.34, percent: 1.93, trusted: true, period: 'day' as const, asOf: '2026-01-02T16:00:00Z' } };
    const output = html(<Quote quote={quote} />);
    expect(output).toContain('quote-price financial-value');
    expect(output).toContain('data-direction="positive"');
    expect(output).toContain('+$2.34');
    expect(output).toContain('Stale quote');
    expect(output).toContain('EST');
    expect(html(<Quote quote={{ ...quote, change: { ...quote.change, asOf: '2026-01-01T16:00:00Z' } }} />)).not.toContain('+$2.34');
    expect(html(<Quote quote={{ ...quote, change: { ...quote.change, trusted: false } }} />)).not.toContain('+$2.34');
    expect(html(<Quote quote={{ ...quote, change: { ...quote.change, period: 'week' } }} />)).not.toContain('+$2.34');
    expect(html(<Quote quote={null} />)).toContain('Quote unavailable');
  });
});

describe('known symbol parsing', () => {
  it('preserves AI prose exactly while recognizing explicit $AI and ordinary SYNTHB', () => {
    const text = 'AI infrastructure, generative AI, AI-led growth; $AI and SYNTHB.';
    const tokens = parseTickerMentions(text, aiKnown);
    expect(tokens.filter(t => t.type === 'ticker').map(t => [t.text, t.symbol])).toEqual([['$AI', 'AI'], ['SYNTHB', 'SYNTHB']]);
    expect(tokens.map(t => t.text).join('')).toBe(text);
  });
  it('still requires explicit $AI to be known and outside protected text and token substrings', () => {
    expect(parseTickerMentions('$AI', []).filter(t => t.type === 'ticker')).toHaveLength(0);
    const text = '`$AI` [$AI](https://example.com/AI) https://example.com/$AI X$AI $AIx';
    const tokens = parseTickerMentions(text, aiKnown);
    expect(tokens.filter(t => t.type === 'ticker')).toHaveLength(0);
    expect(tokens.map(t => t.text).join('')).toBe(text);
  });
  it('accepts canonical international symbols and exchange forms, not money or substrings', () => {
    const tokens = parseTickerMentions('$SYNTHA SYNTHA $0000.HK AMS:SYNTHI $500 $USD XSYNTHA SYNTHAx', known);
    expect(tokens.filter(t => t.type === 'ticker').map(t => t.symbol)).toEqual(['SYNTHA', 'SYNTHA', '0000.HK', 'SYNTHI']);
    expect(tokens.map(t => t.text).join('')).toBe('$SYNTHA SYNTHA $0000.HK AMS:SYNTHI $500 $USD XSYNTHA SYNTHAx');
  });
  it('does not parse URLs, email, inline/fenced code, or existing Markdown links', () => {
    const text = 'https://test.test/SYNTHA person@example.invalid `SYNTHA` [SYNTHA](https://test.test/SYNTHA)\n```\nSYNTHA\n```\nSYNTHA';
    expect(parseTickerMentions(text, known).filter(t => t.type === 'ticker')).toHaveLength(1);
  });
  it('leaves reference links and raw HTML anchors untouched by ticker parsing', () => {
    const text = '[SYNTHA][filing] [filing]: https://example.com/SYNTHA\n<a href="https://example.com">SYNTHA</a>';
    expect(parseTickerMentions(text, known).filter(t => t.type === 'ticker')).toHaveLength(0);
    expect(html(<Narrative content={text} knownSymbols={known} />)).not.toContain('href="#research/SYNTHA"');
  });
  it('links only safe actual destinations and never duplicates dollar prefixes', () => {
    expect(html(<Ticker symbol="$SYNTHA" href="#research/SYNTHA" />)).toContain('>$SYNTHA</a>');
    expect(html(<Ticker symbol="SYNTHA" href="javascript:alert(1)" />)).not.toContain('<a');
    expect(html(<Ticker symbol="SYNTHI" />)).not.toContain('<a');
  });
});

describe('safe shared narrative', () => {
  for (const Renderer of [Narrative, ResearchHeadline]) {
    describe(Renderer.name, () => {
      it.each(['AI infrastructure', 'generative AI', 'AI-led'])('keeps %s as exact plain text', content => {
        const output = html(<Renderer content={content} knownSymbols={aiKnown} />);
        expect(output).not.toContain('<a');
        expect(output).not.toContain('ticker');
        expect(output.replace(/<[^>]*>/g, '')).toBe(content);
      });
      it('preserves explicit markdown links and links eligible $AI and SYNTHB without rewriting text', () => {
        const content = 'AI infrastructure, **generative AI**, *AI-led*; [AI](https://example.com/AI), [$AI](https://example.com/company), $AI and SYNTHB.';
        const output = html(<Renderer content={content} knownSymbols={aiKnown} />);
        expect(output).toContain('href="https://example.com/AI" rel="noopener noreferrer">AI</a>');
        expect(output).toContain('href="https://example.com/company" rel="noopener noreferrer">$AI</a>');
        expect(output).toContain('href="#research/AI">$AI</a>');
        expect(output).toContain('href="#research/SYNTHB">SYNTHB</a>');
        expect(output.match(/<a /g)).toHaveLength(4);
        expect(output.replace(/<[^>]*>/g, '')).toBe('AI infrastructure, generative AI, AI-led; AI, $AI, $AI and SYNTHB.');
      });
      it('keeps $AI unlinked without an eligible destination', () => {
        for (const knownSymbols of [[], [{ symbol: 'AI' }], [{ symbol: 'AI', href: 'javascript:alert(1)' }]]) {
          const output = html(<Renderer content="$AI" knownSymbols={knownSymbols} />);
          expect(output).not.toContain('<a');
          expect(output.replace(/<[^>]*>/g, '')).toBe('$AI');
        }
      });
    });
  }
  it('renders headings, emphasis, lists, quotes and tables, retaining emoji and conditions', () => {
    const output = html(<Narrative knownSymbols={known} content={'## View\n\n📌 **$SYNTHA** may improve only if revenue grows; do not buy yet.\n\n- 🟡 Evidence pending\n- Risk remains\n\n> Not a recommendation\n\n| Metric | Value |\n| --- | ---: |\n| Margin | 12% |'} />);
    for (const tag of ['<h2>', '<strong>', '<ul>', '<blockquote>', '<table>']) expect(output).toContain(tag);
    expect(output).toContain('📌');
    expect(output).toContain('🟡');
    expect(output).toContain('may improve only if revenue grows; do not buy yet.');
    expect(output).toContain('href="#research/SYNTHA"');
  });
  it('never executes HTML, unsafe URLs, or creates nested links', () => {
    const output = html(<Narrative knownSymbols={known} content={'<script>alert(1)</script> <img src=x onerror=alert(1)> [bad](javascript:alert(1)) [SYNTHA](https://example.com) `SYNTHA`\n\n```html\n<iframe src="evil"></iframe> SYNTHA\n```'} />);
    expect(output).not.toContain('<script');
    expect(output).not.toContain('<img');
    expect(output).not.toContain('<iframe');
    expect(output).not.toContain('href="javascript:');
    expect(output.match(/<a /g)).toHaveLength(1);
    expect(output).toContain('<code>SYNTHA</code>');
  });
  it('does not auto-link a ticker inside a bare URL or Markdown link', () => {
    const output = html(<Narrative knownSymbols={known} content={'https://example.com/SYNTHA [**SYNTHA**](https://example.com)'} />);
    expect(output.match(/<a /g)).toHaveLength(2); // Two source links, never a nested ticker link.
    expect(output).not.toContain('#research/SYNTHA');
  });
});

describe('public assessments and supported history', () => {
  it('withholds unknown structured codes from text and accessibility attributes', () => {
    const output = html(<Status value="UNREVIEWED_INTERNAL_CODE" marker="📌" />);
    expect(output).toContain('Assessment unavailable');
    expect(output).not.toContain('UNREVIEWED_INTERNAL_CODE');
    expect(output).toContain('📌');
  });
  it('reads approved assessments from the shared vocabulary, without guessing code meanings', () => {
    expect(html(<Status value="Watch" />)).toContain('>Watch<');
    expect(html(<Status value="WAIT_FOR_PROOF" />)).toContain('Assessment unavailable');
  });
  it('shows only supplied thesis facts and safe sources', () => {
    const output = html(<ThesisUpdate currentView="May improve only if demand returns." sources={[{ label: 'Filing', url: 'https://example.com/filing' }, { label: 'Unsafe', url: 'data:text/html,bad' }]} />);
    expect(output).toContain('Current view');
    expect(output).not.toContain('Previous view');
    expect(output).not.toContain('New evidence');
    expect(output).not.toContain('data:text');
    expect(output).toContain('May improve only if demand returns.');
  });
});
