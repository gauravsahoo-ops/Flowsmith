import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useWorkflowStore, confirmDiscard } from '../stores/workflowStore'
import { useExecutionStore } from '../stores/executionStore'
import { useUiStore } from '../stores/uiStore'
import { useBrandingStore } from '../stores/brandingStore'
import FlowsmithBrandMark from './FlowsmithBrandMark'
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
  onImportWorkflow,
  debuggerOpen,
  setDebuggerOpen,
  hasExecution,
  _onLogout,
  onOpenHistory,
  onOpenExecutions,
  onOpenApprovals,
  onOpenTemplates,
  onOpenEnv,
  onOpenTests,
  onOpenRag,
  onOpenSmith,
  onOpenAIChat,
  onOpenAICopilot,
}) {
  const navigate = useNavigate()
  const workflow = useWorkflowStore((s) => s.workflow)
  const saving = useWorkflowStore((s) => s.saving)
  const savedAt = useWorkflowStore((s) => s.savedAt)
  const save = useWorkflowStore((s) => s.save)
  const saveError = useWorkflowStore((s) => s.error)
  const isDirty = useWorkflowStore((s) => s._dirty)
  const autoSave = useWorkflowStore((s) => s.autoSave)
  const setAutoSave = useWorkflowStore((s) => s.setAutoSave)
  const setName = useWorkflowStore((s) => s.setName)
  const setWorkflowSettings = useWorkflowStore((s) => s.setWorkflowSettings)
  const toggleActive = useWorkflowStore((s) => s.toggleActive)
  const setActive = useWorkflowStore((s) => s.setActive)
  const togglePinned = useWorkflowStore((s) => s.togglePinned)
  const isPinned = Boolean(workflow?.pinned || workflow?.settings?.pinned)
  const historyDrawerOpen = useUiStore((s) => s.historyDrawerOpen)
  const toggleHistoryDrawer = useUiStore((s) => s.toggleHistoryDrawer)
  const runStatus = useExecutionStore((s) => s.status)
  const running = useExecutionStore((s) => s.running)
  const run = useExecutionStore((s) => s.run)
  const cancel = useExecutionStore((s) => s.cancel)
  const [workflows, setWorkflows] = useState([])
  const [ioError, setIoError] = useState(null)
  const [downloading, setDownloading] = useState(false)
  const [docModalOpen, setDocModalOpen] = useState(false)
  const [activating, setActivating] = useState(false)
  const isActivatingRef = useRef(false)
  const wasRunningRef = useRef(false)
  const fileRef = useRef(null)

  // Branding store for default/custom logo
  const appName = useBrandingStore((s) => s.appName) || 'Flowsmith'
  const logoUrl = useBrandingStore((s) => s.logoUrl)
  const logoData = useBrandingStore((s) => s.logoData)
  const logoSrc = logoData || logoUrl

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

  async function handleDuplicate() {
    const wf = workflow
    if (!wf?.id) return
    try {
      const duplicated = await api.duplicateWorkflow(wf.id)
      if (duplicated?.id) {
        window.location.href = `/workflows/${duplicated.id}`
      }
    } catch (err) {
      setIoError(err.message || 'Failed to duplicate workflow')
      alert(`Duplicate failed: ${err.message || 'Unknown error'}`)
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
      if (typeof isDirty === 'function' && isDirty() && typeof confirmDiscard === 'function' && !confirmDiscard()) {
        return
      }
      const text = await file.text()
      const doc = JSON.parse(text)
      const imported = await api.importWorkflow(doc)
      if (imported?.id) {
        if (onImportWorkflow) {
          onImportWorkflow(imported)
        } else {
          window.location.href = `/workflows/${imported.id}`
        }
      }
    } catch (err) {
      const msg = err.message || 'Failed to import workflow'
      setIoError(msg)
      alert(`Import failed: ${msg}`)
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

  const handleToggleActive = async () => {
    await toggleActive()
    if (workflow?.id) {
      try {
        const { data } = await api.listExecutions({ workflowId: workflow.id, pageSize: 2 })
        if (Array.isArray(data) && data[0]?.id) {
          useExecutionStore.getState().load(data[0].id).catch(() => {})
        }
      } catch {}
    }
  }

  // Auto-activate workflow when an activation run completes successfully
  useEffect(() => {
    if (running) {
      wasRunningRef.current = true
      return
    }

    if (wasRunningRef.current && !running) {
      wasRunningRef.current = false
      if (isActivatingRef.current) {
        isActivatingRef.current = false
        setActivating(false)

        if (runStatus === 'success' && workflow?.id) {
          // Execution succeeded! Automatically turn the workflow on (Inactive -> Active)
          setActive(true).then(() => {
            // Reload execution to keep the canvas live
            api.listExecutions({ workflowId: workflow.id, pageSize: 2 }).then(({ data }) => {
              if (Array.isArray(data) && data[0]?.id) {
                useExecutionStore.getState().load(data[0].id).catch(() => {})
              }
            }).catch(() => {})
          }).catch((err) => {
            console.error('Failed to auto-activate workflow:', err)
          })
        } else if (runStatus === 'failed') {
          // Execution failed; open console so user can inspect error
          if (setDebuggerOpen) {
            setDebuggerOpen(true)
          }
        }
      }
    }
  }, [running, runStatus, workflow?.id, setActive, setDebuggerOpen])

  const handleActivate = async () => {
    if (!workflow?.id) return
    if (useWorkflowStore.getState()._dirty) {
      try {
        await save()
      } catch (err) {
        const msg = err?.message || 'Save failed'
        const readable = msg.includes('413')
          ? 'Workflow payload too large (HTTP 413). Check node file uploads or server proxy body size limit.'
          : msg
        alert(`Cannot activate: Workflow save failed (${readable}). Please fix the error before running.`)
        return
      }
    }
    isActivatingRef.current = true
    setActivating(true)
    run(workflow.id)
  }

  const handleRun = async () => {
    if (!workflow?.id) return
    if (useWorkflowStore.getState()._dirty) {
      try {
        await save()
      } catch (err) {
        const msg = err?.message || 'Save failed'
        const readable = msg.includes('413')
          ? 'Workflow payload too large (HTTP 413). Check node file uploads or server proxy body size limit.'
          : msg
        alert(`Cannot run: Workflow save failed (${readable}). Please fix the error before running.`)
        return
      }
    }
    run(workflow.id)
  }

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
          {saveError ? (
            <span
              className="err"
              title={typeof saveError === 'object' ? (saveError.message || JSON.stringify(saveError)) : saveError}
            >
              Save error
            </span>
          ) : saving ? (
            <span className="save-state-saving">
              <span className="save-dot save-dot-saving" />
              <span>saving…</span>
            </span>
          ) : isDirty ? (
            <span className="save-state-unsaved" title="Unsaved changes — click Save or press Ctrl+S">
              <span className="save-dot save-dot-unsaved" />
              <span>unsaved</span>
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
        <button className={`toggle toggle--active ${workflow?.active ? 'is-active' : ''}`} onClick={handleToggleActive} title={workflow?.active ? 'Active — triggers armed' : 'Inactive — triggers disarmed'}>
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
        {ioError && <span className="err" title={ioError}>{ioError}</span>}
        {running ? (
          <span className="run-status status-running">
            <span className="status-dot status-dot-running" />
            {activating ? 'activating…' : 'running…'}
          </span>
        ) : runStatus ? (
          <span className={`run-status status-${runStatus}`}>
            <span className={`status-dot status-dot-${runStatus}`} />
            {STATUS_LABEL[runStatus] || runStatus}
          </span>
        ) : null}
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
          className={`ghost ghost--quiet ${isDirty ? 'btn-save-dirty' : ''}`}
          disabled={saving || !workflow?.id}
          onClick={() => {
            save().catch((err) => {
              const msg = err?.message || 'Save failed'
              const readable = msg.includes('413')
                ? 'Workflow payload too large (HTTP 413). Check node file uploads or server proxy body size limit.'
                : msg
              alert(`Save failed: ${readable}`)
            })
          }}
          title={isDirty ? "Save workflow (Ctrl+S) — Unsaved changes" : "Save workflow (Ctrl+S)"}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
            <polyline points="17 21 17 13 7 13 7 21" />
            <polyline points="7 3 7 8 15 8" />
          </svg>
          <span>{saving ? 'Saving…' : 'Save'}</span>
          {isDirty && !saving && (
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#38bdf8', display: 'inline-block' }} />
          )}
        </button>
        <button
          className={`ghost ghost--quiet ${docModalOpen ? 'active' : ''}`}
          disabled={!workflow?.id}
          onClick={() => setDocModalOpen((v) => !v)}
          title={docModalOpen ? 'Close Workflow Architecture & Docs' : 'View & Export Workflow Architecture Blueprint & Docs'}
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
        <button
          className="ghost ghost--quiet topbar-smith-btn"
          onClick={onOpenSmith || onOpenAIChat || onOpenAICopilot}
          title="Smith — AI Copilot & Automation Assistant"
          aria-label="Smith AI Assistant"
        >
          {logoSrc ? (
            <img
              src={logoSrc}
              alt={appName}
              style={{ width: 16, height: 16, objectFit: 'contain', borderRadius: 3, flexShrink: 0 }}
            />
          ) : (
            <FlowsmithBrandMark size={16} variant="badge" />
          )}
          <span>Smith</span>
        </button>

        {running ? (
          <button
            className="danger danger--sm"
            onClick={cancel}
            aria-label={runStatus === 'cancelling' ? 'Force cancel' : 'Cancel'}
            title={runStatus === 'cancelling' ? 'Click to force cancel immediately' : 'Cancel'}
          >
            {runStatus === 'cancelling' ? 'Force Cancel' : activating ? 'Cancel Activation' : 'Cancel'}
          </button>
        ) : (
          <button
            className={`primary primary--run ${workflow?.active ? 'is-active' : ''}`}
            disabled={!workflow?.id}
            onClick={workflow?.active ? handleRun : handleActivate}
            aria-label={workflow?.active ? 'Run workflow' : 'Activate workflow'}
            title={
              workflow?.active
                ? 'Workflow is active — click to run manually'
                : 'Activate workflow — runs once to verify and automatically turns active on success'
            }
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
              <polygon points="5 3 19 12 5 21 5 3" />
            </svg>
            <span>{workflow?.active ? 'Run' : 'Activate'}</span>
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
              <button role="menuitem" onClick={() => { setMenuOpen(false); setDocModalOpen(true); }} disabled={!workflow?.id}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                  <line x1="16" y1="13" x2="8" y2="13" />
                  <line x1="16" y1="17" x2="8" y2="17" />
                </svg>
                <span>Architecture & Docs</span>
              </button>
              <button role="menuitem" onClick={() => { setMenuOpen(false); togglePinned(); }} disabled={!workflow?.id}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill={isPinned ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: isPinned ? '#fbbf24' : 'currentColor' }}>
                  <line x1="12" y1="17" x2="12" y2="22" />
                  <path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.89A2 2 0 0 1 15 10.77V6a3 3 0 0 0-6 0v4.77a2 2 0 0 1-1.11 1.79l-1.78.89A2 2 0 0 0 5 15.24Z" />
                </svg>
                <span>{isPinned ? 'Unpin Workflow' : 'Pin to Top'}</span>
              </button>
              <button role="menuitem" onClick={() => { setMenuOpen(false); handleDuplicate(); }} disabled={!workflow?.id}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                  <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                </svg>
                <span>Duplicate Workflow</span>
              </button>
              <button role="menuitem" onClick={() => { setMenuOpen(false); handleExport(); }} disabled={!workflow?.id}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="7 10 12 15 17 10" />
                  <line x1="12" y1="15" x2="12" y2="3" />
                </svg>
                <span>Download Workflow (JSON)</span>
              </button>
              <button role="menuitem" onClick={() => { setMenuOpen(false); fileRef.current?.click(); }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="17 8 12 3 7 8" />
                  <line x1="12" y1="3" x2="12" y2="15" />
                </svg>
                <span>Import Workflow</span>
              </button>
              <button role="menuitem" onClick={() => { setMenuOpen(false); handleSaveAsTemplate(); }} disabled={!workflow?.id}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect width="18" height="18" x="3" y="3" rx="2" />
                  <line x1="3" y1="9" x2="21" y2="9" />
                  <line x1="9" y1="21" x2="9" y2="9" />
                </svg>
                <span>Save as Template</span>
              </button>
              <div className="ctx-sep" />
              <div className="topbar-menu-section" onClick={(e) => e.stopPropagation()}>
                <span className="topbar-menu-section-title">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="3" />
                    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
                  </svg>
                  Workflow Settings
                </span>
                <label className="topbar-menu-field">
                  <span>Timeout (seconds, 0 = none)</span>
                  <input
                    type="number" min={0} max={86400}
                    className="topbar-menu-input"
                    value={workflow?.settings?.timeout_seconds ?? 0}
                    onChange={(e) => setWorkflowSettings({ timeout_seconds: Math.max(0, Number(e.target.value) || 0) })}
                  />
                </label>
                <label className="topbar-menu-field">
                  <span>Max parallelism (1–32)</span>
                  <input
                    type="number" min={1} max={32}
                    className="topbar-menu-input"
                    value={workflow?.settings?.max_parallelism ?? 8}
                    onChange={(e) => setWorkflowSettings({ max_parallelism: Math.min(32, Math.max(1, Number(e.target.value) || 8)) })}
                  />
                </label>
                <label className="topbar-menu-check">
                  <input
                    type="checkbox"
                    checked={autoSave}
                    onChange={(e) => setAutoSave(e.target.checked)}
                  />
                  <span>Auto-save workflow changes (disabled by default)</span>
                </label>
                <label className="topbar-menu-check">
                  <input
                    type="checkbox"
                    checked={Boolean(workflow?.settings?.save_execution_progress)}
                    onChange={(e) => setWorkflowSettings({ save_execution_progress: e.target.checked })}
                  />
                  <span>Save execution progress</span>
                </label>
                <label className="topbar-menu-check">
                  <input
                    type="checkbox"
                    checked={Boolean(workflow?.settings?.error_workflow_id)}
                    onChange={(e) => setWorkflowSettings({ error_workflow_id: e.target.checked ? 'default' : null })}
                  />
                  <span>Route failure to error workflow</span>
                </label>
                <label className="topbar-menu-field">
                  <span>Error workflow</span>
                  <select
                    className="glass-select"
                    value={workflow?.settings?.on_error_workflow_id || ''}
                    onChange={(e) => setWorkflowSettings({ on_error_workflow_id: e.target.value || null })}
                    style={{ width: '100%', height: 32 }}
                  >
                    <option value="">None</option>
                    {(workflows || []).filter((w) => w.id !== workflow?.id).map((w) => (
                      <option key={w.id} value={w.id}>{w.name || w.id}</option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="ctx-sep" />
              <button role="menuitem" onClick={() => { setMenuOpen(false); onOpenTests(); }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M14.5 2v6.5L19 17a2.5 2.5 0 0 1-2.2 3.8H7.2A2.5 2.5 0 0 1 5 17l4.5-8.5V2" />
                  <path d="M8.5 2h7" />
                  <path d="M7 16h10" />
                </svg>
                <span>Tests</span>
              </button>
              <button role="menuitem" onClick={() => { setMenuOpen(false); onOpenRag(); }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z" />
                  <path d="M6 6h10" />
                  <path d="M6 10h10" />
                </svg>
                <span>Knowledge & RAG</span>
              </button>
              <button role="menuitem" onClick={() => { setMenuOpen(false); onOpenEnv(); }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="16 18 22 12 16 6" />
                  <polyline points="8 6 2 12 8 18" />
                </svg>
                <span>Variables</span>
              </button>
              <button role="menuitem" onClick={() => { setMenuOpen(false); onOpenApprovals(); }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                  <polyline points="9 12 11 14 15 10" />
                </svg>
                <span>Approvals</span>
              </button>
              <button role="menuitem" onClick={() => { setMenuOpen(false); onOpenTemplates(); }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect width="7" height="7" x="3" y="3" rx="1" />
                  <rect width="7" height="7" x="14" y="3" rx="1" />
                  <rect width="7" height="7" x="14" y="14" rx="1" />
                  <rect width="7" height="7" x="3" y="14" rx="1" />
                </svg>
                <span>Templates</span>
              </button>
              <div className="ctx-sep" />
              <button
                role="menuitem"
                onClick={() => {
                  setMenuOpen(false)
                  if (onOpenHistory) {
                    onOpenHistory()
                  } else {
                    toggleHistoryDrawer()
                  }
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10" />
                  <polyline points="12 6 12 12 16 14" />
                </svg>
                <span>Workflow History</span>
              </button>
              <button
                role="menuitem"
                onClick={() => {
                  setMenuOpen(false)
                  if (onOpenExecutions) {
                    onOpenExecutions()
                  } else {
                    navigate(workflow?.id ? `/executions?workflow_id=${workflow.id}` : '/executions')
                  }
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="4 17 10 11 4 5" />
                  <line x1="12" y1="19" x2="20" y2="19" />
                </svg>
                <span>Execution Logs</span>
              </button>
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
