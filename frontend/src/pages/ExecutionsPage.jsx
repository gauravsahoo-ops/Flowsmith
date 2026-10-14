import { useEffect, useState, useCallback, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import PageHeader from '../components/shared/PageHeader'
import EmptyState from '../components/shared/EmptyState'
import LoadingSkeleton from '../components/shared/LoadingSkeleton'
import WorkspaceTabs from '../components/shared/WorkspaceTabs'
import { NodeIcon } from '../components/NodeIcons'

const STATUS_OPTS = ['', 'success', 'failed', 'running', 'queued', 'cancelled', 'waiting_approval']
const STATUS_LABEL = {
  running: 'Running…',
  queued: 'Queued…',
  success: 'Success',
  failed: 'Failed',
  cancelled: 'Cancelled',
  waiting_approval: 'Waiting Approval',
  partial_success: 'Partial Success',
  retrying: 'Retrying…',
}

const CONNECTOR_PRESETS = [
  { id: '', label: 'All Connectors' },
  { id: 'hubspot', label: 'HubSpot' },
  { id: 'salesforce', label: 'Salesforce' },
  { id: 'dynamics_crm', label: 'Dynamics CRM' },
  { id: 'google_sheets', label: 'Google Sheets' },
  { id: 'http_request', label: 'HTTP / Webhook' },
  { id: 'postgres', label: 'PostgreSQL' },
  { id: 'stripe', label: 'Stripe' },
  { id: 'slack', label: 'Slack' },
]

const HTTP_STATUS_OPTS = [
  { id: '', label: 'All HTTP Statuses' },
  { id: '200', label: '200 OK' },
  { id: '201', label: '201 Created' },
  { id: '400', label: '400 Bad Request' },
  { id: '401', label: '401 Unauthorized' },
  { id: '403', label: '403 Forbidden' },
  { id: '404', label: '404 Not Found' },
  { id: '429', label: '429 Rate Limited' },
  { id: '500', label: '500 Server Error' },
  { id: '502', label: '502 Bad Gateway' },
  { id: '503', label: '503 Service Unavailable' },
]

const ERROR_TYPE_OPTS = [
  { id: '', label: 'All Error Categories' },
  { id: 'AUTH_ERROR', label: 'Auth Error (401/403)' },
  { id: 'RATE_LIMIT', label: 'Rate Limit (429)' },
  { id: 'DOWNSTREAM_5XX', label: 'Downstream Server Error (5xx)' },
  { id: 'VALIDATION_ERROR', label: 'Payload / Schema Validation' },
  { id: 'TIMEOUT', label: 'Network Timeout' },
  { id: 'ENGINE_INTERNAL', label: 'Engine Internal' },
  { id: 'UNKNOWN', label: 'Unknown Error' },
]

const DATE_RANGE_OPTS = [
  { id: '', label: 'All Time' },
  { id: '1h', label: 'Last 1 Hour' },
  { id: '24h', label: 'Last 24 Hours' },
  { id: '7d', label: 'Last 7 Days' },
  { id: '30d', label: 'Last 30 Days' },
]

const SORT_OPTS = [
  { id: 'started_at:desc', label: 'Newest First' },
  { id: 'started_at:asc', label: 'Oldest First' },
  { id: 'duration:desc', label: 'Longest Duration' },
  { id: 'duration:asc', label: 'Shortest Duration' },
  { id: 'records_processed:desc', label: 'Most Records Processed' },
  { id: 'status:asc', label: 'Status (A-Z)' },
]

function fmtTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function fmtDur(s, f) {
  if (!s) return '—'
  const ms = f ? new Date(f) - new Date(s) : Date.now() - new Date(s)
  if (ms < 1000) return `${Math.max(0, Math.round(ms))}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function getDateRangeIso(preset) {
  if (!preset) return { fromDate: undefined, toDate: undefined }
  const now = new Date()
  let from = new Date(now)
  if (preset === '1h') from.setHours(from.getHours() - 1)
  else if (preset === '24h') from.setDate(from.getDate() - 1)
  else if (preset === '7d') from.setDate(from.getDate() - 7)
  else if (preset === '30d') from.setDate(from.getDate() - 30)
  return { fromDate: from.toISOString(), toDate: now.toISOString() }
}

export default function ExecutionsPage() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()

  const [execs, setExecs] = useState([])
  const [meta, setMeta] = useState({ page: 1, pageSize: 25, total: 0 })
  const [loading, setLoading] = useState(true)
  const [exporting, setExporting] = useState(false)
  const [exportNotice, setExportNotice] = useState(null)
  const [error, setError] = useState(null)

  // Filters state
  const [search, setSearch] = useState(params.get('search') || '')
  const [debouncedSearch, setDebouncedSearch] = useState(search)
  const [status, setStatus] = useState(params.get('status') || '')
  const [workflowId, setWorkflowId] = useState(params.get('workflow_id') || '')
  const [connector, setConnector] = useState(params.get('connector') || '')
  const [httpStatus, setHttpStatus] = useState(params.get('http_status') || '')
  const [errorType, setErrorType] = useState(params.get('error_type') || '')
  const [dateRange, setDateRange] = useState(params.get('date_range') || '')
  const [sortKey, setSortKey] = useState(params.get('sort') || 'started_at:desc')
  const [pageSize, setPageSize] = useState(Number(params.get('pageSize') || 25))

  const [workflows, setWorkflows] = useState([])
  const [copiedId, setCopiedId] = useState(null)

  const page = Number(params.get('page') || 1)
  const abortRef = useRef(null)

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search)
    }, 350)
    return () => clearTimeout(timer)
  }, [search])

  const load = useCallback(async (p = page, silent = false) => {
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl

    if (!silent) setLoading(true)
    setError(null)

    const [sortBy, sortOrder] = sortKey.split(':')
    const { fromDate, toDate } = getDateRangeIso(dateRange)

    try {
      const { data, meta: m } = await api.listExecutions(
        {
          workflowId: workflowId || undefined,
          status: status || undefined,
          connector: connector || undefined,
          httpStatus: httpStatus || undefined,
          errorType: errorType || undefined,
          search: debouncedSearch || undefined,
          fromDate,
          toDate,
          sortBy,
          sortOrder,
          page: p,
          pageSize,
        },
        { signal: ctrl.signal },
      )
      if (ctrl.signal.aborted) return
      setExecs(data || [])
      if (m) setMeta(m)
    } catch (e) {
      if (ctrl.signal.aborted) return
      if (!silent) setError(e.message)
    } finally {
      if (!ctrl.signal.aborted && !silent) setLoading(false)
    }
  }, [workflowId, status, connector, httpStatus, errorType, debouncedSearch, dateRange, sortKey, pageSize, page])

  useEffect(() => {
    load()
    return () => abortRef.current?.abort()
  }, [load])

  useEffect(() => {
    api.listWorkflows().then(d => setWorkflows(Array.isArray(d) ? d : [])).catch(() => {})
  }, [])

  // Auto-poll every 2.5s while any execution in view is active
  useEffect(() => {
    const hasActive = execs.some(e => ['running', 'queued', 'waiting_approval', 'retrying'].includes(e.status))
    if (!hasActive) return

    const timer = setInterval(() => {
      load(page, true)
    }, 2500)

    return () => clearInterval(timer)
  }, [execs, load, page])

  function updateParams(newFilters = {}) {
    const q = new URLSearchParams()
    const merged = {
      status,
      workflow_id: workflowId,
      connector,
      http_status: httpStatus,
      error_type: errorType,
      date_range: dateRange,
      sort: sortKey,
      search,
      page: 1,
      pageSize,
      ...newFilters,
    }

    if (merged.status) q.set('status', merged.status)
    if (merged.workflow_id) q.set('workflow_id', merged.workflow_id)
    if (merged.connector) q.set('connector', merged.connector)
    if (merged.http_status) q.set('http_status', merged.http_status)
    if (merged.error_type) q.set('error_type', merged.error_type)
    if (merged.date_range) q.set('date_range', merged.date_range)
    if (merged.sort && merged.sort !== 'started_at:desc') q.set('sort', merged.sort)
    if (merged.search) q.set('search', merged.search)
    if (merged.page > 1) q.set('page', String(merged.page))
    if (merged.pageSize !== 25) q.set('pageSize', String(merged.pageSize))

    setParams(q, { replace: true })
  }

  function handleStatusChange(nextStatus) {
    setStatus(nextStatus)
    updateParams({ status: nextStatus, page: 1 })
  }

  function clearAllFilters() {
    setSearch('')
    setDebouncedSearch('')
    setStatus('')
    setWorkflowId('')
    setConnector('')
    setHttpStatus('')
    setErrorType('')
    setDateRange('')
    setSortKey('started_at:desc')
    setParams(new URLSearchParams(), { replace: true })
  }

  async function handleExportCsv() {
    if (exporting) return
    setExporting(true)
    setExportNotice('Generating sanitized CSV export…')
    const { fromDate, toDate } = getDateRangeIso(dateRange)
    try {
      const blob = await api.exportExecutionsCsv({
        workflowId: workflowId || undefined,
        status: status || undefined,
        connector: connector || undefined,
        httpStatus: httpStatus || undefined,
        errorType: errorType || undefined,
        search: debouncedSearch || undefined,
        fromDate,
        toDate,
      })
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `flowsmith_executions_${new Date().toISOString().slice(0, 10)}.csv`
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
      setExportNotice('CSV export downloaded successfully.')
      setTimeout(() => setExportNotice(null), 4000)
    } catch (err) {
      setExportNotice(`Export failed: ${err.message}`)
      setTimeout(() => setExportNotice(null), 5000)
    } finally {
      setExporting(false)
    }
  }

  function copyExecutionId(id, e) {
    e.stopPropagation()
    if (navigator?.clipboard?.writeText) {
      navigator.clipboard.writeText(id)
      setCopiedId(id)
      setTimeout(() => setCopiedId(null), 2000)
    }
  }

  const hasActiveFilters = Boolean(
    status || workflowId || connector || httpStatus || errorType || dateRange || debouncedSearch,
  )

  return (
    <div className="page executions-page">
      <PageHeader
        title="Execution Logs & Monitoring"
        description="Centralized integration execution history, step traces, source & destination API calls, and record processing diagnostics."
        actions={
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <button
              className="ghost"
              onClick={handleExportCsv}
              disabled={exporting || loading}
              title="Export filtered execution records to sanitized CSV with formula injection protection"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
            >
              {exporting ? (
                <>
                  <span className="spinner-sm" />
                  <span>Exporting…</span>
                </>
              ) : (
                <>
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                    <polyline points="7 10 12 15 17 10" />
                    <line x1="12" y1="15" x2="12" y2="3" />
                  </svg>
                  <span>Export CSV</span>
                </>
              )}
            </button>
            <button
              className="ghost"
              onClick={() => load(1)}
              disabled={loading}
              title="Refresh executions list"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
            >
              <span className={loading ? 'spinning' : ''}>↻</span>
              <span>Refresh</span>
            </button>
          </div>
        }
      />

      <WorkspaceTabs />

      {exportNotice && (
        <div className={`banner-inline ${exportNotice.includes('failed') ? 'err' : 'info'}`} style={{ marginBottom: 12 }}>
          {exportNotice}
        </div>
      )}

      {/* Main Filter Control Bar */}
      <div className="exec-filter-bar">
        {/* Status Chips */}
        <div className="exec-status-chips">
          {[
            { id: '', label: 'All Runs' },
            { id: 'running', label: 'Running', dotColor: '#38bdf8' },
            { id: 'success', label: 'Success', dotColor: '#10b981' },
            { id: 'failed', label: 'Failed', dotColor: '#f43f5e' },
            { id: 'queued', label: 'Queued', dotColor: '#f59e0b' },
            { id: 'waiting_approval', label: 'Approval', dotColor: '#a855f7' },
          ].map(chip => (
            <button
              key={chip.id}
              type="button"
              className={`exec-status-chip ${status === chip.id ? 'is-active' : ''}`}
              onClick={() => handleStatusChange(chip.id)}
            >
              {chip.dotColor && (
                <span className="chip-dot" style={{ background: chip.dotColor, boxShadow: `0 0 6px ${chip.dotColor}` }} />
              )}
              <span>{chip.label}</span>
            </button>
          ))}
        </div>

        {/* Search Bar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: '1 1 240px', maxWidth: 360 }}>
          <div style={{ position: 'relative', width: '100%' }}>
            <input
              type="search"
              placeholder="Search ID, workflow, connector, error…"
              value={search}
              onChange={e => {
                setSearch(e.target.value)
                updateParams({ search: e.target.value, page: 1 })
              }}
              style={{
                width: '100%',
                padding: '6px 10px 6px 30px',
                fontSize: 12.5,
                background: 'rgba(255, 255, 255, 0.04)',
                border: '1px solid rgba(255, 255, 255, 0.1)',
                borderRadius: 8,
                color: '#f8fafc',
              }}
            />
            <svg
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#94a3b8"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
              style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }}
            >
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
          </div>
        </div>
      </div>

      {/* Secondary Multi-Attribute Filter Bar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          flexWrap: 'wrap',
          marginBottom: 16,
          padding: '10px 14px',
          background: 'rgba(15, 20, 31, 0.6)',
          border: '1px solid rgba(255, 255, 255, 0.06)',
          borderRadius: 10,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text-muted)' }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
          </svg>
          <span>Filters:</span>
        </div>

        {/* Workflow Selector */}
        <select
          value={workflowId}
          onChange={e => {
            setWorkflowId(e.target.value)
            updateParams({ workflow_id: e.target.value, page: 1 })
          }}
          aria-label="Filter by workflow"
          style={{ fontSize: 12, padding: '5px 8px' }}
        >
          <option value="">All Workflows</option>
          {workflows.map(w => (
            <option key={w.id} value={w.id}>{w.name}</option>
          ))}
        </select>

        {/* Connector Selector */}
        <select
          value={connector}
          onChange={e => {
            setConnector(e.target.value)
            updateParams({ connector: e.target.value, page: 1 })
          }}
          aria-label="Filter by connector"
          style={{ fontSize: 12, padding: '5px 8px' }}
        >
          {CONNECTOR_PRESETS.map(c => (
            <option key={c.id} value={c.id}>{c.label}</option>
          ))}
        </select>

        {/* HTTP Status Code */}
        <select
          value={httpStatus}
          onChange={e => {
            setHttpStatus(e.target.value)
            updateParams({ http_status: e.target.value, page: 1 })
          }}
          aria-label="Filter by HTTP status"
          style={{ fontSize: 12, padding: '5px 8px' }}
        >
          {HTTP_STATUS_OPTS.map(h => (
            <option key={h.id} value={h.id}>{h.label}</option>
          ))}
        </select>

        {/* Error Taxonomy */}
        <select
          value={errorType}
          onChange={e => {
            setErrorType(e.target.value)
            updateParams({ error_type: e.target.value, page: 1 })
          }}
          aria-label="Filter by error category"
          style={{ fontSize: 12, padding: '5px 8px' }}
        >
          {ERROR_TYPE_OPTS.map(et => (
            <option key={et.id} value={et.id}>{et.label}</option>
          ))}
        </select>

        {/* Date Range Selector */}
        <select
          value={dateRange}
          onChange={e => {
            setDateRange(e.target.value)
            updateParams({ date_range: e.target.value, page: 1 })
          }}
          aria-label="Filter by time range"
          style={{ fontSize: 12, padding: '5px 8px' }}
        >
          {DATE_RANGE_OPTS.map(dr => (
            <option key={dr.id} value={dr.id}>{dr.label}</option>
          ))}
        </select>

        {/* Sort Selector */}
        <select
          value={sortKey}
          onChange={e => {
            setSortKey(e.target.value)
            updateParams({ sort: e.target.value, page: 1 })
          }}
          aria-label="Sort executions"
          style={{ fontSize: 12, padding: '5px 8px' }}
        >
          {SORT_OPTS.map(s => (
            <option key={s.id} value={s.id}>Sort: {s.label}</option>
          ))}
        </select>

        {hasActiveFilters && (
          <button
            type="button"
            className="ghost"
            onClick={clearAllFilters}
            style={{ fontSize: 11.5, padding: '4px 8px', color: '#f87171' }}
          >
            ✕ Reset Filters
          </button>
        )}

        <div style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-muted)' }}>
          <strong>{meta.total}</strong> total runs
        </div>
      </div>

      {error && <div className="banner-inline err">{error}</div>}

      {/* Main Execution Table */}
      {loading ? (
        <LoadingSkeleton rows={10} />
      ) : execs.length === 0 ? (
        hasActiveFilters ? (
          <EmptyState
            icon="search"
            title="No matching execution logs"
            description="No integration executions matched your filter criteria."
            action={<button className="ghost" onClick={clearAllFilters}>Clear all filters</button>}
          />
        ) : (
          <EmptyState
            icon="executions"
            badge="Monitoring Telemetry Active"
            title="No workflow executions recorded yet"
            description="When workflows run via trigger, scheduler, webhook, or manual test, comprehensive step traces, API telemetry, and record counts appear here."
            action={<button className="primary" onClick={() => navigate('/workflows')}>Go to Workflows</button>}
            secondaryAction={<button className="ghost" onClick={() => navigate('/monitoring')}>View Monitoring Dashboard</button>}
          />
        )
      ) : (
        <>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: 140 }}>Execution ID</th>
                  <th>Workflow</th>
                  <th>Integration Flow</th>
                  <th>Objects</th>
                  <th>Status</th>
                  <th>HTTP Call</th>
                  <th>Duration</th>
                  <th>Records</th>
                  <th>Started</th>
                  <th style={{ textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {execs.map(e => {
                  const hasRetry = Boolean(e.retry_count && e.retry_count > 0)
                  const hasHttp = Boolean(e.http_status_code || e.http_method)
                  const httpSuccess = e.http_status_code && e.http_status_code >= 200 && e.http_status_code < 300
                  const httpError = e.http_status_code && e.http_status_code >= 400
                  const recordsRead = e.records_read || 0
                  const recordsProc = e.records_processed || 0
                  const recordsFail = e.records_failed || 0

                  return (
                    <tr
                      key={e.id}
                      className="clickable"
                      onClick={() => navigate(`/executions/${e.id}`)}
                      tabIndex={0}
                      onKeyDown={ev => {
                        if (ev.key === 'Enter') navigate(`/executions/${e.id}`)
                      }}
                    >
                      {/* Execution ID with Copy */}
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <code className="exec-id-cell" title={e.id} style={{ fontSize: 11.5 }}>
                            {e.id.length > 12 ? `${e.id.slice(0, 10)}…` : e.id}
                          </code>
                          <button
                            type="button"
                            className="ghost"
                            onClick={ev => copyExecutionId(e.id, ev)}
                            title="Copy full Execution ID"
                            style={{
                              padding: '2px 4px',
                              height: 20,
                              minWidth: 20,
                              fontSize: 10,
                              color: copiedId === e.id ? '#34d399' : '#94a3b8',
                              background: 'transparent',
                              border: 'none',
                            }}
                          >
                            {copiedId === e.id ? '✓' : '⧉'}
                          </button>
                        </div>
                        {hasRetry && (
                          <div style={{ marginTop: 2 }}>
                            <span
                              style={{
                                fontSize: 10,
                                fontWeight: 600,
                                padding: '1px 5px',
                                borderRadius: 4,
                                background: 'rgba(245, 158, 11, 0.15)',
                                color: '#f59e0b',
                                border: '1px solid rgba(245, 158, 11, 0.3)',
                              }}
                            >
                              ↻ Attempt #{e.retry_count}
                            </span>
                          </div>
                        )}
                      </td>

                      {/* Workflow Name */}
                      <td className="wf-name-cell">
                        <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                          <span style={{ color: '#818cf8', display: 'inline-flex', flexShrink: 0 }}>
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" fillOpacity="0.2" stroke="currentColor" strokeWidth="2">
                              <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                            </svg>
                          </span>
                          <strong style={{ fontWeight: 600, color: '#f1f5f9', fontSize: 13 }}>
                            {e.workflow_name || (e.workflow_id ? e.workflow_id.slice(0, 10) : '—')}
                          </strong>
                        </div>
                      </td>

                      {/* Connectors (Source -> Destination) */}
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          {e.source_connector ? (
                            <span
                              style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: 4,
                                padding: '2px 6px',
                                background: 'rgba(255, 255, 255, 0.04)',
                                border: '1px solid rgba(255, 255, 255, 0.08)',
                                borderRadius: 5,
                                fontSize: 11,
                                color: '#e2e8f0',
                              }}
                              title={`Source Connector: ${e.source_connector}`}
                            >
                              <NodeIcon type={e.source_connector} size={13} />
                              <span>{e.source_connector}</span>
                            </span>
                          ) : (
                            <span className="muted" style={{ fontSize: 11 }}>Webhook/API</span>
                          )}

                          <span style={{ color: '#64748b', fontSize: 11 }}>→</span>

                          {e.destination_connector ? (
                            <span
                              style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: 4,
                                padding: '2px 6px',
                                background: 'rgba(255, 255, 255, 0.04)',
                                border: '1px solid rgba(255, 255, 255, 0.08)',
                                borderRadius: 5,
                                fontSize: 11,
                                color: '#e2e8f0',
                              }}
                              title={`Destination Connector: ${e.destination_connector}`}
                            >
                              <NodeIcon type={e.destination_connector} size={13} />
                              <span>{e.destination_connector}</span>
                            </span>
                          ) : (
                            <span className="muted" style={{ fontSize: 11 }}>Output</span>
                          )}
                        </div>
                      </td>

                      {/* Objects (e.g. Contacts -> Leads) */}
                      <td style={{ fontSize: 11.5, color: '#94a3b8' }}>
                        {e.source_object || e.destination_object ? (
                          <span>
                            {e.source_object || '—'}
                            {' → '}
                            {e.destination_object || '—'}
                          </span>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>

                      {/* Status */}
                      <td>
                        <span className={`status-label status-${e.status}`}>
                          {STATUS_LABEL[e.status] || e.status}
                        </span>
                      </td>

                      {/* HTTP Status Code & Method */}
                      <td>
                        {hasHttp ? (
                          <span
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: 4,
                              padding: '2px 6px',
                              borderRadius: 4,
                              fontSize: 11,
                              fontFamily: 'monospace',
                              fontWeight: 600,
                              background: httpSuccess
                                ? 'rgba(16, 185, 129, 0.12)'
                                : httpError
                                ? 'rgba(239, 68, 68, 0.12)'
                                : 'rgba(255, 255, 255, 0.06)',
                              color: httpSuccess ? '#34d399' : httpError ? '#f87171' : '#cbd5e1',
                              border: `1px solid ${
                                httpSuccess
                                  ? 'rgba(16, 185, 129, 0.25)'
                                  : httpError
                                  ? 'rgba(239, 68, 68, 0.25)'
                                  : 'rgba(255, 255, 255, 0.1)'
                              }`,
                            }}
                          >
                            <span>{e.http_method || 'HTTP'}</span>
                            <span>{e.http_status_code || ''}</span>
                          </span>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>

                      {/* Duration */}
                      <td>
                        <span className="exec-dur-badge">
                          {fmtDur(e.started_at, e.finished_at)}
                        </span>
                      </td>

                      {/* Records Processed Breakdown */}
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11.5 }}>
                          <span style={{ color: '#e2e8f0', fontWeight: 600 }}>{recordsProc.toLocaleString()}</span>
                          <span className="muted" style={{ fontSize: 10 }}>proc</span>
                          {recordsFail > 0 && (
                            <span
                              style={{
                                padding: '1px 4px',
                                background: 'rgba(239, 68, 68, 0.15)',
                                color: '#f87171',
                                borderRadius: 3,
                                fontSize: 10,
                                fontWeight: 700,
                              }}
                            >
                              {recordsFail} err
                            </span>
                          )}
                          {recordsRead > recordsProc && (
                            <span className="muted" style={{ fontSize: 10 }}>
                              ({recordsRead} read)
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Started Time */}
                      <td className="muted" style={{ fontSize: 12 }}>
                        {fmtTime(e.started_at)}
                      </td>

                      {/* Action */}
                      <td style={{ textAlign: 'right' }}>
                        <span className="exec-inspect-btn">
                          Trace →
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* Pagination Controls */}
          <div className="pagination" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 14 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span className="hint">
                Showing {Math.min(meta.total, (meta.page - 1) * meta.pageSize + 1)}–
                {Math.min(meta.total, meta.page * meta.pageSize)} of {meta.total} executions
              </span>
              <select
                value={pageSize}
                onChange={e => {
                  const ps = Number(e.target.value)
                  setPageSize(ps)
                  updateParams({ pageSize: ps, page: 1 })
                }}
                style={{ fontSize: 12, padding: '3px 6px' }}
                aria-label="Items per page"
              >
                <option value={25}>25 / page</option>
                <option value={50}>50 / page</option>
                <option value={100}>100 / page</option>
              </select>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <button
                className="ghost"
                disabled={meta.page <= 1 || loading}
                onClick={() => updateParams({ page: meta.page - 1 })}
              >
                ← Prev
              </button>
              <span className="hint" style={{ fontWeight: 600 }}>
                Page {meta.page} of {Math.max(1, Math.ceil(meta.total / meta.pageSize))}
              </span>
              <button
                className="ghost"
                disabled={meta.page * meta.pageSize >= meta.total || loading}
                onClick={() => updateParams({ page: meta.page + 1 })}
              >
                Next →
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
