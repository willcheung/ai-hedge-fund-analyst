import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { renderSiteMetadata } from './src/siteMetadata'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  if (env.VITE_MARKETS_DATA_MODE === 'production' && (!env.VITE_MARKETS_MANIFEST_URL || !env.VITE_MARKETS_BLOB_ORIGIN)) throw new Error('Production requires explicit manifest URL and Blob origin')
  const demo = env.VITE_MARKETS_DATA_MODE !== 'production'
  const csp = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-src 'none'; object-src 'none'; base-uri 'self'; form-action 'none'"
  return {
  base: './',
  build: { sourcemap: false },
  plugins: [react(), { name: 'shared-site-identity', transformIndexHtml: html => renderSiteMetadata(demo ? html.replace('<head>', `<head><meta http-equiv="Content-Security-Policy" content="${csp}">`) : html) }],
  }
})
