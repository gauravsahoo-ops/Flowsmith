// RagPanel: knowledge-base collections (Phase 18: production RAG).
//
// Collections are tenant-scoped server-side (workspace or personal).
// Ingestion is idempotent per document id; the query box is also the
// retrieval debugger — it shows scores, the threshold funnel and
// per-phase timings, plus citation refs for each hit.

import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'

export default function RagPanel({ open, onClose }) {
  const [collections, setCollections] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [busy, setBusy] = useState(false)

  const [newName, setNewName] = useState('')
  const [ingestText, setIngestText] = useState('')
  const [docId, setDocId] = useState('')
  const [query, setQuery] = useState('')
  const [result, setResult] = useState(null) // {hits, debug}

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.listRagCollections()
      setCollections(data || [])
      if (data?.length && !selectedId) setSelectedId(data[0].id)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (open) load()
  }, [open, load])

  async function createCollection(e) {
    e.preventDefault()
    if (!newName.trim()) return
    setBusy(true)
    setError(null)
    try {
      const rec = await api.createRagCollection({ name: newName.trim() })
      setNotice(`Created “${rec.name}”.`)
      setNewName('')
      setSelectedId(rec.id)
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function removeCollection(c) {
    if (!window.confirm(`Delete collection “${c.name}” and all of its vectors?`)) return
    setError(null)
    try {
      await api.deleteRagCollection(c.id)
      if (selectedId === c.id) {
        setSelectedId(null)
        setResult(null)
      }
      setNotice(`Deleted “${c.name}”.`)
      await load()
    } catch (err) {
      setError(err.message)
    }
  }

  async function ingest() {
    if (!selectedId || !ingestText.trim()) return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const doc = { text: ingestText }
      if (docId.trim()) doc.id = docId.trim()
      const res = await api.ragIngest(selectedId, { documents: [doc] })
      setNotice(`Upserted ${res.chunks_upserted} chunk(s).`)
      setIngestText('')
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function runQuery(e) {
    e.preventDefault()
    if (!selectedId || !query.trim()) return
    setBusy(true)
    setError(null)
    try {
      const res = await api.ragQuery(selectedId, { query: query.trim(), top_k: 5 })
      setResult(res)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (!open) return null

  const selected = collections.find((c) => c.id === selectedId) || null

  return (
    <aside className="panel ragpanel">
      <header>
        <h2>Knowledge bases</h2>
        <button className="ghost" onClick={onClose} title="Close">✕</button>
      </header>
      <p className="hint">
        Collections are private to you (or scoped to their workspace).
        Ingestion replaces documents with the same id — re-index freely.
      </p>

      <form className="rag-form" onSubmit={createCollection}>
        <input placeholder="New collection name" value={newName}
          onChange={(e) => setNewName(e.target.value)} disabled={busy} />
        <button className="primary" type="submit" disabled={busy || !newName.trim()}>
          Create
        </button>
      </form>

      {error && <div className="banner-inline err">{error}</div>}
      {notice && <div className="banner-inline ok">{notice}</div>}

      {!loading && collections.length === 0 && <p className="hint">No collections yet.</p>}
      <div className="rag-list">
        {collections.map((c) => (
          <div key={c.id} className={`rag-row ${c.id === selectedId ? 'is-selected' : ''}`}>
            <button className="rag-item" onClick={() => { setSelectedId(c.id); setResult(null) }}>
              <span className="rag-name">{c.name}</span>
              <span className="rag-meta">{c.workspace_id ? 'workspace' : 'personal'}</span>
            </button>
            <button className="ghost" onClick={() => removeCollection(c)} title="Delete collection">🗑</button>
          </div>
        ))}
      </div>

      {selected && (
        <section className="rag-detail">
          <h3>{selected.name}</h3>

          <label className="rag-field">
            Document text
            <textarea rows={4} value={ingestText} spellCheck="false"
              onChange={(e) => setIngestText(e.target.value)}
              placeholder="Paste content to embed…" />
          </label>
          <label className="rag-field">
            Document id <span className="hint">(optional; same id replaces)</span>
            <input value={docId} onChange={(e) => setDocId(e.target.value)} />
          </label>
          <button className="ghost" onClick={ingest} disabled={busy || !ingestText.trim()}>
            📥 Ingest / re-index
          </button>

          <form className="rag-form" onSubmit={runQuery}>
            <input placeholder="Query this collection…" value={query}
              onChange={(e) => setQuery(e.target.value)} disabled={busy} />
            <button className="primary" type="submit" disabled={busy || !query.trim()}>
              🔍 Query
            </button>
          </form>

          {result && (
            <div className="rag-result">
              <p className="hint">
                {result.debug.after_threshold}/{result.debug.total_candidates} hits ≥
                {' '}threshold · embed {result.debug.timing_ms.embed}ms · search{' '}
                {result.debug.timing_ms.search}ms
              </p>
              {result.hits.map((hit) => (
                <div key={`${hit.ref}-${hit.doc_id}`} className="rag-hit">
                  <span className="check-badge badge-pass">[{hit.ref}]</span>
                  <div className="rag-hit-body">
                    <code className="rag-score">sim {hit.similarity?.toFixed(3)}</code>
                    <div className="rag-excerpt">{hit.content?.slice(0, 180)}</div>
                    {hit.metadata?.document_id && (
                      <div className="rag-meta">doc {hit.metadata.document_id} · chunk {hit.metadata.chunk_index ?? '?'}</div>
                    )}
                  </div>
                </div>
              ))}
              {result.hits.length === 0 && <p className="hint">Nothing above threshold.</p>}
            </div>
          )}
        </section>
      )}
    </aside>
  )
}
