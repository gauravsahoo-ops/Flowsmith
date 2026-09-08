// TemplatesPanel: reusable workflow templates (Phase 32). "Use" copies a
// template into a brand-new workflow via the import endpoint (which
// validates the graph and assigns a fresh id) and loads it on the canvas.

import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import { useWorkflowStore } from '../stores/workflowStore'

export default function TemplatesPanel({ open, onClose }) {
  const [templates, setTemplates] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [busyId, setBusyId] = useState(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.listTemplates()
      setTemplates(data || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) refresh()
  }, [open, refresh])

  async function use(t) {
    setBusyId(t.id)
    setError(null)
    try {
      const { workflow_data: doc } = await api.useTemplate(t.id)
      // Import assigns a fresh id + validates; then load onto the canvas.
      const imported = await api.importWorkflow(doc)
      await useWorkflowStore.getState().load(imported.id)
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusyId(null)
    }
  }

  async function del(t) {
    if (!window.confirm(`Delete template “${t.name}”?`)) return
    setBusyId(t.id)
    setError(null)
    try {
      await api.deleteTemplate(t.id)
      await refresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusyId(null)
    }
  }

  if (!open) return null

  return (
    <aside className="panel templates">
      <header>
        <h2>Templates</h2>
        <button className="ghost" onClick={onClose} title="Close">
          ✕
        </button>
      </header>
      <p className="hint">
        Start from a ready-made workflow.
        <button className="ghost linklike" onClick={refresh} disabled={loading}>
          ↻ Refresh
        </button>
      </p>
      {error && <div className="banner-inline err">{error}</div>}
      {!loading && templates.length === 0 && (
        <p className="hint">No templates yet. Save one with “⭐ Save as template”.</p>
      )}
      <div className="templates-list">
        {templates.map((t) => (
          <div key={t.id} className="templates-row">
            <div className="templates-info">
              <span className="templates-name">
                {t.name}
                {t.is_mine && <span className="muted"> (yours)</span>}
              </span>
              {t.description && <span className="templates-description">{t.description}</span>}
              <span className="templates-meta">
                {t.category} · used {t.use_count ?? 0}×
              </span>
            </div>
            <div className="approvals-actions">
              <button
                className="primary"
                disabled={busyId === t.id}
                onClick={() => use(t)}
                title="Create a new workflow from this template"
              >
                Use
              </button>
              {t.is_mine && (
                <button
                  className="danger"
                  disabled={busyId === t.id}
                  onClick={() => del(t)}
                  title="Delete this template"
                >
                  🗑
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </aside>
  )
}
