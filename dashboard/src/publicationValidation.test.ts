// SYNTHETIC regression inputs only; no research snapshot dependencies.
import {describe,it,expect} from 'vitest'
import {hasPublicationContract,isPublication} from './publicationValidation'
import {formatTimestamp,parseTickerMentions} from './researchComponents'
import {publicRoute} from './publicationTypes'
describe('publication structure and migration guard',()=>{
 const item={schemaVersion:1,id:'safe',jobId:'fixture',type:'brief',title:'Evidence',summary:'No conclusion yet.',publishedAt:null,informationAt:null,tickers:[],sections:[],sources:[]};
 it('rejects missing pre-contract data and malformed arrays/types',()=>{expect(hasPublicationContract({})).toBe(false);expect(hasPublicationContract({publications:{}})).toBe(false);expect(hasPublicationContract({publications:[item]})).toBe(true);for(const patch of [{sections:null},{sources:null},{type:'plugin'},{schemaVersion:2},{action:{prerequisites:null}},{thesisHistory:{}}])expect(isPublication({...item,...patch})).toBe(false)})
 it('validates optional known dates without inventing clocks',()=>{expect(isPublication({...item,informationDate:'2026-09-06'})).toBe(true);expect(isPublication({...item,informationDate:'2026-02-31'})).toBe(false);expect(isPublication({...item,publishedDate:7})).toBe(false)});
 it('preserves date-only precision without inventing midnight',()=>{expect(formatTimestamp('2026-09-06')).toBe('2026-09-06');expect(formatTimestamp('2026-02-31')).toBe('Timestamp unavailable')})
 it('handles malformed hashes without throwing',()=>{for(const hash of ['#briefs/%E0%A4%A','#themes/%E0%A4%A','#research/%E0%A4%A'])expect(()=>publicRoute(hash)).not.toThrow()})
 it('recognizes Nokia when explicitly marked but not currency amounts',()=>{const result=parseTickerMentions('$NOK reports; NOK 100 and $100.',[{symbol:'NOK'}]);expect(result.filter(t=>t.type==='ticker')).toHaveLength(1)})
})
