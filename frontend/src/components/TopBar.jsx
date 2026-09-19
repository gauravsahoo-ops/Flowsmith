import { useState, useRef, useEffect } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import { useExecutionStore } from '../stores/executionStore'
import { useUiStore } from '../stores/uiStore'
import { toWorkflowJson, withDecorations } from '../mappers'
import { api } from '../api'
import WorkflowDocModal from './WorkflowDocModal'

const STATUS_LABEL = {
  idle: 'idle',
  running: 'running…',
  success: 'success',
  failed: 'failed',
  cancelled: 'cancelled',
  waiting_approval: 'waiting approval',
}

export default function TopBar({
  onBack,
  debuggerOpen,
  setDebuggerOpen,
  hasExecution,
  _onLogout,
  onOpenHistory,
  onOpenApprovals,
  onOpenTemplates,
  onOpenEnv,
  onOpenTests,
  onOpenRag,
}) {
  const workflow = useWorkflowStore((s) => s.workflow)
  const saving = useWorkflowStore((s) => s.saving)
  const savedAt = useWorkflowStore((s) => s.savedAt)
  const save = useWorkflowStore((s) => s.save)
  const setName = useWorkflowStore((s) => s.setName)
  const setWorkflowSettings = useWorkflowStore((s) => s.setWorkflowSettings)
  const toggleActive = useWorkflowStore((s) => s.toggleActive)
  const togglePinned = useWorkflowStore((s) => s.togglePinned)
  const isPinned = Boolean(workflow?.pinned || workflow?.settings?.pinned)
  const historyDrawerOpen = useUiStore((s) => s.historyDrawerOpen)
  const toggleHistoryDrawer = useUiStore((s) => s.toggleHistoryDrawer)
  const runStatus = useExecutionStore((s) => s.status)
  const running = useExecutionStore((s) => s.running)
  const run = useExecutionStore((s) => s.run)
  const cancel = useExecutionStore((s) => s.cancel)
  const error = useExecutionStore((s) => s.error)
  const [workflows, setWorkflows] = useState([])
  const [deleteError, setDeleteError] = useState(null)
  const [ioError, setIoError] = useState(null)
  const [downloading, setDownloading] = useState(false)
  const [docModalOpen, setDocModalOpen] = useState(false)
  const fileRef = useRef(null)

  async function listWorkflows() {
    setWorkflows(await api.listWorkflows())
  }

  async function handleExport() {
    const storeState = useWorkflowStore.getState()
    const wf = storeState.workflow || workflow
    if (!wf?.id && !storeState.nodes?.length) return
    setIoError(null)
    setDownloading(true)
    try {
      // First ensure pending changes are saved if possible
      if (storeState.save) {
        await storeState.save().catch(() => {})
      }

      let doc = null
      if (wf?.id) {
        try {
          doc = await api.exportWorkflow(wf.id)
        } catch (apiErr) {
          console.warn('Backend export failed, falling back to local canvas serialization', apiErr)
        }
      }

      // If backend export was unavailable or failed, serialize from live canvas state
      if (!doc || !doc.workflow) {
        const currentNodes = storeState.nodes || []
        const currentEdges = storeState.edges || []
        const payload = withDecorations(
          toWorkflowJson(wf || { id: 'wf_exported', name: 'My Workflow' }, currentNodes, currentEdges),
          {
            comments: storeState.comments || [],
            groups: storeState.groups || [],
            edgeLabels: storeState.edgeLabels || {},
          }
        )
        doc = {
          format: 'opencode-workflow',
          version: 1,
          exported_at: new Date().toISOString(),
          workflow: payload,
        }
      }

      const jsonStr = JSON.stringify(doc, null, 2)
      const blob = new Blob([jsonStr], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      const rawName = (wf?.name || 'workflow').trim()
      const safeName = rawName.replace(/[^a-zA-Z0-9_-]+/g, '_') || 'workflow'
      a.download = `${safeName}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (err) {
      setIoError(err.message || 'Failed to download workflow')
    } finally {
      setDownloading(false)
    }
  }

  async function handleSaveAsTemplate() {
    const wf = workflow
    if (!wf?.id) return
    const name = window.prompt('Template name:', wf.name || 'My template')
    if (!name) return
    const description = window.prompt('Template description (optional):', '') || ''
    try {
      const doc = await api.exportWorkflow(wf.id)
      await api.createTemplate({
        name,
        description,
        category: 'general',
        is_public: false,
        workflow_data: { ...doc, id: undefined, name: undefined },
      })
      setIoError(null)
      alert(`Saved “${name}” to your templates.`)
    } catch (err) {
      setIoError(err.message)
    }
  }

  async function handleImportFile(file) {
    setIoError(null)
    try {
      const doc = JSON.parse(await file.text())
      const imported = await api.importWorkflow(doc)
      await useWorkflowStore.getState().load(imported.id)
    } catch (err) {
      setIoError(err.message)
    }
  }

  async function handleDelete() {
    const wf = workflow
    if (!wf?.id) return
    if (!window.confirm(`Delete workflow "${wf.name}"? This cannot be undone.`)) return
    setDeleteError(null)
    try {
      if (useWorkflowStore.getState().isDirty?.()) await useWorkflowStore.getState().save()
      await useWorkflowStore.getState().deleteWorkflow(wf.id)
    } catch (err) {
      setDeleteError(err.message)
    }
  }

  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef(null)
  useEffect(() => {
    if (!menuOpen) return
    listWorkflows().catch(() => {})
    const onDoc = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setMenuOpen(false)
      }
    }
    const onKey = (e) => { if (e.key === 'Escape') setMenuOpen(false) }
    window.addEventListener('pointerdown', onDoc, true)
    window.addEventListener('touchstart', onDoc, true)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('pointerdown', onDoc, true)
      window.removeEventListener('touchstart', onDoc, true)
      window.removeEventListener('keydown', onKey)
    }
  }, [menuOpen])

  return (
    <header className="topbar topbar--workflow">
      <div className="topbar-left">
        {onBack && (
          <>
            <button
              className="ghost ghost--quiet ghost--back"
              onClick={onBack}
              title="Back to Workflows"
            >
              ← Workflows
            </button>
            <span className="topbar-sep">/</span>
          </>
        )}
        <input
          className="workflow-name"
          value={workflow?.name || ''}
          onChange={(e) => setName(e.target.value)}
          placeholder="Untitled workflow"
          maxLength={255}
          aria-label="Workflow name"
        />
        <span className="save-state">
          {error ? (
            <span className="err" title={typeof error === 'object' ? JSON.stringify(error) : error}>
              {typeof error === 'object' ? (error.message || 'Error') : error}
            </span>
          ) : saving ? (
            <span className="save-state-saving">
              <span className="save-dot save-dot-saving" />
              <span>saving…</span>
            </span>
          ) : savedAt ? (
            <span className="save-state-saved">
              <span className="save-dot save-dot-saved" />
              <span>saved</span>
            </span>
          ) : (
            <span className="save-state-unsaved">
              <span className="save-dot save-dot-unsaved" />
              <span>unsaved</span>
            </span>
          )}
        </span>
        <button className={`toggle toggle--active ${workflow?.active ? 'is-active' : ''}`} onClick={toggleActive} title={workflow?.active ? 'Active — triggers armed' : 'Inactive — triggers disarmed'}>
          <span className="toggle-dot" />
          {workflow?.active ? 'Active' : 'Inactive'}
        </button>
        <button
          className={`toggle toggle--pin ${isPinned ? 'is-pinned' : ''}`}
          onClick={togglePinned}
          title={isPinned ? 'Pinned to top — click to unpin' : 'Pin workflow to top'}
          aria-label={isPinned ? 'Unpin workflow' : 'Pin workflow to top'}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 5,
            height: 28,
            padding: '0 8px',
            borderRadius: 6,
            fontSize: 12,
            fontWeight: 500,
            cursor: 'pointer',
            border: isPinned ? '1px solid rgba(245, 158, 11, 0.45)' : '1px solid rgba(255, 255, 255, 0.12)',
            background: isPinned ? 'rgba(245, 158, 11, 0.15)' : 'rgba(255, 255, 255, 0.04)',
            color: isPinned ? '#fbbf24' : '#94a3b8',
            transition: 'all 0.15s ease',
          }}
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill={isPinned ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="12" y1="17" x2="12" y2="22" />
            <path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.89A2 2 0 0 1 15 10.77V6a3 3 0 0 0-6 0v4.77a2 2 0 0 1-1.11 1.79l-1.78.89A2 2 0 0 0 5 15.24Z" />
          </svg>
          <span>{isPinned ? 'Pinned' : 'Pin'}</span>
        </button>
      </div>

      <div className="topbar-center">
        {deleteError && <span className="err" title={deleteError}>{deleteError}</span>}
        {ioError && <span className="err" title={ioError}>{ioError}</span>}
        {runStatus && runStatus !== 'running' && (
          <span className={`run-status status-${runStatus}`}>
            <span className={`status-dot status-dot-${runStatus}`} />
            {STATUS_LABEL[runStatus] || runStatus}
          </span>
        )}
      </div>

      <div className="topbar-right">
        {setDebuggerOpen && (
          <button
            className={`ghost ghost--quiet ${debuggerOpen ? 'active' : ''}`}
            onClick={() => setDebuggerOpen((v) => !v)}
            title="Toggle Console (timeline, step payloads, and retry)"
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="4 17 10 11 4 5" />
              <line x1="12" y1="19" x2="20" y2="19" />
            </svg>
            <span>Console</span>
            {hasExecution && !debuggerOpen && (
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#38bdf8', display: 'inline-block' }} />
            )}
          </button>
        )}
        <button
          className="ghost ghost--quiet"
          disabled={saving || !workflow?.id}
          onClick={() => save().catch(() => {})}
          title="Save (auto-saves on change)"
          style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
            <polyline points="17 21 17 13 7 13 7 21" />
            <polyline points="7 3 7 8 15 8" />
          </svg>
          <span>{saving ? 'Saving…' : 'Save'}</span>
        </button>
        <button
          className="ghost ghost--quiet"
          disabled={!workflow?.id}
          onClick={() => setDocModalOpen(true)}
          title="View & Export Workflow Architecture Blueprint & Docs"
          aria-label="Workflow Architecture"
          style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
          </svg>
          <span>Docs</span>
        </button>
        <button
          className="ghost ghost--quiet"
          disabled={downloading || (!workflow?.id && !useWorkflowStore.getState().nodes?.length)}
          onClick={handleExport}
          title="Download workflow JSON file to your computer"
          aria-label="Download workflow"
          style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          <span>{downloading ? 'Downloading…' : 'Download'}</span>
        </button>
        <button
          className={`ghost ghost--quiet ${historyDrawerOpen ? 'active' : ''}`}
          onClick={onOpenHistory || toggleHistoryDrawer}
          title="Workflow history to view and restore previous versions of your workflows"
          aria-label="Workflow history"
          style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
        </button>

        {running ? (
          <button className="danger danger--sm" onClick={cancel} aria-label="Cancel run">
            Cancel
          </button>
        ) : (
          <button
            className="primary primary--run"
            disabled={!workflow?.id}
            onClick={() => run(workflow.id)}
            aria-label="Run workflow"
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
              <polygon points="5 3 19 12 5 21 5 3" />
            </svg>
            <span>Run</span>
          </button>
        )}

        <div className="topbar-menu-wrap" ref={menuRef}>
          <button className="ghost ghost--icon" onClick={() => setMenuOpen((v) => !v)} aria-haspopup="menu" aria-expanded={menuOpen} aria-label="More actions">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="1.5" />
              <circle cx="12" cy="5" r="1.5" />
              <circle cx="12" cy="19" r="1.5" />
            </svg>
          </button>
          {menuOpen && (
            <div className="topbar-menu" role="menu">
              <button role="menuitem" onClick={() => { setMenuOpen(false); setDocModalOpen(true); }} disabled={!workflow?.id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                  <line x1="16" y1="13" x2="8" y2="13" />
                  <line x1="16" y1="17" x2="8" y2="17" />
                </svg>
                <span>Architecture & Docs</span>
              </button>
              <button role="menuitem" onClick={() => { setMenuOpen(false); togglePinned(); }} disabled={!workflow?.id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill={isPinned ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: isPinned ? '#fbbf24' : 'currentColor' }}>
                  <line x1="12" y1="17" x2="12" y2="22" />
                  <path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.89A2 2 0 0 1 15 10.77V6a3 3 0 0 0-6 0v4.77a2 2 0 0 1-1.11 1.79l-1.78.89A2 2 0 0 0 5 15.24Z" />
                </svg>
                <span>{isPinned ? 'Unpin Workflow' : 'Pin to Top'}</span>
              </button>
              <button role="menuitem" onClick={() => { setMenuOpen(false); handleExport(); }} disabled={!workflow?.id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="7 10 12 15 17 10" />
                  <line x1="12" y1="15" x2="12" y2="3" />
                </svg>
                <span>Download Workflow (JSON)</span>
              </button>
              <button role="menuitem" onClick={() => { setMenuOpen(false); fileRef.current?.click(); }}>Import Workflow</button>
              <button role="menuitem" onClick={() => { setMenuOpen(false); handleSaveAsTemplate(); }} disabled={!workflow?.id}>Save as Template</button>
              <div className="ctx-sep" />
              <div style={{ padding: '8px 12px', display: 'flex', flexDirection: 'column', gap: 8 }} onClick={(e) => e.stopPropagation()}>
                <span className="hint" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5 }}>Workflow settings</span>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: 12 }}>
                  <span>Timeout (seconds, 0 = none)</span>
                  <input
                    type="number" min={0} max={86400}
                    value={workflow?.settings?.timeout_seconds ?? 0}
                    onChange={(e) => setWorkflowSettings({ timeout_seconds: Math.max(0, Number(e.target.value) || 0) })}
                    style={{ width: '100%' }}
                  />
                </label>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: 12 }}>
                  <span>Max parallelism (1–32)</span>
                  <input
                    type="number" min={1} max={32}
                    value={workflow?.settings?.max_parallelism ?? 8}
                    onChange={(e) => setWorkflowSettings({ max_parallelism: Math.min(32, Math.max(1, Number(e.target.value) || 8)) })}
                    style={{ width: '100%' }}
                  />
                </label>
                <label className="check" style={{ fontSize: 12 }}>
                  <input
                    type="checkbox"
                    checked={Boolean(workflow?.settings?.save_execution_progress)}
                    onChange={(e) => setWorkflowSettings({ save_execution_progress: e.target.checked })}
                  />
                  Save execution progress
                </label>
                <label className="check" style={{ fontSize: 12 }}>
                  <input
                    type="checkbox"
                    checked={Boolean(workflow?.settings?.error_workflow_id)}
                    onChange={(e) => setWorkflowSettings({ error_workflow_id: e.target.checked ? 'default' : null })}
                  />
                  Route failure to error workflow
                </label>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: 12 }}>
                  <span>Error workflow</span>
                  <select
                    value={workflow?.settings?.on_error_workflow_id || ''}
                    onChange={(e) => setWorkflowSettings({ on_error_workflow_id: e.target.value || null })}
                    style={{ width: '100%' }}
                  >
                    <option value="">None</option>
                    {(workflows || []).filter((w) => w.id !== workflow?.id).map((w) => (
                      <option key={w.id} value={w.id}>{w.name || w.id}</option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="ctx-sep" />
              <button role="menuitem" onClick={() => { setMenuOpen(false); onOpenTests(); }}>Tests</button>
              <button role="menuitem" onClick={() => { setMenuOpen(false); onOpenRag(); }}>Knowledge & RAG</button>
              <button role="menuitem" onClick={() => { setMenuOpen(false); onOpenEnv(); }}>Variables</button>
              <button role="menuitem" onClick={() => { setMenuOpen(false); onOpenApprovals(); }}>Approvals</button>
              <button role="menuitem" onClick={() => { setMenuOpen(false); onOpenTemplates(); }}>Templates</button>
              <div className="ctx-sep" />
              <button role="menuitem" onClick={() => { setMenuOpen(false); toggleHistoryDrawer(); }}>Workflow History</button>
              <button role="menuitem" onClick={() => { setMenuOpen(false); if (onOpenHistory && !historyDrawerOpen) onOpenHistory(); else window.open('/executions', '_blank'); }}>Execution Logs</button>
              <div className="ctx-sep" />
              <button role="menuitem" className="ctx-danger" onClick={() => { setMenuOpen(false); handleDelete(); }} disabled={!workflow?.id}>Delete Workflow</button>
            </div>
          )}
        </div>

        <input
          ref={fileRef}
          type="file"
          accept="application/json,.json"
          style={{ display: 'none' }}
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) handleImportFile(f)
            e.target.value = ''
          }}
        />

        <WorkflowDocModal
          isOpen={docModalOpen}
          onClose={() => setDocModalOpen(false)}
          workflowId={workflow?.id}
          workflowName={workflow?.name}
        />
      </div>
      {running && <div className="execution-progress-beam" />}
    </header>
  )
}
