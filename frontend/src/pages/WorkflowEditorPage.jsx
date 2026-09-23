import React, { Component, useEffect, useState, isValidElement } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ReactFlowProvider } from '@xyflow/react'
import TopBar from '../components/TopBar'
import Sidebar from '../components/Sidebar'
import Canvas from '../components/Canvas'
import ExecutionInspector from '../components/ExecutionInspector'
import { useWorkflowStore, isDirty, confirmDiscard } from '../stores/workflowStore'
import { useUiStore } from '../stores/uiStore'
import { useExecutionStore } from '../stores/executionStore'
import PageHeader from '../components/shared/PageHeader'
import LogsPanel from '../components/LogsPanel'
import WorkflowHistoryDrawer from '../components/WorkflowHistoryDrawer'
import SmithDrawer from '../components/SmithDrawer'
import { setToken } from '../api'

class CanvasErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }
  static getDerivedStateFromError(error) {
    return { error }
  }
  componentDidCatch(error, info) {
    console.error('Canvas render error contained:', error, info)
  }
  render() {
    if (this.state.error) {
      return (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '2rem', textAlign: 'center', background: 'var(--bg, #0b0e14)', color: 'var(--text, #f8fafc)' }}>
          <div style={{ width: 48, height: 48, borderRadius: '50%', background: 'rgba(239, 68, 68, 0.15)', color: '#ef4444', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 16, fontSize: 24 }}>
            ⚠
          </div>
          <h3 style={{ margin: '0 0 8px', fontSize: 18, fontWeight: 600 }}>Canvas Render Interrupted</h3>
          <p style={{ margin: '0 0 16px', color: 'var(--muted, #8492a6)', maxWidth: 460, fontSize: 13, lineHeight: 1.5 }}>
            A node or edge failed to render properly. Your workflow data is safe.
          </p>
          <div style={{ padding: '8px 14px', borderRadius: 6, background: 'rgba(239, 68, 68, 0.08)', border: '1px solid rgba(239, 68, 68, 0.25)', color: '#fca5a5', fontFamily: 'monospace', fontSize: 12, marginBottom: 16, maxWidth: 500, overflowX: 'auto' }}>
            {this.state.error?.message || String(this.state.error)}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button type="button" className="primary" onClick={() => this.setState({ error: null })}>
              Retry Canvas
            </button>
            <button type="button" className="ghost" onClick={() => window.location.reload()}>
              Reload Editor
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

export default function WorkflowEditorPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const workflow = useWorkflowStore(s => s.workflow)
  const loading = useWorkflowStore(s => s.loading)
  const error = useWorkflowStore(s => s.error)
  const executionError = useExecutionStore(s => s.error)
  const activeError = error || executionError
  const load = useWorkflowStore(s => s.load)
  const sidebarOpen = useUiStore(s => s.sidebarOpen)
  const toggleSidebar = useUiStore(s => s.toggleSidebar)
  const closeSidebar = useUiStore(s => s.closeSidebar)
  const historyDrawerOpen = useUiStore(s => s.historyDrawerOpen)
  const closeHistoryDrawer = useUiStore(s => s.closeHistoryDrawer)
  const hasExecution = useExecutionStore(s => !!s.executionId)
  const [localError, setLocalError] = useState(null)
  const [debuggerOpen, setDebuggerOpen] = useState(false)
  const [smithOpen, setSmithOpen] = useState(false)

  const handleSetDebuggerOpen = (val) => {
    setDebuggerOpen((prev) => {
      const next = typeof val === 'function' ? val(prev) : val
      if (next) {
        closeSidebar()
        closeHistoryDrawer()
        setSmithOpen(false)
      }
      return next
    })
  }

  const handleToggleSidebar = () => {
    if (debuggerOpen) setDebuggerOpen(false)
    if (smithOpen) setSmithOpen(false)
    toggleSidebar()
  }

  useEffect(() => {
    if (!id) return
    // Ensure nodes panel is closed so workflow opens clean and full in fit view
    useUiStore.getState().closeSidebar()
    // If switching workflows with unsaved changes, guard
    if (workflow && workflow.id !== id && isDirty()) {
      if (!confirmDiscard()) {
        navigate(`/workflows/${workflow.id}`, { replace: true })
        return
      }
    }
    setLocalError(null)
    load(id).catch(e => setLocalError(e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  // Also ensure canvas is visible even if store still loading
  if (loading && !workflow) return <div className="center-message">Loading workflow…</div>
  if (localError) {
    return (
      <div className="page">
        <PageHeader title="Workflow" description={id} />
        <div className="banner-inline err">{localError} <button className="ghost" onClick={() => navigate('/workflows')}>Back to list</button></div>
      </div>
    )
  }
  if (error && !workflow) {
    return (
      <div className="page">
        <div className="banner err">{typeof error === 'object' && error !== null ? (error.message || JSON.stringify(error)) : error}</div>
        <button className="ghost" onClick={() => navigate('/workflows')}>Back to Workflows</button>
      </div>
    )
  }

  // If loaded workflow id mismatch (still loading next), show loading
  if (workflow && workflow.id !== id) return <div className="center-message">Switching workflow…</div>

  return (
    <div className="workflow-editor-page">
      <div className="workflow-editor-shell">
        <TopBar
          onBack={() => {
            if (isDirty() && !confirmDiscard()) return
            navigate('/workflows')
          }}
          debuggerOpen={debuggerOpen}
          setDebuggerOpen={handleSetDebuggerOpen}
          hasExecution={hasExecution}
          onLogout={() => { setToken(null); window.location.reload() }}
          onOpenHistory={() => {
            if (debuggerOpen) setDebuggerOpen(false)
            if (smithOpen) setSmithOpen(false)
            useUiStore.getState().toggleHistoryDrawer()
          }}
          onOpenApprovals={() => navigate('/approvals')}
          onOpenTemplates={() => navigate('/templates')}
          onOpenEnv={() => navigate('/variables')}
          onOpenTests={() => navigate('/settings')}
          onOpenRag={() => navigate('/knowledge')}
          onOpenSmith={() => {
            if (debuggerOpen) setDebuggerOpen(false)
            closeHistoryDrawer()
            setSmithOpen(true)
          }}
        />
        {activeError && (
          <div
            className="banner-inline err"
            style={{
              margin: '8px 16px 0',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              zIndex: 10,
              boxShadow: '0 2px 12px rgba(0,0,0,0.3)',
            }}
          >
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginRight: 12 }}>
              {typeof activeError === 'object' && activeError !== null && !isValidElement(activeError)
                ? (activeError.message || (activeError.code ? `${activeError.code}: ${JSON.stringify(activeError.details || activeError)}` : JSON.stringify(activeError)))
                : String(activeError)}
            </span>
            <button
              className="ghost"
              style={{ padding: '2px 8px', fontSize: 12, flexShrink: 0 }}
              onClick={() => {
                if (error) useWorkflowStore.setState({ error: null })
                if (executionError) useExecutionStore.setState({ error: null })
              }}
            >
              Dismiss
            </button>
          </div>
        )}
        <div className="main" style={{ flex: 1, minHeight: 0, minWidth: 0, overflow: 'hidden', position: 'relative', display: 'flex' }}>
          <ReactFlowProvider>
            <div className="canvas-wrapper">
              <CanvasErrorBoundary>
                <Canvas />
              </CanvasErrorBoundary>
              <LogsPanel onOpenDebugger={() => handleSetDebuggerOpen(true)} />
            </div>
            <WorkflowHistoryDrawer />
            <div className={`nodes-palette-wrap ${sidebarOpen ? 'is-open' : 'is-closed'}`}>
              <Sidebar onOpenCredentials={() => navigate('/credentials')} />
            </div>
            {!debuggerOpen && !historyDrawerOpen && !smithOpen && (
              <button
                type="button"
                className={`sidebar-unhide-btn ${sidebarOpen ? 'is-hidden' : ''}`}
                onClick={handleToggleSidebar}
                title="Open nodes palette (search & add nodes)"
                aria-label="Open nodes palette"
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="12" y1="5" x2="12" y2="19" />
                  <line x1="5" y1="12" x2="19" y2="12" />
                </svg>
                <span>Nodes</span>
              </button>
            )}
          </ReactFlowProvider>
          {debuggerOpen && (
            <>
              <div className="debugger-backdrop" onClick={() => setDebuggerOpen(false)} />
              <div className="debugger-drawer">
                <ExecutionInspector onClose={() => setDebuggerOpen(false)} />
              </div>
            </>
          )}
          {smithOpen && (
            <SmithDrawer isOpen={smithOpen} onClose={() => setSmithOpen(false)} />
          )}
        </div>
      </div>
    </div>
  )
}


