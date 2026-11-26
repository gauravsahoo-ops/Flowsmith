import { useEffect, useState, useCallback } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import AppSidebar from './AppSidebar'
import GlobalSearch from '../components/shared/GlobalSearch'
import { useWorkflowStore, isDirty } from '../stores/workflowStore'
import { useCredentialStore } from '../stores/credentialStore'
import { useBrandingStore } from '../stores/brandingStore'
import { syncUserProfile } from '../utils/userProfile'
import NotificationBell from '../components/NotificationBell'
import { api } from '../api'

export default function AppShell({ onLogout }) {
  const location = useLocation()
  const navigate = useNavigate()
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem('flowsmith_sidebar_collapsed') === '1' } catch { return false }
  })
  const [mobileOpen, setMobileOpen] = useState(false)
  const [isMobile, setIsMobile] = useState(() => typeof window !== 'undefined' ? window.innerWidth < 900 : false)
  const [searchOpen, setSearchOpen] = useState(false)
  const isMac = typeof navigator !== 'undefined' && /Mac|iPod|iPhone|iPad/.test(navigator.platform || '')

  const toggleCollapsed = useCallback(() => {
    setCollapsed(v => {
      const next = !v
      try { localStorage.setItem('flowsmith_sidebar_collapsed', next ? '1' : '0') } catch {}
      return next
    })
  }, [])

  // Global shortcut for search (Ctrl+K or Cmd+K) and sidebar toggle (Ctrl+B or Cmd+B)
  useEffect(() => {
    const onKeyDown = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setSearchOpen((prev) => !prev)
      } else if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'b' && !e.shiftKey && !e.altKey) {
        const tag = document.activeElement?.tagName?.toLowerCase()
        if (tag !== 'input' && tag !== 'textarea' && !document.activeElement?.isContentEditable) {
          e.preventDefault()
          toggleCollapsed()
        }
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [toggleCollapsed])

  useEffect(() => {
    const onResize = () => {
      const mobile = window.innerWidth < 900
      setIsMobile(mobile)
      if (!mobile) setMobileOpen(false)
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  // Close mobile drawer on route change
  useEffect(() => {
    setMobileOpen(false)
  }, [location.pathname])

  // Init stores once. When the app opens directly on /workflows/:id, the
  // editor page owns hydration; init must not auto-load the most-recent
  // workflow and overwrite it.
  useEffect(() => {
    const match = typeof window !== 'undefined'
      ? window.location.pathname.match(/^\/workflows\/([^/]+)\/?$/)
      : null
    let routeWorkflowId = null
    if (match) {
      try {
        routeWorkflowId = decodeURIComponent(match[1])
      } catch {
        routeWorkflowId = match[1]
      }
    }
    useBrandingStore.getState().init().catch(() => {})
    useWorkflowStore.getState().init(routeWorkflowId).catch(() => {})
    useCredentialStore.getState().load().catch(() => {})
    syncUserProfile(api).catch(() => {})

    const handler = (e) => {
      if (isDirty && isDirty()) {
        e.preventDefault()
        e.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [])

  const isCanvas = location.pathname.startsWith('/workflows/') && location.pathname !== '/workflows'

  return (
    <div className={`app-shell ${collapsed ? 'sidebar-collapsed' : 'sidebar-expanded'} ${isMobile ? 'is-mobile' : ''} ${isCanvas ? 'is-canvas' : ''}`}>
      <AppSidebar
        collapsed={collapsed}
        onToggle={toggleCollapsed}
        isMobile={isMobile}
        mobileOpen={mobileOpen}
        onMobileClose={() => setMobileOpen(false)}
        onLogout={onLogout}
      />
      <div className="app-main">
        <header className="app-topbar">
          <div className="app-topbar-left">
            <button
              className="app-topbar-hamburger"
              onClick={isMobile ? () => setMobileOpen(v => !v) : toggleCollapsed}
              aria-label={(isMobile ? mobileOpen : !collapsed) ? 'Collapse sidebar (Ctrl+B)' : 'Expand sidebar (Ctrl+B)'}
              title={(isMobile ? mobileOpen : !collapsed) ? 'Collapse sidebar (Ctrl+B)' : 'Expand sidebar (Ctrl+B)'}
            >
              {(isMobile ? mobileOpen : !collapsed) ? (
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect width="18" height="18" x="3" y="3" rx="2.5" />
                  <path d="M9 3v18" />
                  <path d="m15 9-3 3 3 3" />
                </svg>
              ) : (
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect width="18" height="18" x="3" y="3" rx="2.5" />
                  <path d="M9 3v18" />
                  <path d="m14 9 3 3-3 3" />
                </svg>
              )}
            </button>
          </div>
          <div className="app-topbar-center">
            <button
              type="button"
              className="app-topbar-search-btn"
              onClick={() => setSearchOpen(true)}
              aria-label={`Search workflows, connectors, credentials… ${isMac ? '⌘K' : 'Ctrl K'}`}
              title="Search workflows, credentials, templates (Ctrl+K)"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
              <span className="app-topbar-search-text">Search workflows, connectors, credentials…</span>
              <kbd className="app-topbar-search-kbd">{isMac ? '⌘K' : 'Ctrl K'}</kbd>
            </button>
          </div>
          <div className="app-topbar-right">
            <NotificationBell />

            {!isCanvas && !['/overview', '/workflows'].includes(location.pathname) && (
              <button
                className="primary small topbar-create-btn"
                onClick={() => navigate('/workflows')}
                title="Create or manage workflows"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '5px 12px',
                  fontSize: 12,
                  fontWeight: 600,
                  background: 'var(--accent, #10b981)',
                  borderRadius: 6,
                  boxShadow: '0 1px 2px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.15)',
                  border: '1px solid rgba(255, 255, 255, 0.12)',
                  color: '#fff',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                }}
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="12" y1="5" x2="12" y2="19" />
                  <line x1="5" y1="12" x2="19" y2="12" />
                </svg>
                <span>New Workflow</span>
              </button>
            )}
          </div>
        </header>
        <main className="app-content" role="main">
          <div key={location.pathname} className="page-transition">
            <Outlet />
          </div>
        </main>
      </div>
      <GlobalSearch open={searchOpen} onClose={() => setSearchOpen(false)} />
    </div>
  )
}
