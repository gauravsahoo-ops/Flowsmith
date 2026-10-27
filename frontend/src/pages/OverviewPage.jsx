import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import PageHeader from '../components/shared/PageHeader'
import EmptyState from '../components/shared/EmptyState'
import { summarizeConnectors } from '../utils/connectorStats'

function Icon({ name, size = 18, color = 'currentColor' }) {
  const common = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: color,
    strokeWidth: 1.8,
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
  }
  switch (name) {
    case 'workflows':
      return (
        <svg {...common}>
          <rect x="3" y="3" width="7" height="7" rx="1.5" />
          <rect x="14" y="3" width="7" height="7" rx="1.5" />
          <rect x="14" y="14" width="7" height="7" rx="1.5" />
          <rect x="3" y="14" width="7" height="7" rx="1.5" />
        </svg>
      )
    case 'executions':
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="9" />
          <polyline points="12 7 12 12 15.5 14" />
        </svg>
      )
    case 'credentials':
      return (
        <svg {...common}>
          <circle cx="8" cy="15" r="3.5" />
          <path d="m10.5 12.5 8-8" />
          <path d="m15 8 3 3" />
          <path d="m18 5 2 2" />
        </svg>
      )
    case 'connectors':
      return (
        <svg {...common}>
          <path d="M12 3v5m0 8v5M3 12h5m8 0h5" />
          <rect x="8" y="8" width="8" height="8" rx="2" />
        </svg>
      )
    case 'health':
      return (
        <svg {...common}>
          <path d="M3 12h4l2.5-6 4 12 2.5-6H21" />
        </svg>
      )
    case 'plus':
      return (
        <svg {...common}>
          <line x1="12" y1="5" x2="12" y2="19" />
          <line x1="5" y1="12" x2="19" y2="12" />
        </svg>
      )
    case 'data':
      return (
        <svg {...common}>
          <ellipse cx="12" cy="5" rx="7" ry="3" />
          <path d="M5 5v7c0 1.7 3.1 3 7 3s7-1.3 7-3V5" />
          <path d="M5 12v7c0 1.7 3.1 3 7 3s7-1.3 7-3v-7" />
        </svg>
      )
    case 'templates':
      return (
        <svg {...common}>
          <rect x="3" y="4" width="18" height="16" rx="2" />
          <path d="M3 9h18M8 4v16" />
        </svg>
      )
    case 'ai':
      return (
        <svg {...common}>
          <path d="m12 3-1.6 4.8a2 2 0 0 1-1.3 1.3L4.5 11l4.6 1.9a2 2 0 0 1 1.3 1.3L12 19l1.6-4.8a2 2 0 0 1 1.3-1.3L19.5 11l-4.6-1.9a2 2 0 0 1-1.3-1.3Z" />
        </svg>
      )
    case 'approvals':
      return (
        <svg {...common}>
          <path d="M12 21s7-3.5 7-9V5l-7-3-7 3v7c0 5.5 7 9 7 9z" />
          <path d="m9 12 2 2 4-4" />
        </svg>
      )
    case 'arrow':
      return (
        <svg {...common}>
          <path d="M5 12h14M13 6l6 6-6 6" />
        </svg>
      )
    default:
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="9" />
          <path d="M12 8v4m0 4h.01" />
        </svg>
      )
  }
}

function formatRelative(value) {
  if (!value) return 'Never'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Unknown'
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000))
  if (seconds < 60) return 'Just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}d ago`
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function formatDuration(started, finished) {
  if (!started || !finished) return '—'
  const ms = new Date(finished).getTime() - new Date(started).getTime()
  if (!Number.isFinite(ms) || ms < 0) return '—'
  if (ms < 1000) return `${Math.round(ms)}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`
}

function KpiCard({ icon, label, value, meta, tone = 'neutral' }) {
  return (
    <div className={`f-kpi f-kpi--${tone}`}>
      <div className="f-kpi-top">
        <span className="f-kpi-label">{label}</span>
        <span className="f-kpi-icon"><Icon name={icon} size={16} /></span>
      </div>
      <div className="f-kpi-value">{value}</div>
      <div className="f-kpi-meta">{meta}</div>
    </div>
  )
}

function WorkflowRow({ workflow, onOpen }) {
  const nodeCount = workflow.data?.nodes?.length ?? workflow.node_count ?? 0
  return (
    <button type="button" className="f-workflow-row" onClick={() => onOpen(workflow.id)}>
      <span className="f-workflow-icon"><Icon name="workflows" size={17} /></span>
      <span className="f-workflow-copy">
        <strong>{workflow.name || 'Untitled workflow'}</strong>
        <small>{workflow.id.slice(0, 12)} · v{workflow.version || 1} · {nodeCount} nodes</small>
      </span>
      <span className={`f-status ${workflow.active ? 'is-active' : 'is-idle'}`}>
        <span />{workflow.active ? 'Active' : 'Inactive'}
      </span>
      <span className="f-workflow-time">{formatRelative(workflow.updated_at)}</span>
      <span className="f-row-arrow"><Icon name="arrow" size={14} /></span>
    </button>
  )
}

function ExecutionTable({ executions, loading, onOpen }) {
  if (loading) {
    return (
      <div className="f-skeleton-list">
        {[0, 1, 2, 3].map((row) => <div key={row} className="f-skeleton-row" />)}
      </div>
    )
  }
  if (!executions.length) {
    return (
      <EmptyState
        icon="executions"
        title="No executions yet"
        description="Run a workflow and its execution history will appear here."
        action={<button className="ghost" onClick={() => onOpen(null)}>View executions</button>}
      />
    )
  }
  return (
    <div className="f-table-wrap">
      <table className="f-table">
        <thead>
          <tr>
            <th>Workflow</th>
            <th>Status</th>
            <th>Started</th>
            <th>Duration</th>
            <th aria-label="Open" />
          </tr>
        </thead>
        <tbody>
          {executions.slice(0, 6).map((execution) => (
            <tr
              key={execution.id}
              onClick={() => onOpen(execution.id)}
              onKeyDown={(event) => { if (event.key === 'Enter') onOpen(execution.id) }}
              tabIndex={0}
            >
              <td>
                <div className="f-exec-workflow">
                  <span className="f-exec-icon"><Icon name="executions" size={14} /></span>
                  <div>
                    <strong>{execution.workflow_name || execution.workflow_id?.slice(0, 12) || 'Workflow'}</strong>
                    <small>{execution.id}</small>
                  </div>
                </div>
              </td>
              <td><span className={`f-status status-${execution.status}`}><span />{execution.status}</span></td>
              <td className="f-table-muted">{formatRelative(execution.started_at)}</td>
              <td className="f-table-mono">{formatDuration(execution.started_at, execution.finished_at)}</td>
              <td><span className="f-row-arrow"><Icon name="arrow" size={14} /></span></td>
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
  const [connectorStats, setConnectorStats] = useState({ total: 0, native: 0, generated: 0, catalogOnly: 0 })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    setLoading(true)
    Promise.allSettled([
      api.listWorkflows(),
      api.listExecutions({ pageSize: 10 }).then((result) => result.data || result),
      api.listCredentials().catch(() => []),
      api.listTemplates().catch(() => []),
      api.listDataTables({ pageSize: 100 }).then((result) => result.data || []).catch(() => []),
      api.getHealth().catch(() => null),
      api.listConnectors().catch(() => []),
    ]).then(([wf, ex, cr, tp, dt, hl, cn]) => {
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
      if (cn.status === 'fulfilled') {
        const connectorList = Array.isArray(cn.value) ? cn.value : (cn.value?.data || cn.value?.connectors || [])
        if (connectorList.length > 0) setConnectorStats(summarizeConnectors(connectorList))
      }
      setLoading(false)
    }).catch((err) => {
      if (alive) {
        setError(err.message)
        setLoading(false)
      }
    })
    return () => { alive = false }
  }, [])

  useEffect(() => {
    const hasActive = executions.some((execution) => ['running', 'queued', 'waiting_approval'].includes(execution.status))
    if (!hasActive) return undefined
    const timer = setInterval(() => {
      api.listExecutions({ pageSize: 10 }).then((result) => {
        const data = result?.data ?? result
        if (Array.isArray(data)) setExecutions(data)
      }).catch(() => {})
    }, 3000)
    return () => clearInterval(timer)
  }, [executions])

  const activeCount = workflows.filter((workflow) => workflow.active).length
  const failedRecent = executions.filter((execution) => execution.status === 'failed').length
  const successRate = executions.length
    ? Math.round(((executions.length - failedRecent) / executions.length) * 100)
    : 100
  const successTone = successRate >= 90 ? 'positive' : successRate >= 70 ? 'warning' : 'negative'
  const connectorCount = connectorStats.native || connectorStats.total || 0
  const totalRows = dataTables.reduce((sum, table) => sum + (table.row_count || 0), 0)
  const today = new Date().toLocaleDateString(undefined, {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  })

  if (error) {
    return (
      <div className="page overview-page">
        <PageHeader title="Overview" description="Your automation workspace at a glance." />
        <div className="banner-inline err">{error} <button className="ghost small" onClick={() => window.location.reload()}>Retry</button></div>
      </div>
    )
  }

  return (
    <div className="page overview-page">
      <PageHeader
        title="Overview"
        description={`${today} · Personal workspace`}
        actions={
          <>
            <button className="ghost" onClick={() => navigate('/executions')}>Run history</button>
            <button className="primary" onClick={() => navigate('/workflows')}>
              <Icon name="plus" size={14} />
              New workflow
            </button>
          </>
        }
      />

      <div className="f-kpi-grid">
        <KpiCard
          icon="workflows"
          label="Active workflows"
          value={loading ? '—' : activeCount}
          meta={loading ? 'Loading workspace' : `${workflows.length} total workflows`}
        />
        <KpiCard
          icon="executions"
          label="Recent executions"
          value={loading ? '—' : executions.length}
          meta={loading ? 'Loading run history' : `${failedRecent} failed in the last 10 runs`}
          tone={failedRecent ? 'warning' : 'neutral'}
        />
        <KpiCard
          icon="health"
          label="Success rate"
          value={loading ? '—' : `${successRate}%`}
          meta={loading ? 'Loading telemetry' : 'Across the last 10 executions'}
          tone={successTone}
        />
        <KpiCard
          icon="connectors"
          label="Connectors"
          value={loading ? '—' : connectorCount}
          meta={loading ? 'Loading catalog' : `${connectorStats.total || connectorCount} registered entries`}
        />
      </div>

      <div className="f-overview-grid">
        <section className="f-panel f-recent-workflows">
          <div className="f-panel-head">
            <div>
              <h2>Recent workflows</h2>
              <p>Pick up where you left off.</p>
            </div>
            <button className="ghost small" onClick={() => navigate('/workflows')}>View all</button>
          </div>
          {loading ? (
            <div className="f-skeleton-list">
              {[0, 1, 2, 3].map((row) => <div key={row} className="f-skeleton-row" />)}
            </div>
          ) : workflows.length ? (
            <div className="f-workflow-list">
              {workflows.slice(0, 8).map((workflow) => (
                <WorkflowRow key={workflow.id} workflow={workflow} onOpen={(id) => navigate(`/workflows/${id}`)} />
              ))}
            </div>
          ) : (
            <EmptyState
              icon="workflows"
              title="No workflows yet"
              description="Create your first workflow to start automating your workspace."
              action={<button className="primary" onClick={() => navigate('/workflows')}>Create workflow</button>}
            />
          )}
        </section>

        <aside className="f-overview-side">
          <section className="f-panel f-health-panel">
            <div className="f-panel-head">
              <div>
                <h2>System health</h2>
                <p>Runtime and telemetry.</p>
              </div>
              <span className={`f-status ${health ? 'is-active' : 'is-idle'}`}>
                <span />{health ? 'Operational' : 'Connecting'}
              </span>
            </div>
            <div className="f-health-list">
              <div><span>Version</span><strong>{health?.version || '—'}</strong></div>
              <div><span>Uptime</span><strong>{health?.uptime_s != null ? `${Math.floor(health.uptime_s / 60)}m ${Math.round(health.uptime_s % 60)}s` : '—'}</strong></div>
              <div><span>Credentials</span><strong>{credentials.length}</strong></div>
              <div><span>Data tables</span><strong>{dataTables.length} <small>{totalRows} rows</small></strong></div>
              <div><span>Templates</span><strong>{templates.length}</strong></div>
            </div>
            <button className="ghost f-full-button" onClick={() => navigate('/monitoring')}>Open monitoring</button>
          </section>

          <section className="f-panel f-quick-panel">
            <div className="f-panel-head">
              <div>
                <h2>Quick actions</h2>
                <p>Common workspace shortcuts.</p>
              </div>
            </div>
            <div className="f-quick-grid">
              <button onClick={() => navigate('/credentials')}><span><Icon name="credentials" size={16} /></span>Credential</button>
              <button onClick={() => navigate('/templates')}><span><Icon name="templates" size={16} /></span>Templates</button>
              <button onClick={() => navigate('/data-tables')}><span><Icon name="data" size={16} /></span>Data table</button>
              <button onClick={() => navigate('/ai')}><span><Icon name="ai" size={16} /></span>AI Studio</button>
              <button onClick={() => navigate('/approvals')}><span><Icon name="approvals" size={16} /></span>Approvals</button>
              <button onClick={() => navigate('/integrations')}><span><Icon name="connectors" size={16} /></span>Connectors</button>
            </div>
          </section>
        </aside>
      </div>

      <section className="f-panel f-execution-panel">
        <div className="f-panel-head">
          <div>
            <h2>Recent executions</h2>
            <p>Latest runs across your workspace.</p>
          </div>
          <button className="ghost small" onClick={() => navigate('/executions')}>View all</button>
        </div>
        <ExecutionTable
          executions={executions}
          loading={loading}
          onOpen={(id) => navigate(id ? `/executions/${id}` : '/executions')}
        />
      </section>
    </div>
  )
}
