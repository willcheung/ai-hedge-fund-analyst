// SYNTHETIC regression inputs only; no research snapshot dependencies.
import {describe,it,expect} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import {publishedValuationAction,DailyBriefTimeline,type DashboardData} from './App'

describe('published valuation actions and brief identity',()=>{
 it('uses explicit current membership, not old valuation trade text or price flags',()=>{
  const shortlist={rows:[{symbol:'AAA',bucket:'Kill / Do Not Average',bucketReason:'Required evidence failed.'},{symbol:'BBB',bucket:'Add After Proof',bucketReason:'Wait for business evidence.'}]} as Parameters<typeof publishedValuationAction>[1]
  expect(publishedValuationAction('AAA',shortlist)).toMatchObject({label:'Kill / Do Not Average',tone:'urgent',reason:'Required evidence failed.'})
  expect(publishedValuationAction('BBB',shortlist).label).toBe('Add After Proof')
  expect(publishedValuationAction('CCC',shortlist).label).toBe('No published action')
 })
 it('does not turn unknown or absent membership into a recommendation',()=>{
  expect(publishedValuationAction('AAA').label).toBe('No published action')
  const shortlist={rows:[{symbol:'AAA',bucket:'UNRECOGNIZED',bucketReason:'Price looks cheap',entryEligible:true}]} as unknown as Parameters<typeof publishedValuationAction>[1]
  expect(publishedValuationAction('AAA',shortlist).label).toBe('No published action')
 })
 it('renders explicit source tickers in brief headlines as research links',()=>{
  const data={tickers:[{symbol:'AAA'}],cronTimeline:[{id:'fixture',jobName:'$AAA — Company research update',category:'Other research job',runTime:'2026-09-06 23:20:25',summary:'Demand improved.',highlights:[]}]} as unknown as DashboardData
  const html=renderToStaticMarkup(<DailyBriefTimeline data={data}/>)
  expect(html).toContain('href="#research/AAA"')
  expect(html).toContain('$AAA')
  expect(html).not.toContain('Other research job')
  expect(html).not.toContain('(timezone unspecified)')
 })
})
