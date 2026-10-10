import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'

export default function NotificationBell() {
  const navigate = useNavigate()
  const [stats, setStats] = useState({ unresolved_count: 0, critical_count: 0 })
  const [recentEvents, setRecentEvents] = useState([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const popoverRef = useRef(null)

  const loadStats = async () => {
    try {
      const data = await api.getNotificationStats()
      if (data) setStats(data)
    } catch {
      // Best-effort in background
    }
  }

  const loadRecentEvents = async () => {
    setLoading(true)
    try {
      const res = await api.listNotifications({ resolved: false, limit: 5 })
      if (res?.items) setRecentEvents(res.items)
    } catch {
      // Best-effort
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadStats()
    const timer = setInterval(loadStats, 30000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    if (open) {
      loadRecentEvents()
    }
  }, [open])

  // Close on outside click
  useEffect(() => {
    function handleClickOutside(e) {
      if (popoverRef.current && !popoverRef.current.contains(e.target)) {
        setOpen(false)
      }
    }
    if (open) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  const handleAcknowledge = async (id, e) => {
    e.stopPropagation()
    try {
      await api.acknowledgeNotification(id)
      setRecentEvents(prev => prev.filter(ev => ev.id !== id))
      setStats(prev => ({ ...prev, unresolved_count: Math.max(0, prev.unresolved_count - 1) }))
    } catch {
      // Best effort
    }
  }

  const badgeCount = stats.unresolved_count
  const isCritical = stats.critical_count > 0

  return (
    <div className="notification-bell-container" ref={popoverRef} style={{ position: 'relative' }}>
      <button
        type="button"
        className="ghost ghost--sm topbar-bell-btn"
        onClick={() => setOpen(prev => !prev)}
        aria-label={`Error alerts: ${badgeCount} unresolved`}
        title={`Error alerts: ${badgeCount} unresolved`}
        style={{
          position: 'relative',
          padding: '5px 8px',
          borderRadius: 6,
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: badgeCount > 0 ? (isCritical ? '#f43f5e' : '#fbbf24') : 'var(--text-muted)',
          background: badgeCount > 0 ? (isCritical ? 'rgba(244, 63, 94, 0.12)' : 'rgba(251, 191, 36, 0.1)') : 'transparent',
          border: badgeCount > 0 ? `1px solid ${isCritical ? 'rgba(244, 63, 94, 0.3)' : 'rgba(251, 191, 36, 0.25)'}` : '1px solid transparent',
          cursor: 'pointer',
        }}
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>

        {badgeCount > 0 && (
          <span
            style={{
              position: 'absolute',
              top: -4,
              right: -4,
              minWidth: 16,
              height: 16,
              padding: '0 4px',
              borderRadius: 8,
              background: isCritical ? '#e11d48' : '#f59e0b',
              color: '#ffffff',
              fontSize: 10,
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: isCritical ? '0 0 8px rgba(225, 29, 72, 0.6)' : 'none',
              animation: isCritical ? 'pulse 2s infinite' : 'none',
            }}
          >
            {badgeCount > 99 ? '99+' : badgeCount}
          </span>
        )}
      </button>

      {open && (
        <div
          className="notification-popover"
          style={{
            position: 'absolute',
            top: 'calc(100% + 8px)',
            right: 0,
            width: 360,
            maxWidth: '90vw',
            background: 'var(--panel-1, #1e293b)',
            border: '1px solid var(--border, #334155)',
            borderRadius: 10,
            boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.3)',
            zIndex: 1000,
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              padding: '12px 16px',
              borderBottom: '1px solid var(--border, #334155)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              background: 'var(--panel-2, #0f172a)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text, #f1f5f9)' }}>Error Alerts</span>
              {badgeCount > 0 && (
                <span
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    padding: '1px 6px',
                    borderRadius: 999,
                    background: isCritical ? '#e11d48' : '#f59e0b',
                    color: '#fff',
                  }}
                >
                  {badgeCount} unresolved
                </span>
              )}
            </div>
            <button
              className="ghost ghost--xs"
              onClick={() => {
                setOpen(false)
                navigate('/monitoring?tab=alerts')
              }}
              style={{ fontSize: 11, color: '#38bdf8', padding: '2px 6px', cursor: 'pointer' }}
            >
              View All
            </button>
          </div>

          <div style={{ maxHeight: 320, overflowY: 'auto' }}>
            {loading && recentEvents.length === 0 ? (
              <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted, #94a3b8)', fontSize: 12 }}>
                Loading alerts…
              </div>
            ) : recentEvents.length === 0 ? (
              <div style={{ padding: '28px 16px', textAlign: 'center' }}>
                <div style={{ fontSize: 24, marginBottom: 6 }}>✓</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#10b981' }}>No Unresolved Errors</div>
                <div style={{ fontSize: 12, color: 'var(--text-muted, #94a3b8)', marginTop: 2 }}>
                  All workflows and connectors are operating normally.
                </div>
              </div>
            ) : (
              recentEvents.map(ev => {
                const isCrit = ev.severity === 'CRITICAL'
                const sevColor = isCrit ? '#e11d48' : ev.severity === 'WARNING' ? '#d97706' : '#ef4444'
                return (
                  <div
                    key={ev.id}
                    onClick={() => {
                      setOpen(false)
                      navigate(`/monitoring?tab=alerts&event_id=${ev.id}`)
                    }}
                    style={{
                      padding: '12px 14px',
                      borderBottom: '1px solid var(--border, #334155)',
                      cursor: 'pointer',
                      transition: 'background 0.15s ease',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 4,
                    }}
                    onMouseEnter={e => (e.currentTarget.style.background = 'var(--panel-2, #0f172a)')}
                    onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <span
                        style={{
                          fontSize: 10,
                          fontWeight: 700,
                          padding: '1px 5px',
                          borderRadius: 4,
                          background: `${sevColor}22`,
                          color: sevColor,
                          border: `1px solid ${sevColor}44`,
                        }}
                      >
                        {ev.severity}
                      </span>
                      <span style={{ fontSize: 11, color: 'var(--text-muted, #94a3b8)' }}>
                        {ev.created_at ? new Date(ev.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
                      </span>
                    </div>
                    <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text, #f1f5f9)', lineHeight: 1.3 }}>
                      {ev.title}
                    </div>
                    <div style={{ fontSize: 11.5, color: 'var(--text-muted, #94a3b8)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {ev.workflow_name || ev.connector_type || 'Platform Operation'}
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 4 }}>
                      <button
                        className="ghost ghost--xs"
                        onClick={(e) => handleAcknowledge(ev.id, e)}
                        title="Dismiss from unread alerts"
                        style={{ fontSize: 11, padding: '2px 8px', borderRadius: 4, color: '#94a3b8' }}
                      >
                        Acknowledge
                      </button>
                    </div>
                  </div>
                )
              })
            )}
          </div>

          <div
            style={{
              padding: '10px 16px',
              borderTop: '1px solid var(--border, #334155)',
              textAlign: 'center',
              background: 'var(--panel-2, #0f172a)',
            }}
          >
            <button
              className="ghost ghost--sm"
              onClick={() => {
                setOpen(false)
                navigate('/monitoring?tab=alerts')
              }}
              style={{ fontSize: 12, fontWeight: 600, color: '#38bdf8', width: '100%' }}
            >
              Open Error Monitoring Center →
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
