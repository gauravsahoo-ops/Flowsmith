import { useState, useEffect, useRef } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import { useUiStore } from '../stores/uiStore'
import { api } from '../api'

function formatDate(dateStr) {
  if (!dateStr) return 'just now'
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return String(dateStr)
  return d.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export default function WorkflowHistoryDrawer() {
  const workflow = useWorkflowStore((s) => s.workflow)
  const rawVersions = useWorkflowStore((s) => s.versions)
  const versions = Array.isArray(rawVersions) ? rawVersions : []
  const listVersions = useWorkflowStore((s) => s.listVersions)
  const rollbackVersion = useWorkflowStore((s) => s.rollbackVersion)
  const previewVersion = useWorkflowStore((s) => s.previewVersion)
  const setPreviewVersion = useWorkflowStore((s) => s.setPreviewVersion)
  const exitPreview = useWorkflowStore((s) => s.exitPreview)

  const historyDrawerOpen = useUiStore((s) => s.historyDrawerOpen)
  const closeHistoryDrawer = useUiStore((s) => s.closeHistoryDrawer)
  const historyTab = useUiStore((s) => s.historyTab)
  const setHistoryTab = useUiStore((s) => s.setHistoryTab)

  const [loading, setLoading] = useState(false)
  const [timelineEvents, setTimelineEvents] = useState([])
  const [timelineLoading, setTimelineLoading] = useState(false)
  const [activeMenuVersion, setActiveMenuVersion] = useState(null)
  const [versionsExpanded, setVersionsExpanded] = useState(true)
  const [restoring, setRestoring] = useState(false)
  const [error, setError] = useState(null)

  const menuRef = useRef(null)

  // Refresh versions list when drawer opens
  useEffect(() => {
    if (!historyDrawerOpen || !workflow?.id) return
    setLoading(true)
    listVersions(workflow.id)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [historyDrawerOpen, workflow?.id, listVersions])

  // Load activation history when switching to timeline tab
  useEffect(() => {
    if (!historyDrawerOpen || !workflow?.id || historyTab !== 'timeline') return
    setTimelineLoading(true)
    api.getActivationHistory(workflow.id)
      .then((res) => {
        const list = Array.isArray(res) ? res : (res?.data || [])
        setTimelineEvents(list)
      })
      .catch((e) => setError(e.message))
      .finally(() => setTimelineLoading(false))
  }, [historyDrawerOpen, workflow?.id, historyTab])

  // Close context menu on click outside
  useEffect(() => {
    if (!activeMenuVersion) return
    const handleClick = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setActiveMenuVersion(null)
      }
    }
    window.addEventListener('pointerdown', handleClick, true)
    window.addEventListener('touchstart', handleClick, true)
    return () => {
      window.removeEventListener('pointerdown', handleClick, true)
      window.removeEventListener('touchstart', handleClick, true)
    }
  }, [activeMenuVersion])

  if (!historyDrawerOpen) return null

  const handleRestore = async (verNum) => {
    if (!verNum) return
    if (!window.confirm(`Restore workflow to version ${verNum}? Current unsaved edits will be replaced.`)) return
    setRestoring(true)
    setError(null)
    try {
      await rollbackVersion(workflow.id, verNum)
      setActiveMenuVersion(null)
    } catch (err) {
      setError(`Failed to restore: ${err.message}`)
    } finally {
      setRestoring(false)
    }
  }

  const handleClone = async (ver) => {
    try {
      const detail = await api.getVersion(workflow.id, ver.version)
      const data = detail.data?.data || detail.data
      if (!data) return
      const newId = crypto.randomUUID()
      const payload = {
        ...data,
        id: newId,
        name: `${data.name || workflow.name} (from v${ver.version})`,
      }
      await api.createWorkflow(payload)
      window.open(`/workflows/${newId}`, '_blank')
    } catch (err) {
      alert(`Clone failed: ${err.message}`)
    }
  }

  const handleDownload = async (ver) => {
    try {
      const detail = await api.getVersion(workflow.id, ver.version)
      const data = detail.data?.data || detail.data
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${workflow.name || 'workflow'}-v${ver.version}.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      alert(`Download failed: ${err.message}`)
    }
  }

  // Active version is the one marked is_active, or the current saved workflow.version if active
  const activeVersionNum = workflow?.active ? (versions.find((v) => v.is_active)?.version || workflow.version) : null

  return (
    <aside className="history-drawer" aria-label="Workflow History">
      {/* Header & Tabs */}
      <div className="history-drawer-header">
        <div className="history-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={historyTab === 'versions'}
            className={`history-tab-btn ${historyTab === 'versions' ? 'is-active' : ''}`}
            onClick={() => setHistoryTab('versions')}
          >
            Versions
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={historyTab === 'timeline'}
            className={`history-tab-btn ${historyTab === 'timeline' ? 'is-active' : ''}`}
            onClick={() => setHistoryTab('timeline')}
          >
            Active Timeline
          </button>
        </div>
        <button
          type="button"
          className="history-drawer-close"
          onClick={closeHistoryDrawer}
          title="Close History Panel"
          aria-label="Close History Panel"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>

      {error && (
        <div className="history-drawer-err">
          <span>{error}</span>
          <button type="button" onClick={() => setError(null)}>Dismiss</button>
        </div>
      )}

      {/* Tab 1: Versions */}
      {historyTab === 'versions' && (
        <div className="history-drawer-body">
          {/* Current changes card */}
          <div
            className={`history-item history-item--current ${!previewVersion ? 'is-selected' : ''}`}
            onClick={() => exitPreview()}
            role="button"
            tabIndex={0}
          >
            <div className="history-item-dot dot-current" title="Current draft" />
            <div className="history-item-info">
              <div className="history-item-title">Current changes</div>
              <div className="history-item-subtitle">
                {formatDate(workflow?.updated_at || new Date())}
              </div>
            </div>
            <div className="history-item-badge">Draft</div>
          </div>

          {/* Collapsible header for version list */}
          <div
            className="history-versions-header"
            onClick={() => setVersionsExpanded(!versionsExpanded)}
            role="button"
            tabIndex={0}
          >
            <svg
              className={`history-chevron ${versionsExpanded ? 'is-open' : ''}`}
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
            >
              <polyline points="9 18 15 12 9 6" />
            </svg>
            <span>{versions.length} {versions.length === 1 ? 'version' : 'versions'}</span>
          </div>

          {/* Versions list */}
          {versionsExpanded && (
            <div className="history-versions-list">
              {loading && versions.length === 0 ? (
                <div className="history-empty">Loading versions...</div>
              ) : versions.length === 0 ? (
                <div className="history-empty">No previous versions saved yet.</div>
              ) : (
                versions.map((ver) => {
                  const isPreviewing = previewVersion?.version === ver.version
                  const isActive = ver.is_active || ver.version === activeVersionNum
                  return (
                    <div
                      key={ver.id || ver.version}
                      className={`history-item ${isPreviewing ? 'is-selected' : ''} ${isActive ? 'is-active-ver' : ''}`}
                      onClick={() => setPreviewVersion(ver.version)}
                      role="button"
                      tabIndex={0}
                    >
                      <div
                        className={`history-item-dot ${isActive ? 'dot-active' : 'dot-saved'}`}
                        title={isActive ? 'Active version' : `Version ${ver.version}`}
                      />
                      <div className="history-item-info">
                        <div className="history-item-title">
                          Version {ver.version} {isActive && <span className="active-tag">(Active)</span>}
                        </div>
                        <div className="history-item-subtitle">
                          {ver.author_name || ver.author_email ? `${ver.author_name || ver.author_email}, ` : ''}
                          {formatDate(ver.updated_at)}
                        </div>
                      </div>

                      {/* Action Menu (⋮) */}
                      <div className="history-item-menu-wrap" onClick={(e) => e.stopPropagation()}>
                        <button
                          type="button"
                          className="history-item-menu-btn"
                          onClick={() => setActiveMenuVersion(activeMenuVersion === ver.version ? null : ver.version)}
                          aria-label={`Options for version ${ver.version}`}
                        >
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                            <circle cx="12" cy="5" r="2" />
                            <circle cx="12" cy="12" r="2" />
                            <circle cx="12" cy="19" r="2" />
                          </svg>
                        </button>
                        {activeMenuVersion === ver.version && (
                          <div className="history-menu-dropdown" ref={menuRef}>
                            <button
                              type="button"
                              onClick={() => {
                                setPreviewVersion(ver.version)
                                setActiveMenuVersion(null)
                              }}
                            >
                              Preview version
                            </button>
                            <button
                              type="button"
                              disabled={restoring}
                              onClick={() => handleRestore(ver.version)}
                            >
                              Restore version
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                handleClone(ver)
                                setActiveMenuVersion(null)
                              }}
                            >
                              Clone as new workflow
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                handleDownload(ver)
                                setActiveMenuVersion(null)
                              }}
                            >
                              Export JSON
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          )}

          <div className="history-footer-hint">
            Workflow history is saved automatically every time changes are saved.
          </div>
        </div>
      )}

      {/* Tab 2: Active Timeline */}
      {historyTab === 'timeline' && (
        <div className="history-drawer-body">
          {timelineLoading && timelineEvents.length === 0 ? (
            <div className="history-empty">Loading active timeline...</div>
          ) : timelineEvents.length === 0 ? (
            <div className="history-empty">No activation events recorded yet.</div>
          ) : (
            <div className="history-timeline">
              {timelineEvents.map((ev, i) => {
                const isActivated = ev.is_active || ev.action === 'activated'
                return (
                  <div key={ev.id || i} className="timeline-item">
                    <div className="timeline-rail">
                      <div className={`timeline-dot ${isActivated ? 'dot-active' : 'dot-deactive'}`} />
                      {i < timelineEvents.length - 1 && <div className="timeline-line" />}
                    </div>
                    <div className="timeline-content">
                      <div className="timeline-header">
                        <span className={`timeline-badge ${isActivated ? 'badge-active' : 'badge-inactive'}`}>
                          {isActivated ? 'Active' : 'Inactive'}
                        </span>
                        <span className="timeline-ver">v{ev.version}</span>
                      </div>
                      <div className="timeline-user">
                        {ev.user_name || ev.user_email || 'System user'}
                      </div>
                      <div className="timeline-time">
                        {formatDate(ev.created_at)}
                      </div>
                      <div className="timeline-actions">
                        <button
                          type="button"
                          className="timeline-preview-btn"
                          onClick={() => {
                            setPreviewVersion(ev.version)
                            setHistoryTab('versions')
                          }}
                        >
                          View version {ev.version}
                        </button>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}
    </aside>
  )
}
