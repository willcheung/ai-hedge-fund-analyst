// SYNTHETIC regression inputs only; no research snapshot dependencies.
import {describe,it,expect} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import {DailyBriefTimeline,type DashboardData} from './App'
import {PublicationArticle} from './MarketsApp'
import type {Publication} from './publicationTypes'

function expandedTimelineArticle(html: string) {
 const timelineStart=html.indexOf('<div class="timeline-list">')
 expect(timelineStart).toBeGreaterThan(-1)
 const timeline=html.slice(timelineStart)
 expect(timeline).not.toContain('<details')
 const articles=timeline.match(/<article\b[^>]*class="timeline-item"[^>]*>[\s\S]*?<\/article>/g)
 expect(articles).toHaveLength(1)
 // Only the meter methodology may collapse, and it must end before research starts.
 expect(html.match(/<details\b[^>]*>/g)).toEqual(['<details class="macro-meter-method">'])
 const disclosure=html.match(/<details\b[^>]*>[\s\S]*?<\/details>/)?.[0]
 expect(disclosure).toContain('<summary>How this is calculated</summary>')
 expect(html.slice(0,timelineStart)).toContain(disclosure)
 return articles![0]
}

describe('weekly and macro presentation',()=>{
 it('shows sourced why-selected in the open timeline, preserving report title',()=>{
  const html=renderToStaticMarkup(<DailyBriefTimeline data={{tickers:[],cronTimeline:[{id:'weekly',jobId:'synthetic-job-08',category:'Weekly Stock Analysis',jobName:'$SYNTHC — Synthetic Optics: synthetic demand, with incomplete valuation inputs',runTime:'2026-09-06',summary:'WAIT for September 10 proof.',highlights:[],articleBody:'## Why selected this week\n\nA future synthetic update can clarify margins.'}]} as unknown as DashboardData}/>);
  const article=expandedTimelineArticle(html)
  expect(article).toContain('Weekly Stock Analysis');expect(article).toContain('Why selected this week');expect(article).toContain('A future synthetic update');expect(article).toContain('incomplete valuation inputs');expect(article).not.toContain('<details');
 });
 it('shows commentary coverage and confidence semantics without collapsing',()=>{
  const html=renderToStaticMarkup(<DailyBriefTimeline data={{tickers:[],cronTimeline:[{id:'macro',category:'Macro Read',jobName:'Macro Read',runTime:'2026-09-06',summary:'Stance: cautious/selective.',highlights:['Stance: neutral/cautious — evidence confidence: medium'],articleBody:'## Commentary views\n\n1 commentary note unavailable.\n\nEvidence confidence is not bullishness.'}]} as unknown as DashboardData}/>);
  const article=expandedTimelineArticle(html)
  expect(article.match(/>Macro Read</g)).toHaveLength(1);expect(article).not.toContain('<h3');expect(article).toContain('aria-label="Combined macro commentary"');expect(article).toContain('Stance: cautious/selective.');expect(article).toContain('neutral/cautious');expect(article).toContain('evidence confidence: medium');expect(article).toContain('1 commentary note unavailable');expect(article).toContain('not bullishness');
 });
 it.each(['synthetic-job-08','synthetic-job-0c'])('labels weekly publications for %s',jobId=>{
  const item={schemaVersion:1,id:'weekly',jobId,type:'brief',title:'$SYNTHC — Original report title',summary:'WAIT.',publishedAt:null,informationAt:null,tickers:['SYNTHC'],sections:[],sources:[]} as Publication;
  expect(renderToStaticMarkup(<PublicationArticle item={item} symbols={[]}/>)).toContain('Weekly Stock Analysis');
 });
});
