import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Login from './components/Login'
import NodeEditorModal from './components/NodeEditorModal'
import AppShell from './layout/AppShell'
import OverviewPage from './pages/OverviewPage'
import WorkflowsPage from './pages/WorkflowsPage'
import WorkflowEditorPage from './pages/WorkflowEditorPage'
import CredentialsPage from './pages/CredentialsPage'
import ExecutionsPage from './pages/ExecutionsPage'
import ExecutionDetailPage from './pages/ExecutionDetailPage'
import TemplatesPage from './pages/TemplatesPage'
import VariablesPage from './pages/VariablesPage'
import DataTablesPage from './pages/DataTablesPage'
import DataTableEditorPage from './pages/DataTableEditorPage'
import KnowledgePage from './pages/KnowledgePage'
import ApprovalsPage from './pages/ApprovalsPage'
import SharedPage from './pages/SharedPage'
import SettingsPage from './pages/SettingsPage'
import HelpPage from './pages/HelpPage'
import MonitoringPage from './pages/MonitoringPage'
import OAuthCallbackPage from './pages/OAuthCallbackPage'
import { getToken, setToken } from './api'

// Fallback for unknown routes
function NotFound() {
  return (
    <div className="page">
      <h1>Not found</h1>
      <p className="hint">The page you requested does not exist.</p>
      <a href="/overview" className="ghost">Go to Overview</a>
    </div>
  )
}

function AuthenticatedRoutes({ onLogout }) {
  return (
    <>
      <Routes>
        <Route element={<AppShell onLogout={onLogout} />}>
          <Route index element={<Navigate to="/overview" replace />} />
          <Route path="overview" element={<OverviewPage />} />
          <Route path="workflows" element={<WorkflowsPage />} />
          <Route path="workflows/:id" element={<WorkflowEditorPage />} />
          <Route path="credentials" element={<CredentialsPage />} />
          <Route path="executions" element={<ExecutionsPage />} />
          <Route path="executions/:id" element={<ExecutionDetailPage />} />
          <Route path="templates" element={<TemplatesPage />} />
          <Route path="variables" element={<VariablesPage />} />
          <Route path="data-tables" element={<DataTablesPage />} />
          <Route path="data-tables/:tableId" element={<DataTableEditorPage />} />
          <Route path="knowledge" element={<KnowledgePage />} />
          <Route path="approvals" element={<ApprovalsPage />} />
          <Route path="shared" element={<SharedPage />} />
          <Route path="monitoring" element={<MonitoringPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="help" element={<HelpPage />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
      <NodeEditorModal />
    </>
  )
}

function handleOAuthPopup() {
  const params = new URLSearchParams(window.location.search)
  const legacyOk = params.get('salesforce_connected') === '1'
  const legacyFail = params.get('salesforce_connect_failed') === '1'
  const genericOk = params.get('oauth_connected') === '1'
  const genericFail = params.get('oauth_connect_failed') === '1'
  if (legacyOk || legacyFail || genericOk || genericFail) {
    const ok = legacyOk || genericOk
    const provider = params.get('provider') || 'salesforce'
    const error = ok ? null : params.get('error') || `${provider} authorization failed.`
    if (window.opener) {
      window.opener.postMessage(
        { source: legacyOk || legacyFail ? 'salesforce-oauth' : 'oauth', ok, error, provider },
        '*',
      )
      const clean = window.location.pathname
      window.history.replaceState({}, '', clean)
      window.close()
      return true
    }
  }
  return false
}

export default function App() {
  const [authed, setAuthed] = useState(Boolean(getToken()))

  useEffect(() => {
    // Handle OAuth popup callback even when not authed (popup window has no token)
    if (handleOAuthPopup()) return
    function onExpired() {
      setAuthed(false)
    }
    window.addEventListener('auth:expired', onExpired)
    return () => window.removeEventListener('auth:expired', onExpired)
  }, [])

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/oauth/callback" element={<OAuthCallbackPage />} />
        <Route path="/oauth/callback/:provider" element={<OAuthCallbackPage />} />
        <Route
          path="*"
          element={
            !authed ? (
              <Login onAuthed={() => setAuthed(true)} />
            ) : (
              <AuthenticatedRoutes
                onLogout={() => {
                  setToken(null)
                  setAuthed(false)
                }}
              />
            )
          }
        />
      </Routes>
    </BrowserRouter>
  )
}
