import { useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'

function NavIcon({ name, size = 18 }) {
  switch (name) {
    case 'overview':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="3" width="7" height="7" rx="1.5" />
          <rect x="14" y="3" width="7" height="7" rx="1.5" />
          <rect x="14" y="14" width="7" height="7" rx="1.5" />
          <rect x="3" y="14" width="7" height="7" rx="1.5" />
        </svg>
      )
    case 'workflows':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" fill="currentColor" fillOpacity="0.15" />
        </svg>
      )
    case 'shared':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8" />
          <polyline points="16 6 12 2 8 6" />
          <line x1="12" y1="2" x2="12" y2="15" />
        </svg>
      )
    case 'credentials':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="m15.5 7.5 3 3L22 7l-3-3" />
          <circle cx="7.5" cy="16.5" r="4.5" />
          <line x1="10.5" y1="13.5" x2="17" y2="7" />
        </svg>
      )
    case 'executions':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <polyline points="12 6 12 12 16 14" />
        </svg>
      )
    case 'variables':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <line x1="2" y1="12" x2="22" y2="12" />
          <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
        </svg>
      )
    case 'data-tables':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect width="18" height="18" x="3" y="3" rx="2" />
          <line x1="3" y1="9" x2="21" y2="9" />
          <line x1="3" y1="15" x2="21" y2="15" />
          <line x1="9" y1="3" x2="9" y2="21" />
        </svg>
      )
    case 'knowledge':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
          <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
          <line x1="9" y1="7" x2="15" y2="7" />
          <line x1="9" y1="11" x2="13" y2="11" />
        </svg>
      )
    case 'approvals':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
          <polyline points="9 12 11 14 15 10" />
        </svg>
      )
    case 'templates':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polygon points="12 2 2 7 12 12 22 7 12 2" />
          <polyline points="2 17 12 22 22 17" />
          <polyline points="2 12 12 17 22 12" />
        </svg>
      )
    case 'monitoring':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <line x1="18" y1="20" x2="18" y2="10" />
          <line x1="12" y1="20" x2="12" y2="4" />
          <line x1="6" y1="20" x2="6" y2="14" />
        </svg>
      )
    case 'billing':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect width="20" height="14" x="2" y="5" rx="2" />
          <line x1="2" y1="10" x2="22" y2="10" />
        </svg>
      )
    case 'settings':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
      )
    case 'help':
    default:
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
          <line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
      )
  }
}

const NAV = [
  {
    section: 'Main',
    items: [
      { id: 'overview', label: 'Overview', path: '/overview', desc: 'Dashboard' },
      { id: 'workflows', label: 'Workflows', path: '/workflows', desc: 'Your workflows' },
      { id: 'shared', label: 'Shared with you', path: '/shared', desc: 'Shared workflows' },
    ],
  },
  {
    section: 'Workspace',
    items: [
      { id: 'credentials', label: 'Credentials', path: '/credentials', desc: 'Connections' },
      { id: 'executions', label: 'Executions', path: '/executions', desc: 'Run history' },
      { id: 'variables', label: 'Variables', path: '/variables', desc: 'Environment' },
      { id: 'data-tables', label: 'Data Tables', path: '/data-tables', desc: 'Structured data' },
      { id: 'knowledge', label: 'Knowledge', path: '/knowledge', desc: 'RAG collections' },
    ],
  },
  {
    section: 'Automate',
    items: [
      { id: 'approvals', label: 'Approvals', path: '/approvals', desc: 'Awaiting decision' },
      { id: 'templates', label: 'Templates', path: '/templates', desc: 'Gallery' },
    ],
  },
  {
    section: 'Administration',
    items: [
      { id: 'monitoring', label: 'Monitoring', path: '/monitoring', desc: 'System health' },
      { id: 'settings', label: 'Settings', path: '/settings', desc: 'Preferences' },
      { id: 'help', label: 'Help', path: '/help', desc: 'Docs & support' },
    ],
  },
]

function SidebarItem({ item, collapsed, mobileClose }) {
  const location = useLocation()
  const active = location.pathname === item.path || location.pathname.startsWith(item.path + '/')
  return (
    <NavLink
      to={item.path}
      onClick={mobileClose}
      className={`app-sidebar-item ${active ? 'active' : ''} ${collapsed ? 'collapsed' : ''}`}
      title={collapsed ? item.label : undefined}
      aria-label={item.label}
      aria-current={active ? 'page' : undefined}
    >
      <span className="app-sidebar-icon" aria-hidden="true">
        <NavIcon name={item.id} size={18} />
      </span>
      <span className="app-sidebar-label">
        <span className="app-sidebar-label-text">{item.label}</span>
        <span className="app-sidebar-label-desc">{item.desc}</span>
      </span>
    </NavLink>
  )
}

export default function AppSidebar({ collapsed, onToggle, isMobile, mobileOpen, onMobileClose }) {
  const sidebarClass = `app-sidebar ${collapsed ? 'is-collapsed' : 'is-expanded'} ${isMobile ? 'is-mobile' : ''} ${mobileOpen ? 'mobile-open' : ''}`

  const content = (
    <>
      <div className="app-sidebar-brand">
        <div
          className="app-sidebar-brand-mark"
          title={collapsed ? 'Click to open full tab' : 'Flowsmith'}
          onClick={collapsed ? onToggle : undefined}
          style={collapsed ? { cursor: 'pointer' } : undefined}
          role={collapsed ? 'button' : undefined}
          aria-label={collapsed ? 'Open full tab' : 'Flowsmith'}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" fill="currentColor" />
          </svg>
        </div>
        <span className="app-sidebar-brand-name">Flowsmith</span>
      </div>

      <nav className="app-sidebar-nav" aria-label="Main navigation">
        {NAV.map((group) => (
          <div key={group.section} className="app-sidebar-group">
            <div className="app-sidebar-group-label">{group.section}</div>
            <div className="app-sidebar-group-sep" aria-hidden="true" />
            <div className="app-sidebar-group-items">
              {group.items.map((item) => (
                <SidebarItem
                  key={item.path}
                  item={item}
                  collapsed={collapsed && !isMobile}
                  mobileClose={onMobileClose}
                />
              ))}
            </div>
          </div>
        ))}
      </nav>
    </>
  )

  if (isMobile) {
    return (
      <>
        <aside className={sidebarClass} aria-label="Sidebar" aria-hidden={!mobileOpen}>
          {content}
        </aside>
        {mobileOpen && <div className="app-sidebar-backdrop" onClick={onMobileClose} aria-hidden="true" />}
      </>
    )
  }

  return (
    <aside className={sidebarClass} aria-label="Sidebar">
      {content}
    </aside>
  )
}
