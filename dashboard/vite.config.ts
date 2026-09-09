import { defineConfig } from 'vitest/config'
import { loadEnv } from 'vite'
import { readFileSync } from 'node:fs'
import react from '@vitejs/plugin-react'
import { renderSiteMetadata } from './src/siteMetadata'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const live = mode === 'live' || (mode !== 'bundled' && env.VITE_MARKETS_DATA_MODE === 'production')
  if (live && (!env.VITE_MARKETS_MANIFEST_URL || !env.VITE_MARKETS_BLOB_ORIGIN)) throw new Error('Production requires explicit manifest URL and Blob origin')
  const demo = !live
  const csp = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-src 'none'; object-src 'none'; base-uri 'self'; form-action 'none'"
  return {
  base: './',
  test: { css: { include: [/\/src\/(?:theme|styles)\.css\?raw$/] } },
  define: live ? { 'import.meta.env.VITE_MARKETS_DATA_MODE': JSON.stringify('production') }
    : mode === 'bundled' ? { 'import.meta.env.VITE_MARKETS_DATA_MODE': JSON.stringify('bundled') } : {},
  publicDir: live ? false : 'public',
  build: { sourcemap: false, outDir: live ? 'dist/live' : 'dist' },
  plugins: [react(), { name: 'shared-site-identity', transformIndexHtml: html => renderSiteMetadata(demo ? html.replace('<head>', `<head><meta http-equiv="Content-Security-Policy" content="${csp}">`) : html) }, {
    name: 'live-static-assets',
    generateBundle() {
      if (!live) return
      // Copy only reviewed static assets, never a previously staged dataset.
      for (const fileName of ['apple-touch-icon.png', 'favicon-32.png', 'favicon.svg',
        'fonts/Inter-OFL.txt', 'fonts/Source-Serif-4-OFL.txt',
        'fonts/inter-latin-variable.woff2', 'fonts/source-serif-4-latin-600.woff2']) {
        this.emitFile({ type: 'asset', fileName, source: readFileSync(new URL(`./public/${fileName}`, import.meta.url)) })
      }
    },
  }],
  }
})
