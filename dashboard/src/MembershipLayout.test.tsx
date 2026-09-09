// SYNTHETIC regression inputs only; no research snapshot dependencies.
import {describe,it,expect} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import type {ComponentProps} from 'react'
import {ShortlistMembershipSection,MEMBERSHIP_BUCKET_GUIDE} from './App'
type Shortlist=NonNullable<ComponentProps<typeof ShortlistMembershipSection>['shortlist']>
const render=(shortlist:unknown)=>renderToStaticMarkup(<ShortlistMembershipSection shortlist={shortlist as Shortlist} onSelectTicker={()=>{}}/>)
describe('source-grounded Conviction List',()=>{
 it('retains only exact canonical active buckets, source reasons, and ticker drilldowns',()=>{
  const html=render({generatedAt:'2026-09-06T05:59:42Z',rows:[
   {symbol:'SCOUT',rank:'2',bucket:'Buy / Scout Now',bucketReason:'Attractive entry with primary-business proof.'},
   {symbol:'PROOF',rank:'1',bucket:'Add After Proof',bucketReason:'Qualifies, with scaling gated on new contracts.'},
   {symbol:'SYNTHWAIT',rank:'3',bucket:'Wait for Trigger',bucketReason:'Synthetic trigger remains unmet.'},
   {symbol:'MEMORY',rank:'4',bucket:'Research Memory / Not Live Action',bucketReason:'Research only.'},
   {symbol:'KILL',rank:'5',bucket:'Kill / Do Not Average',bucketReason:'Required evidence failed.'},
   {symbol:'UNKNOWN',rank:'6',bucket:'Unrecognized bucket',bucketReason:'Must not be inferred from prose.'},
  ]})
  expect([...html.matchAll(/<th\b[^>]*>(.*?)<\/th>/g)].map(m=>m[1])).toEqual(['Company','Pick status','Why it qualifies'])
  expect(html).not.toContain('bucket-cell')
  expect(html).not.toContain('Research tier')
  expect(html).not.toContain('What each pick status means')
  expect(html).not.toContain('aria-label="Pick status meanings"')
  expect(html).not.toContain('<aside')
  expect(html).not.toContain('2 Conviction List theses')
  expect(html).not.toContain('Source updated')
  expect(html).toContain('Attractive entry with primary-business proof.')
  expect(html).toContain('Qualifies, with scaling gated on new contracts.')
  expect(html).toContain('class="text-link membership-ticker"')
  expect((html.match(/data-label="Company"/g)||[])).toHaveLength(2)
  expect((html.match(/data-label="Pick status"/g)||[])).toHaveLength(2)
  expect((html.match(/data-label="Why it qualifies"/g)||[])).toHaveLength(2)
  for(const omitted of ['SYNTHWAIT','MEMORY','KILL','UNKNOWN','Synthetic trigger','Research only.','Required evidence failed.','Must not be inferred']) expect(html).not.toContain(omitted)
 })
 it('keeps each active assignment and its full source reason without deriving a new action',()=>{
  for(const item of MEMBERSHIP_BUCKET_GUIDE.filter(item=>['Buy / Scout Now','Add After Proof'].includes(item.bucket))){
   const html=render({rows:[{symbol:'AAA',rank:'1',bucket:item.bucket,bucketReason:'Condition remains unfulfilled; do not buy before verification.'}]})
   const body=html.match(/<tbody>(.*?)<\/tbody>/)?.[1]||''
   expect(body).toContain(item.label)
   expect(body).toContain('Condition remains unfulfilled; do not buy before verification.')
   expect((body.match(/<td\b/g)||[])).toHaveLength(3)
  }
 })
 it('uses the exact proof trigger for Add After Proof when the source bucket reason is empty',()=>{
  const proofTrigger='Q2/Q3 order-to-revenue conversion and backlog durability'
  const contradictoryEntryReason='No structured ideal-entry band; keep on watch, not the actionable list.'
  const html=render({rows:[{
   symbol:'PROOF',
   bucket:'Add After Proof',
   bucketReason:'',
   proofTrigger,
   entryReason:contradictoryEntryReason,
  }]})
  const reason=html.match(/<td class="membership-reason" data-label="Why it qualifies">(.*?)<\/td>/)?.[1]||''
  expect(reason).toBe(proofTrigger)
  expect(reason).not.toContain(contradictoryEntryReason)
  expect(reason).not.toContain('not the actionable list')
 })
 it.each([
  {state:'populated',shortlist:{rows:[{symbol:'AAA',bucket:'Buy / Scout Now',bucketReason:'Source reason.'}]},preceding:'</table></div></div>'},
  {state:'empty',shortlist:{rows:[]},preceding:'<p class="markets-empty">No qualified Conviction List theses are available in this edition.</p>'},
  {state:'filtered empty',shortlist:{rows:[{symbol:'WAIT',bucket:'Wait for Trigger'}]},preceding:'<p class="markets-empty">No qualified Conviction List theses are available in this edition.</p>'},
  {state:'unavailable',shortlist:null,preceding:'<p class="markets-empty">Conviction List source data is unavailable in this edition. No fallback theses are shown.</p>'},
 ])('places the exact one-paragraph methodology after the $state picks content',({shortlist,preceding})=>{
  const html=render(shortlist)
  const methodology='<div class="membership-methodology"><h3>How picks qualify</h3><p>Each pick is reviewed for business quality, valuation, evidence, and risk—not just price moves or hype. The list includes only Buy / Scout Now and Add After Proof names, with the key evidence still needed shown for each.</p></div>'
  expect(html.match(/<div class="membership-methodology">[\s\S]*?<\/div>/g)).toEqual([methodology])
  expect(html).toContain(`${preceding}${methodology}</section>`)
  expect(html).not.toContain('What each pick status means')
  for(const removed of ['Capital action is a separate decision','automatically fall off this page','records remain available in Research','published audit data','canonical MarketWiki list','five-minute publisher','refresh wrapper','deterministic builder','may force Wait but cannot promote']) expect(html).not.toContain(removed)
 })
 it('shows an honest empty state when there are no active rows and never substitutes a fallback',()=>{
  const html=render({generatedAt:'2026-09-06T05:59:42Z',rows:[
   {symbol:'WAIT',bucket:'Wait for Trigger',bucketReason:'Wait.'},
   {symbol:'KILL',bucket:'Kill / Do Not Average',bucketReason:'Failed.'},
   {symbol:'UNKNOWN',bucket:'UNRECOGNIZED',bucketReason:'Unknown.'},
  ]})
  expect(html).toContain('No qualified Conviction List theses are available in this edition.')
  expect(html).not.toContain('Source updated')
  expect(html).not.toContain('<table')
  for(const symbol of ['WAIT','KILL','UNKNOWN']) expect(html).not.toContain(`$${symbol}`)
 })
 it('preserves distinct synthetic proof triggers and excludes inactive rows',()=>{
  const expectedProofTriggers = {
   SYNTHA: 'Synthetic customer confirmation remains pending.',
   SYNTHB: 'Synthetic margin evidence remains pending.',
  }
  const source={rows:[
   ...Object.entries(expectedProofTriggers).map(([symbol,proofTrigger])=>({symbol,bucket:'Add After Proof',bucketReason:'',proofTrigger,entryReason:'Unrelated entry condition.'})),
   {symbol:'SYNTHC',bucket:'Wait for Trigger',bucketReason:'Synthetic wait condition.'},
  ]}
  const html=render(source)
  expect((html.match(/data-top-pick-symbol=/g)||[])).toHaveLength(2)
  for(const [symbol,proofTrigger] of Object.entries(expectedProofTriggers)){
   expect(html).toContain(`data-top-pick-symbol="${symbol}"`)
   expect(html).toContain(proofTrigger)
  }
  expect(html).not.toContain('Unrelated entry condition.')
  expect(html).not.toContain('SYNTHC')
 })
 it('shows a work in progress badge beside the h2 heading, one h3 methodology heading, and keeps responsive table hooks',()=>{
  const html=render({rows:[{symbol:'AAA',bucket:'Buy / Scout Now',bucketReason:'Source reason.'}]})
  expect(html).toContain('<div class="section-header"><h2>Current picks</h2><span class="membership-system-pill">Work in progress</span></div>')
  expect(html).not.toContain('Selected theses classified as Buy / Scout Now or Add After Proof appear here')
  expect(html).not.toContain('<h2>Current picks</h2><p>')
  expect([...html.matchAll(/<h3>(.*?)<\/h3>/g)].map(match=>match[1])).toEqual(['How picks qualify'])
  expect(html).toContain('<table class="membership-matrix membership-list">')
  expect(html).toContain('<div class="membership-layout"><div class="table-scroll">')
  for(const label of ['Company','Pick status','Why it qualifies']) expect(html).toContain(`data-label="${label}"`)
 })
})
