import { useEffect, useState } from 'react'
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

  useEffect(() => {
    let alive = true
    api.listWorkflows().then(data => {
      if (!alive) return
      const all = Array.isArray(data) ? data : []
      // permission field is 'view'/'edit' for shared, 'owner' for owned
      setWorkflows(all.filter(w => w.permission && w.permission !== 'owner'))
    }).catch(e => { if (alive) setError(e.message)}).finally(()=> { if(alive) setLoading(false)})
    return () => { alive = false }
  }, [])

  return (
    <div className="page shared-page">
      <PageHeader title="Shared with you" description="Workflows others have shared with you." />

      {error && <div className="banner-inline err">{error}</div>}

      {loading ? <LoadingSkeleton rows={4} /> : workflows.length === 0 ? (
        <EmptyState icon="↗" title="No workflows have been shared with you." description="When someone shares a workflow, it appears here with view or edit access." action={<button className="primary" onClick={() => navigate('/workflows')}>Back to Personal</button>} />
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>Workflow</th><th>Permission</th><th>Owner</th><th>Updated</th><th>Action</th></tr></thead>
            <tbody>
              {workflows.map(w => (
                <tr key={w.id}>
                  <td><strong>{w.name || w.id.slice(0,8)}</strong><div className="hint" style={{ fontSize: 11 }}>{w.id.slice(0,8)} · v{w.version}</div></td>
                  <td><span className={`badge ${w.permission === 'edit' ? 'badge-green' : 'badge-muted'}`}>{w.permission}</span></td>
                  <td className="muted">{w.user_id ?? '—'}</td>
                  <td className="muted">{w.updated_at ? new Date(w.updated_at).toLocaleString() : '—'}</td>
                  <td><button className="ghost small" onClick={() => navigate(`/workflows/${w.id}`)}>Open</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
