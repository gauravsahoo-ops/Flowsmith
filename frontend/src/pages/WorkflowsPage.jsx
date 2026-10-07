import { useEffect, useState, useMemo, useRef, useLayoutEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import PageHeader from '../components/shared/PageHeader'
import EmptyState from '../components/shared/EmptyState'
import LoadingSkeleton from '../components/shared/LoadingSkeleton'
import ConfirmDialog from '../components/shared/ConfirmDialog'
import WorkspaceTabs from '../components/shared/WorkspaceTabs'
import { useWorkflowStore } from '../stores/workflowStore'

function PortalMenu({ anchorRef, open, onClose, children }) {
  const menuRef = useRef(null)
  const [pos, setPos] = useState({ top: 0, left: 0, maxHeight: 400 })

  useLayoutEffect(() => {
    if (!open || !anchorRef.current || !menuRef.current) return
    const anchor = anchorRef.current.getBoundingClientRect()
    const menu = menuRef.current.getBoundingClientRect()
    const viewportH = window.innerHeight
    const viewportW = window.innerWidth
    const margin = 8
    let top = anchor.bottom + 6
    let left = anchor.right - menu.width
    // flip above if not enough room below
    if (top + menu.height + margin > viewportH && anchor.top - menu.height - 6 > margin) {
      top = anchor.top - menu.height - 6
    }
    // keep inside viewport horizontally
    if (left < margin) left = margin
    if (left + menu.width + margin > viewportW) left = viewportW - menu.width - margin
    setPos({ top, left, maxHeight: Math.min(400, viewportH - top - margin) })
  }, [open, anchorRef])

  useEffect(() => {
    if (!open) return
    const onDoc = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target) && anchorRef.current && !anchorRef.current.contains(e.target)) onClose()
    }
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('pointerdown', onDoc, true)
    window.addEventListener('touchstart', onDoc, true)
    document.addEventListener('keydown', onKey)
    // focus first item for keyboard nav
    requestAnimationFrame(() => {
      const first = menuRef.current?.querySelector('[role="menuitem"]')
      first?.focus()
    })
    return () => {
      window.removeEventListener('pointerdown', onDoc, true)
      window.removeEventListener('touchstart', onDoc, true)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, onClose, anchorRef])

  if (!open) return null
  return createPortal(
    <div
      ref={menuRef}
      className="context-menu context-menu--portal"
      role="menu"
      style={{ position: 'fixed', top: pos.top, left: pos.left, width: 185, maxWidth: '90vw', maxHeight: pos.maxHeight, overflowY: 'auto', zIndex: 9999 }}
    >
      {children}
    </div>,
    document.body
  )
}

function WorkflowRow({ wf, isPinned, onTogglePin, onOpen, onDuplicate, onDelete, onToggleActive, onExport }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const buttonRef = useRef(null)
  return (
    <tr className={isPinned ? 'row-pinned' : ''}>
      <td>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{
            width: 34, height: 34, borderRadius: 8,
            background: isPinned ? 'rgba(245, 158, 11, 0.15)' : 'rgba(99, 102, 241, 0.12)',
            border: isPinned ? '1px solid rgba(245, 158, 11, 0.35)' : '1px solid rgba(99, 102, 241, 0.25)',
            display: 'grid', placeItems: 'center', color: isPinned ? '#fbbf24' : '#818cf8', flexShrink: 0
          }}>
            {isPinned ? (
              <svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="12" y1="17" x2="12" y2="22" />
                <path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.89A2 2 0 0 1 15 10.77V6a3 3 0 0 0-6 0v4.77a2 2 0 0 1-1.11 1.79l-1.78.89A2 2 0 0 0 5 15.24Z" />
              </svg>
            ) : (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" fill="currentColor" fillOpacity="0.2" />
              </svg>
            )}
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
              <button className="linklike" onClick={() => onOpen(wf.id)} title={wf.name || wf.id} style={{ textAlign: 'left' }}>
                <strong style={{ fontSize: 14, color: '#f8fafc', letterSpacing: '-0.01em' }}>
                  {wf.name ? wf.name : <span className="muted">Untitled workflow</span>}
                </strong>
              </button>
              {isPinned && (
                <span
                  title="Pinned workflow"
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 3,
                    fontSize: 10,
                    padding: '1px 6px',
                    borderRadius: 4,
                    background: 'rgba(245, 158, 11, 0.15)',
                    color: '#fbbf24',
                    border: '1px solid rgba(245, 158, 11, 0.35)',
                    fontWeight: 600,
                  }}
                >
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor">
                    <line x1="12" y1="17" x2="12" y2="22" />
                    <path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.89A2 2 0 0 1 15 10.77V6a3 3 0 0 0-6 0v4.77a2 2 0 0 1-1.11 1.79l-1.78.89A2 2 0 0 0 5 15.24Z" />
                  </svg>
                  <span>Pinned</span>
                </span>
              )}
            </div>
            <div className="hint" style={{ fontSize: 11, fontFamily: 'JetBrains Mono, monospace', marginTop: 3 }}>
              {wf.id.slice(0, 8)} · v{wf.version} · {(wf.data?.nodes?.length ?? wf.node_count ?? 0)} nodes
            </div>
          </div>
        </div>
      </td>
      <td>
        <span className={`status-pill ${wf.active ? 'status-success' : 'status-failed'}`} style={{
          color: wf.active ? '#34d399' : '#94a3b8',
          background: wf.active ? 'rgba(16, 185, 129, 0.12)' : 'rgba(255, 255, 255, 0.05)',
          borderColor: wf.active ? 'rgba(16, 185, 129, 0.28)' : 'rgba(255, 255, 255, 0.1)'
        }}>
          <span className="dot" style={{ width: 6, height: 6, borderRadius: '50%', background: 'currentColor' }} />
          {wf.active ? 'Active' : 'Inactive'}
        </span>
      </td>
      <td className="muted" style={{ fontSize: 12 }}>{wf.updated_at ? new Date(wf.updated_at).toLocaleString() : '—'}</td>
      <td className="muted" style={{ fontSize: 12 }}>{wf.created_at ? new Date(wf.created_at).toLocaleDateString() : '—'}</td>
      <td>
        <div className="row-actions">
          <button
            className={`ghost small ${isPinned ? 'is-pinned' : ''}`}
            onClick={() => onTogglePin(wf)}
            title={isPinned ? 'Unpin workflow' : 'Pin workflow to top'}
            aria-label={isPinned ? 'Unpin workflow' : 'Pin workflow to top'}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: isPinned ? '#fbbf24' : 'var(--text-muted, #94a3b8)',
              background: isPinned ? 'rgba(245, 158, 11, 0.14)' : undefined,
              borderColor: isPinned ? 'rgba(245, 158, 11, 0.35)' : undefined,
            }}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill={isPinned ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="12" y1="17" x2="12" y2="22" />
              <path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.89A2 2 0 0 1 15 10.77V6a3 3 0 0 0-6 0v4.77a2 2 0 0 1-1.11 1.79l-1.78.89A2 2 0 0 0 5 15.24Z" />
            </svg>
          </button>
          <button className="ghost small" onClick={() => onOpen(wf.id)}>Open</button>
          <button
            className="ghost small"
            onClick={() => onExport(wf)}
            title="Download workflow (JSON)"
            aria-label="Download workflow"
            style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
          </button>
          <button ref={buttonRef} className="ghost small" onClick={() => setMenuOpen(v => !v)} aria-label="More actions" aria-haspopup="menu" aria-expanded={menuOpen}>⋮</button>
          <PortalMenu anchorRef={buttonRef} open={menuOpen} onClose={() => setMenuOpen(false)}>
            <button role="menuitem" autoFocus onClick={() => { setMenuOpen(false); onOpen(wf.id) }} style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
              <span>Open</span>
            </button>
            <button role="menuitem" onClick={() => { setMenuOpen(false); onTogglePin(wf) }} style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill={isPinned ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: isPinned ? '#fbbf24' : 'currentColor' }}>
                <line x1="12" y1="17" x2="12" y2="22" />
                <path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.89A2 2 0 0 1 15 10.77V6a3 3 0 0 0-6 0v4.77a2 2 0 0 1-1.11 1.79l-1.78.89A2 2 0 0 0 5 15.24Z" />
              </svg>
              <span>{isPinned ? 'Unpin from Top' : 'Pin to Top'}</span>
            </button>
            <button role="menuitem" onClick={() => { setMenuOpen(false); onToggleActive(wf) }} style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
              <span>{wf.active ? 'Deactivate' : 'Activate'}</span>
            </button>
            <button role="menuitem" onClick={() => { setMenuOpen(false); onExport(wf) }} style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              <span>Download (JSON)</span>
            </button>
            <button role="menuitem" onClick={() => { setMenuOpen(false); onDuplicate(wf) }} style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
              <span>Duplicate</span>
            </button>
            <div className="ctx-sep" />
            <button role="menuitem" className="ctx-danger" onClick={() => { setMenuOpen(false); onDelete(wf) }} style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
              <span>Delete</span>
            </button>
          </PortalMenu>
        </div>
      </td>
    </tr>
  )
}

export default function WorkflowsPage() {
  const navigate = useNavigate()
  const [workflows, setWorkflows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState('')
  const [sortBy, setSortBy] = useState('updated') // updated | name | created
  const [filterActive, setFilterActive] = useState('all') // all | pinned | active | inactive
  const [createOpen, setCreateOpen] = useState(false)
  const [importError, setImportError] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [busy, setBusy] = useState(false)
  const [pinnedIds, setPinnedIds] = useState(() => {
    try {
      const stored = JSON.parse(localStorage.getItem('pinned_workflows') || '[]')
      return new Set(Array.isArray(stored) ? stored : [])
    } catch {
      return new Set()
    }
  })
  const fileRef = useRef(null)
  const createRef = useRef(null)

  const isWfPinned = useCallback((w) => {
    return Boolean(pinnedIds.has(w.id) || w.pinned || w.settings?.pinned)
  }, [pinnedIds])

  const handleTogglePin = async (wf) => {
    const currentlyPinned = isWfPinned(wf)
    const nextPinned = !currentlyPinned
    const nextSet = new Set(pinnedIds)
    if (nextPinned) nextSet.add(wf.id); else nextSet.delete(wf.id)
    setPinnedIds(nextSet)
    try {
      localStorage.setItem('pinned_workflows', JSON.stringify([...nextSet]))
    } catch (err) { console.error('[flowsmith] pages/WorkflowsPage.jsx', err) }

    setWorkflows(prev => prev.map(w => w.id === wf.id ? { ...w, pinned: nextPinned, settings: { ...(w.settings || {}), pinned: nextPinned } } : w))

    try {
      await api.setPinned(wf.id, nextPinned)
    } catch (err) {
      console.warn('Backend setPinned warning (saved in localStorage):', err)
    }
  }

  const load = async () => {
    setLoading(true); setError(null)
    try {
      const data = await api.listWorkflows()
      const list = Array.isArray(data) ? data : []
      setWorkflows(list)
      // Server pin state is authoritative for every workflow it returned —
      // an add-only union would make an unpin (here or on another device)
      // silently revert on reload. Local entries survive only for workflows
      // missing from this response.
      const serverPinned = new Set()
      const idsInList = new Set()
      list.forEach(w => {
        idsInList.add(w.id)
        if (w.pinned || w.settings?.pinned) serverPinned.add(w.id)
      })
      const mergedSet = new Set([...pinnedIds].filter(id => !idsInList.has(id)))
      serverPinned.forEach(id => mergedSet.add(id))
      setPinnedIds(mergedSet)
      try {
        localStorage.setItem('pinned_workflows', JSON.stringify([...mergedSet]))
      } catch (err) { console.error('[flowsmith] pages/WorkflowsPage.jsx', err) }
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load() }, [])
  useEffect(() => {
    if (!createOpen) return
    const onDoc = (e) => { if (createRef.current && !createRef.current.contains(e.target)) setCreateOpen(false) }
    window.addEventListener('pointerdown', onDoc, true)
    window.addEventListener('touchstart', onDoc, true)
    return () => {
      window.removeEventListener('pointerdown', onDoc, true)
      window.removeEventListener('touchstart', onDoc, true)
    }
  }, [createOpen])

  const filtered = useMemo(() => {
    let out = [...workflows]
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      out = out.filter(w => `${w.name} ${w.id}`.toLowerCase().includes(q))
    }
    if (filterActive === 'pinned') {
      out = out.filter(w => isWfPinned(w))
    } else if (filterActive !== 'all') {
      out = out.filter(w => filterActive === 'active' ? w.active : !w.active)
    }
    out.sort((a, b) => {
      // Pinned workflows ALWAYS sort to the top
      const aPinned = isWfPinned(a)
      const bPinned = isWfPinned(b)
      if (aPinned && !bPinned) return -1
      if (!aPinned && bPinned) return 1
      if (sortBy === 'name') return (a.name || '').localeCompare(b.name || '')
      if (sortBy === 'created') return new Date(b.created_at) - new Date(a.created_at)
      return new Date(b.updated_at) - new Date(a.updated_at)
    })
    return out
  }, [workflows, search, sortBy, filterActive, isWfPinned])

  async function handleCreateBlank() {
    setBusy(true)
    try {
      const id = `wf_${Math.random().toString(36).slice(2, 10)}`
      const wf = await api.createWorkflow({ id, name: 'My Workflow', nodes: [], connections: [], settings: {} })
      await load()
      navigate(`/workflows/${wf.id}`)
    } catch (e) { setError(e.message) }
    finally { setBusy(false); setCreateOpen(false) }
  }


  async function handleImportFile(file) {
    setImportError(null)
    try {
      const doc = JSON.parse(await file.text())
      const imported = await api.importWorkflow(doc)
      await load()
      navigate(`/workflows/${imported.id}`)
    } catch (e) { setImportError(e.message) }
  }

  async function handleDuplicate(wf) {
    try {
      // Use export/import roundtrip to duplicate
      const exported = await api.exportWorkflow(wf.id)
      const copyDoc = { ...exported, name: `${exported.name || wf.name} (copy)` }
      // Try import
      const imported = await api.importWorkflow(copyDoc)
      await load()
      navigate(`/workflows/${imported.id}`)
    } catch (e) { setError(e.message) }
  }

  async function handleDelete(wf) {
    try {
      await useWorkflowStore.getState().deleteWorkflow(wf.id)
      await load()
      setDeleteTarget(null)
    } catch (e) { setError(e.message) }
  }

  async function handleToggleActive(wf) {
    try {
      await api.setActive(wf.id, !wf.active)
      await load()
    } catch (e) { setError(e.message) }
  }

  async function handleExport(wf) {
    if (!wf?.id) return
    try {
      const doc = await api.exportWorkflow(wf.id)
      const blob = new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      const safeName = (wf.name || 'workflow').trim().replace(/[^a-zA-Z0-9_-]+/g, '_') || 'workflow'
      a.download = `${safeName}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (e) {
      setError(e.message || 'Failed to download workflow')
    }
  }

  return (
    <div className="page workflows-page">
      <PageHeader
        title="Workflows"
        description="Manage, run, and automate workflows in your workspace."
        breadcrumbs={[{ label: 'Personal' }, { label: 'Workflows' }]}
        actions={
          <div className="page-header-actions-group">
            <div className="create-wrap" ref={createRef}>
              <button className="primary" onClick={() => setCreateOpen(v => !v)} aria-haspopup="menu" aria-expanded={createOpen} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                <span>Create workflow</span>
                <span style={{ fontSize: 10, marginLeft: 2 }}>▼</span>
              </button>
              {createOpen && (
                <div className="dropdown-menu" role="menu">
                  <button
                    role="menuitem"
                    className="dropdown-item--ai-builder"
                    onClick={() => { setCreateOpen(false); navigate('/ai?tab=builder') }}
                    style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: '8px',
                      padding: '10px 14px',
                      background: 'rgba(99, 102, 241, 0.08)',
                      borderBottom: '1px solid var(--border, #334155)',
                      textAlign: 'left',
                      width: '100%',
                      cursor: 'pointer',
                    }}
                  >
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginTop: '2px', color: 'var(--accent, #6366f1)', flexShrink: 0 }}>
                      <rect x="3" y="3" width="7" height="7" rx="1.5" />
                      <rect x="14" y="3" width="7" height="7" rx="1.5" />
                      <rect x="14" y="14" width="7" height="7" rx="1.5" />
                      <rect x="3" y="14" width="7" height="7" rx="1.5" />
                    </svg>
                    <div>
                      <div style={{ fontWeight: 600, color: 'var(--accent, #6366f1)', fontSize: '13px' }}>AI Builder</div>
                      <div style={{ fontSize: '11px', color: 'var(--text-muted, #94a3b8)', marginTop: '2px' }}>Describe what you want</div>
                    </div>
                  </button>
                  <button role="menuitem" onClick={handleCreateBlank} disabled={busy}>Blank workflow</button>
                  <button role="menuitem" onClick={() => { setCreateOpen(false); navigate('/templates') }}>From template</button>
                  <button role="menuitem" onClick={() => { setCreateOpen(false); fileRef.current?.click() }}>Import from file</button>
                </div>
              )}
            </div>
            <input ref={fileRef} type="file" accept="application/json,.json" style={{ display: 'none' }} onChange={e => { const f = e.target.files?.[0]; if (f) handleImportFile(f); e.target.value = '' }} />
          </div>
        }
      />
      <WorkspaceTabs />

      <div className="toolbar">
        <div className="toolbar-left">
          <input className="search-input" placeholder="Search workflows…" value={search} onChange={e => setSearch(e.target.value)} aria-label="Search workflows" />
        </div>
        <div className="toolbar-right">
          <select value={sortBy} onChange={e => setSortBy(e.target.value)} aria-label="Sort by">
            <option value="updated">Sort by last updated</option>
            <option value="created">Sort by created</option>
            <option value="name">Sort by name</option>
          </select>
          <select value={filterActive} onChange={e => setFilterActive(e.target.value)} aria-label="Filter">
            <option value="all">All ({workflows.length})</option>
            <option value="pinned">Pinned ({workflows.filter(isWfPinned).length})</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </div>
      </div>

      {error && <div className="banner-inline err">{error} <button className="ghost small" onClick={() => setError(null)}>Dismiss</button></div>}
      {importError && <div className="banner-inline err">Import failed: {importError}</div>}

      {loading ? <LoadingSkeleton rows={6} /> : filtered.length === 0 ? (
        workflows.length === 0 ? (
          <EmptyState
            icon="workflows"
            badge="Workspace Ready"
            title="Create your first automated workflow"
            description="Build resilient multi-step pipelines connecting 88+ connectors, REST APIs, and autonomous AI agents."
            guidance="Start with a blank canvas, create via AI Builder, or clone from pre-built production templates."
            highlights={[
              {
                icon: (
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" fill="currentColor" fillOpacity="0.2"/></svg>
                ),
                title: 'Visual DAG Canvas',
                desc: 'Drag & drop triggers, conditionals, transforms, and parallel branches.',
              },
              {
                icon: (
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/></svg>
                ),
                title: 'AI Copilot & Agents',
                desc: 'Prompt-to-workflow generation and multi-agent cognitive swarms.',
              },
              {
                icon: (
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M12 2v6m0 8v6M2 12h6m8 0h6"/><rect x="8" y="8" width="8" height="8" rx="2"/></svg>
                ),
                title: '88+ Integrations',
                desc: 'Native connectors for Slack, Salesforce, HubSpot, Stripe, OpenAI, and more.',
              },
            ]}
            action={<button className="primary" onClick={handleCreateBlank} disabled={busy}>Create blank workflow</button>}
            secondaryAction={<button className="ghost" onClick={() => navigate('/templates')}>Browse templates</button>}
          />
        ) : (
          <EmptyState
            icon="search"
            title="No matching workflows"
            description={`No workflows match “${search}” with the current filter.`}
            action={<button className="ghost" onClick={() => { setSearch(''); setFilterActive('all') }}>Reset filters</button>}
          />
        )
      ) : (
        <>
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Workflow</th><th>Status</th><th>Updated</th><th>Created</th><th>Actions</th></tr></thead>
              <tbody>
                {filtered.map(w => (
                  <WorkflowRow
                    key={w.id}
                    wf={w}
                    isPinned={isWfPinned(w)}
                    onTogglePin={handleTogglePin}
                    onOpen={(id) => navigate(`/workflows/${id}`)}
                    onDuplicate={handleDuplicate}
                    onDelete={(wf) => setDeleteTarget(wf)}
                    onToggleActive={handleToggleActive}
                    onExport={handleExport}
                  />
                ))}
              </tbody>
            </table>
          </div>
          <div className="hint" style={{ marginTop: 12, padding: '0 4px', fontSize: 13, color: 'var(--muted)' }}>
            {filtered.length} workflow{filtered.length !== 1 ? 's' : ''} · {workflows.length} total
          </div>
        </>
      )}

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title={`Delete “${deleteTarget?.name}”?`}
        description="This cannot be undone. Executions and versions remain for audit."
        confirmLabel="Delete"
        variant="danger"
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => handleDelete(deleteTarget)}
      />
    </div>
  )
}
