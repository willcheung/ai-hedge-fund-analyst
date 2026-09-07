import React from 'react'
import { createRoot } from 'react-dom/client'
import { Analytics } from '@vercel/analytics/react'
import App from './MarketsApp'
import { sanitizeAnalyticsEvent } from './analytics'
import { isStagedPreviewBuild } from './useMarketData'
import 'datatables.net-dt/css/dataTables.dataTables.css'
import './styles.css'
import {ThemeProvider} from './theme'
import './theme.css'

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider><App /></ThemeProvider>
    {import.meta.env.PROD && import.meta.env.VITE_ENABLE_ANALYTICS === 'true' && !isStagedPreviewBuild && <Analytics beforeSend={sanitizeAnalyticsEvent} />}
  </React.StrictMode>,
)
