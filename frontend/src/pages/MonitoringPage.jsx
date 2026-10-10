import { useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, getToken, setToken } from '../api'
import PageHeader from '../components/shared/PageHeader'
import LoadingSkeleton from '../components/shared/LoadingSkeleton'
import ErrorAlertsList from '../components/ErrorAlertsList'

function renderStatIcon(type) {
  switch (type) {
    case 'running':
      return (
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
        </svg>
      )
    case 'queued':
      return (
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <polyline points="12 6 12 12 16 14" />
        </svg>
      )
    case 'success':
      return (
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="20 6 9 17 4 12" />
        </svg>
      )
    case 'failed':
      return (
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <line x1="18" y1="6" x2="6" y2="18" />
          <line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      )
    default:
      return null
  }
}

function MonitoringStatCard({ title, value, subtitle, color, icon }) {
  return (
    <div className="monitoring-card" style={{ padding: '16px 18px', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <span style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{title}</span>
        <span style={{ fontSize: 13, width: 28, height: 28, borderRadius: 'var(--radius-xs, 4px)', display: 'grid', placeItems: 'center', background: `${color}14`, color, border: `1px solid ${color}28` }}>{icon}</span>
      </div>
      <div style={{ fontSize: 24, fontWeight: 600, color, letterSpacing: '-0.02em', lineHeight: 1.15 }}>{value}</div>
      {subtitle && <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 6, lineHeight: 1.4 }}>{subtitle}</div>}
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

export default function MonitoringPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const currentTab = searchParams.get('tab') === 'telemetry' ? 'telemetry' : 'alerts'
  const [tab, setTab] = useState(currentTab)
  const highlightedEventId = searchParams.get('event_id')
  const [alertStats, setAlertStats] = useState({ unresolved_count: 0, critical_count: 0 })

  useEffect(() => {
    const qTab = searchParams.get('tab')
    if (qTab === 'telemetry') {
      setTab('telemetry')
    } else if (qTab === 'alerts' || !qTab) {
      setTab('alerts')
    }
  }, [searchParams])

  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const fetchStats = useCallback(() => {
    api.getMonitoringStats()
      .then((data) => {
        setStats(data)
        setError(null)
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  const fetchAlertStats = useCallback(() => {
    api.getNotificationStats()
      .then((data) => {
        if (data) setAlertStats(data)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    fetchStats()
    fetchAlertStats()
    // Automatic live background telemetry refresh (10s interval)
    const timer = setInterval(() => {
      if (typeof document !== 'undefined' && document.hidden) return
      fetchStats()
      fetchAlertStats()
    }, 10000)

    const handleVisibility = () => {
      if (typeof document !== 'undefined' && !document.hidden) {
        fetchStats()
        fetchAlertStats()
      }
    }
    document.addEventListener('visibilitychange', handleVisibility)

    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [fetchStats, fetchAlertStats])

  // Fetch the scrape endpoint with the bearer header and open the blob —
  // a plain href would need ?token= and leak the JWT into history/Referer.
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

  if (loading && !stats && tab === 'telemetry') return <div className="page monitoring-page"><LoadingSkeleton rows={6} /></div>
  if (error && !stats && tab === 'telemetry') return <div className="page monitoring-page"><div className="banner-inline err">Error: {error}</div></div>

  return (
    <div className="page monitoring-page">
      {error && (
        <div className="banner-inline err" style={{ marginBottom: 12 }}>
          Live telemetry update paused: {error} — retrying automatically.
        </div>
      )}
      <PageHeader
        title="Central Monitoring & Alert Center"
        description="Global error monitoring, automatic email alerts, worker throughput, and cluster telemetry."
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
              title="Open raw Prometheus & OpenTelemetry text scrape endpoint"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
              </svg>
              <span>Prometheus Exporter</span>
              <span className="monitoring-exporter-badge">↗</span>
            </a>
          </div>
        }
      />

      {/* Primary Tab Navigation */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 20, borderBottom: '1px solid var(--border)' }}>
        <button
          type="button"
          onClick={() => {
            setTab('alerts')
            setSearchParams(p => { p.set('tab', 'alerts'); return p })
          }}
          style={{
            padding: '10px 18px',
            fontSize: 13,
            fontWeight: 600,
            cursor: 'pointer',
            borderBottom: tab === 'alerts' ? '2px solid #6366f1' : '2px solid transparent',
            color: tab === 'alerts' ? '#6366f1' : 'var(--text-muted)',
            background: 'transparent',
            borderTop: 'none', borderLeft: 'none', borderRight: 'none',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
          }}
        >
          <span>Error Monitoring & Alerts</span>
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

        <button
          type="button"
          onClick={() => {
            setTab('telemetry')
            setSearchParams(p => { p.set('tab', 'telemetry'); return p })
          }}
          style={{
            padding: '10px 18px',
            fontSize: 13,
            fontWeight: 600,
            cursor: 'pointer',
            borderBottom: tab === 'telemetry' ? '2px solid #6366f1' : '2px solid transparent',
            color: tab === 'telemetry' ? '#6366f1' : 'var(--text-muted)',
            background: 'transparent',
            borderTop: 'none', borderLeft: 'none', borderRight: 'none',
          }}
        >
          Cluster & Runtime Telemetry
        </button>
      </div>

      {tab === 'alerts' ? (
        <ErrorAlertsList highlightedEventId={highlightedEventId} />
      ) : (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 14, marginBottom: 20 }}>
            <MonitoringStatCard title="Running Executions" value={stats?.executions?.running || 0} color="#38bdf8" icon={renderStatIcon('running')} subtitle="Currently active in runtime" />
            <MonitoringStatCard title="Queued Runs" value={stats?.executions?.queued || 0} color="#f59e0b" icon={renderStatIcon('queued')} subtitle="Waiting for available worker" />
            <MonitoringStatCard title="Success (Past 1h)" value={stats?.last_hour?.success || 0} color="#10b981" icon={renderStatIcon('success')} subtitle="Completed without error" />
            <MonitoringStatCard title="Failed (Past 1h)" value={stats?.last_hour?.failed || 0} color="#ef4444" icon={renderStatIcon('failed')} subtitle="Errored execution runs" />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: 18, marginBottom: 20 }}>
            <ExecutionTimeline stats={stats} />
            <QueueStatus stats={stats} />
          </div>

          <SystemInfo stats={stats} />
        </>
      )}
    </div>
  )
}
