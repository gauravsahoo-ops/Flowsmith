import { Component, Suspense, lazy, useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Login from './components/Login'
import AppShell from './layout/AppShell'
import OverviewPage from './pages/OverviewPage'
import WorkflowsPage from './pages/WorkflowsPage'
import CredentialsPage from './pages/CredentialsPage'
import ExecutionsPage from './pages/ExecutionsPage'
import TemplatesPage from './pages/TemplatesPage'
import VariablesPage from './pages/VariablesPage'
import DataTablesPage from './pages/DataTablesPage'
import ApprovalsPage from './pages/ApprovalsPage'
import SharedPage from './pages/SharedPage'
import SettingsPage from './pages/SettingsPage'
import HelpPage from './pages/HelpPage'
import MonitoringPage from './pages/MonitoringPage'
import OAuthCallbackPage from './pages/OAuthCallbackPage'
import { getToken, setToken } from './api'

// Heavy routes split out so /login doesn't pay for ReactFlow + Monaco.
const WorkflowEditorPage = lazy(() => import('./pages/WorkflowEditorPage'))
const ExecutionDetailPage = lazy(() => import('./pages/ExecutionDetailPage'))
const DataTableEditorPage = lazy(() => import('./pages/DataTableEditorPage'))
const KnowledgePage = lazy(() => import('./pages/KnowledgePage'))
const NodeEditorModal = lazy(() => import('./components/NodeEditorModal'))
const FormFillPage = lazy(() => import('./pages/FormFillPage'))
const ChatPage = lazy(() => import('./pages/ChatPage'))

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

class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }
  static getDerivedStateFromError(error) {
    return { error }
  }
  componentDidCatch(error, info) {
    // Keep prod crashes visible but contained; details in console for diagnostics.
    console.error('UI crash contained:', error, info)
  }
  render() {
    if (this.state.error) {
      return (
        <div className="page" style={{ padding: '2rem', maxWidth: 800 }}>
          <h1 style={{ color: '#ef4444' }}>Something went wrong</h1>
          <p className="hint">The view crashed. Reload or go back to Overview.</p>
          <div style={{ marginTop: '1rem', padding: '1rem', borderRadius: '8px', background: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.3)', color: '#fca5a5', fontFamily: 'monospace', fontSize: '13px', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
            <strong>{this.state.error?.name}: {this.state.error?.message}</strong>
            {this.state.error?.stack && (
              <div style={{ marginTop: '0.5rem', opacity: 0.8, maxHeight: 200, overflowY: 'auto' }}>
                {this.state.error.stack}
              </div>
            )}
          </div>
          <div style={{ marginTop: '1.5rem', display: 'flex', gap: '0.75rem' }}>
            <button className="primary" onClick={() => { this.setState({ error: null }); window.location.reload() }}>Reload</button>
            <a href="/overview" className="ghost">Go to Overview</a>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

function AuthenticatedRoutes({ onLogout }) {
  return (
    <>
      <Suspense fallback={<div className="page"><p className="hint">Loading…</p></div>}>
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
      </Suspense>
      <Suspense fallback={null}>
        <NodeEditorModal />
      </Suspense>
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
        window.location.origin,
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
      setToken(null)
      setAuthed(false)
    }
    window.addEventListener('auth:expired', onExpired)

    // Validate stored token against the server on startup
    const token = getToken()
    if (token) {
      api.getMe().catch((err) => {
        if (err.status === 401) {
          setToken(null)
          setAuthed(false)
        }
      })
    }

    return () => window.removeEventListener('auth:expired', onExpired)
  }, [])

  return (
    <BrowserRouter>
      <ErrorBoundary>
      <Routes>
        <Route path="/oauth/callback" element={<OAuthCallbackPage />} />
        <Route path="/oauth/callback/:provider" element={<OAuthCallbackPage />} />
        <Route path="/forms/:slug" element={
          <Suspense fallback={<div className="page"><p className="hint">Loading…</p></div>}>
            <FormFillPage />
          </Suspense>
        } />
        <Route path="/chat/:slug" element={
          <Suspense fallback={<div className="page"><p className="hint">Loading…</p></div>}>
            <ChatPage />
          </Suspense>
        } />
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
      </ErrorBoundary>
    </BrowserRouter>
  )
}
