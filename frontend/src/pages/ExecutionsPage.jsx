import { useEffect, useState, useCallback, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import PageHeader from '../components/shared/PageHeader'
import EmptyState from '../components/shared/EmptyState'
import LoadingSkeleton from '../components/shared/LoadingSkeleton'
import WorkspaceTabs from '../components/shared/WorkspaceTabs'
import UniversalExecutionSearch, { HighlightMatch } from '../components/UniversalExecutionSearch'
import { NodeIcon } from '../components/NodeIcons'

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

const ERROR_TYPE_LABELS = {
  AUTHENTICATION_ERROR: 'Authentication / Authorization',
  RATE_LIMITED: 'Rate Limited (429)',
  TIMEOUT: 'Network Timeout',
  NETWORK_ERROR: 'Network / Connection',
  VALIDATION_ERROR: 'Payload / Schema Validation',
  CONNECTOR_ERROR: 'Connector / Provider Error',
  CANCELLED: 'Cancelled',
  INTERNAL_ERROR: 'Engine Internal',
  EXECUTION_ERROR: 'Execution Error',
  UNKNOWN_ERROR: 'Unknown Error',
  // Values written by older telemetry versions remain selectable.
  AUTH_ERROR: 'Auth Error (legacy)',
  RATE_LIMIT: 'Rate Limit (legacy)',
  DOWNSTREAM_5XX: 'Downstream Server Error (legacy)',
  ENGINE_INTERNAL: 'Engine Internal (legacy)',
  UNKNOWN: 'Unknown Error (legacy)',
}

const ERROR_TYPE_OPTS = [
  { id: '', label: 'All Error Categories' },
  { id: 'AUTHENTICATION_ERROR', label: ERROR_TYPE_LABELS.AUTHENTICATION_ERROR },
  { id: 'RATE_LIMITED', label: ERROR_TYPE_LABELS.RATE_LIMITED },
  { id: 'TIMEOUT', label: ERROR_TYPE_LABELS.TIMEOUT },
  { id: 'NETWORK_ERROR', label: ERROR_TYPE_LABELS.NETWORK_ERROR },
  { id: 'VALIDATION_ERROR', label: ERROR_TYPE_LABELS.VALIDATION_ERROR },
  { id: 'CONNECTOR_ERROR', label: ERROR_TYPE_LABELS.CONNECTOR_ERROR },
  { id: 'CANCELLED', label: ERROR_TYPE_LABELS.CANCELLED },
  { id: 'INTERNAL_ERROR', label: ERROR_TYPE_LABELS.INTERNAL_ERROR },
  { id: 'EXECUTION_ERROR', label: ERROR_TYPE_LABELS.EXECUTION_ERROR },
  { id: 'UNKNOWN_ERROR', label: ERROR_TYPE_LABELS.UNKNOWN_ERROR },
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

function titleCaseErrorType(value) {
  if (ERROR_TYPE_LABELS[value]) return ERROR_TYPE_LABELS[value]
  return String(value)
    .toLowerCase()
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function buildErrorTypeOptions(rows) {
  const options = [...ERROR_TYPE_OPTS]
  const existing = new Set(options.map((option) => option.id))
  for (const row of Array.isArray(rows) ? rows : []) {
    const value = row?.value
    if (!value || existing.has(value)) continue
    existing.add(value)
    options.push({ id: value, label: titleCaseErrorType(value) })
  }
  return options
}

function fmtTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function fmtDur(s, f) {
  if (!s) return '—'
  const ms = f ? new Date(f) - new Date(s) : Date.now() - new Date(s)
  if (ms < 1000) return `${Math.max(0, Math.round(ms))}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function getDateRangeIso(preset) {
  if (!preset) return { startDate: undefined, endDate: undefined }
  const now = new Date()
  let from = new Date(now)
  if (preset === '1h') from.setHours(from.getHours() - 1)
  else if (preset === '24h') from.setDate(from.getDate() - 1)
  else if (preset === '7d') from.setDate(from.getDate() - 7)
  else if (preset === '30d') from.setDate(from.getDate() - 30)
  return { startDate: from.toISOString(), endDate: now.toISOString() }
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
  const [searchCategory, setSearchCategory] = useState(params.get('category') || 'all')
  const [searchFacets, setSearchFacets] = useState({})
  const [viewMode, setSearchViewMode] = useState('table') // 'table' | 'occurrences'
  const [occurrences, setOccurrences] = useState([])
  const [occurrencePage, setOccurrencePage] = useState(1)
  const [occurrencesMeta, setOccurrencesMeta] = useState({ total: 0, page: 1, pageSize: 50 })
  const [loadingOccurrences, setLoadingOccurrences] = useState(false)

  const [status, setStatus] = useState(params.get('status') || '')
  const [workflowId, setWorkflowId] = useState(params.get('workflow_id') || '')
  const [connector, setConnector] = useState(params.get('connector') || '')
  const [httpStatus, setHttpStatus] = useState(params.get('http_status') || '')
  const [errorType, setErrorType] = useState(params.get('error_type') || '')
  const [dateRange, setDateRange] = useState(params.get('date_range') || '')
  const [sortKey, setSortKey] = useState(params.get('sort') || 'started_at:desc')
  const [pageSize, setPageSize] = useState(Number(params.get('pageSize') || 25))

  const [workflows, setWorkflows] = useState([])
  const [connectorOptions, setConnectorOptions] = useState([])
  const [errorTypeOptions, setErrorTypeOptions] = useState(ERROR_TYPE_OPTS)
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

  // Sync category from params if changed externally
  useEffect(() => {
    const cat = params.get('category')
    if (cat && cat !== searchCategory) {
      setSearchCategory(cat)
    }
  }, [params, searchCategory])

  // A new query/filter starts at page 1; paging only changes occurrencePage.
  useEffect(() => {
    setOccurrencePage(1)
  }, [debouncedSearch, searchCategory, dateRange, workflowId, status])

  // Fetch universal occurrences & facet counts when search query is active
  useEffect(() => {
    if (!debouncedSearch || !debouncedSearch.trim()) {
      setOccurrences([])
      setSearchFacets({})
      setOccurrencesMeta({ total: 0, page: 1, pageSize: 50 })
      return
    }

    let active = true
    setLoadingOccurrences(true)
    const { startDate, endDate } = getDateRangeIso(dateRange)
    api
      .universalSearchExecutions({
        q: debouncedSearch.trim(),
        category: searchCategory !== 'all' ? searchCategory : undefined,
        workflowId: workflowId || undefined,
        status: status || undefined,
        startDate,
        endDate,
        page: occurrencePage,
        pageSize: 50,
      })
      .then((res) => {
        if (!active) return
        setOccurrences(res?.data || [])
        setOccurrencesMeta(res?.meta || { total: 0, page: occurrencePage, pageSize: 50 })
        if (res?.meta?.facets) {
          setSearchFacets(res.meta.facets)
        }
      })
      .catch(() => {
        if (active) setOccurrences([])
      })
      .finally(() => {
        if (active) setLoadingOccurrences(false)
      })

    return () => {
      active = false
    }
  }, [debouncedSearch, searchCategory, dateRange, occurrencePage, workflowId, status])

  const load = useCallback(async (p = page, silent = false) => {
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl

    if (!silent) setLoading(true)
    setError(null)

    const [sortBy, sortOrder] = sortKey.split(':')
    const { startDate, endDate } = getDateRangeIso(dateRange)

    try {
      const { data, meta: m } = await api.listExecutions(
        {
          workflowId: workflowId || undefined,
          status: status || undefined,
          connector: connector || undefined,
          httpStatus: httpStatus || undefined,
          errorType: errorType || undefined,
          search: debouncedSearch || undefined,
          startDate,
          endDate,
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
    let active = true
    Promise.allSettled([
      api.listWorkflows(),
      api.listConnectors(),
      api.getExecutionErrorTypes(),
    ]).then(([workflowResult, connectorResult, errorTypeResult]) => {
      if (!active) return
      if (workflowResult.status === 'fulfilled') {
        setWorkflows(Array.isArray(workflowResult.value) ? workflowResult.value : [])
      }
      if (connectorResult.status === 'fulfilled') {
        const connectors = Array.isArray(connectorResult.value) ? connectorResult.value : []
        const options = connectors
          .map((c) => ({
            id: c.connector_key || c.id,
            label: c.display_name || c.connector_key || c.id,
          }))
          .filter((c) => c.id)
          .sort((a, b) => String(a.label).localeCompare(String(b.label)))
        if (options.length) {
          setConnectorOptions([{ id: '', label: 'All Connectors' }, ...options])
        }
      }
      if (errorTypeResult.status === 'fulfilled') {
        setErrorTypeOptions(buildErrorTypeOptions(errorTypeResult.value))
      }
    })
    return () => {
      active = false
    }
  }, [])

  // Auto-poll every 2.5s while any execution in view is active
  useEffect(() => {
    const hasActive = execs.some(e => ['running', 'queued', 'waiting_approval', 'retrying'].includes(e.status))
    if (!hasActive) return

    const timer = setInterval(() => {
      if (typeof document !== 'undefined' && document.hidden) return
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
      category: searchCategory !== 'all' ? searchCategory : undefined,
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
    if (merged.category && merged.category !== 'all') q.set('category', merged.category)
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
    setSearchCategory('all')
    setOccurrences([])
    setSearchFacets({})
    setSearchViewMode('table')
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
    const { startDate, endDate } = getDateRangeIso(dateRange)
    try {
      const { blob, truncated, limit } = await api.exportExecutionsCsv({
        workflowId: workflowId || undefined,
        status: status || undefined,
        connector: connector || undefined,
        httpStatus: httpStatus || undefined,
        errorType: errorType || undefined,
        search: debouncedSearch || undefined,
        startDate,
        endDate,
      })
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `flowsmith_executions_${new Date().toISOString().slice(0, 10)}.csv`
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
      setExportNotice(
        truncated
          ? `CSV downloaded, but the export was capped at ${(limit || 10000).toLocaleString()} rows. Narrow the filters to export the remainder.`
          : 'CSV export downloaded successfully.',
      )
      setTimeout(() => setExportNotice(null), truncated ? 8000 : 4000)
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
  const connectorChoices = connectorOptions.length ? connectorOptions : CONNECTOR_PRESETS
  const occurrenceTotalPages = Math.max(
    1,
    Math.ceil((occurrencesMeta.total || 0) / (occurrencesMeta.pageSize || 50)),
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

      {/* YouTube-like Universal Execution Search Bar */}
      <div style={{ marginBottom: 16 }}>
        <UniversalExecutionSearch
          value={search}
          onChange={(val) => {
            setSearch(val)
            updateParams({ search: val, page: 1 })
          }}
          onSearch={(term, cat) => {
            setSearch(term)
            setSearchCategory(cat)
            updateParams({ search: term, category: cat, page: 1 })
          }}
          category={searchCategory}
          onCategoryChange={(cat) => {
            setSearchCategory(cat)
            updateParams({ category: cat, page: 1 })
          }}
          facets={searchFacets}
          autoFocus={Boolean(params.get('search'))}
        />
      </div>

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
          ].map((chip) => (
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

        {/* View Mode Switcher (Visible when searching) */}
        {debouncedSearch && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 'auto' }}>
            <span style={{ fontSize: 12, color: 'var(--text-muted)', marginRight: 4 }}>
              Results for &ldquo;<strong style={{ color: '#c7d2fe' }}>{debouncedSearch}</strong>&rdquo;:
            </span>
            <button
              type="button"
              className={`exec-status-chip ${viewMode === 'table' ? 'is-active' : ''}`}
              onClick={() => setSearchViewMode('table')}
              style={{ fontSize: 11.5, padding: '4px 10px', display: 'inline-flex', alignItems: 'center', gap: 6 }}
              title="View matching executions in standard table"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect width="18" height="18" x="3" y="3" rx="2" />
                <path d="M3 9h18" />
                <path d="M3 15h18" />
                <path d="M9 3v18" />
              </svg>
              <span>Table Runs ({meta.total})</span>
            </button>
            <button
              type="button"
              className={`exec-status-chip ${viewMode === 'occurrences' ? 'is-active' : ''}`}
              onClick={() => setSearchViewMode('occurrences')}
              style={{ fontSize: 11.5, padding: '4px 10px', display: 'inline-flex', alignItems: 'center', gap: 6 }}
              title="View every individual matched step, error, payload or record occurrence"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="8" y1="6" x2="21" y2="6" />
                <line x1="8" y1="12" x2="21" y2="12" />
                <line x1="8" y1="18" x2="21" y2="18" />
                <line x1="3" y1="6" x2="3.01" y2="6" />
                <line x1="3" y1="12" x2="3.01" y2="12" />
                <line x1="3" y1="18" x2="3.01" y2="18" />
              </svg>
              <span>All Occurrences ({occurrencesMeta.total || 0})</span>
            </button>
          </div>
        )}
      </div>

      {/* Secondary Multi-Attribute Filter Bar */}
      <div className="exec-filter-bar">
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
        >
          {connectorChoices.map(c => (
            <option key={c.id} value={c.id}>{c.label}</option>
          ))}
          {connector && !connectorChoices.some(c => c.id === connector) && (
            <option value={connector}>{connector}</option>
          )}
        </select>

        {/* HTTP Status Code */}
        <select
          value={httpStatus}
          onChange={e => {
            setHttpStatus(e.target.value)
            updateParams({ http_status: e.target.value, page: 1 })
          }}
          aria-label="Filter by HTTP status"
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
        >
          {errorTypeOptions.map(et => (
            <option key={et.id} value={et.id}>{et.label}</option>
          ))}
          {errorType && !errorTypeOptions.some(et => et.id === errorType) && (
            <option value={errorType}>{titleCaseErrorType(errorType)}</option>
          )}
        </select>

        {/* Date Range Selector */}
        <select
          value={dateRange}
          onChange={e => {
            setDateRange(e.target.value)
            updateParams({ date_range: e.target.value, page: 1 })
          }}
          aria-label="Filter by time range"
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
            style={{ fontSize: 11.5, padding: '4px 8px', color: '#f87171', display: 'inline-flex', alignItems: 'center', gap: 4 }}
          >
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
            <span>Reset Filters</span>
          </button>
        )}

        <div style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-muted)' }}>
          <strong>{meta.total}</strong> total runs
        </div>
      </div>

      {error && <div className="banner-inline err">{error}</div>}

      {/* Main Execution Content: Table View vs Occurrences View */}
      {viewMode === 'occurrences' && debouncedSearch ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {loadingOccurrences ? (
            <LoadingSkeleton rows={8} />
          ) : occurrences.length === 0 ? (
            <EmptyState
              icon="search"
              title="No matching occurrences found"
              description={`No execution details or telemetry logs matched "${debouncedSearch}" in category "${searchCategory}".`}
              action={
                <button
                  className="ghost"
                  onClick={() => {
                    setSearchCategory('all')
                    updateParams({ category: 'all' })
                  }}
                >
                  Search in All Categories
                </button>
              }
            />
          ) : (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(400px, 1fr))', gap: 14 }}>
                {occurrences.map((occ) => {
                  const colors = {
                    steps: { bg: 'rgba(99, 102, 241, 0.15)', text: '#818cf8', border: 'rgba(99, 102, 241, 0.35)' },
                    errors: { bg: 'rgba(239, 68, 68, 0.15)', text: '#f87171', border: 'rgba(239, 68, 68, 0.35)' },
                    records: { bg: 'rgba(16, 185, 129, 0.15)', text: '#34d399', border: 'rgba(16, 185, 129, 0.35)' },
                    api_requests: { bg: 'rgba(56, 189, 248, 0.15)', text: '#38bdf8', border: 'rgba(56, 189, 248, 0.35)' },
                    payloads: { bg: 'rgba(245, 158, 11, 0.15)', text: '#fbbf24', border: 'rgba(245, 158, 11, 0.35)' },
                    metadata: { bg: 'rgba(168, 85, 247, 0.15)', text: '#c084fc', border: 'rgba(168, 85, 247, 0.35)' },
                  }[occ.category] || { bg: 'rgba(255,255,255,0.06)', text: '#cbd5e1', border: 'rgba(255,255,255,0.12)' }

                  return (
                    <div
                      key={occ.id}
                      onClick={() => navigate(occ.url || `/executions/${occ.execution_id}`)}
                      style={{
                        background: 'rgba(19, 23, 34, 0.75)',
                        backdropFilter: 'blur(12px)',
                        border: '1px solid rgba(255, 255, 255, 0.08)',
                        borderRadius: 10,
                        padding: '14px 16px',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 10,
                        cursor: 'pointer',
                        transition: 'transform 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease',
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.borderColor = 'rgba(99, 102, 241, 0.45)'
                        e.currentTarget.style.transform = 'translateY(-2px)'
                        e.currentTarget.style.boxShadow = '0 6px 20px rgba(0,0,0,0.3)'
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.08)'
                        e.currentTarget.style.transform = 'translateY(0)'
                        e.currentTarget.style.boxShadow = 'none'
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                        <span
                          style={{
                            fontSize: 10.5,
                            fontWeight: 700,
                            padding: '2px 7px',
                            borderRadius: 4,
                            background: colors.bg,
                            color: colors.text,
                            border: `1px solid ${colors.border}`,
                            textTransform: 'uppercase',
                            letterSpacing: '0.03em',
                          }}
                        >
                          {occ.location_badge}
                        </span>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          {occ.started_at && (
                            <span style={{ fontSize: 11, color: '#94a3b8', display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#818cf8" strokeWidth="2">
                                <circle cx="12" cy="12" r="10" />
                                <polyline points="12 6 12 12 16 14" />
                              </svg>
                              <HighlightMatch text={fmtTime(occ.started_at)} query={debouncedSearch} />
                            </span>
                          )}
                          <span className={`status-label status-${occ.status}`} style={{ fontSize: 10.5, padding: '1px 6px' }}>
                            {STATUS_LABEL[occ.status] || occ.status}
                          </span>
                          <span style={{ fontSize: 11, color: '#94a3b8', fontFamily: 'monospace' }}>
                            {fmtDur(occ.started_at, occ.finished_at)}
                          </span>
                        </div>
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, fontSize: 12 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#818cf8" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
                            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                          </svg>
                          <strong style={{ color: '#f1f5f9', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {occ.workflow_name}
                          </strong>
                        </div>
                        <code style={{ fontSize: 11, color: '#94a3b8' }}>{occ.execution_id.slice(0, 10)}…</code>
                      </div>

                      <div
                        style={{
                          background: 'rgba(0,0,0,0.3)',
                          padding: '8px 10px',
                          borderRadius: 6,
                          fontSize: 12,
                          fontFamily: 'monospace',
                          color: '#cbd5e1',
                          border: '1px solid rgba(255,255,255,0.04)',
                          maxHeight: 80,
                          overflowY: 'auto',
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word',
                        }}
                      >
                        <HighlightMatch text={occ.snippet || occ.matched_value} query={debouncedSearch} />
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 'auto', paddingTop: 4, fontSize: 11 }}>
                        <span style={{ color: 'var(--text-muted)' }}>
                          Field: <code style={{ color: '#94a3b8' }}>{occ.matched_field}</code>
                        </span>
                        <span style={{ color: '#818cf8', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                          <span>Inspect Detail</span>
                          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                            <polyline points="9 18 15 12 9 6" />
                          </svg>
                        </span>
                      </div>
                    </div>
                  )
                })}
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 10, gap: 12, flexWrap: 'wrap' }}>
                <span className="hint">
                  {occurrencesMeta.total > 0
                    ? `Showing ${(occurrencesMeta.page - 1) * occurrencesMeta.pageSize + 1}–${Math.min(
                        occurrencesMeta.page * occurrencesMeta.pageSize,
                        occurrencesMeta.total,
                      )} of ${occurrencesMeta.total} occurrences`
                    : 'No matching occurrences'}
                </span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <button
                    type="button"
                    className="ghost"
                    disabled={occurrencePage <= 1 || loadingOccurrences}
                    onClick={() => setOccurrencePage((current) => Math.max(1, current - 1))}
                    style={{ fontSize: 12 }}
                  >
                    ← Previous
                  </button>
                  <span className="hint" style={{ fontWeight: 600 }}>
                    Page {occurrencePage} of {occurrenceTotalPages}
                  </span>
                  <button
                    type="button"
                    className="ghost"
                    disabled={occurrencePage >= occurrenceTotalPages || loadingOccurrences}
                    onClick={() => setOccurrencePage((current) => current + 1)}
                    style={{ fontSize: 12 }}
                  >
                    Next →
                  </button>
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => setSearchViewMode('table')}
                    style={{ fontSize: 12 }}
                  >
                    Switch to Table View
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      ) : loading ? (
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
          <div className="table-wrap exec-table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: 110, minWidth: 100 }}>Execution ID</th>
                  <th style={{ minWidth: 140, maxWidth: 220 }}>Workflow</th>
                  <th style={{ minWidth: 155 }}>Integration Flow</th>
                  <th style={{ minWidth: 110 }}>Objects</th>
                  <th style={{ minWidth: 85 }}>Status</th>
                  <th style={{ minWidth: 80 }}>HTTP Call</th>
                  <th style={{ minWidth: 65 }}>Duration</th>
                  <th style={{ minWidth: 70 }}>Records</th>
                  <th style={{ minWidth: 105 }}>Started</th>
                  <th style={{ textAlign: 'right', minWidth: 75, width: 85 }}>Actions</th>
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
                              display: 'inline-flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                            }}
                          >
                            {copiedId === e.id ? (
                              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#34d399" strokeWidth="2.5">
                                <polyline points="20 6 9 17 4 12" />
                              </svg>
                            ) : (
                              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" strokeWidth="2">
                                <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                              </svg>
                            )}
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

                      {/* Workflow Name & Match Badges */}
                      <td className="wf-name-cell" style={{ maxWidth: 240 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, overflow: 'hidden' }}>
                          <span style={{ color: '#818cf8', display: 'inline-flex', flexShrink: 0 }}>
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" fillOpacity="0.2" stroke="currentColor" strokeWidth="2">
                              <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                            </svg>
                          </span>
                          <strong
                            title={e.workflow_name || (e.workflow_id ? e.workflow_id : '')}
                            style={{
                              fontWeight: 600,
                              color: '#f1f5f9',
                              fontSize: 12.5,
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                            }}
                          >
                            <HighlightMatch text={e.workflow_name || (e.workflow_id ? e.workflow_id.slice(0, 10) : '—')} query={debouncedSearch} />
                          </strong>
                        </div>
                        {e.search_matches && e.search_matches.length > 0 && (
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                            {e.search_matches.slice(0, 3).map((m, idx) => (
                              <button
                                key={idx}
                                type="button"
                                onClick={(ev) => {
                                  ev.stopPropagation()
                                  navigate(m.url || `/executions/${e.id}`)
                                }}
                                style={{
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: 4,
                                  fontSize: 10,
                                  fontWeight: 600,
                                  padding: '1px 6px',
                                  borderRadius: 4,
                                  background: 'rgba(99, 102, 241, 0.16)',
                                  color: '#c7d2fe',
                                  border: '1px solid rgba(99, 102, 241, 0.35)',
                                  cursor: 'pointer',
                                  maxWidth: 210,
                                  overflow: 'hidden',
                                  textOverflow: 'ellipsis',
                                  whiteSpace: 'nowrap',
                                  transition: 'all 0.15s ease',
                                }}
                                title={`Jump to match: ${m.label} — ${m.snippet || ''}`}
                              >
                                <span style={{ width: 4, height: 4, borderRadius: '50%', background: '#818cf8', flexShrink: 0 }} />
                                <span>{m.label}</span>
                              </button>
                            ))}
                            {e.search_matches.length > 3 && (
                              <span style={{ fontSize: 9.5, color: '#94a3b8', alignSelf: 'center' }}>
                                +{e.search_matches.length - 3} more
                              </span>
                            )}
                          </div>
                        )}
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
                              <NodeIcon type={e.source_connector} size={16} />
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
                              <NodeIcon type={e.destination_connector} size={16} />
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
                      <td
                        className="muted"
                        style={{ fontSize: 11.5 }}
                        title={e.started_at ? new Date(e.started_at).toLocaleString() : ''}
                      >
                        {fmtTime(e.started_at)}
                      </td>

                      {/* Action */}
                      <td style={{ textAlign: 'right' }}>
                        <span className="exec-inspect-btn" title="Inspect execution trace & waterfall">
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
