// SYNTHETIC regression inputs only; no research snapshot dependencies.
import { describe, expect, it } from 'vitest'
import { filterResearch, researchCategoryCounts, type CompanyRow, type Publication } from './publicationTypes'
import snapshot from '../tests/fixtures/demo-dashboard.json'
const rows=snapshot.tickers as CompanyRow[]
const publications=snapshot.publications as Publication[]

describe('category counts and results share the same filters',()=>{
 for(const search of ['', 'SYNTHA', 'power', 'NO_SUCH_COMPANY_123']) {
  it(`matches every category result with search ${JSON.stringify(search)} and every available stance`,()=>{
   const stances=['',...new Set(publications.filter(p=>p.type==='company').map(p=>p.assessment).filter((s):s is string=>!!s))]
   for(const stance of stances) {
    const counts=researchCategoryCounts(rows,search,stance,publications)
    for(const [category,count] of counts) expect(filterResearch(rows,search,category,stance,publications).length,`${category}/${stance}`).toBe(count)
   }
  })
 }
 it('shows zero rather than a full-category total when search excludes that category',()=>{
  expect(researchCategoryCounts(rows,'SYNTHA','',publications).get('AI power / energy')).toBe(0)
  const sourceCount = rows.filter(row=>row.category==='AI power / energy').length
  expect(sourceCount).toBeGreaterThan(0)
  expect(researchCategoryCounts(rows,'','',publications).get('AI power / energy')).toBe(sourceCount)
 })
})
