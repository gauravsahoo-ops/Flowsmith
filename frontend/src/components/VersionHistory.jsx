import { useState, useEffect, useMemo } from 'react'
import { api } from '../api'
import { EmptyState } from './shared/EmptyState'
import { LoadingSkeleton } from './shared/LoadingSkeleton'
import { Status } from './shared/Status'

function VersionDiff({ oldVersion, newVersion }) {
  const changes = useMemo(() => {
    if (!oldVersion || !newVersion) return []
    const diffs = []
    const oldNodes = oldVersion.nodes || []
    const newNodes = newVersion.nodes || []
    const oldEdges = oldVersion.edges || []
    const newEdges = newVersion.edges || []

    const oldNodeIds = new Set(oldNodes.map((n) => n.id))
    const newNodeIds = new Set(newNodes.map((n) => n.id))

    for (const n of newNodes) {
      if (!oldNodeIds.has(n.id)) {
        diffs.push({ type: 'added', kind: 'node', id: n.id, label: n.type || n.id })
      }
    }
    for (const n of oldNodes) {
      if (!newNodeIds.has(n.id)) {
        diffs.push({ type: 'removed', kind: 'node', id: n.id, label: n.type || n.id })
      }
    }

    const oldNodeMap = Object.fromEntries(oldNodes.map((n) => [n.id, n]))
    const newNodeMap = Object.fromEntries(newNodes.map((n) => [n.id, n]))
    for (const id of oldNodeIds) {
      if (newNodeIds.has(id)) {
        const old = JSON.stringify(oldNodeMap[id])
        const nw = JSON.stringify(newNodeMap[id])
        if (old !== nw) {
          diffs.push({ type: 'modified', kind: 'node', id, label: newNodeMap[id].type || id })
        }
      }
    }

    const oldEdgeSet = new Set(oldEdges.map((e) => `${e.source}->${e.target}`))
    const newEdgeSet = new Set(newEdges.map((e) => `${e.source}->${e.target}`))
    for (const e of newEdges) {
      const key = `${e.source}->${e.target}`
      if (!oldEdgeSet.has(key)) {
        diffs.push({ type: 'added', kind: 'edge', id: key, label: `${e.source} → ${e.target}` })
      }
    }
    for (const e of oldEdges) {
      const key = `${e.source}->${e.target}`
      if (!newEdgeSet.has(key)) {
        diffs.push({ type: 'removed', kind: 'edge', id: key, label: `${e.source} → ${e.target}` })
      }
    }
    return diffs
  }, [oldVersion, newVersion])

  if (changes.length === 0) return <p style={{ color: '#888', fontSize: 13 }}>No differences</p>

  return (
    <div style={{ fontSize: 13 }}>
      {changes.map((c, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0' }}>
          <Status
            status={c.type === 'added' ? 'success' : c.type === 'removed' ? 'failed' : 'idle'}
          />
          <span style={{ color: '#888', width: 60 }}>{c.type}</span>
          <span style={{ color: '#aaa', width: 40 }}>{c.kind}</span>
          <span style={{ fontFamily: 'monospace' }}>{c.label}</span>
        </div>
      ))}
    </div>
  )
}

export function VersionHistory({ workflowId }) {
  const [versions, setVersions] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(null)
  const [compareWith, setCompareWith] = useState(null)
  const [rollbacking, setRollbacking] = useState(false)

  useEffect(() => {
    if (!workflowId) return
    setLoading(true)
    api
      .listVersions(workflowId)
      .then(({ data }) => setVersions(data || []))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [workflowId])

  const handleRollback = async (version) => {
    if (!confirm(`Rollback to version ${version}?`)) return
    setRollbacking(true)
    try {
      await api.rollbackVersion(workflowId, { version })
      const { data } = await api.listVersions(workflowId)
      setVersions(data || [])
      setSelected(null)
      setCompareWith(null)
    } catch (err) {
      alert(`Rollback failed: ${err.message}`)
    } finally {
      setRollbacking(false)
    }
  }

  if (loading) return <LoadingSkeleton rows={8} />
  if (error) return <EmptyState title="Error loading versions" description={error} />
  if (versions.length === 0) return <EmptyState title="No versions yet" description="Versions are created automatically when you save changes." />

  return (
    <div>
      <h3 style={{ marginBottom: 16 }}>Version History</h3>
      <div style={{ display: 'flex', gap: 16 }}>
        <div style={{ flex: '0 0 280px' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {versions.map((v) => (
              <div
                key={v.version}
                onClick={() => setSelected(v)}
                style={{
                  padding: '10px 14px',
                  borderRadius: 6,
                  cursor: 'pointer',
                  background: selected?.version === v.version ? '#1a3a5c' : 'transparent',
                  border: `1px solid ${selected?.version === v.version ? '#2563eb' : 'transparent'}`,
                  transition: 'all 0.15s',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontWeight: 600, fontSize: 14 }}>v{v.version}</span>
                  <span style={{ fontSize: 11, color: '#888' }}>
                    {new Date(v.updated_at).toLocaleString()}
                  </span>
                </div>
                {v.node_count != null && (
                  <span style={{ fontSize: 11, color: '#888' }}>{v.node_count} nodes</span>
                )}
              </div>
            ))}
          </div>
        </div>

        <div style={{ flex: 1 }}>
          {selected ? (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
                <h4 style={{ margin: 0 }}>Version {selected.version}</h4>
                <div style={{ display: 'flex', gap: 8 }}>
                  <select
                    value={compareWith?.version || ''}
                    onChange={(e) => {
                      const v = versions.find((x) => x.version === Number(e.target.value))
                      setCompareWith(v || null)
                    }}
                    style={{ padding: '4px 8px', borderRadius: 4, background: '#1a1a2e', color: '#fff', border: '1px solid #333' }}
                  >
                    <option value="">Compare with...</option>
                    {versions
                      .filter((v) => v.version !== selected.version)
                      .map((v) => (
                        <option key={v.version} value={v.version}>v{v.version}</option>
                      ))}
                  </select>
                  {selected.version > 1 && (
                    <button
                      className="ghost"
                      onClick={() => handleRollback(selected.version)}
                      disabled={rollbacking}
                    >
                      ↻ Rollback to v{selected.version}
                    </button>
                  )}
                </div>
              </div>
              {compareWith && (
                <div className="card" style={{ padding: 16, marginBottom: 12 }}>
                  <h5 style={{ margin: '0 0 8px' }}>
                    Diff: v{Math.min(compareWith.version, selected.version)} → v{Math.max(compareWith.version, selected.version)}
                  </h5>
                  <VersionDiff
                    oldVersion={compareWith.version < selected.version ? compareWith : selected}
                    newVersion={compareWith.version < selected.version ? selected : compareWith}
                  />
                </div>
              )}
              <div className="card" style={{ padding: 16 }}>
                <h5 style={{ margin: '0 0 8px' }}>Nodes</h5>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {(selected.nodes || []).map((n) => (
                    <div key={n.id} style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13 }}>
                      <Status status="success" />
                      <span style={{ fontFamily: 'monospace' }}>{n.id}</span>
                      <span style={{ color: '#888' }}>({n.type || 'unknown'})</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <EmptyState title="Select a version" description="Click a version on the left to view details." />
          )}
        </div>
      </div>
    </div>
  )
}
