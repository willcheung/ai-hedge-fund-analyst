import type {Publication} from './publicationTypes'
const record=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v)
const text=(v:unknown):v is string=>typeof v==='string'
const strings=(v:unknown):v is string[]=>Array.isArray(v)&&v.every(text)
const clock=(v:unknown)=>v===null||(text(v)&&/T.*(?:Z|[+-]\d\d:\d\d)$/.test(v)&&Number.isFinite(Date.parse(v)))
/** Structural browser guard; publication privacy/editorial validation remains upstream. */
export function isPublication(v:unknown):v is Publication {
 if(!record(v)||v.schemaVersion!==1||!['brief','company','theme'].includes(String(v.type)))return false
 if(!['id','jobId','title','summary'].every(k=>text(v[k]))||!clock(v.publishedAt)||!clock(v.informationAt)||!strings(v.tickers))return false
 if(!['publishedDate','informationDate'].every(k=>v[k]===undefined||(text(v[k])&&/^\d{4}-\d{2}-\d{2}$/.test(v[k])&&Number.isFinite(Date.parse(v[k]))&&new Date(v[k]).toISOString().slice(0,10)===v[k])))return false
 if(!Array.isArray(v.sections)||!v.sections.every(s=>record(s)&&text(s.heading)&&text(s.markdown)&&(s.sourceIds===undefined||strings(s.sourceIds))&&(s.emoji===undefined||text(s.emoji))))return false
 if(!Array.isArray(v.sources)||!v.sources.every(s=>record(s)&&text(s.id)&&text(s.title)&&text(s.url)))return false
 if(v.assessment!==undefined&&!text(v.assessment))return false
 if(v.action!==undefined){const a=v.action;if(!record(a)||!text(a.currentView)||!text(a.why)||!strings(a.prerequisites)||!strings(a.sourceIds)||!['horizon','context','mainRisk'].every(k=>a[k]===undefined||text(a[k])))return false}
 if(v.quote!==undefined){const q=v.quote;if(!record(q)||!text(q.symbol)||!text(q.currency)||typeof q.price!=='number'||!Number.isFinite(q.price)||!clock(q.asOf)||q.asOf===null||!['change','changePct'].every(k=>q[k]===undefined||(typeof q[k]==='number'&&Number.isFinite(q[k]))))return false}
 if(v.thesisHistory!==undefined&&(!Array.isArray(v.thesisHistory)||!v.thesisHistory.every(h=>record(h)&&['previousView','evidence','currentView'].every(k=>text(h[k]))&&clock(h.informationAt)&&strings(h.sourceIds))))return false
 return true
}
export function hasPublicationContract(v:unknown):v is {publications:Publication[]} {return record(v)&&Array.isArray(v.publications)&&v.publications.every(isPublication)}
