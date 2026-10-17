import { useState, useEffect, useCallback } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { api, getToken, setToken } from '../api'
import PageHeader from '../components/shared/PageHeader'
import LoadingSkeleton from '../components/shared/LoadingSkeleton'
import ErrorAlertsList from '../components/ErrorAlertsList'
import UniversalExecutionSearch from '../components/UniversalExecutionSearch'

function MonitoringStatCard({ title, value, subtitle, color, icon, badge }) {
  return (
    <div className="monitoring-card" style={{ padding: '16px 18px', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <span style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
          {title}
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {badge && (
            <span style={{ fontSize: 10.5, fontWeight: 700, padding: '1px 5px', borderRadius: 4, background: `${color}18`, color }}>
              {badge}
            </span>
          )}
          <span
            style={{
              fontSize: 13,
              width: 28,
              height: 28,
              borderRadius: 'var(--radius-xs, 4px)',
              display: 'grid',
              placeItems: 'center',
              background: `${color}14`,
              color,
              border: `1px solid ${color}28`,
            }}
          >
            {icon}
          </span>
        </div>
      </div>
      <div style={{ fontSize: 24, fontWeight: 600, color, letterSpacing: '-0.02em', lineHeight: 1.15 }}>
        {value}
      </div>
      {subtitle && (
        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 6, lineHeight: 1.4 }}>
          {subtitle}
        </div>
      )}
    </div>
  )
}

function HealthBar({ label, value, max, color }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 12.5, lineHeight: 1.4, marginBottom: 5 }}>
        <span style={{ color: 'var(--text)', fontWeight: 500 }}>{label}</span>
        <span style={{ color: 'var(--text-muted)', fontWeight: 600, fontSize: 12 }}>
          {value} <span style={{ color: 'var(--text-muted)', fontWeight: 400, opacity: 0.7 }}>/ {max}</span>
        </span>
      </div>
      <div style={{ height: 6, background: 'var(--panel-3)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 3, transition: 'width 0.3s ease' }} />
      </div>
    </div>
  )
}

function ExecutionTimeline({ stats }) {
  const hourTotal = (stats?.last_hour?.success || 0) + (stats?.last_hour?.failed || 0)
  const dayTotal = (stats?.last_24h?.success || 0) + (stats?.last_24h?.failed || 0)
  return (
    <div className="monitoring-card" style={{ padding: '18px 20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>Execution Activity</h3>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16 }}>
        <div style={{ background: 'var(--panel-2)', padding: '14px 16px', borderRadius: 'var(--radius-sm, 6px)', border: '1px solid var(--border)' }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 12 }}>Last Hour</div>
          <HealthBar
            label="Success"
            value={stats?.last_hour?.success || 0}
            max={Math.max(hourTotal, 1)}
            color="#059669"
          />
          <HealthBar
            label="Failed"
            value={stats?.last_hour?.failed || 0}
            max={Math.max(hourTotal, 1)}
            color="#e11d48"
          />
        </div>
        <div style={{ background: 'var(--panel-2)', padding: '14px 16px', borderRadius: 'var(--radius-sm, 6px)', border: '1px solid var(--border)' }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 12 }}>Last 24 Hours</div>
          <HealthBar
            label="Success"
            value={stats?.last_24h?.success || 0}
            max={Math.max(dayTotal, 1)}
            color="#059669"
          />
          <HealthBar
            label="Failed"
            value={stats?.last_24h?.failed || 0}
            max={Math.max(dayTotal, 1)}
            color="#e11d48"
          />
        </div>
      </div>
    </div>
  )
}

function QueueStatus({ stats }) {
  const isHealthy = (stats?.executions?.running || 0) < 10 && (stats?.executions?.queued || 0) < 50
  return (
    <div className="monitoring-card" style={{ padding: '18px 20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>Queue & Backlog</h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, background: isHealthy ? 'rgba(5, 150, 105, 0.08)' : 'rgba(225, 29, 72, 0.08)', border: `1px solid ${isHealthy ? 'rgba(5, 150, 105, 0.2)' : 'rgba(225, 29, 72, 0.2)'}`, padding: '2px 8px', borderRadius: 'var(--radius-xs, 4px)' }}>
          <div style={{
            width: 6, height: 6, borderRadius: '50%',
            background: isHealthy ? '#059669' : '#e11d48',
          }} />
          <span style={{ fontSize: 11.5, fontWeight: 500, color: isHealthy ? '#059669' : '#e11d48' }}>
            {isHealthy ? 'Normal' : 'Backpressure'}
          </span>
        </div>
      </div>
      <div style={{ background: 'var(--panel-2)', padding: '14px 16px', borderRadius: 'var(--radius-sm, 6px)', border: '1px solid var(--border)' }}>
        <HealthBar
          label="Running Concurrency"
          value={stats?.executions?.running || 0}
          max={10}
          color="#0284c7"
        />
        <HealthBar
          label="Queued Backlog"
          value={stats?.executions?.queued || 0}
          max={50}
          color="#d97706"
        />
      </div>
    </div>
  )
}

function SystemInfo({ stats }) {
  const uptimeH = Math.floor((stats?.uptime_seconds || 0) / 3600)
  const uptimeM = Math.floor(((stats?.uptime_seconds || 0) % 3600) / 60)
  return (
    <div className="monitoring-card" style={{ marginTop: 18, padding: '18px 20px' }}>
      <h3 style={{ margin: '0 0 14px', fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>System Infrastructure</h3>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
        <div style={{ background: 'var(--panel-2)', padding: '12px 14px', borderRadius: 'var(--radius-sm, 6px)', border: '1px solid var(--border)' }}>
          <div style={{ color: 'var(--text-muted)', fontSize: 11.5, fontWeight: 500, marginBottom: 4 }}>System Uptime</div>
          <div style={{ fontWeight: 600, fontSize: 16, color: 'var(--text)', lineHeight: 1.3 }}>{uptimeH}h {uptimeM}m</div>
        </div>
        <div style={{ background: 'var(--panel-2)', padding: '12px 14px', borderRadius: 'var(--radius-sm, 6px)', border: '1px solid var(--border)' }}>
          <div style={{ color: 'var(--text-muted)', fontSize: 11.5, fontWeight: 500, marginBottom: 4 }}>Total Workflows</div>
          <div style={{ fontWeight: 600, fontSize: 16, color: 'var(--text)', lineHeight: 1.3 }}>{stats?.workflows?.total || 0}</div>
        </div>
        <div style={{ background: 'var(--panel-2)', padding: '12px 14px', borderRadius: 'var(--radius-sm, 6px)', border: '1px solid var(--border)' }}>
          <div style={{ color: 'var(--text-muted)', fontSize: 11.5, fontWeight: 500, marginBottom: 4 }}>Active Workflows</div>
          <div style={{ fontWeight: 600, fontSize: 16, color: '#059669', lineHeight: 1.3 }}>{stats?.workflows?.active || 0}</div>
        </div>
        <div style={{ background: 'var(--panel-2)', padding: '12px 14px', borderRadius: 'var(--radius-sm, 6px)', border: '1px solid var(--border)' }}>
          <div style={{ color: 'var(--text-muted)', fontSize: 11.5, fontWeight: 500, marginBottom: 4 }}>Total Executions</div>
          <div style={{ fontWeight: 600, fontSize: 16, color: 'var(--text)', lineHeight: 1.3 }}>{stats?.executions?.total || 0}</div>
        </div>
        <div style={{ background: 'var(--panel-2)', padding: '12px 14px', borderRadius: 'var(--radius-sm, 6px)', border: '1px solid var(--border)' }}>
          <div style={{ color: 'var(--text-muted)', fontSize: 11.5, fontWeight: 500, marginBottom: 4 }}>Webhook Deliveries (1h)</div>
          <div style={{ fontWeight: 600, fontSize: 16, color: 'var(--text)', lineHeight: 1.3 }}>{stats?.webhooks?.last_hour || 0}</div>
        </div>
        <div style={{ background: 'var(--panel-2)', padding: '12px 14px', borderRadius: 'var(--radius-sm, 6px)', border: '1px solid var(--border)' }}>
          <div style={{ color: 'var(--text-muted)', fontSize: 11.5, fontWeight: 500, marginBottom: 4 }}>Total Deliveries</div>
          <div style={{ fontWeight: 600, fontSize: 16, color: 'var(--text)', lineHeight: 1.3 }}>{stats?.webhooks?.total || 0}</div>
        </div>
      </div>
    </div>
  )
}

function getDateRangeIso(preset) {
  if (!preset || preset === 'all') return { fromDate: undefined, toDate: undefined }
  const now = new Date()
  let from = new Date(now)
  if (preset === '1h') from.setHours(from.getHours() - 1)
  else if (preset === '24h') from.setDate(from.getDate() - 1)
  else if (preset === '7d') from.setDate(from.getDate() - 7)
  else if (preset === '30d') from.setDate(from.getDate() - 30)
  return { fromDate: from.toISOString(), toDate: now.toISOString() }
}

const DATE_OPTIONS = [
  { id: '24h', label: 'Last 24 Hours' },
  { id: '1h', label: 'Last 1 Hour' },
  { id: '7d', label: 'Last 7 Days' },
  { id: '30d', label: 'Last 30 Days' },
  { id: 'all', label: 'All Time' },
]

export default function MonitoringPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  const qTab = searchParams.get('tab')
  const defaultTab = qTab === 'telemetry' || qTab === 'alerts' ? qTab : 'summary'
  const [tab, setTab] = useState(defaultTab)

  const [datePreset, setDatePreset] = useState(searchParams.get('range') || '24h')
  const highlightedEventId = searchParams.get('event_id')

  // Summary Metrics State (Cyclr-style integration telemetry)
  const [summary, setSummary] = useState(null)
  const [loadingSummary, setLoadingSummary] = useState(true)

  // Cluster Runtime Stats & Alert Stats
  const [stats, setStats] = useState(null)
  const [alertStats, setAlertStats] = useState({ unresolved_count: 0, critical_count: 0 })
  const [loadingCluster, setLoadingCluster] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    const t = searchParams.get('tab')
    if (t === 'telemetry' || t === 'alerts') {
      setTab(t)
    } else if (t === 'summary' || !t) {
      setTab('summary')
    }
  }, [searchParams])

  const fetchSummary = useCallback(() => {
    setLoadingSummary(true)
    const { fromDate, toDate } = getDateRangeIso(datePreset)
    api
      .getMonitoringSummary({ fromDate, toDate })
      .then((data) => {
        setSummary(data)
      })
      .catch((err) => {
        console.error('Error fetching monitoring summary', err)
      })
      .finally(() => setLoadingSummary(false))
  }, [datePreset])

  const fetchClusterStats = useCallback(() => {
    api
      .getMonitoringStats()
      .then((data) => {
        setStats(data)
        setError(null)
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoadingCluster(false))
  }, [])

  const fetchAlertStats = useCallback(() => {
    api
      .getNotificationStats()
      .then((data) => {
        if (data) setAlertStats(data)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    fetchSummary()
    fetchClusterStats()
    fetchAlertStats()

    const timer = setInterval(() => {
      if (typeof document !== 'undefined' && document.hidden) return
      fetchSummary()
      fetchClusterStats()
      fetchAlertStats()
    }, 12000)

    const handleVisibility = () => {
      if (typeof document !== 'undefined' && !document.hidden) {
        fetchSummary()
        fetchClusterStats()
        fetchAlertStats()
      }
    }
    document.addEventListener('visibilitychange', handleVisibility)

    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [fetchSummary, fetchClusterStats, fetchAlertStats])

  const openMetricsExporter = async (e) => {
    e.preventDefault()
    const bearer = getToken()
    try {
      const res = await fetch('/api/metrics', {
        headers: bearer ? { Authorization: `Bearer ${bearer}` } : {},
      })
      if (res.status === 401) {
        setToken(null)
        window.dispatchEvent(new Event('auth:expired'))
        return
      }
      if (!res.ok) throw new Error(`Export failed: ${res.statusText}`)
      const blob = await res.blob()
      const url = window.URL.createObjectURL(blob)
      window.open(url, '_blank', 'noopener,noreferrer')
      setTimeout(() => window.URL.revokeObjectURL(url), 60000)
    } catch (err) {
      console.error('metrics exporter open failed', err)
    }
  }

  function handleTabChange(nextTab) {
    setTab(nextTab)
    setSearchParams((p) => {
      p.set('tab', nextTab)
      return p
    })
  }

  function handleRangeChange(preset) {
    setDatePreset(preset)
    setSearchParams((p) => {
      p.set('range', preset)
      return p
    })
  }

  return (
    <div className="page monitoring-page">
      {error && (
        <div className="banner-inline err" style={{ marginBottom: 12 }}>
          Live telemetry update notice: {error} — auto-retrying.
        </div>
      )}

      <PageHeader
        title="Central Monitoring & Diagnostics"
        description="Global integration execution health, Cyclr-style telemetry, API throughput, and cluster error diagnostics."
        actions={
          <div className="monitoring-toolbar" role="toolbar" aria-label="Monitoring controls">
            <div className="monitoring-live-badge" title="Live telemetry: auto-updating continuously in background">
              <span className="monitoring-pulse-dot" />
              <span>Live Engine</span>
            </div>

            <div className="monitoring-toolbar-divider" />

            <a
              href="/api/metrics"
              onClick={openMetricsExporter}
              target="_blank"
              rel="noopener noreferrer"
              className="monitoring-btn-exporter"
              title="Open raw Prometheus & OpenTelemetry scrape endpoint"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
              </svg>
              <span>Prometheus Scraper</span>
              <span className="monitoring-exporter-badge">↗</span>
            </a>
          </div>
        }
      />

      {/* Universal Execution & Telemetry Search Bar */}
      <div style={{ marginBottom: 18 }}>
        <UniversalExecutionSearch
          placeholder="Search all execution logs, errors, steps, API payloads, or records from Monitoring..."
          onSearch={(q, cat) => {
            if (q && q.trim()) {
              navigate(`/executions?search=${encodeURIComponent(q.trim())}${cat && cat !== 'all' ? `&category=${cat}` : ''}`)
            }
          }}
        />
      </div>

      {/* Primary Tab Navigation */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          borderBottom: '1px solid var(--border)',
          marginBottom: 20,
          flexWrap: 'wrap',
          gap: 12,
        }}
      >
        <div style={{ display: 'flex', gap: 6 }}>
          <button
            type="button"
            onClick={() => handleTabChange('summary')}
            style={{
              padding: '10px 16px',
              fontSize: 13,
              fontWeight: 600,
              cursor: 'pointer',
              borderBottom: tab === 'summary' ? '2px solid #6366f1' : '2px solid transparent',
              color: tab === 'summary' ? '#818cf8' : 'var(--text-muted)',
              background: 'transparent',
              borderTop: 'none',
              borderLeft: 'none',
              borderRight: 'none',
            }}
          >
            Integration Health & Telemetry
          </button>

          <button
            type="button"
            onClick={() => handleTabChange('telemetry')}
            style={{
              padding: '10px 16px',
              fontSize: 13,
              fontWeight: 600,
              cursor: 'pointer',
              borderBottom: tab === 'telemetry' ? '2px solid #6366f1' : '2px solid transparent',
              color: tab === 'telemetry' ? '#818cf8' : 'var(--text-muted)',
              background: 'transparent',
              borderTop: 'none',
              borderLeft: 'none',
              borderRight: 'none',
            }}
          >
            Cluster & Runtime Telemetry
          </button>

          <button
            type="button"
            onClick={() => handleTabChange('alerts')}
            style={{
              padding: '10px 16px',
              fontSize: 13,
              fontWeight: 600,
              cursor: 'pointer',
              borderBottom: tab === 'alerts' ? '2px solid #6366f1' : '2px solid transparent',
              color: tab === 'alerts' ? '#818cf8' : 'var(--text-muted)',
              background: 'transparent',
              borderTop: 'none',
              borderLeft: 'none',
              borderRight: 'none',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 8,
            }}
          >
            <span>Error Alerts & Notifications</span>
            {alertStats.unresolved_count > 0 && (
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  padding: '1px 7px',
                  borderRadius: 999,
                  background: alertStats.critical_count > 0 ? '#e11d48' : '#f59e0b',
                  color: '#fff',
                }}
              >
                {alertStats.unresolved_count}
              </span>
            )}
          </button>
        </div>

        {/* Date Range Selector Pill Set (Active on summary tab) */}
        {tab === 'summary' && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
            <span style={{ fontSize: 11.5, color: 'var(--text-muted)', marginRight: 2 }}>Timeframe:</span>
            {DATE_OPTIONS.map((opt) => (
              <button
                key={opt.id}
                type="button"
                className={`ghost ${datePreset === opt.id ? 'active' : ''}`}
                onClick={() => handleRangeChange(opt.id)}
                style={{
                  fontSize: 11.5,
                  padding: '3px 9px',
                  borderRadius: 6,
                  background: datePreset === opt.id ? 'rgba(99, 102, 241, 0.25)' : 'rgba(255, 255, 255, 0.03)',
                  color: datePreset === opt.id ? '#ffffff' : '#94a3b8',
                  border: `1px solid ${datePreset === opt.id ? 'rgba(99, 102, 241, 0.5)' : 'rgba(255, 255, 255, 0.08)'}`,
                  fontWeight: datePreset === opt.id ? 600 : 400,
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Tab 1: Integration & Execution Health (Cyclr Metrics) */}
      {tab === 'summary' && (
        <div>
          {loadingSummary && !summary ? (
            <LoadingSkeleton rows={8} />
          ) : (
            <>
              {/* 8 Summary Metric Cards Grid */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))',
                  gap: 14,
                  marginBottom: 20,
                }}
              >
                {/* 1. Total Executions */}
                <MonitoringStatCard
                  title="Total Executions"
                  value={(summary?.total_executions || 0).toLocaleString()}
                  color="#f8fafc"
                  icon={
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                    </svg>
                  }
                  subtitle={`${summary?.running_executions || 0} active in-flight`}
                />

                {/* 2. Successful Executions */}
                <MonitoringStatCard
                  title="Successful Executions"
                  value={(summary?.successful_executions || 0).toLocaleString()}
                  color="#10b981"
                  icon={
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                  }
                  subtitle="Completed with 0 errors"
                />

                {/* 3. Failed Executions */}
                <MonitoringStatCard
                  title="Failed Executions"
                  value={(summary?.failed_executions || 0).toLocaleString()}
                  color="#ef4444"
                  icon={
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <line x1="18" y1="6" x2="6" y2="18" />
                      <line x1="6" y1="6" x2="18" y2="18" />
                    </svg>
                  }
                  subtitle="Diagnosed error outcomes"
                />

                {/* 4. Success Rate % */}
                <MonitoringStatCard
                  title="Success Rate"
                  value={`${summary?.success_rate_percent ?? 100}%`}
                  color={
                    (summary?.success_rate_percent ?? 100) >= 98
                      ? '#10b981'
                      : (summary?.success_rate_percent ?? 100) >= 90
                      ? '#f59e0b'
                      : '#ef4444'
                  }
                  icon={
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <circle cx="12" cy="12" r="10" />
                      <path d="M12 6v6l4 2" />
                    </svg>
                  }
                  badge="SLA Target 99%"
                  subtitle="Across all integration nodes"
                />

                {/* 5. Total Records Processed */}
                <MonitoringStatCard
                  title="Records Processed"
                  value={(summary?.total_records_processed || 0).toLocaleString()}
                  color="#38bdf8"
                  icon={
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <ellipse cx="12" cy="5" rx="9" ry="3" />
                      <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
                      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
                    </svg>
                  }
                  subtitle="Payload items processed"
                />

                {/* 6. Outbound API Calls */}
                <MonitoringStatCard
                  title="Outbound API Calls"
                  value={(summary?.total_api_calls || 0).toLocaleString()}
                  color="#818cf8"
                  icon={
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <circle cx="12" cy="12" r="10" />
                      <line x1="2" y1="12" x2="22" y2="12" />
                      <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
                    </svg>
                  }
                  subtitle="Network requests traced"
                />

                {/* 7. Average Duration */}
                <MonitoringStatCard
                  title="Average Duration"
                  value={
                    summary?.avg_duration_ms != null
                      ? summary.avg_duration_ms < 1000
                        ? `${Math.round(summary.avg_duration_ms)}ms`
                        : `${(summary.avg_duration_ms / 1000).toFixed(2)}s`
                      : '—'
                  }
                  color="#c084fc"
                  icon={
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <circle cx="12" cy="12" r="10" />
                      <polyline points="12 6 12 12 14 14" />
                    </svg>
                  }
                  subtitle="Runtime execution latency"
                />

                {/* 8. Total Retries Attempted */}
                <MonitoringStatCard
                  title="Retries Attempted"
                  value={(summary?.total_retries || 0).toLocaleString()}
                  color="#f59e0b"
                  icon={
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <polyline points="1 4 1 10 7 10" />
                      <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" />
                    </svg>
                  }
                  subtitle="Idempotent auto/manual replays"
                />
              </div>

              {/* Error Taxonomy & Diagnostic Categories */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))',
                  gap: 16,
                  marginBottom: 20,
                }}
              >
                {/* Error Breakdown Panel */}
                <div className="monitoring-card" style={{ padding: '18px 20px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
                    <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>
                      Failure Taxonomy & Diagnostics
                    </h3>
                    <span className="hint" style={{ fontSize: 11.5 }}>
                      Click any category to view logs
                    </span>
                  </div>

                  {summary?.error_breakdown && Object.keys(summary.error_breakdown).length > 0 ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                      {Object.entries(summary.error_breakdown).map(([cat, count]) => {
                        const totalErr = summary.failed_executions || 1
                        const pct = Math.round((count / totalErr) * 100)
                        return (
                          <button
                            key={cat}
                            type="button"
                            onClick={() => navigate(`/executions?error_type=${cat}`)}
                            style={{
                              display: 'flex',
                              flexDirection: 'column',
                              gap: 4,
                              background: 'var(--panel-2)',
                              border: '1px solid var(--border)',
                              borderRadius: 7,
                              padding: '10px 12px',
                              cursor: 'pointer',
                              textAlign: 'left',
                              transition: 'all 0.15s ease',
                            }}
                          >
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                              <span style={{ fontWeight: 600, fontSize: 12.5, color: '#f8fafc' }}>
                                {cat}
                              </span>
                              <span style={{ fontSize: 12, fontWeight: 700, color: '#f87171' }}>
                                {count} <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--text-muted)' }}>({pct}%)</span>
                              </span>
                            </div>
                            <div style={{ height: 4, background: 'rgba(255,255,255,0.06)', borderRadius: 2, overflow: 'hidden' }}>
                              <div style={{ height: '100%', width: `${pct}%`, background: '#ef4444', borderRadius: 2 }} />
                            </div>
                          </button>
                        )
                      })}
                    </div>
                  ) : (
                    <div style={{ padding: 24, textAlign: 'center', color: '#10b981', fontSize: 13 }}>
                      ✓ Zero integration errors detected in this timeframe. All executions healthy!
                    </div>
                  )}
                </div>

                {/* Quick Diagnostics & Operations Links */}
                <div className="monitoring-card" style={{ padding: '18px 20px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                  <div>
                    <h3 style={{ margin: '0 0 12px', fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>
                      Integration Operations
                    </h3>
                    <p style={{ margin: '0 0 16px', fontSize: 12.5, color: 'var(--text-muted)', lineHeight: 1.5 }}>
                      Review granular execution traces, inspect live request & response network payloads, export sanitized CSV audits, or configure automatic alert policies.
                    </p>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      <button
                        type="button"
                        className="ghost"
                        onClick={() => navigate('/executions')}
                        style={{ justifyContent: 'space-between', display: 'flex', alignItems: 'center', padding: '10px 14px' }}
                      >
                        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <line x1="8" y1="6" x2="21" y2="6" />
                            <line x1="8" y1="12" x2="21" y2="12" />
                            <line x1="8" y1="18" x2="21" y2="18" />
                            <line x1="3" y1="6" x2="3.01" y2="6" />
                            <line x1="3" y1="12" x2="3.01" y2="12" />
                            <line x1="3" y1="18" x2="3.01" y2="18" />
                          </svg>
                          <span>Open Execution Logs Table</span>
                        </span>
                        <span>→</span>
                      </button>

                      <button
                        type="button"
                        className="ghost"
                        onClick={() => navigate('/executions?status=failed')}
                        style={{ justifyContent: 'space-between', display: 'flex', alignItems: 'center', padding: '10px 14px', color: '#f87171' }}
                      >
                        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <circle cx="12" cy="12" r="10" />
                            <line x1="15" y1="9" x2="9" y2="15" />
                            <line x1="9" y1="9" x2="15" y2="15" />
                          </svg>
                          <span>Review Failed Runs ({summary?.failed_executions || 0})</span>
                        </span>
                        <span>→</span>
                      </button>

                      <button
                        type="button"
                        className="ghost"
                        onClick={() => handleTabChange('alerts')}
                        style={{ justifyContent: 'space-between', display: 'flex', alignItems: 'center', padding: '10px 14px' }}
                      >
                        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                            <path d="M13.73 21a2 2 0 0 1-3.46 0" />
                          </svg>
                          <span>Manage Notification & Alert Policies</span>
                        </span>
                        <span>→</span>
                      </button>
                    </div>
                  </div>

                  <div style={{ marginTop: 16, paddingTop: 12, borderTop: '1px solid var(--border)', fontSize: 11.5, color: 'var(--text-muted)' }}>
                    Auto-refreshed via Flowsmith async telemetry collector every 12 seconds.
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {/* Tab 2: Cluster & Runtime Telemetry (Existing Queue & Infra Views) */}
      {tab === 'telemetry' && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 14, marginBottom: 20 }}>
            <MonitoringStatCard
              title="Running Executions"
              value={stats?.executions?.running || 0}
              color="#38bdf8"
              icon={
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                </svg>
              }
              subtitle="Active in worker runtime"
            />
            <MonitoringStatCard
              title="Queued Runs"
              value={stats?.executions?.queued || 0}
              color="#f59e0b"
              icon={
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10" />
                  <polyline points="12 6 12 12 16 14" />
                </svg>
              }
              subtitle="Awaiting available slot"
            />
            <MonitoringStatCard
              title="Success (Past 1h)"
              value={stats?.last_hour?.success || 0}
              color="#10b981"
              icon={
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              }
              subtitle="Completed without error"
            />
            <MonitoringStatCard
              title="Failed (Past 1h)"
              value={stats?.last_hour?.failed || 0}
              color="#ef4444"
              icon={
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              }
              subtitle="Errored execution runs"
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: 18, marginBottom: 20 }}>
            <ExecutionTimeline stats={stats} />
            <QueueStatus stats={stats} />
          </div>

          <SystemInfo stats={stats} />
        </>
      )}

      {/* Tab 3: Error Alerts & Notifications (Existing Alerts List) */}
      {tab === 'alerts' && (
        <ErrorAlertsList highlightedEventId={highlightedEventId} />
      )}
    </div>
  )
}
