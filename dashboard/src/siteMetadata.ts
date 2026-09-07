import { siteConfig } from './siteConfig'

const escapeHtml = (value: string) => value.replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]!))

/** The static HTML and hydrated app share one maintained identity. */
export function renderSiteMetadata(html: string, config: {name:string; attribution:string; description:string} = siteConfig): string {
  return html
    .replace(/__SITE_TITLE__/g, () => escapeHtml(config.name))
    .replace(/__SITE_ATTRIBUTION__/g, () => escapeHtml(config.attribution))
    .replace(/__SITE_DESCRIPTION__/g, () => escapeHtml(config.description))
}
