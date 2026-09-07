// SYNTHETIC regression inputs only; no research snapshot dependencies.
import {describe,it,expect} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import {PublicationArticle} from './MarketsApp'
import type {Publication} from './publicationTypes'
describe('shared publication templates',()=>{
 const item:Publication={schemaVersion:1,id:'fixture-a',jobId:'publisher-a',type:'brief',title:'Evidence update',summary:'📌 $AAA may improve only if demand holds.',publishedAt:'2026-09-06T12:00:00Z',informationAt:'2026-09-05T20:00:00Z',tickers:['AAA'],sections:[{heading:'Main risk',markdown:'Do not assume growth. [Source](https://example.com/evidence).'}],sources:[{id:'evidence',title:'Company disclosure',url:'https://example.com/evidence'}]};
 it('keeps date-only metadata and ticker headlines semantic',()=>{const html=renderToStaticMarkup(<PublicationArticle item={{...item,title:'$AAA demand may improve',publishedAt:null,informationAt:null,publishedDate:'2026-09-06',informationDate:'2026-09-05'}} symbols={[{symbol:'AAA',href:'#research/AAA'}]}/>);expect(html).toContain('2026-09-06');expect(html).not.toContain('00:00');expect(html).toMatch(/<h1><span class="ticker-group">/);expect(html).not.toContain('<h1><p>')});
 it('renders two publishers through the same type template without changing conditional meaning',()=>{
 for(const jobId of ['publisher-a','publisher-b']){const html=renderToStaticMarkup(<PublicationArticle item={{...item,jobId,id:jobId}} symbols={[{symbol:'AAA',href:'#research/AAA'}]}/>);expect(html).toContain('data-content-type="brief"');expect(html).toContain(`data-publication-id="${jobId}"`);expect(html).toContain('may improve only if demand holds');expect(html).toContain('Do not assume growth');expect(html).toContain('📌');expect(html).not.toContain('Live');expect(html).toContain('UTC')}
 });
});
