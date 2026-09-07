// SYNTHETIC regression inputs only; no research snapshot dependencies.
import {describe,it,expect} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import type {ComponentProps} from 'react'
import {ShortlistMembershipSection,MEMBERSHIP_BUCKET_GUIDE} from './App'
import snapshot from '../tests/fixtures/demo-dashboard.json'
type Shortlist=NonNullable<ComponentProps<typeof ShortlistMembershipSection>['shortlist']>
const render=(shortlist:unknown)=>renderToStaticMarkup(<ShortlistMembershipSection shortlist={shortlist as Shortlist} onSelectTicker={()=>{}}/>)
describe('compact source-grounded membership list',()=>{
 it('has one bucket column, source reasons and a five-bucket side guide',()=>{
  const html=render(snapshot.currentAsymmetricShortlist)
  expect([...html.matchAll(/<th\b[^>]*>(.*?)<\/th>/g)].map(m=>m[1])).toEqual(['Company','Membership bucket','Reason'])
  expect(html).not.toContain('bucket-cell')
  expect(html).not.toContain('Research tier')
  expect((html.match(/<dt\b/g)||[])).toHaveLength(5)
  expect(html).not.toContain('Membership update details')
  expect(html).not.toContain('Change statistics are unavailable')
  expect(html).toContain(`${snapshot.currentAsymmetricShortlist.rows.length} companies · List updated`)
  expect(html.match(/List updated/g)).toHaveLength(1)
  expect(html).not.toContain('Assessment unavailable')
 })
 it('keeps each known assignment and its full source reason without deriving a new action',()=>{
  for(const item of MEMBERSHIP_BUCKET_GUIDE){
   const html=render({rows:[{symbol:'AAA',rank:'1',bucket:item.bucket,bucketReason:'Condition remains unfulfilled; do not buy before verification.'}]})
   const body=html.match(/<tbody>(.*?)<\/tbody>/)?.[1]||''
   expect(body).toContain(item.label)
   expect(body).toContain('Condition remains unfulfilled; do not buy before verification.')
   expect((body.match(/<td\b/g)||[])).toHaveLength(3)
  }
 })
 it('does not guess a bucket from a price condition or manufacture no-change statistics',()=>{
  const html=render({rows:[{symbol:'AAA',bucket:'UNRECOGNIZED',bucketReason:'Price is in the entry zone',entryStatus:'inside_zone'}]})
  const body=html.match(/<tbody>(.*?)<\/tbody>/)?.[1]||''
  expect(body).toContain('Assessment unavailable')
  expect(body).not.toContain('Buy / Scout Now')
  expect(html).not.toContain('No membership change')
  expect(html).toContain('no bucket is inferred')
 })
})
