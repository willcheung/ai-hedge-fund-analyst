// SYNTHETIC regression inputs only; no research snapshot dependencies.
import {describe,it,expect} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import {DailyBriefTimeline,type DashboardData} from './App'
import {PublicationArticle} from './MarketsApp'
import type {Publication} from './publicationTypes'

describe('weekly and macro presentation',()=>{
 it('shows sourced why-selected in the open timeline, preserving report title',()=>{
  const html=renderToStaticMarkup(<DailyBriefTimeline data={{tickers:[],cronTimeline:[{id:'weekly',jobId:'synthetic-job-08',category:'Weekly Stock Analysis',jobName:'$SYNTHC — Synthetic Optics: synthetic demand, with incomplete valuation inputs',runTime:'2026-09-06',summary:'WAIT for September 10 proof.',highlights:[],articleBody:'## Why selected this week\n\nA future synthetic update can clarify margins.'}]} as unknown as DashboardData}/>);
  expect(html).toContain('Weekly Stock Analysis');expect(html).toContain('Why selected this week');expect(html).toContain('A future synthetic update');expect(html).toContain('incomplete valuation inputs');expect(html).not.toContain('<details');
 });
 it('shows commentary coverage and confidence semantics without collapsing',()=>{
  const html=renderToStaticMarkup(<DailyBriefTimeline data={{tickers:[],cronTimeline:[{id:'macro',category:'Macro Read',jobName:'Macro Read',runTime:'2026-09-06',summary:'Stance: cautious/selective.',highlights:['Stance: neutral/cautious — evidence confidence: medium'],articleBody:'## Commentary views\n\n1 commentary note unavailable.\n\nEvidence confidence is not bullishness.'}]} as unknown as DashboardData}/>);
  expect(html).toContain('Macro Read');expect(html).toContain('neutral/cautious');expect(html).toContain('evidence confidence: medium');expect(html).toContain('1 commentary note unavailable');expect(html).toContain('not bullishness');expect(html).not.toContain('<details');
 });
 it.each(['synthetic-job-08','synthetic-job-0c'])('labels weekly publications for %s',jobId=>{
  const item={schemaVersion:1,id:'weekly',jobId,type:'brief',title:'$SYNTHC — Original report title',summary:'WAIT.',publishedAt:null,informationAt:null,tickers:['SYNTHC'],sections:[],sources:[]} as Publication;
  expect(renderToStaticMarkup(<PublicationArticle item={item} symbols={[]}/>)).toContain('Weekly Stock Analysis');
 });
});
