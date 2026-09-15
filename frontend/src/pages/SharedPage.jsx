import { useEffect, useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import PageHeader from '../components/shared/PageHeader'
import EmptyState from '../components/shared/EmptyState'
import LoadingSkeleton from '../components/shared/LoadingSkeleton'

export default function SharedPage() {
  const navigate = useNavigate()
  const [workflows, setWorkflows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState('')

  const loadShared = () => {
    setLoading(true)
    setError(null)
    let alive = true
    api
      .listWorkflows()
      .then((data) => {
        if (!alive) return
        const all = Array.isArray(data) ? data : []
        // permission field is 'view'/'edit' for shared, 'owner' for owned
        setWorkflows(all.filter((w) => w && w.permission && w.permission !== 'owner'))
      })
      .catch((e) => {
        if (alive) setError(e.message || 'Failed to load shared workflows.')
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }

  useEffect(() => {
    return loadShared()
  }, [])

  const filteredWorkflows = useMemo(() => {
    if (!search.trim()) return workflows
    const q = search.toLowerCase().trim()
    return workflows.filter(
      (w) =>
        (w.name && w.name.toLowerCase().includes(q)) ||
        (w.id && String(w.id).toLowerCase().includes(q))
    )
  }, [workflows, search])

  return (
    <div className="page shared-page">
      <PageHeader
        title="Shared with you"
        description="Workflows others in your workspace or organization have shared with you."
        actions={
          <button className="ghost small" onClick={loadShared} title="Refresh shared workflows">
            Refresh
          </button>
        }
      />

      {error && <div className="banner-inline err">{error}</div>}

      {loading ? (
        <LoadingSkeleton rows={4} />
      ) : workflows.length === 0 ? (
        <EmptyState
          icon="shared"
          title="No workflows have been shared with you"
          description="When colleagues or team members share a workflow with you, it will appear here with view or edit permissions."
          action={
            <button className="primary" onClick={() => navigate('/workflows')}>
              Go to My Workflows
            </button>
          }
        />
      ) : (
        <div className="workflows-table-container">
          <div className="workflows-filter-bar" style={{ marginBottom: 16 }}>
            <div className="search-box" style={{ maxWidth: 320 }}>
              <input
                type="text"
                placeholder="Filter shared workflows…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                aria-label="Filter shared workflows"
              />
            </div>
            <span className="muted" style={{ fontSize: 13 }}>
              {filteredWorkflows.length} {filteredWorkflows.length === 1 ? 'workflow' : 'workflows'}
            </span>
          </div>

          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Workflow</th>
                  <th>Permission</th>
                  <th>Owner</th>
                  <th>Updated</th>
                  <th style={{ textAlign: 'right' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {filteredWorkflows.map((w) => {
                  const wfId = String(w?.id || '')
                  const shortId = wfId.length > 8 ? wfId.slice(0, 8) : wfId
                  const name = w?.name || `Workflow ${shortId}`
                  const isEdit = w?.permission === 'edit'
                  return (
                    <tr key={wfId}>
                      <td>
                        <strong>{name}</strong>
                        <div className="hint" style={{ fontSize: 11 }}>
                          {shortId} · v{w?.version ?? 1}
                        </div>
                      </td>
                      <td>
                        <span className={`badge ${isEdit ? 'badge-green' : 'badge-muted'}`}>
                          {w?.permission || 'view'}
                        </span>
                      </td>
                      <td className="muted">{w?.user_id ?? '—'}</td>
                      <td className="muted">
                        {w?.updated_at ? new Date(w.updated_at).toLocaleString() : '—'}
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <button
                          className="ghost small"
                          onClick={() => navigate(`/workflows/${wfId}`)}
                        >
                          Open
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
