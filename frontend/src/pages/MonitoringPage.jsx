import { useState, useEffect, useCallback } from 'react'
import { api } from '../api'
import PageHeader from '../components/shared/PageHeader'
import LoadingSkeleton from '../components/shared/LoadingSkeleton'

function MonitoringStatCard({ title, value, subtitle, color, icon }) {
  return (
    <div className="monitoring-card" style={{ padding: '20px 22px', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <span style={{ fontSize: 12.5, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{title}</span>
        <span style={{ fontSize: 15, width: 32, height: 32, borderRadius: 8, display: 'grid', placeItems: 'center', background: `${color}18`, color, border: `1px solid ${color}33` }}>{icon}</span>
      </div>
      <div style={{ fontSize: 32, fontWeight: 800, color, letterSpacing: '-0.02em', lineHeight: 1.15 }}>{value}</div>
      {subtitle && <div style={{ fontSize: 12, color: '#64748b', marginTop: 8, lineHeight: 1.4 }}>{subtitle}</div>}
    </div>
  )
}

function HealthBar({ label, value, max, color }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 13, lineHeight: 1.5, marginBottom: 6 }}>
        <span style={{ color: '#e2e8f0', fontWeight: 500 }}>{label}</span>
        <span style={{ color: '#94a3b8', fontWeight: 600, fontSize: 12 }}>
          {value} <span style={{ color: '#64748b', fontWeight: 400 }}>/ {max}</span>
        </span>
      </div>
      <div style={{ height: 8, background: 'rgba(255, 255, 255, 0.06)', borderRadius: 4, overflow: 'hidden', border: '1px solid rgba(255, 255, 255, 0.05)' }}>
        <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 4, transition: 'width 0.4s ease' }} />
      </div>
    </div>
  )
}

function ExecutionTimeline({ stats }) {
  const hourTotal = (stats?.last_hour?.success || 0) + (stats?.last_hour?.failed || 0)
  const dayTotal = (stats?.last_24h?.success || 0) + (stats?.last_24h?.failed || 0)
  return (
    <div className="monitoring-card">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 18 }}>
        <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: '#f8fafc' }}>Execution Activity</h3>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 20 }}>
        <div style={{ background: 'rgba(255,255,255,0.02)', padding: '16px 18px', borderRadius: 10, border: '1px solid rgba(255,255,255,0.04)' }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 14 }}>Last Hour</div>
          <HealthBar
            label="Success"
            value={stats?.last_hour?.success || 0}
            max={Math.max(hourTotal, 1)}
            color="#10b981"
          />
          <HealthBar
            label="Failed"
            value={stats?.last_hour?.failed || 0}
            max={Math.max(hourTotal, 1)}
            color="#ef4444"
          />
        </div>
        <div style={{ background: 'rgba(255,255,255,0.02)', padding: '16px 18px', borderRadius: 10, border: '1px solid rgba(255,255,255,0.04)' }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 14 }}>Last 24 Hours</div>
          <HealthBar
            label="Success"
            value={stats?.last_24h?.success || 0}
            max={Math.max(dayTotal, 1)}
            color="#10b981"
          />
          <HealthBar
            label="Failed"
            value={stats?.last_24h?.failed || 0}
            max={Math.max(dayTotal, 1)}
            color="#ef4444"
          />
        </div>
      </div>
    </div>
  )
}

function QueueStatus({ stats }) {
  const isHealthy = (stats?.executions?.running || 0) < 10 && (stats?.executions?.queued || 0) < 50
  return (
    <div className="monitoring-card">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 18 }}>
        <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: '#f8fafc' }}>Queue Status</h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, background: isHealthy ? 'rgba(16, 185, 129, 0.12)' : 'rgba(239, 68, 68, 0.12)', border: `1px solid ${isHealthy ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`, padding: '4px 10px', borderRadius: 999 }}>
          <div style={{
            width: 8, height: 8, borderRadius: '50%',
            background: isHealthy ? '#10b981' : '#ef4444',
            boxShadow: `0 0 8px ${isHealthy ? '#10b981' : '#ef4444'}`,
          }} />
          <span style={{ fontSize: 12, fontWeight: 600, color: isHealthy ? '#10b981' : '#ef4444' }}>
            {isHealthy ? 'Cluster Healthy' : 'Backpressure Detected'}
          </span>
        </div>
      </div>
      <div style={{ background: 'rgba(255,255,255,0.02)', padding: '16px 18px', borderRadius: 10, border: '1px solid rgba(255,255,255,0.04)' }}>
        <HealthBar
          label="Running Concurrency"
          value={stats?.executions?.running || 0}
          max={10}
          color="#38bdf8"
        />
        <HealthBar
          label="Queued Backlog"
          value={stats?.executions?.queued || 0}
          max={50}
          color="#f59e0b"
        />
      </div>
    </div>
  )
}

function SystemInfo({ stats }) {
  const uptimeH = Math.floor((stats?.uptime_seconds || 0) / 3600)
  const uptimeM = Math.floor(((stats?.uptime_seconds || 0) % 3600) / 60)
  return (
    <div className="monitoring-card" style={{ marginTop: 20 }}>
      <h3 style={{ margin: '0 0 16px', fontSize: 16, fontWeight: 700, color: '#f8fafc' }}>System Infrastructure</h3>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16 }}>
        <div style={{ background: 'rgba(255,255,255,0.02)', padding: '14px 18px', borderRadius: 10, border: '1px solid rgba(255,255,255,0.04)' }}>
          <div style={{ color: '#94a3b8', fontSize: 12, fontWeight: 500, marginBottom: 4 }}>System Uptime</div>
          <div style={{ fontWeight: 700, fontSize: 18, color: '#f8fafc', lineHeight: 1.3 }}>{uptimeH}h {uptimeM}m</div>
        </div>
        <div style={{ background: 'rgba(255,255,255,0.02)', padding: '14px 18px', borderRadius: 10, border: '1px solid rgba(255,255,255,0.04)' }}>
          <div style={{ color: '#94a3b8', fontSize: 12, fontWeight: 500, marginBottom: 4 }}>Total Workflows</div>
          <div style={{ fontWeight: 700, fontSize: 18, color: '#f8fafc', lineHeight: 1.3 }}>{stats?.workflows?.total || 0}</div>
        </div>
        <div style={{ background: 'rgba(255,255,255,0.02)', padding: '14px 18px', borderRadius: 10, border: '1px solid rgba(255,255,255,0.04)' }}>
          <div style={{ color: '#94a3b8', fontSize: 12, fontWeight: 500, marginBottom: 4 }}>Active Workflows</div>
          <div style={{ fontWeight: 700, fontSize: 18, color: '#10b981', lineHeight: 1.3 }}>{stats?.workflows?.active || 0}</div>
        </div>
        <div style={{ background: 'rgba(255,255,255,0.02)', padding: '14px 18px', borderRadius: 10, border: '1px solid rgba(255,255,255,0.04)' }}>
          <div style={{ color: '#94a3b8', fontSize: 12, fontWeight: 500, marginBottom: 4 }}>Total Executions</div>
          <div style={{ fontWeight: 700, fontSize: 18, color: '#f8fafc', lineHeight: 1.3 }}>{stats?.executions?.total || 0}</div>
        </div>
        <div style={{ background: 'rgba(255,255,255,0.02)', padding: '14px 18px', borderRadius: 10, border: '1px solid rgba(255,255,255,0.04)' }}>
          <div style={{ color: '#94a3b8', fontSize: 12, fontWeight: 500, marginBottom: 4 }}>Webhook Deliveries (1h)</div>
          <div style={{ fontWeight: 700, fontSize: 18, color: '#f8fafc', lineHeight: 1.3 }}>{stats?.webhooks?.last_hour || 0}</div>
        </div>
        <div style={{ background: 'rgba(255,255,255,0.02)', padding: '14px 18px', borderRadius: 10, border: '1px solid rgba(255,255,255,0.04)' }}>
          <div style={{ color: '#94a3b8', fontSize: 12, fontWeight: 500, marginBottom: 4 }}>Total Deliveries</div>
          <div style={{ fontWeight: 700, fontSize: 18, color: '#f8fafc', lineHeight: 1.3 }}>{stats?.webhooks?.total || 0}</div>
        </div>
      </div>
    </div>
  )
}

export default function MonitoringPage() {
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [autoRefresh, setAutoRefresh] = useState(true)

  const fetchStats = useCallback(() => {
    api.getMonitoringStats()
      .then(setStats)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    fetchStats()
    let timer
    if (autoRefresh) {
      timer = setInterval(fetchStats, 15000)
    }
    return () => clearInterval(timer)
  }, [autoRefresh, fetchStats])

  if (loading) return <div className="page monitoring-page"><LoadingSkeleton rows={6} /></div>
  if (error) return <div className="page monitoring-page"><div className="banner-inline err">Error: {error}</div></div>

  return (
    <div className="page monitoring-page">
      <PageHeader
        title="Monitoring Dashboard"
        description="Real-time execution queue metrics, worker throughput, and cluster health."
        actions={
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: '#94a3b8', cursor: 'pointer', userSelect: 'none' }}>
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
              />
              Auto-refresh (15s)
            </label>
            <button className="ghost" onClick={fetchStats} disabled={loading}>↻ Refresh</button>
          </div>
        }
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 14, marginBottom: 20 }}>
        <MonitoringStatCard title="Running Executions" value={stats?.executions?.running || 0} color="#38bdf8" icon="⚡" subtitle="Currently active in runtime" />
        <MonitoringStatCard title="Queued Runs" value={stats?.executions?.queued || 0} color="#f59e0b" icon="⏳" subtitle="Waiting for available worker" />
        <MonitoringStatCard title="Success (Past 1h)" value={stats?.last_hour?.success || 0} color="#10b981" icon="✓" subtitle="Completed without error" />
        <MonitoringStatCard title="Failed (Past 1h)" value={stats?.last_hour?.failed || 0} color="#ef4444" icon="✕" subtitle="Errored execution runs" />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: 18, marginBottom: 20 }}>
        <ExecutionTimeline stats={stats} />
        <QueueStatus stats={stats} />
      </div>

      <SystemInfo stats={stats} />
    </div>
  )
}
