// Mirrors the single publishing schema; validation and legacy adaptation live in Python.
export interface Publication {
 schemaVersion: 1; id: string; jobId: string; type: 'brief'|'company'|'theme'; title: string; summary: string;
 publishedAt: string|null; informationAt: string|null; publishedDate?: string; informationDate?: string; tickers: string[];
 sections: {heading:string;markdown:string;sourceIds?:string[];emoji?:string}[];
 sources: {id:string;title:string;url:string}[]; assessment?:string;
 action?: {currentView:string;why:string;prerequisites:string[];horizon?:string;context?:string;mainRisk?:string;sourceIds:string[]};
 quote?: {symbol:string;price:number;currency:string;asOf:string;change?:number;changePct?:number;period?:'day';previousAsOf?:string};
 thesisHistory?: {previousView:string;evidence:string;currentView:string;informationAt:string;sourceIds:string[]}[];
}
export type CompanyRow = {symbol:string;exchange?:string;tradingViewSymbol?:string;title:string;updated:string;tags:string[];category:string;summary:string;status:string;actionBucket:string;thesis?:string;risk?:string;detailSections?:{title:string;summary:string;bullets?:string[]}[]}
export function publicRoute(hash:string): {page:string;id?:string} {
 const value=hash.replace(/^#\/?/,'');
 const match=value.match(/^(?:ticker|research)\/(.+)$/);
 if(match) {try{return {page:'company',id:decodeURIComponent(match[1])}}catch{return {page:'research'}}}
 if(value.startsWith('briefs/')||value.startsWith('themes/')) {try{return {page:'publication',id:decodeURIComponent(value.slice(7))}}catch{return {page:'brief'}}}
 if(value==='stocks') return {page:'research'};
 if(value==='market'||value==='daily'||!value) return {page:'brief'};
 if(['strategy','projections','valuation'].includes(value)) return {page:'evaluation'};
 if(value==='ops') return {page:'ops'};
 if(['sources','owner'].includes(value)) return {page:'owner'};
 return {page:['brief','cio','evaluation','briefs','research','themes','about'].includes(value)?value:'brief'};
}
/** Facet counts use the same search/stance scope as the results, before category selection. */
export function researchCategoryCounts(rows:CompanyRow[],search:string,assessment:string,publications:Publication[]) {
 const matches=filterResearch(rows,search,'',assessment,publications);
 const counts=new Map<string,number>(rows.map(row=>[row.category,0]));
 for(const row of matches) counts.set(row.category,(counts.get(row.category)||0)+1);
 counts.set('',matches.length);
 return counts;
}
export function filterResearch(rows:CompanyRow[],search:string,theme:string,assessment:string,publications:Publication[]) {
 return rows.filter(row=> {
 const item=publications.find(p=>p.type==='company'&&p.tickers.includes(row.symbol));
 return (!search || `${row.symbol} ${row.title} ${row.summary} ${row.tags.join(' ')}`.toLowerCase().includes(search.toLowerCase().trim())) && (!theme || row.category===theme) && (!assessment || item?.assessment===assessment);
 });
}
