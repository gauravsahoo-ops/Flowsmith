import { useEffect, useState, useCallback } from 'react'
import { api } from '../api'
import PageHeader from '../components/shared/PageHeader'
import EmptyState from '../components/shared/EmptyState'
import LoadingSkeleton from '../components/shared/LoadingSkeleton'
import ConfirmDialog from '../components/shared/ConfirmDialog'
import WorkspaceTabs from '../components/shared/WorkspaceTabs'

export default function KnowledgePage() {
  const [collections, setCollections] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [busy, setBusy] = useState(false)
  const [newName, setNewName] = useState('')
  const [ingestText, setIngestText] = useState('')
  const [docId, setDocId] = useState('')
  const [query, setQuery] = useState('')
  const [result, setResult] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try { const data = await api.listRagCollections(); setCollections(data || []); if (data?.length && !selectedId) setSelectedId(data[0].id) } catch(e){ setError(e.message)} finally{ setLoading(false)}
  }, [selectedId])

  useEffect(() => { load() }, [load])

  async function handleCreate(e) {
    e.preventDefault()
    if (!newName.trim()) return
    setBusy(true); setError(null)
    try { const rec = await api.createRagCollection({ name: newName.trim() }); setNotice(`Created “${rec.name}”.`); setNewName(''); setSelectedId(rec.id); await load() } catch(err){ setError(err.message)} finally{ setBusy(false)}
  }
  async function handleIngest() {
    if (!selectedId || !ingestText.trim()) return
    setBusy(true); setError(null)
    try { const doc = { text: ingestText }; if (docId.trim()) doc.id = docId.trim(); const res = await api.ragIngest(selectedId, { documents: [doc] }); setNotice(`Upserted ${res.chunks_upserted} chunk(s).`); setIngestText(''); await load() } catch(err){ setError(err.message)} finally{ setBusy(false)}
  }
  async function handleQuery(e) {
    e.preventDefault()
    if (!selectedId || !query.trim()) return
    setBusy(true); setError(null)
    try { const res = await api.ragQuery(selectedId, { query: query.trim(), top_k: 5 }); setResult(res)} catch(err){ setError(err.message)} finally{ setBusy(false)}
  }

  const selected = collections.find(c => c.id === selectedId) || null

  return (
    <div className="page knowledge-page">
      <PageHeader title="Knowledge" description="RAG collections — ingest documents, embed with sentence-transformers, and retrieve with similarity search." />
      <WorkspaceTabs />

      <div className="knowledge-layout">
        <div className="knowledge-sidebar">
          <form onSubmit={handleCreate} className="knowledge-create">
            <input placeholder="New collection name" value={newName} onChange={e => setNewName(e.target.value)} disabled={busy} />
            <button className="primary" type="submit" disabled={busy || !newName.trim()}>Create</button>
          </form>

          {error && <div className="banner-inline err">{error}</div>}
          {notice && <div className="banner-inline ok">{notice}</div>}

          {loading ? <LoadingSkeleton rows={3} /> : collections.length === 0 ? (
            <EmptyState icon="knowledge" title="No collections" description="Create a collection to start ingesting documents." />
          ) : (
            <div className="rag-list" style={{ marginTop: 12 }}>
              {collections.map(c => (
                <div key={c.id} className={`rag-row ${c.id === selectedId ? 'is-selected' : ''}`}>
                  <button className="rag-item" onClick={() => { setSelectedId(c.id); setResult(null) }}>
                    <span className="rag-name">{c.name}</span>
                    <span className="rag-meta">{c.workspace_id ? 'workspace' : 'personal'}</span>
                  </button>
                  <button className="ghost small" onClick={() => setDeleteTarget(c)} title="Delete collection" style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                    </svg>
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="knowledge-main">
          {!selected ? (
            <EmptyState
              icon="knowledge"
              badge="Cognitive RAG Engine"
              title="Vector Knowledge Base & Embeddings"
              description="Ingest PDFs, enterprise docs, and API specs for semantic similarity and hybrid retrieval across your AI workflows."
              guidance="Select an existing collection from the sidebar to inspect documents and query embeddings, or create a new collection above."
              highlights={[
                {
                  icon: (
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                  ),
                  title: 'Dense & Sparse Embeddings',
                  desc: 'Vector cosine similarity powered by pgvector and multi-language models.',
                },
                {
                  icon: (
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/></svg>
                  ),
                  title: 'In-Workflow AI Ingestion',
                  desc: 'Auto-embed documents directly inside execution pipelines and swarms.',
                },
              ]}
            />
          ) : (
            <div className="knowledge-detail">
              <h3>{selected.name}</h3>
              <p className="hint">Collection {selected.id.slice(0,8)} · {selected.workspace_id ? 'Workspace scoped' : 'Personal'}</p>

              <section className="card" style={{ marginTop: 16 }}>
                <h4>Ingest document</h4>
                <label>Text<textarea rows={4} value={ingestText} onChange={e => setIngestText(e.target.value)} placeholder="Paste content to embed…" /></label>
                <label>Document ID <span className="hint">(optional; same ID replaces)</span><input value={docId} onChange={e => setDocId(e.target.value)} /></label>
                <button className="ghost" onClick={handleIngest} disabled={busy || !ingestText.trim()} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="22 12 16 12 14 15 10 15 8 12 2 12" />
                    <path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
                  </svg>
                  Ingest / re-index
                </button>
              </section>

              <section className="card" style={{ marginTop: 16 }}>
                <h4>Query</h4>
                <form onSubmit={handleQuery} className="rag-form">
                  <input placeholder="Query this collection…" value={query} onChange={e => setQuery(e.target.value)} disabled={busy} />
                  <button className="primary" type="submit" disabled={busy || !query.trim()} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="11" cy="11" r="8" />
                      <line x1="21" y1="21" x2="16.65" y2="16.65" />
                    </svg>
                    Query
                  </button>
                </form>
                {result && (
                  <div className="rag-result" style={{ marginTop: 12 }}>
                    <p className="hint">{result.debug.after_threshold}/{result.debug.total_candidates} hits ≥ threshold · embed {result.debug.timing_ms.embed}ms · search {result.debug.timing_ms.search}ms</p>
                    {result.hits.map(hit => (
                      <div key={`${hit.ref}-${hit.doc_id}`} className="rag-hit">
                        <span className="check-badge badge-pass">[{hit.ref}]</span>
                        <div className="rag-hit-body">
                          <code className="rag-score">sim {hit.similarity?.toFixed(3)}</code>
                          <div className="rag-excerpt">{hit.content?.slice(0, 240)}</div>
                          {hit.metadata?.document_id && <div className="rag-meta">doc {hit.metadata.document_id} · chunk {hit.metadata.chunk_index ?? '?'}</div>}
                        </div>
                      </div>
                    ))}
                    {result.hits.length === 0 && <p className="hint">Nothing above threshold.</p>}
                  </div>
                )}
              </section>
            </div>
          )}
        </div>
      </div>

      <ConfirmDialog open={Boolean(deleteTarget)} title={`Delete “${deleteTarget?.name}”?`} description="All vectors in this collection will be deleted." confirmLabel="Delete" variant="danger" onCancel={() => setDeleteTarget(null)} onConfirm={async () => { try{ await api.deleteRagCollection(deleteTarget.id); if (selectedId === deleteTarget.id) { setSelectedId(null); setResult(null)} setNotice(`Deleted “${deleteTarget.name}”.`); await load() } catch(e){ setError(e.message)} finally{ setDeleteTarget(null)} }} />
    </div>
  )
}
