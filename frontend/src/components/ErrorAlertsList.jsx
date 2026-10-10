import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'

function SeverityBadge({ severity }) {
  const sev = (severity || 'ERROR').toUpperCase()
  const colors = {
    CRITICAL: { bg: 'rgba(225, 29, 72, 0.15)', text: '#f43f5e', border: 'rgba(225, 29, 72, 0.35)' },
    ERROR: { bg: 'rgba(239, 68, 68, 0.12)', text: '#ef4444', border: 'rgba(239, 68, 68, 0.3)' },
    WARNING: { bg: 'rgba(245, 158, 11, 0.12)', text: '#f59e0b', border: 'rgba(245, 158, 11, 0.3)' },
    INFO: { bg: 'rgba(59, 130, 246, 0.12)', text: '#3b82f6', border: 'rgba(59, 130, 246, 0.3)' },
  }
  const config = colors[sev] || colors.ERROR

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        padding: '2px 8px',
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.04em',
        background: config.bg,
        color: config.text,
        border: `1px solid ${config.border}`,
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: config.text,
          boxShadow: sev === 'CRITICAL' ? `0 0 6px ${config.text}` : 'none',
        }}
      />
      {sev}
    </span>
  )
}

function StatusPill({ status }) {
  const st = (status || 'DETECTED').toUpperCase()
  let color = '#94a3b8'
  let bg = 'rgba(148, 163, 184, 0.1)'

  if (st === 'NOTIFIED') {
    color = '#10b981'
    bg = 'rgba(16, 185, 129, 0.12)'
  } else if (st === 'NOTIFICATION_PENDING') {
    color = '#38bdf8'
    bg = 'rgba(56, 189, 248, 0.12)'
  } else if (st === 'RESOLVED') {
    color = '#10b981'
    bg = 'rgba(16, 185, 129, 0.12)'
  } else if (st === 'ACKNOWLEDGED') {
    color = '#a855f7'
    bg = 'rgba(168, 85, 247, 0.12)'
  } else if (st === 'SUPPRESSED') {
    color = '#d97706'
    bg = 'rgba(217, 119, 6, 0.12)'
  } else if (st === 'NOTIFICATION_FAILED') {
    color = '#ef4444'
    bg = 'rgba(239, 68, 68, 0.12)'
  }

  return (
    <span
      style={{
        padding: '2px 8px',
        borderRadius: 999,
        fontSize: 10.5,
        fontWeight: 600,
        background: bg,
        color,
        border: `1px solid ${color}33`,
      }}
    >
      {st.replace(/_/g, ' ')}
    </span>
  )
}

export default function ErrorAlertsList({ highlightedEventId }) {
  const navigate = useNavigate()
  const [events, setEvents] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Filters
  const [search, setSearch] = useState('')
  const [severityFilter, setSeverityFilter] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [onlyUnresolved, setOnlyUnresolved] = useState(true)

  // Expanded technical details state
  const [expandedDetails, setExpandedDetails] = useState({})
  const [actionBusy, setActionBusy] = useState({})

  const fetchEvents = useCallback(async () => {
    setLoading(true)
    try {
      const params = {
        limit: 50,
        resolved: onlyUnresolved ? false : undefined,
      }
      if (severityFilter) params.severity = severityFilter
      if (categoryFilter) params.category = categoryFilter

      const res = await api.listNotifications(params)
      if (res) {
        setEvents(res.items || [])
        setTotal(res.total || 0)
        setError(null)
      }
    } catch (err) {
      setError(err.message || 'Failed to load error events')
    } finally {
      setLoading(false)
    }
  }, [onlyUnresolved, severityFilter, categoryFilter])

  useEffect(() => {
    fetchEvents()
    const timer = setInterval(fetchEvents, 20000)
    return () => clearInterval(timer)
  }, [fetchEvents])

  // Automatically expand highlighted event if provided
  useEffect(() => {
    if (highlightedEventId) {
      setExpandedDetails(prev => ({ ...prev, [highlightedEventId]: true }))
    }
  }, [highlightedEventId])

  const toggleDetails = (id) => {
    setExpandedDetails(prev => ({ ...prev, [id]: !prev[id] }))
  }

  const handleAcknowledge = async (id) => {
    setActionBusy(prev => ({ ...prev, [id]: true }))
    try {
      await api.acknowledgeNotification(id)
      setEvents(prev =>
        prev.map(ev => (ev.id === id ? { ...ev, status: 'ACKNOWLEDGED', acknowledged_at: new Date().toISOString() } : ev))
      )
    } catch (err) {
      alert(`Acknowledge failed: ${err.message}`)
    } finally {
      setActionBusy(prev => ({ ...prev, [id]: false }))
    }
  }

  const handleResolve = async (id) => {
    setActionBusy(prev => ({ ...prev, [id]: true }))
    try {
      await api.resolveNotification(id)
      if (onlyUnresolved) {
        setEvents(prev => prev.filter(ev => ev.id !== id))
        setTotal(prev => Math.max(0, prev - 1))
      } else {
        setEvents(prev =>
          prev.map(ev => (ev.id === id ? { ...ev, status: 'RESOLVED', resolved_at: new Date().toISOString() } : ev))
        )
      }
    } catch (err) {
      alert(`Resolve failed: ${err.message}`)
    } finally {
      setActionBusy(prev => ({ ...prev, [id]: false }))
    }
  }

  // Filter events locally by search term
  const filteredEvents = events.filter(ev => {
    if (!search.trim()) return true
    const q = search.toLowerCase()
    return (
      ev.title?.toLowerCase().includes(q) ||
      ev.message?.toLowerCase().includes(q) ||
      ev.workflow_name?.toLowerCase().includes(q) ||
      ev.code?.toLowerCase().includes(q) ||
      ev.connector_type?.toLowerCase().includes(q) ||
      ev.node_name?.toLowerCase().includes(q)
    )
  })

  return (
    <div className="error-alerts-container" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Controls & Filter Bar */}
      <div
        className="monitoring-card"
        style={{
          padding: '14px 16px',
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
        }}
      >
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10, flex: 1, minWidth: 280 }}>
          <div style={{ position: 'relative', width: 260 }}>
            <input
              type="text"
              placeholder="Search by workflow, error, node…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{
                width: '100%',
                padding: '7px 10px 7px 30px',
                fontSize: 12.5,
                borderRadius: 6,
                background: 'var(--panel-2, #0f172a)',
                border: '1px solid var(--border, #334155)',
                color: 'var(--text, #f1f5f9)',
              }}
            />
            <svg
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              style={{ position: 'absolute', left: 10, top: 10, color: 'var(--text-muted, #94a3b8)' }}
            >
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
          </div>

          <select
            value={severityFilter}
            onChange={e => setSeverityFilter(e.target.value)}
            style={{
              padding: '7px 10px',
              fontSize: 12.5,
              borderRadius: 6,
              background: 'var(--panel-2, #0f172a)',
              border: '1px solid var(--border, #334155)',
              color: 'var(--text, #f1f5f9)',
            }}
          >
            <option value="">All Severities</option>
            <option value="CRITICAL">Critical</option>
            <option value="ERROR">Error</option>
            <option value="WARNING">Warning</option>
            <option value="INFO">Info</option>
          </select>

          <select
            value={categoryFilter}
            onChange={e => setCategoryFilter(e.target.value)}
            style={{
              padding: '7px 10px',
              fontSize: 12.5,
              borderRadius: 6,
              background: 'var(--panel-2, #0f172a)',
              border: '1px solid var(--border, #334155)',
              color: 'var(--text, #f1f5f9)',
            }}
          >
            <option value="">All Categories</option>
            <option value="AUTH_SESSION_EXPIRED">Auth & Session Expired</option>
            <option value="CREDENTIAL_REVOKED">Credential Issues</option>
            <option value="CONNECTOR_RATE_LIMIT">API Rate Limit</option>
            <option value="NODE_EXECUTION_FAILED">Node Execution Failed</option>
            <option value="WORKFLOW_TIMEOUT">Timeout / Unavailable</option>
            <option value="SCHEMA_VALIDATION_ERROR">Schema & Variables</option>
            <option value="INFRASTRUCTURE_FAILURE">Worker & Infrastructure</option>
          </select>

          <label
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              fontSize: 12.5,
              color: 'var(--text, #f1f5f9)',
              cursor: 'pointer',
              userSelect: 'none',
              marginLeft: 4,
            }}
          >
            <input
              type="checkbox"
              checked={onlyUnresolved}
              onChange={e => setOnlyUnresolved(e.target.checked)}
              style={{ accentColor: '#6366f1' }}
            />
            <span>Unresolved only</span>
          </label>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span className="hint" style={{ fontSize: 12 }}>
            {filteredEvents.length < total
              ? `${filteredEvents.length} of ${total} alerts`
              : `${total} ${total === 1 ? 'alert' : 'alerts'}`}
          </span>
          <button
            className="ghost ghost--sm"
            onClick={fetchEvents}
            title="Refresh alerts"
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12 }}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="23 4 23 10 17 10" />
              <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
            </svg>
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="banner-inline err" style={{ padding: '10px 14px', borderRadius: 8 }}>
          {error}
        </div>
      )}

      {/* Events List */}
      {loading && filteredEvents.length === 0 ? (
        <div className="monitoring-card" style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
          Loading error monitoring records…
        </div>
      ) : filteredEvents.length === 0 ? (
        <div
          className="monitoring-card"
          style={{
            padding: '48px 24px',
            textAlign: 'center',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 12,
          }}
        >
          <div
            style={{
              width: 48,
              height: 48,
              borderRadius: '50%',
              background: 'rgba(16, 185, 129, 0.12)',
              color: '#10b981',
              display: 'grid',
              placeItems: 'center',
              fontSize: 22,
              fontWeight: 700,
            }}
          >
            ✓
          </div>
          <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)' }}>
            No Matching Error Events
          </div>
          <p style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)', maxWidth: 460 }}>
            {search || severityFilter || categoryFilter
              ? 'No errors match your filter criteria. Try clearing filters.'
              : 'All workflows, connectors, and scheduled triggers are running normally.'}
          </p>
        </div>
      ) : (
        filteredEvents.map(ev => {
          const isHighlighted = highlightedEventId === ev.id
          const isExpanded = Boolean(expandedDetails[ev.id])
          const busy = actionBusy[ev.id]

          return (
            <div
              key={ev.id}
              className="monitoring-card"
              style={{
                padding: '18px 20px',
                borderLeft: `4px solid ${
                  ev.severity === 'CRITICAL' ? '#e11d48' : ev.severity === 'WARNING' ? '#d97706' : '#ef4444'
                }`,
                background: isHighlighted ? 'rgba(99, 102, 241, 0.06)' : undefined,
                boxShadow: isHighlighted ? '0 0 0 1px #6366f1' : undefined,
                transition: 'all 0.2s ease',
              }}
            >
              {/* Header row */}
              <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginBottom: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <SeverityBadge severity={ev.severity} />
                  <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                    {ev.category?.replace(/_/g, ' ')}
                  </span>
                  <StatusPill status={ev.status} />
                </div>

                <div style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>
                  {ev.created_at ? new Date(ev.created_at).toLocaleString() : ''}
                </div>
              </div>

              {/* Title & Root Cause */}
              <h3 style={{ margin: '0 0 6px', fontSize: 15, fontWeight: 700, color: 'var(--text)' }}>
                {ev.title}
              </h3>
              <p style={{ margin: '0 0 14px', fontSize: 13.5, color: 'var(--text-muted)', lineHeight: 1.5 }}>
                {ev.message}
              </p>

              {/* Context Pill Row */}
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, fontSize: 12, color: 'var(--text-muted)', marginBottom: 14 }}>
                {ev.workflow_name && (
                  <div>
                    <span style={{ fontWeight: 600, color: 'var(--text)' }}>Workflow: </span>
                    <span>{ev.workflow_name}</span>
                  </div>
                )}
                {ev.node_name && (
                  <div>
                    <span style={{ fontWeight: 600, color: 'var(--text)' }}>Node: </span>
                    <span style={{ color: '#38bdf8' }}>{ev.node_name}</span>
                  </div>
                )}
                {ev.connector_type && (
                  <div>
                    <span style={{ fontWeight: 600, color: 'var(--text)' }}>Connector: </span>
                    <span style={{ textTransform: 'capitalize' }}>{ev.connector_type.replace('_', ' ')}</span>
                  </div>
                )}
                {ev.execution_id && (
                  <div>
                    <span style={{ fontWeight: 600, color: 'var(--text)' }}>Execution ID: </span>
                    <code style={{ fontSize: 11, padding: '1px 5px', borderRadius: 4, background: 'var(--panel-2)' }}>
                      {ev.execution_id.slice(0, 12)}…
                    </code>
                  </div>
                )}
              </div>

              {/* Recommended Action Callout */}
              {ev.resolution && (
                <div
                  style={{
                    background: 'rgba(37, 99, 235, 0.08)',
                    border: '1px solid rgba(37, 99, 235, 0.25)',
                    borderRadius: 8,
                    padding: '12px 14px',
                    marginBottom: 14,
                    display: 'flex',
                    alignItems: 'flex-start',
                    justifyContent: 'space-between',
                    gap: 12,
                    flexWrap: 'wrap',
                  }}
                >
                  <div style={{ flex: 1, minWidth: 200 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 700, color: '#38bdf8', marginBottom: 3 }}>
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="12" cy="12" r="10" />
                        <line x1="12" y1="16" x2="12" y2="12" />
                        <line x1="12" y1="8" x2="12.01" y2="8" />
                      </svg>
                      <span>RECOMMENDED RESOLUTION</span>
                    </div>
                    <div style={{ fontSize: 12.5, color: 'var(--text)', lineHeight: 1.45 }}>
                      {ev.resolution}
                    </div>
                  </div>

                  {/* Contextual Action Button */}
                  {ev.category === 'AUTH_SESSION_EXPIRED' || ev.category === 'CREDENTIAL_REVOKED' ? (
                    <button
                      className="primary small"
                      onClick={() => navigate('/credentials')}
                      style={{ padding: '6px 12px', fontSize: 12, fontWeight: 600, whiteSpace: 'nowrap' }}
                    >
                      Reconnect Credential →
                    </button>
                  ) : ev.execution_id ? (
                    <button
                      className="secondary small"
                      onClick={() => navigate(`/executions/${ev.execution_id}`)}
                      style={{ padding: '6px 12px', fontSize: 12, fontWeight: 600, whiteSpace: 'nowrap' }}
                    >
                      Review Execution →
                    </button>
                  ) : null}
                </div>
              )}

              {/* Technical Diagnostics Accordion */}
              {ev.technical_details && Object.keys(ev.technical_details).length > 0 && (
                <div style={{ marginBottom: 14 }}>
                  <button
                    className="ghost ghost--xs"
                    onClick={() => toggleDetails(ev.id)}
                    style={{ fontSize: 11, color: '#94a3b8', display: 'inline-flex', alignItems: 'center', gap: 4, padding: 0 }}
                  >
                    <span>{isExpanded ? '▼ Hide Diagnostics' : '▶ Show Technical Diagnostics (Sanitized)'}</span>
                  </button>

                  {isExpanded && (
                    <pre
                      style={{
                        marginTop: 8,
                        padding: 12,
                        borderRadius: 6,
                        background: 'var(--panel-2, #0f172a)',
                        border: '1px solid var(--border, #334155)',
                        color: '#cbd5e1',
                        fontSize: 11.5,
                        lineHeight: 1.5,
                        overflowX: 'auto',
                        maxHeight: 220,
                      }}
                    >
                      {JSON.stringify(ev.technical_details, null, 2)}
                    </pre>
                  )}
                </div>
              )}

              {/* Action Buttons Row */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 12,
                  borderTop: '1px solid var(--border)',
                  paddingTop: 12,
                }}
              >
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  {ev.status === 'NOTIFIED' ? '✓ Email Alert Sent' : ev.status === 'SUPPRESSED' ? 'Suppressed (Cooldown / Policy)' : 'Notification Pending'}
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  {ev.status !== 'ACKNOWLEDGED' && ev.status !== 'RESOLVED' && (
                    <button
                      className="ghost ghost--sm"
                      onClick={() => handleAcknowledge(ev.id)}
                      disabled={busy}
                      style={{ fontSize: 11.5, padding: '4px 10px' }}
                    >
                      Acknowledge
                    </button>
                  )}

                  {ev.status !== 'RESOLVED' ? (
                    <button
                      className="secondary small"
                      onClick={() => handleResolve(ev.id)}
                      disabled={busy}
                      style={{ fontSize: 11.5, padding: '4px 12px' }}
                    >
                      Mark Resolved
                    </button>
                  ) : (
                    <span style={{ fontSize: 11.5, color: '#10b981', fontWeight: 600 }}>
                      ✓ Resolved
                    </span>
                  )}
                </div>
              </div>
            </div>
          )
        })
      )}
    </div>
  )
}
