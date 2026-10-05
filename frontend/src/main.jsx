import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { initTheme } from './utils/theme'
import { useWorkflowStore } from './stores/workflowStore'

// Initialize theme before initial render to prevent theme flashing
initTheme()
import { useExecutionStore } from './stores/executionStore'
import { useUiStore } from './stores/uiStore'

import { useCredentialStore } from './stores/credentialStore'

// Expose stores for e2e tests (dev only — avoids prod window pollution)
if (import.meta.env.DEV) {
  window.__wfStore = useWorkflowStore
  window.__uiStore = useUiStore
  window.__executionStore = useExecutionStore
  window.__execStore = useExecutionStore
  window.__credentialStore = useCredentialStore
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
