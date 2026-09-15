import { useEffect, useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api'

export default function GlobalSearch({ open, onClose }) {
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState({ workflows: [], credentials: [], templates: [], dataTables: [], executions: [] })
  const inputRef = useRef(null)
  const navigate = useNavigate()

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 30)
    } else {
      setQuery('')
      setResults({ workflows: [], credentials: [], templates: [], dataTables: [], executions: [] })
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  useEffect(() => {
    const q = query.trim().toLowerCase()
    if (!q || q.length < 2) {
      setResults({ workflows: [], credentials: [], templates: [], dataTables: [], executions: [] })
      return
    }
    let cancelled = false
    setLoading(true)
    const t = setTimeout(async () => {
      try {
        const [workflows, creds, templates, dtRes] = await Promise.all([
          api.listWorkflows().catch(() => []),
          api.listCredentials().catch(() => []),
          api.listTemplates().catch(() => []),
          api.listDataTables({ pageSize: 100 }).then(r => r.data || []).catch(() => []),
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
        setResults({ workflows: wf, credentials: cr, templates: tp, dataTables: dts, executions: [] })
      } catch {
        if (!cancelled) setResults({ workflows: [], credentials: [], templates: [], dataTables: [], executions: [] })
      } finally {
        if (!cancelled) setLoading(false)
      }
    }, 250)
    return () => { cancelled = true; clearTimeout(t) }
  }, [query])

  const hasResults = results.workflows.length || results.credentials.length || results.templates.length || results.dataTables.length
  const total = results.workflows.length + results.credentials.length + results.templates.length + results.dataTables.length

  if (!open) return null

  function go(path) {
    onClose()
    navigate(path)
  }

  return (
    <div className="palette-overlay" onClick={onClose} role="dialog" aria-modal="true" aria-label="Global search">
      <div className="palette global-search" onClick={e => e.stopPropagation()}>
        <input
          ref={inputRef}
          className="palette-input"
          placeholder="Search workflows, credentials, templates, tables…"
          value={query}
          onChange={e => setQuery(e.target.value)}
        />
        <div className="global-search-body">
          {loading && <p className="hint" style={{ padding: '12px 16px' }}>Searching…</p>}
          {!loading && query.trim().length >= 2 && !hasResults && (
            <p className="hint" style={{ padding: '12px 16px' }}>No results for “{query}”.</p>
          )}
          {!loading && query.trim().length < 2 && (
            <p className="hint" style={{ padding: '12px 16px' }}>Type at least 2 characters to search.</p>
          )}
          {results.workflows.length > 0 && (
            <section className="global-search-group">
              <h4 className="global-search-heading">Workflows</h4>
              {results.workflows.map(w => (
                <button key={w.id} className="palette-item" onClick={() => go(`/workflows/${w.id}`)}>
                  <span className="palette-title">{w.name || w.id}</span>
                  <span className="palette-kind">{w.active ? 'active' : 'inactive'} · v{w.version}</span>
                </button>
              ))}
            </section>
          )}
          {results.credentials.length > 0 && (
            <section className="global-search-group">
              <h4 className="global-search-heading">Credentials</h4>
              {results.credentials.map(c => (
                <button key={c.id} className="palette-item" onClick={() => go('/credentials')}>
                  <span className="palette-title">{c.name}</span>
                  <span className="palette-kind">{c.type}</span>
                </button>
              ))}
            </section>
          )}
          {results.templates.length > 0 && (
            <section className="global-search-group">
              <h4 className="global-search-heading">Templates</h4>
              {results.templates.map(t => (
                <button key={t.id} className="palette-item" onClick={() => go('/templates')}>
                  <span className="palette-title">{t.name}</span>
                  <span className="palette-kind">{t.category}</span>
                </button>
              ))}
            </section>
          )}
          {results.dataTables.length > 0 && (
            <section className="global-search-group">
              <h4 className="global-search-heading">Data Tables</h4>
              {results.dataTables.map(t => (
                <button key={t.id} className="palette-item" onClick={() => go(`/data-tables/${t.id}`)}>
                  <span className="palette-title">{t.name}</span>
                  <span className="palette-kind">{t.columns?.length ?? 0} cols</span>
                </button>
              ))}
            </section>
          )}
          {hasResults && (
            <div className="palette-foot hint">{total} result{total !== 1 ? 's' : ''} · Press Esc to close · Ctrl+K to reopen</div>
          )}
        </div>
      </div>
    </div>
  )
}
