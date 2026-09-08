import { useEffect, useState, useCallback } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import AppSidebar from './AppSidebar'
import { useWorkflowStore, isDirty } from '../stores/workflowStore'
import { useCredentialStore } from '../stores/credentialStore'

export default function AppShell({ onLogout }) {
  const location = useLocation()
  const navigate = useNavigate()
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem('flowsmith_sidebar_collapsed') === '1' } catch { return false }
  })
  const [mobileOpen, setMobileOpen] = useState(false)
  const [isMobile, setIsMobile] = useState(() => typeof window !== 'undefined' ? window.innerWidth < 900 : false)

  const toggleCollapsed = useCallback(() => {
    setCollapsed(v => {
      const next = !v
      try { localStorage.setItem('flowsmith_sidebar_collapsed', next ? '1' : '0') } catch {}
      return next
    })
  }, [])

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

  // Init stores once
  useEffect(() => {
    useWorkflowStore.getState().init().catch(() => {})
    useCredentialStore.getState().load().catch(() => {})

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
      />
      <div className="app-main">
        <header className="app-topbar">
          <div className="app-topbar-left">
            <button
              className="app-topbar-hamburger"
              onClick={isMobile ? () => setMobileOpen(v => !v) : toggleCollapsed}
              aria-label={collapsed ? 'Open full tab' : 'Collapse tab'}
              title={collapsed ? 'Open full tab' : 'Collapse tab'}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="3" y1="6" x2="21" y2="6" />
                <line x1="3" y1="12" x2="21" y2="12" />
                <line x1="3" y1="18" x2="21" y2="18" />
              </svg>
            </button>
            <span className="app-topbar-context">
              <span className="app-topbar-context-label">Workspace</span>
              <span className="app-topbar-context-value">Personal</span>
            </span>
          </div>
          <div className="app-topbar-right">
            {!isCanvas && (
              <button className="ghost" onClick={() => navigate('/workflows')} title="Go to workflows">Workflows</button>
            )}
            <button className="ghost" onClick={onLogout} title="Log out">
              Log out
            </button>
          </div>
        </header>
        <main className="app-content" role="main">
          <div key={location.pathname} className="page-transition">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
