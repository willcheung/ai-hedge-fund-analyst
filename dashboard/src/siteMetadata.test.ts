// SYNTHETIC regression inputs only; no research snapshot dependencies.
import {describe,it,expect} from 'vitest'
import {renderSiteMetadata} from './siteMetadata'
import {siteConfig} from './siteConfig'
import template from '../index.html?raw'

describe('shared site identity',()=>{
 it('uses the exact public identity for static titles and previews',()=>{
  const html=renderSiteMetadata(template)
  expect(siteConfig.name).toBe('AI Hedge Fund Analyst')
  expect(siteConfig.attribution).toBe('By Vibe Coding Dad')
  expect(html).toContain('<title>AI Hedge Fund Analyst</title>')
  for(const attribute of ['property="og:title"','name="twitter:title"']) expect(html).toContain(`${attribute} content="AI Hedge Fund Analyst"`)
  expect(html).toContain('name="author" content="By Vibe Coding Dad"')
  expect(html).toContain(siteConfig.description)
  expect(html).not.toMatch(/__SITE_|Rowan|Example/)
 })
 it('escapes configured text rather than introducing executable markup',()=>{
  const html=renderSiteMetadata('<title>__SITE_TITLE__</title><meta content="__SITE_ATTRIBUTION__"><meta content="__SITE_DESCRIPTION__">',{name:'Research & evidence',attribution:'By <Author>',description:'A "quoted" view <script>'})
  expect(html).toContain('Research &amp; evidence')
  expect(html).toContain('&lt;Author&gt;')
  expect(html).toContain('&quot;quoted&quot;')
  expect(html).not.toContain('<script>')
 })
})
