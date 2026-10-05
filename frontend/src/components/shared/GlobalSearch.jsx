import { useEffect, useState, useRef, useMemo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api'
import { NodeIcon } from '../NodeIcons'

const QUICK_ACTIONS = [
  {
    id: 'act-new-workflow',
    title: 'Create New Workflow',
    subtitle: 'Start with a blank canvas or trigger',
    path: '/workflows',
    category: 'Actions',
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" style={{ color: '#38bdf8' }}>
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="8" x2="12" y2="16" />
        <line x1="8" y1="12" x2="16" y2="12" />
      </svg>
    ),
  },
  {
    id: 'act-integrations',
    title: 'Browse 88+ Integrations',
    subtitle: 'Connect Salesforce, Slack, HubSpot, AI models',
    path: '/integrations',
    category: 'Navigation',
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: '#818cf8' }}>
        <path d="M12 2v6m0 8v6M2 12h6m8 0h6" />
        <rect x="8" y="8" width="8" height="8" rx="2" />
      </svg>
    ),
  },
  {
    id: 'act-credentials',
    title: 'Manage Credentials & Keys',
    subtitle: 'Configure OAuth2, API tokens and databases',
    path: '/credentials',
    category: 'Navigation',
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: '#34d399' }}>
        <path d="m15.5 7.5 3 3L22 7l-3-3" />
        <circle cx="7.5" cy="16.5" r="4.5" />
        <line x1="10.5" y1="13.5" x2="17" y2="7" />
      </svg>
    ),
  },
  {
    id: 'act-executions',
    title: 'Live Executions & Audit Log',
    subtitle: 'Inspect runs, step duration and live traces',
    path: '/executions',
    category: 'Navigation',
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: '#fbbf24' }}>
        <circle cx="12" cy="12" r="10" />
        <polyline points="12 6 12 12 16 14" />
      </svg>
    ),
  },
  {
    id: 'act-ai',
    title: 'AI Studio & Prompt Copilot',
    subtitle: 'Autonomous agents and generative workflows',
    path: '/ai',
    category: 'Automate & AI',
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: 'var(--accent)' }}>
        <polyline points="4 17 10 11 4 5" />
        <line x1="12" y1="19" x2="20" y2="19" />
      </svg>
    ),
  },
  {
    id: 'act-settings',
    title: 'Workspace Settings & White-Label',
    subtitle: 'Custom branding, team, and security tokens',
    path: '/settings',
    category: 'Administration',
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: '#94a3b8' }}>
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
      </svg>
    ),
  },
]

export default function GlobalSearch({ open, onClose }) {
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState({
    workflows: [],
    credentials: [],
    templates: [],
    dataTables: [],
    connectors: [],
    executions: [],
  })
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef(null)
  const listRef = useRef(null)
  const navigate = useNavigate()
  const go = useCallback((target) => {
    onClose()
    if (!target) return
    if (typeof target === 'function') {
      target()
    } else if (typeof target === 'string') {
      navigate(target)
    } else if (typeof target.action === 'function') {
      target.action()
    } else if (target.path) {
      navigate(target.path)
    }
  }, [onClose, navigate])

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 30)
      setSelectedIndex(0)
    } else {
      setQuery('')
      setResults({
        workflows: [],
        credentials: [],
        templates: [],
        dataTables: [],
        connectors: [],
        executions: [],
      })
      setSelectedIndex(0)
    }
  }, [open])

  // Flatten active items for keyboard navigation (arrows + enter)
  const flatItems = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) {
      return QUICK_ACTIONS.map(a => ({
        id: a.id,
        title: a.title,
        subtitle: a.subtitle,
        category: a.category,
        kind: 'Action',
        path: a.path,
        action: a.action,
        icon: a.icon,
      }))
    }
    const items = []
    // Include matching quick actions (e.g. searching "light", "theme", "settings")
    QUICK_ACTIONS.filter(a => `${a.title} ${a.subtitle} ${a.category}`.toLowerCase().includes(q)).forEach(a => {
      items.push({
        id: a.id,
        title: a.title,
        subtitle: a.subtitle,
        category: a.category,
        kind: 'Action',
        path: a.path,
        action: a.action,
        icon: a.icon,
      })
    })
    results.workflows.forEach(w => {
      items.push({
        id: `wf-${w.id}`,
        title: w.name || w.id,
        subtitle: `v${w.version || 1} · ${w.active ? 'Active' : 'Draft'}`,
        category: 'Workflows',
        kind: w.active ? 'Active' : 'Draft',
        path: `/workflows/${w.id}`,
        icon: (
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ color: '#818cf8' }}>
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" fill="currentColor" fillOpacity="0.2" />
          </svg>
        ),
      })
    })
    results.connectors.forEach(c => {
      items.push({
        id: `conn-${c.connector_key}`,
        title: c.display_name || c.connector_key,
        subtitle: c.description || c.category,
        category: 'Connectors & Services',
        kind: c.category || 'Connector',
        path: '/integrations',
        icon: (
          <div style={{ width: 18, height: 18, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <NodeIcon type={c.connector_key} name={c.display_name} size={16} />
          </div>
        ),
      })
    })
    results.credentials.forEach(c => {
      items.push({
        id: `cred-${c.id}`,
        title: c.name,
        subtitle: `${c.type} connection`,
        category: 'Credentials',
        kind: c.type,
        path: '/credentials',
        icon: (
          <div style={{ width: 18, height: 18, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <NodeIcon type={c.type} name={c.name} size={16} />
          </div>
        ),
      })
    })
    results.templates.forEach(t => {
      items.push({
        id: `tpl-${t.id}`,
        title: t.name,
        subtitle: t.description || t.category,
        category: 'Templates',
        kind: t.category || 'Template',
        path: '/templates',
        icon: (
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ color: '#38bdf8' }}>
            <polygon points="12 2 2 7 12 12 22 7 12 2" />
            <polyline points="2 17 12 22 22 17" />
            <polyline points="2 12 12 17 22 12" />
          </svg>
        ),
      })
    })
    results.dataTables.forEach(t => {
      items.push({
        id: `dt-${t.id}`,
        title: t.name,
        subtitle: `${t.columns?.length ?? 0} columns`,
        category: 'Data Tables',
        kind: 'Table',
        path: `/data-tables/${t.id}`,
        icon: (
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ color: '#34d399' }}>
            <rect width="18" height="18" x="3" y="3" rx="2" />
            <line x1="3" y1="9" x2="21" y2="9" />
            <line x1="9" y1="3" x2="9" y2="21" />
          </svg>
        ),
      })
    })
    results.executions.forEach(e => {
      items.push({
        id: `exec-${e.id}`,
        title: `Execution ${e.id.slice(0, 8)}`,
        subtitle: `${e.status} · trigger: ${e.trigger || 'manual'}`,
        category: 'Executions',
        kind: e.status,
        path: `/executions/${e.id}`,
        icon: (
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ color: e.status === 'success' ? '#34d399' : e.status === 'failed' ? '#f43f5e' : '#fbbf24' }}>
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
        ),
      })
    })
    return items
  }, [query, results])

  // Clamp selected index
  useEffect(() => {
    if (selectedIndex >= flatItems.length) {
      setSelectedIndex(Math.max(0, flatItems.length - 1))
    }
  }, [flatItems, selectedIndex])

  // Keyboard navigation
  useEffect(() => {
    if (!open) return
    const onKey = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      } else if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSelectedIndex(prev => (prev + 1) % Math.max(1, flatItems.length))
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSelectedIndex(prev => (prev - 1 + flatItems.length) % Math.max(1, flatItems.length))
      } else if (e.key === 'Enter') {
        e.preventDefault()
        const selected = flatItems[selectedIndex]
        if (selected) {
          go(selected)
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose, flatItems, selectedIndex, go])

  // Live async search query with debouncing
  useEffect(() => {
    const q = query.trim().toLowerCase()
    if (!q || q.length < 2) {
      setResults({
        workflows: [],
        credentials: [],
        templates: [],
        dataTables: [],
        connectors: [],
        executions: [],
      })
      return
    }
    let cancelled = false
    setLoading(true)
    const t = setTimeout(async () => {
      try {
        const [workflows, creds, templates, dtRes, connectors, execs] = await Promise.all([
          api.listWorkflows().catch(() => []),
          api.listCredentials().catch(() => []),
          api.listTemplates().catch(() => []),
          api.listDataTables({ pageSize: 100 }).then(r => r.data || []).catch(() => []),
          api.listConnectors().then(r => Array.isArray(r) ? r : (r && r.data) || []).catch(() => []),
          api.listExecutions({ pageSize: 20 }).then(r => Array.isArray(r) ? r : (r && r.data) || []).catch(() => []),
        ])
        if (cancelled) return
        const wf = (Array.isArray(workflows) ? workflows : []).filter(w =>
          `${w.name} ${w.id}`.toLowerCase().includes(q)
        ).slice(0, 5)
        const cr = (Array.isArray(creds) ? creds : []).filter(c =>
          `${c.name} ${c.type}`.toLowerCase().includes(q)
        ).slice(0, 5)
        const tp = (Array.isArray(templates) ? templates : []).filter(t =>
          `${t.name} ${t.description} ${t.category}`.toLowerCase().includes(q)
        ).slice(0, 5)
        const dts = (Array.isArray(dtRes) ? dtRes : []).filter(t =>
          `${t.name} ${t.description}`.toLowerCase().includes(q)
        ).slice(0, 5)
        const conns = (Array.isArray(connectors) ? connectors : []).filter(c =>
          `${c.display_name} ${c.connector_key} ${c.category} ${c.description}`.toLowerCase().includes(q)
        ).slice(0, 5)
        const ex = (Array.isArray(execs) ? execs : []).filter(e =>
          `${e.id} ${e.workflow_id} ${e.status} ${e.trigger}`.toLowerCase().includes(q)
        ).slice(0, 4)
        setResults({ workflows: wf, credentials: cr, templates: tp, dataTables: dts, connectors: conns, executions: ex })
      } catch {
        if (!cancelled) setResults({ workflows: [], credentials: [], templates: [], dataTables: [], connectors: [], executions: [] })
      } finally {
        if (!cancelled) setLoading(false)
      }
    }, 200)
    return () => { cancelled = true; clearTimeout(t) }
  }, [query])

  if (!open) return null

  return (
    <div className="palette-overlay" onClick={onClose} role="dialog" aria-modal="true" aria-label="Global Command Palette">
      <div className="palette global-search" onClick={e => e.stopPropagation()}>
        <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
          <span style={{ position: 'absolute', left: 20, color: '#818cf8', display: 'flex', alignItems: 'center', pointerEvents: 'none' }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
          </span>
          <input
            ref={inputRef}
            className="palette-input"
            style={{ paddingLeft: 50 }}
            placeholder="Type a command or search workflows, credentials, connectors…"
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
        </div>

        <div className="global-search-body" ref={listRef} style={{ maxHeight: '52vh', overflowY: 'auto', padding: '6px 8px' }}>
          {loading && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '16px 20px', color: '#94a3b8', fontSize: 13 }}>
              <span className="app-topbar-context-dot" />
              <span>Searching workspace across services…</span>
            </div>
          )}

          {!loading && query.trim().length >= 2 && flatItems.length === 0 && (
            <div style={{ padding: '36px 20px', textAlign: 'center', color: '#64748b' }}>
              <div style={{ fontSize: 24, marginBottom: 8 }}>🔍</div>
              <div style={{ fontSize: 14, fontWeight: 600, color: '#94a3b8' }}>No results found</div>
              <div style={{ fontSize: 12, marginTop: 4 }}>No workflows, connectors, or credentials matched “{query}”.</div>
            </div>
          )}

          {flatItems.length > 0 && (
            <div>
              {!query.trim() && (
                <div style={{ fontSize: 10.5, textTransform: 'uppercase', letterSpacing: '0.08em', color: '#64748b', fontWeight: 700, padding: '10px 14px 4px' }}>
                  Suggested Quick Actions
                </div>
              )}
              {flatItems.map((item, idx) => {
                const isSelected = idx === selectedIndex
                return (
                  <button
                    key={item.id}
                    type="button"
                    className={`palette-item ${isSelected ? 'active' : ''}`}
                    onClick={() => go(item)}
                    onMouseEnter={() => setSelectedIndex(idx)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 12,
                      width: '100%',
                      padding: '9px 12px',
                      borderRadius: 9,
                      textAlign: 'left',
                      background: isSelected ? 'rgba(99, 102, 241, 0.16)' : 'transparent',
                      border: isSelected ? '1px solid rgba(99, 102, 241, 0.35)' : '1px solid transparent',
                      color: isSelected ? '#ffffff' : '#cbd5e1',
                      cursor: 'pointer',
                      transition: 'all 0.12s ease',
                      marginBottom: 2,
                    }}
                  >
                    <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 28, height: 28, borderRadius: 7, background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', flexShrink: 0 }}>
                      {item.icon}
                    </span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13.5, fontWeight: isSelected ? 600 : 500, color: isSelected ? '#ffffff' : '#f1f5f9', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {item.title}
                      </div>
                      {item.subtitle && (
                        <div style={{ fontSize: 11, color: isSelected ? '#a5b4fc' : '#64748b', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', marginTop: 1 }}>
                          {item.subtitle}
                        </div>
                      )}
                    </div>
                    {item.kind && (
                      <span style={{ fontSize: 10, fontWeight: 600, padding: '2px 7px', borderRadius: 999, background: isSelected ? 'rgba(99,102,241,0.25)' : 'rgba(255,255,255,0.05)', color: isSelected ? '#e0e7ff' : '#94a3b8', border: '1px solid rgba(255,255,255,0.08)', flexShrink: 0, textTransform: 'capitalize' }}>
                        {item.kind}
                      </span>
                    )}
                  </button>
                )
              })}
            </div>
          )}
        </div>

        <div className="palette-foot" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 16px', background: 'rgba(0,0,0,0.28)', borderTop: '1px solid rgba(255,255,255,0.08)', fontSize: 11, color: '#64748b' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <span><kbd className="app-topbar-search-kbd">↵</kbd> Select</span>
            <span><kbd className="app-topbar-search-kbd">↑↓</kbd> Navigate</span>
            <span><kbd className="app-topbar-search-kbd">ESC</kbd> Close</span>
          </div>
          <div>
            <span>{flatItems.length} {flatItems.length === 1 ? 'item' : 'items'} available</span>
          </div>
        </div>
      </div>
    </div>
  )
}
