import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import PageHeader from '../components/shared/PageHeader'
import EmptyState from '../components/shared/EmptyState'
import { SkeletonCard } from '../components/shared/LoadingSkeleton'

function Icon({ name, size = 20, color = 'currentColor' }) {
  switch (name) {
    case 'workflows':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" fill="currentColor" fillOpacity="0.2" />
        </svg>
      )
    case 'executions':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <polyline points="12 6 12 12 16 14" />
        </svg>
      )
    case 'credentials':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="m15.5 7.5 3 3L22 7l-3-3" />
          <circle cx="7.5" cy="16.5" r="4.5" />
          <line x1="10.5" y1="13.5" x2="17" y2="7" />
        </svg>
      )
    case 'data-tables':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect width="18" height="18" x="3" y="3" rx="2" />
          <line x1="3" y1="9" x2="21" y2="9" />
          <line x1="3" y1="15" x2="21" y2="15" />
          <line x1="9" y1="3" x2="9" y2="21" />
        </svg>
      )
    case 'templates':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polygon points="12 2 2 7 12 12 22 7 12 2" />
          <polyline points="2 17 12 22 22 17" />
          <polyline points="2 12 12 17 22 12" />
        </svg>
      )
    case 'knowledge':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
          <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
          <line x1="9" y1="7" x2="15" y2="7" />
          <line x1="9" y1="11" x2="13" y2="11" />
        </svg>
      )
    case 'plus':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <line x1="12" y1="5" x2="12" y2="19" />
          <line x1="5" y1="12" x2="19" y2="12" />
        </svg>
      )
    case 'help':
    default:
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
          <line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
      )
  }
}

function StatCard({ label, value, hint, onClick, iconName, iconColor }) {
  return (
    <button
      className="stat-card"
      onClick={onClick}
      disabled={!onClick}
      style={{ '--stat-color': iconColor }}
      type="button"
    >
      <div
        className="stat-icon"
        style={{
          background: `radial-gradient(circle at 35% 35%, ${iconColor}26 0%, ${iconColor}0a 100%)`,
          borderColor: `${iconColor}45`,
          boxShadow: `0 4px 14px -2px ${iconColor}33`,
        }}
      >
        <Icon name={iconName} size={20} color={iconColor} />
      </div>
      <div className="stat-body">
        <div className="stat-value">{value}</div>
        <div className="stat-label">{label}</div>
        {hint && <div className="stat-hint">{hint}</div>}
      </div>
    </button>
  )
}

function RecentWorkflows({ workflows, loading }) {
  const navigate = useNavigate()
  if (loading) return <div className="skeleton-grid"><SkeletonCard /><SkeletonCard /><SkeletonCard /></div>
  if (!workflows.length) {
    return (
      <EmptyState
        icon="⚡"
        title="No workflows yet"
        description="Create your first workflow to get started."
        action={<button className="primary" onClick={() => navigate('/workflows')}>Create Workflow</button>}
      />
    )
  }
  return (
    <div className="overview-cards">
      {workflows.slice(0, 6).map(w => (
        <button key={w.id} className="overview-card" onClick={() => navigate(`/workflows/${w.id}`)} type="button">
          <div className="overview-card-head">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
              <span className="overview-card-icon" style={{
                width: 24, height: 24, borderRadius: 6,
                background: w.active ? 'rgba(16, 185, 129, 0.15)' : 'rgba(99, 102, 241, 0.12)',
                display: 'inline-grid', placeItems: 'center',
                color: w.active ? '#34d399' : '#818cf8', flexShrink: 0
              }}>
                <Icon name="workflows" size={13} color="currentColor" />
              </span>
              <strong style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {w.name ? w.name : <span className="muted">Untitled workflow</span>}
              </strong>
            </div>
            <span className={`status-pill ${w.active ? 'status-success' : 'status-failed'}`} style={{
              fontSize: 10.5, padding: '2px 8px',
              color: w.active ? '#34d399' : '#94a3b8',
              background: w.active ? 'rgba(16, 185, 129, 0.12)' : 'rgba(255, 255, 255, 0.05)',
              borderColor: w.active ? 'rgba(16, 185, 129, 0.28)' : 'rgba(255, 255, 255, 0.1)'
            }}>
              <span className="dot" style={{ width: 5, height: 5, borderRadius: '50%', background: 'currentColor' }} />
              {w.active ? 'Active' : 'Inactive'}
            </span>
          </div>
          <div className="hint" style={{ fontSize: 11, fontFamily: 'JetBrains Mono, monospace', marginTop: 4 }}>
            {w.id.slice(0, 8)} · v{w.version} · {new Date(w.updated_at).toLocaleDateString()}
          </div>
          <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span className="hint" style={{ color: '#94a3b8', fontSize: 11.5 }}>
              {(w.data?.nodes?.length ?? w.node_count ?? 0)} nodes · {(w.data?.connections?.length ?? 0)} links
            </span>
            <span className="overview-card-arrow">→</span>
          </div>
        </button>
      ))}
    </div>
  )
}

function RecentExecutions({ executions, loading }) {
  const navigate = useNavigate()
  if (loading) return <div className="skeleton-grid"><SkeletonCard /><SkeletonCard /></div>
  if (!executions.length) {
    return (
      <EmptyState
        icon="🕘"
        title="No executions yet"
        description="Run a workflow to see execution history here."
        action={<button className="ghost" onClick={() => navigate('/executions')}>View executions</button>}
      />
    )
  }
  const fmt = (iso) => iso ? new Date(iso).toLocaleString() : '—'
  const dur = (s, f) => {
    if (!s) return ''
    const ms = f ? new Date(f) - new Date(s) : Date.now() - new Date(s)
    return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms/1000).toFixed(1)}s`
  }
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>Workflow</th>
            <th>Status</th>
            <th>Started</th>
            <th>Duration</th>
          </tr>
        </thead>
        <tbody>
          {executions.slice(0, 5).map(e => (
            <tr key={e.id} className="clickable" onClick={() => navigate(`/executions/${e.id}`)} tabIndex={0} onKeyDown={ev => { if (ev.key === 'Enter') navigate(`/executions/${e.id}`)}}>
              <td style={{ fontWeight: 600, color: '#f8fafc' }}>{e.workflow_name || e.workflow_id.slice(0,8)}</td>
              <td>
                <span className={`status-pill status-${e.status}`}>
                  <span className="dot" style={{ width: 6, height: 6, borderRadius: '50%', background: 'currentColor' }} />
                  {e.status}
                </span>
              </td>
              <td className="muted">{fmt(e.started_at)}</td>
              <td className="muted">{dur(e.started_at, e.finished_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function OverviewPage() {
  const navigate = useNavigate()
  const [workflows, setWorkflows] = useState([])
  const [executions, setExecutions] = useState([])
  const [credentials, setCredentials] = useState([])
  const [templates, setTemplates] = useState([])
  const [dataTables, setDataTables] = useState([])
  const [health, setHealth] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    setLoading(true)
    Promise.allSettled([
      api.listWorkflows(),
      api.listExecutions({ pageSize: 10 }).then(r => r.data || r),
      api.listCredentials().catch(() => []),
      api.listTemplates().catch(() => []),
      api.listDataTables({ pageSize: 100 }).then(r => r.data || []).catch(() => []),
      api.getHealth().catch(() => null),
    ]).then(([wf, ex, cr, tp, dt, hl]) => {
      if (!alive) return
      if (wf.status === 'fulfilled') setWorkflows(Array.isArray(wf.value) ? wf.value : [])
      if (ex.status === 'fulfilled') {
        const data = ex.value?.data ?? ex.value
        setExecutions(Array.isArray(data) ? data : [])
      }
      if (cr.status === 'fulfilled') setCredentials(Array.isArray(cr.value) ? cr.value : [])
      if (tp.status === 'fulfilled') setTemplates(Array.isArray(tp.value) ? tp.value : [])
      if (dt.status === 'fulfilled') setDataTables(Array.isArray(dt.value) ? dt.value : [])
      if (hl.status === 'fulfilled') setHealth(hl.value)
      setLoading(false)
    }).catch(err => { if (alive) { setError(err.message); setLoading(false) } })
    return () => { alive = false }
  }, [])

  const activeCount = workflows.filter(w => w.active).length
  const failedRecent = executions.filter(e => e.status === 'failed').length

  if (error) {
    return (
      <div className="page">
        <PageHeader title="Overview" description="Your automation workspace at a glance." />
        <div className="banner-inline err">{error} <button className="ghost" onClick={() => window.location.reload()}>Retry</button></div>
      </div>
    )
  }

  return (
    <div className="page overview-page">
      <PageHeader
        title="Overview"
        description="Your automation workspace — workflows, executions, and shortcuts."
        actions={<>
          <button className="ghost" onClick={() => navigate('/workflows')}>Manage workflows</button>
          <button className="primary" onClick={() => navigate('/workflows')}>Create workflow</button>
        </>}
      />

      <section className="stat-grid">
        <StatCard
          iconName="workflows"
          iconColor="#818cf8"
          label="Workflows"
          value={loading ? '…' : workflows.length}
          hint={loading ? '' : `${activeCount} active`}
          onClick={() => navigate('/workflows')}
        />
        <StatCard
          iconName="executions"
          iconColor="#38bdf8"
          label="Recent executions"
          value={loading ? '…' : executions.length}
          hint={failedRecent ? `${failedRecent} failed` : 'All recent runs fetched'}
          onClick={() => navigate('/executions')}
        />
        <StatCard
          iconName="credentials"
          iconColor="#fbbf24"
          label="Credentials"
          value={loading ? '…' : credentials.length}
          hint={`${credentials.length ? 'Encrypted at rest' : 'No credentials yet'}`}
          onClick={() => navigate('/credentials')}
        />
        <StatCard
          iconName="data-tables"
          iconColor="#c084fc"
          label="Data Tables"
          value={loading ? '…' : dataTables.length}
          hint={`${dataTables.reduce((s, t) => s + (t.row_count||0), 0)} rows`}
          onClick={() => navigate('/data-tables')}
        />
        <StatCard
          iconName="templates"
          iconColor="#f43f5e"
          label="Templates"
          value={loading ? '…' : templates.length}
          hint="Reusable blueprints"
          onClick={() => navigate('/templates')}
        />
      </section>

      {health && (
        <div className="health-banner">
          <span className="dot" />
          <span>System: <strong>{health.status}</strong> · DB: <strong>{health.database}</strong> · Uptime: <strong>{Math.floor((health.uptime_s||0)/60)}m</strong> · v{health.version}</span>
        </div>
      )}

      <section className="overview-section">
        <div className="section-head">
          <h2>Workflows</h2>
          <button className="ghost" onClick={() => navigate('/workflows')}>View all →</button>
        </div>
        <RecentWorkflows workflows={workflows} loading={loading} />
      </section>

      <section className="overview-section">
        <div className="section-head">
          <h2>Recent executions</h2>
          <button className="ghost" onClick={() => navigate('/executions')}>View all →</button>
        </div>
        <RecentExecutions executions={executions} loading={loading} />
      </section>

      <section className="overview-section">
        <h2>Quick actions</h2>
        <div className="quick-actions">
          <button className="quick-action" onClick={() => navigate('/workflows')}>
            <span className="qa-icon"><Icon name="plus" size={16} /></span>
            <span>Create workflow</span>
          </button>
          <button className="quick-action" onClick={() => navigate('/credentials')}>
            <span className="qa-icon"><Icon name="credentials" size={16} /></span>
            <span>Add credential</span>
          </button>
          <button className="quick-action" onClick={() => navigate('/data-tables')}>
            <span className="qa-icon"><Icon name="data-tables" size={16} /></span>
            <span>Create table</span>
          </button>
          <button className="quick-action" onClick={() => navigate('/templates')}>
            <span className="qa-icon"><Icon name="templates" size={16} /></span>
            <span>Use template</span>
          </button>
          <button className="quick-action" onClick={() => navigate('/knowledge')}>
            <span className="qa-icon"><Icon name="knowledge" size={16} /></span>
            <span>Manage knowledge</span>
          </button>
          <button className="quick-action" onClick={() => navigate('/executions')}>
            <span className="qa-icon"><Icon name="executions" size={16} /></span>
            <span>View executions</span>
          </button>
          <button className="quick-action" onClick={() => navigate('/help')}>
            <span className="qa-icon"><Icon name="help" size={16} /></span>
            <span>Help & docs</span>
          </button>
        </div>
      </section>
    </div>
  )
}
