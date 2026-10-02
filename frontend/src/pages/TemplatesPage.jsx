import { useEffect, useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import PageHeader from '../components/shared/PageHeader'
import EmptyState from '../components/shared/EmptyState'
import LoadingSkeleton from '../components/shared/LoadingSkeleton'
import ConfirmDialog from '../components/shared/ConfirmDialog'

const CATEGORY_COLORS = {
  notifications: '#38bdf8',
  salesforce: '#00a1e0',
  dynamics_crm: '#0078d4',
  automation: '#10b981',
  approvals: '#f59e0b',
  ai: '#a855f7',
  general: '#94a3b8',
}

export default function TemplatesPage() {
  const navigate = useNavigate()
  const [templates, setTemplates] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('all')
  const [busyId, setBusyId] = useState(null)

  // Modal dialog state
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [formName, setFormName] = useState('')
  const [formCategory, setFormCategory] = useState('general')
  const [formDesc, setFormDesc] = useState('')
  const [createBusy, setCreateBusy] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState(null)

  const refresh = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.listTemplates()
      setTemplates(data || [])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        setShowCreateModal(false)
        setDeleteTarget(null)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  const categories = useMemo(() => [...new Set(templates.map(t => t.category).filter(Boolean))], [templates])

  const filtered = templates.filter(t => {
    if (category !== 'all' && t.category !== category) return false
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      return `${t.name} ${t.description} ${t.category}`.toLowerCase().includes(q)
    }
    return true
  })

  async function handleUse(t) {
    setBusyId(t.id)
    setError(null)
    try {
      const { workflow_data } = await api.useTemplate(t.id)
      const imported = await api.importWorkflow(workflow_data)
      navigate(`/workflows/${imported.id}`)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusyId(null)
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return
    setBusyId(deleteTarget.id)
    try {
      await api.deleteTemplate(deleteTarget.id)
      setDeleteTarget(null)
      await refresh()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusyId(null)
    }
  }

  async function handleCreateSubmit(e) {
    e.preventDefault()
    if (!formName.trim()) return
    setCreateBusy(true)
    setError(null)
    try {
      await api.createTemplate({
        name: formName.trim(),
        description: formDesc.trim(),
        category: formCategory,
        is_public: false,
        workflow_data: {
          nodes: [{ id: 'trigger', type: 'manual_trigger', position: { x: 100, y: 200 }, parameters: {}, settings: {} }],
          connections: {},
          settings: {}
        }
      })
      setFormName('')
      setFormDesc('')
      setFormCategory('general')
      setShowCreateModal(false)
      await refresh()
    } catch (e) {
      setError(e.message)
    } finally {
      setCreateBusy(false)
    }
  }

  return (
    <div className="page templates-page">
      <PageHeader
        title="Templates"
        description="Start from a production-ready workflow template. Templates are validated and cloned directly into your workspace."
        actions={<button className="primary" onClick={() => setShowCreateModal(true)}>＋ New template</button>}
      />

      <div className="toolbar">
        <div className="toolbar-left">
          <input
            className="search-input"
            placeholder="Search templates…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            aria-label="Search templates"
          />
          <select value={category} onChange={e => setCategory(e.target.value)} aria-label="Filter category">
            <option value="all">All categories</option>
            {categories.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div className="toolbar-right">
          <button className="ghost" onClick={refresh} disabled={loading}>↻ Refresh</button>
        </div>
      </div>

      {error && <div className="banner-inline err">{error}</div>}

      {loading ? (
        <LoadingSkeleton type="cards" rows={6} />
      ) : filtered.length === 0 ? (
        templates.length === 0 ? (
          <EmptyState
            icon="templates"
            title="No templates yet"
            description="Save a workflow as a template from the canvas, or create one here."
            action={<button className="primary" onClick={() => setShowCreateModal(true)}>Create template</button>}
          />
        ) : (
          <EmptyState
            icon="search"
            title="No matches found"
            description="No workflow templates match the current search or category filters."
            action={<button className="ghost" onClick={() => { setSearch(''); setCategory('all') }}>Clear filters</button>}
          />
        )
      ) : (
        <div className="template-grid">
          {filtered.map(t => {
            const catColor = CATEGORY_COLORS[t.category] || '#94a3b8'
            return (
              <div key={t.id} className="template-card">
                <div className="template-card-head">
                  <strong style={{ fontSize: 14.5, color: '#f8fafc', lineHeight: 1.3 }}>{t.name}</strong>
                  {t.is_mine && <span className="badge badge-muted">yours</span>}
                </div>
                {t.description && (
                  <p className="hint" style={{ margin: '4px 0 8px', fontSize: 12.5, lineHeight: 1.5, flex: 1 }}>
                    {t.description}
                  </p>
                )}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 'auto', marginBottom: 6 }}>
                  <span
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      textTransform: 'uppercase',
                      letterSpacing: '0.04em',
                      color: catColor,
                      background: `${catColor}18`,
                      border: `1px solid ${catColor}33`,
                      padding: '2px 8px',
                      borderRadius: 999
                    }}
                  >
                    {t.category}
                  </span>
                  <span className="hint" style={{ fontSize: 11.5, marginLeft: 'auto' }}>
                    {t.use_count > 0 ? `used ${t.use_count}×` : 'popular starter'}
                  </span>
                </div>
                <div className="template-card-actions">
                  <button
                    className="primary"
                    style={{ flex: 1 }}
                    disabled={busyId === t.id}
                    onClick={() => handleUse(t)}
                  >
                    {busyId === t.id ? 'Importing…' : 'Use template →'}
                  </button>
                  {t.is_mine && (
                    <button
                      className="ghost"
                      style={{ color: '#ef4444', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
                      title="Delete template"
                      disabled={busyId === t.id}
                      onClick={() => setDeleteTarget(t)}
                    >
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="3 6 5 6 21 6" />
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                      </svg>
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Create Template Modal */}
      {showCreateModal && (
        <div className="overlay" onClick={() => setShowCreateModal(false)}>
          <div className="confirm-dialog create-table-dialog" onClick={e => e.stopPropagation()}>
            <h3 style={{ margin: '0 0 6px', fontSize: 16 }}>Create Workflow Template</h3>
            <p className="hint" style={{ margin: '0 0 16px', fontSize: 13 }}>
              Create a starter template to publish to your workspace or team gallery.
            </p>
            <form onSubmit={handleCreateSubmit}>
              <div className="form-group" style={{ marginBottom: 12 }}>
                <label style={{ display: 'block', fontSize: 12, marginBottom: 4, fontWeight: 500 }}>
                  Template Name *
                </label>
                <input
                  type="text"
                  placeholder="e.g. Inbound Customer Webhook"
                  value={formName}
                  onChange={e => setFormName(e.target.value)}
                  autoFocus
                  required
                />
              </div>
              <div className="form-group" style={{ marginBottom: 12 }}>
                <label style={{ display: 'block', fontSize: 12, marginBottom: 4, fontWeight: 500 }}>
                  Category
                </label>
                <select value={formCategory} onChange={e => setFormCategory(e.target.value)}>
                  <option value="general">General</option>
                  <option value="notifications">Notifications</option>
                  <option value="salesforce">Salesforce</option>
                  <option value="dynamics_crm">Microsoft Dynamics 365</option>
                  <option value="automation">Automation</option>
                  <option value="approvals">Approvals</option>
                  <option value="ai">AI / RAG</option>
                </select>
              </div>
              <div className="form-group" style={{ marginBottom: 16 }}>
                <label style={{ display: 'block', fontSize: 12, marginBottom: 4, fontWeight: 500 }}>
                  Description
                </label>
                <textarea
                  rows={3}
                  placeholder="Describe what this workflow template accomplishes..."
                  value={formDesc}
                  onChange={e => setFormDesc(e.target.value)}
                  style={{ width: '100%', resize: 'vertical' }}
                />
              </div>
              <div className="confirm-dialog-actions" style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                <button type="button" className="ghost" onClick={() => setShowCreateModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="primary" disabled={!formName.trim() || createBusy}>
                  {createBusy ? 'Creating…' : 'Create Template'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Confirm Delete Dialog */}
      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Delete template?"
        message={`Are you sure you want to delete template “${deleteTarget?.name}”? This action cannot be undone.`}
        confirmLabel="Delete"
        danger
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  )
}
