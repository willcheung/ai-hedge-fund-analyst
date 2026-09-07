// SYNTHETIC regression inputs only; no research snapshot dependencies.
import {describe,it,expect} from 'vitest'
import {filterResearch,publicRoute,type CompanyRow,type Publication} from './publicationTypes'
import {isLocalDataPreview} from './useMarketData'
describe('public navigation and combined research filters',()=>{
 const rows=[{symbol:'AAA',title:'Alpha',tags:['Chips'],category:'Technology',summary:'Evidence',updated:'',status:'',actionBucket:''},{symbol:'BBB',title:'Beta',tags:['Cloud'],category:'Technology',summary:'Evidence',updated:'',status:'',actionBucket:''}] satisfies CompanyRow[]
 const publications=[{type:'company',tickers:['AAA'],assessment:'Watch'}] as Publication[]
 it('combines text, category and assessment; raw tags are searchable, not categories',()=>{expect(filterResearch(rows,'alpha','Technology','Watch',publications)).toHaveLength(1);expect(filterResearch(rows,'alpha','Finance','Watch',publications)).toHaveLength(0);expect(filterResearch(rows,'Chips','','',publications)).toHaveLength(1);expect(filterResearch(rows,'','Chips','',publications)).toHaveLength(0);expect(filterResearch(rows,'','','',publications)).toHaveLength(2)})
 it('preserves company links including international exchange symbols',()=>{expect(publicRoute('#ticker/NASDAQ:AAA')).toEqual({page:'company',id:'NASDAQ:AAA'});expect(publicRoute('#stocks').page).toBe('research');expect(publicRoute('#projections').page).toBe('evaluation')})
 it('allows local QA only on loopback and explicit opt-in',()=>{expect(isLocalDataPreview('localhost','?localData=1')).toBe(true);expect(isLocalDataPreview('127.0.0.1','')).toBe(false);expect(isLocalDataPreview('public.example.invalid','?localData=1')).toBe(false)})
})
