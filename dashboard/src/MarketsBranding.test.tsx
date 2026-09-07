// SYNTHETIC regression inputs only; no research snapshot dependencies.
import {afterEach,describe,it,expect,vi} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import MarketsApp from './MarketsApp'
import {ThemeProvider} from './theme'
vi.mock('./useMarketData',()=>({useMarketData:()=>({data:null,error:null}),isStagedPreviewBuild:true}))
afterEach(()=>vi.unstubAllGlobals())
const renderRoute=(hash:string)=>{
 vi.stubGlobal('window',{location:{hash}})
 return renderToStaticMarkup(<ThemeProvider><MarketsApp/></ThemeProvider>)
}
describe('public branding',()=>{
 it('uses the exact brand and attribution in header and footer, including accessible link text',()=>{
  const html=renderRoute('#brief')
  for(const tag of ['header','footer']) {
   const surface=html.match(new RegExp(`<${tag}\\b[\\s\\S]*?</${tag}>`))?.[0]
   expect(surface).toContain('AI Hedge Fund Analyst')
   expect(surface).toContain('By Vibe Coding Dad')
  }
  expect(html).toContain('<strong>AI Hedge Fund Analyst</strong><span>By Vibe Coding Dad</span>')
  expect(html).not.toMatch(/\bRowan\b|Example|>Markets</)
 })
 it('brands About without requiring research data or personal attribution',()=>{
  const html=renderRoute('#about')
  expect(html).toContain('<h1>About AI Hedge Fund Analyst</h1>')
  expect(html).toContain('AI Hedge Fund Analyst brings together company research')
  expect(html).not.toMatch(/\bRowan\b|Example|About Markets/)
 })
})
