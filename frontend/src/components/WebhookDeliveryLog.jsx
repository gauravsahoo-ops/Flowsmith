import { useState, useEffect, useCallback } from 'react'
import { api } from '../api'
import Status from './shared/Status'
import EmptyState from './shared/EmptyState'
import LoadingSkeleton from './shared/LoadingSkeleton'

const STATUS_VARIANTS = {
  success: 'ok',
  failed: 'err',
  pending: 'warn',
  retrying: 'warn',
}

function DeliveryRow({ delivery, onSelect }) {
  const variant = STATUS_VARIANTS[delivery.status] || 'ok'
  return (
    <tr
      onClick={() => onSelect(delivery)}
      style={{ cursor: 'pointer' }}
      className="hover-row"
    >
      <td>
        <Status status={delivery.status} />
      </td>
      <td style={{ fontFamily: 'monospace', fontSize: 12 }}>
        {delivery.response_status || '—'}
      </td>
      <td style={{ fontSize: 12 }}>
        {delivery.response_time_ms != null ? `${delivery.response_time_ms}ms` : '—'}
      </td>
      <td style={{ fontSize: 12 }}>
        {new Date(delivery.created_at).toLocaleString()}
      </td>
      <td>
        <span className={`badge badge-${variant}`}>{delivery.attempt || 1}</span>
      </td>
    </tr>
  )
}

function DeliveryDetail({ delivery, onClose }) {
  if (!delivery) return null
  return (
    <div className="card" style={{ marginTop: 12, padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
        <h4 style={{ margin: 0 }}>Delivery #{delivery.id}</h4>
        <button className="ghost" onClick={onClose}>✕</button>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, fontSize: 13 }}>
        <div>
          <strong>Status:</strong> <Status status={delivery.status} />
        </div>
        <div>
          <strong>HTTP {delivery.response_status || '—'}</strong>
        </div>
        <div>
          <strong>Duration:</strong> {delivery.response_time_ms != null ? `${delivery.response_time_ms}ms` : '—'}
        </div>
        <div>
          <strong>Attempt:</strong> {delivery.attempt || 1} / {delivery.max_attempts || 1}
        </div>
        <div style={{ gridColumn: '1 / -1' }}>
          <strong>URL:</strong> <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{delivery.url || '—'}</span>
        </div>
        {delivery.error && (
          <div style={{ gridColumn: '1 / -1' }}>
            <strong>Error:</strong>
            <pre style={{ background: '#1a1a2e', padding: 8, borderRadius: 4, fontSize: 12, marginTop: 4, overflow: 'auto' }}>
              {typeof delivery.error === 'string' ? delivery.error : JSON.stringify(delivery.error, null, 2)}
            </pre>
          </div>
        )}
        {delivery.request_headers && (
          <div style={{ gridColumn: '1 / -1' }}>
            <strong>Request Headers:</strong>
            <pre style={{ background: '#1a1a2e', padding: 8, borderRadius: 4, fontSize: 12, marginTop: 4 }}>
              {JSON.stringify(delivery.request_headers, null, 2)}
            </pre>
          </div>
        )}
        {delivery.response_body && (
          <div style={{ gridColumn: '1 / -1' }}>
            <strong>Response Body:</strong>
            <pre style={{ background: '#1a1a2e', padding: 8, borderRadius: 4, fontSize: 12, marginTop: 4, maxHeight: 200, overflow: 'auto' }}>
              {typeof delivery.response_body === 'string'
                ? delivery.response_body
                : JSON.stringify(delivery.response_body, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  )
}

export function WebhookDeliveryLog({ workflowId, nodeId }) {
  const [deliveries, setDeliveries] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(null)
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(false)

  const fetchDeliveries = useCallback(async (p = 1) => {
    setLoading(true)
    setError(null)
    try {
      const params = { workflow_id: workflowId, page: p, pageSize: 20 }
      if (nodeId) params.node_id = nodeId
      const { data, meta } = await api.listWebhookDeliveries(params)
      setDeliveries(data || [])
      setHasMore(meta?.has_more || false)
      setPage(p)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [workflowId, nodeId])

  useEffect(() => {
    fetchDeliveries(1)
  }, [fetchDeliveries])

  if (loading && deliveries.length === 0) return <LoadingSkeleton rows={5} />
  if (error) return <EmptyState title="Error loading deliveries" description={error} />
  if (deliveries.length === 0) return <EmptyState title="No deliveries yet" description="Webhook deliveries will appear here after the workflow runs." />

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <h3 style={{ margin: 0 }}>Webhook Deliveries</h3>
        <button className="ghost" onClick={() => fetchDeliveries(page)} disabled={loading}>
          ↻ Refresh
        </button>
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #333', textAlign: 'left' }}>
              <th style={{ padding: '8px 12px' }}>Status</th>
              <th style={{ padding: '8px 12px' }}>HTTP</th>
              <th style={{ padding: '8px 12px' }}>Duration</th>
              <th style={{ padding: '8px 12px' }}>Time</th>
              <th style={{ padding: '8px 12px' }}>Attempt</th>
            </tr>
          </thead>
          <tbody>
            {deliveries.map((d) => (
              <DeliveryRow
                key={d.id}
                delivery={d}
                onSelect={setSelected}
              />
            ))}
          </tbody>
        </table>
      </div>
      {hasMore && (
        <div style={{ textAlign: 'center', marginTop: 12 }}>
          <button className="ghost" onClick={() => fetchDeliveries(page + 1)} disabled={loading}>
            Load More
          </button>
        </div>
      )}
      <DeliveryDetail delivery={selected} onClose={() => setSelected(null)} />
    </div>
  )
}
