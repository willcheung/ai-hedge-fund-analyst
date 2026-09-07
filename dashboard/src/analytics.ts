import type { BeforeSendEvent } from '@vercel/analytics'

/** Keep public paths, but never forward user-supplied queries or hash routes. */
export function sanitizeAnalyticsEvent(event: BeforeSendEvent): BeforeSendEvent | null {
  try {
    const url = new URL(event.url)
    if (url.protocol !== 'https:' && url.protocol !== 'http:') return null
    return { ...event, url: `${url.origin}${url.pathname}` }
  } catch {
    return null
  }
}
