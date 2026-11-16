import { useCallback, useEffect, useRef, useState } from 'react'
import EmptyState from '../../components/shared/EmptyState'
import ErrorState from '../../components/shared/ErrorState'
import LoadingSkeleton from '../../components/shared/LoadingSkeleton'
import ApprovalDetailDrawer from './ApprovalDetailDrawer'
import { decideApproval, getApproval, listApprovals, resumeApprovalRun } from './approvalsApi'
import {
  approvalActionLabel,
  approvalStatusMeta,
  describeApprovalError,
  expiryMeta,
  formatTimestamp,
  generateDecisionNonce,
  riskTierMeta,
} from './approvalUtils'

const STATUS_OPTIONS = [
  { value: 'pending', label: 'Pending' },
  { value: 'approved', label: 'Approved' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'expired', label: 'Expired' },
  { value: 'cancelled', label: 'Cancelled' },
  { value: '', label: 'All statuses' },
]

function shortId(value) {
  if (!value) return '—'
  return value.length > 18 ? `${value.slice(0, 16)}…` : value
}

export function ApprovalInboxView({
  rows = [],
  loading = false,
  error = null,
  statusFilter = 'pending',
  onStatusChange = () => {},
  onRefresh = () => {},
  onSelect = () => {},
  selectedId = null,
}) {
  const errorInfo = describeApprovalError(error, 'list')

  return (
    <>
      <div className="exec-filter-bar" style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <label htmlFor="approval-status-filter" style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            Status
          </label>
          <select
            id="approval-status-filter"
            value={statusFilter}
            onChange={(event) => onStatusChange(event.target.value)}
            aria-label="Filter tool approvals by status"
          >
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value || 'all'} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            <strong>{rows.length}</strong> {rows.length === 1 ? 'request' : 'requests'}
          </span>
          <button type="button" className="ghost small" onClick={onRefresh} disabled={loading}>
            ↻ Refresh
          </button>
        </div>
      </div>

      {loading ? (
        <div aria-busy="true" aria-live="polite">
          <p className="hint" style={{ marginBottom: 10 }}>Loading tool approvals…</p>
          <LoadingSkeleton rows={6} />
        </div>
      ) : errorInfo ? (
        <ErrorState
          title={errorInfo.title}
          description={errorInfo.description}
          action={<button type="button" className="ghost" onClick={onRefresh}>Retry</button>}
        />
      ) : rows.length === 0 ? (
        <EmptyState
          icon="approvals"
          title={statusFilter === 'pending' ? 'No pending tool approvals' : 'No tool approvals match this filter'}
          description={
            statusFilter === 'pending'
              ? 'When an agent or tool pauses for a human decision, the redacted request appears here with its risk tier and expiry.'
              : 'Try another status or refresh the inbox to check for new approval requests.'
          }
          action={<button type="button" className="primary" onClick={onRefresh}>Refresh inbox</button>}
        />
      ) : (
        <div className="table-wrap" style={{ overflowX: 'auto' }}>
          <table className="data-table" aria-label="Tool approval requests">
            <thead>
              <tr>
                <th style={{ minWidth: 130 }}>Risk tier</th>
                <th style={{ minWidth: 190 }}>Tool / action</th>
                <th style={{ minWidth: 150 }}>Run</th>
                <th style={{ minWidth: 160 }}>Requested</th>
                <th style={{ minWidth: 150 }}>Expires</th>
                <th style={{ minWidth: 100 }}>Status</th>
                <th style={{ minWidth: 90, textAlign: 'right' }}>Review</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const risk = riskTierMeta(row.risk_tier)
                const status = approvalStatusMeta(row.status)
                const expiry = expiryMeta(row.expires_at)
                const selected = selectedId === row.id

                return (
                  <tr
                    key={row.id}
                    className="clickable"
                    tabIndex={0}
                    onClick={() => onSelect(row)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        onSelect(row)
                      }
                    }}
                    style={selected ? { background: 'rgba(99, 102, 241, 0.09)' } : undefined}
                  >
                    <td>
                      <span
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: 5,
                          fontSize: 11,
                          fontWeight: 650,
                          color: risk.tone,
                          background: 'rgba(255, 255, 255, 0.05)',
                          border: `1px solid ${risk.tone}55`,
                          borderRadius: 5,
                          padding: '2px 7px',
                        }}
                        title={risk.label}
                      >
                        Tier {row.risk_tier ?? 0}
                      </span>
                      <div className="hint" style={{ fontSize: 10.5, marginTop: 4 }}>{risk.label}</div>
                    </td>
                    <td>
                      <strong style={{ color: '#f1f5f9', fontSize: 12.5 }}>
                        {approvalActionLabel(row)}
                      </strong>
                      {(row.reason || row.summary) && (
                        <div
                          className="hint"
                          style={{
                            fontSize: 11,
                            marginTop: 3,
                            maxWidth: 260,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                          title={row.reason || row.summary}
                        >
                          {row.reason || row.summary}
                        </div>
                      )}
                    </td>
                    <td>
                      <code className="exec-id-cell" title={row.run_id || undefined} style={{ fontSize: 11.5 }}>
                        {shortId(row.run_id)}
                      </code>
                      {row.node_id && (
                        <div className="hint" style={{ fontSize: 10.5, marginTop: 3 }}>Node: {row.node_id}</div>
                      )}
                    </td>
                    <td>
                      <span title={row.created_at || undefined} style={{ fontSize: 12 }}>
                        {formatTimestamp(row.created_at)}
                      </span>
                      <div className="hint" style={{ fontSize: 10.5, marginTop: 3 }}>
                        {row.requested_by == null ? 'System' : `User #${row.requested_by}`}
                      </div>
                    </td>
                    <td>
                      <span title={row.expires_at || undefined} style={{ fontSize: 12 }}>
                        {formatTimestamp(row.expires_at)}
                      </span>
                      <div
                        className="hint"
                        style={{
                          fontSize: 10.5,
                          marginTop: 3,
                          color: expiry.expired ? '#f87171' : expiry.urgent ? '#fbbf24' : undefined,
                        }}
                      >
                        {expiry.text}
                      </div>
                    </td>
                    <td>
                      <span
                        className={`status-label status-${row.status}`}
                        style={{
                          color: status.tone,
                          borderColor: `${status.tone}55`,
                          background: `${status.tone}14`,
                        }}
                      >
                        {status.label}
                      </span>
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <button
                        type="button"
                        className="ghost small"
                        onClick={(event) => {
                          event.stopPropagation()
                          onSelect(row)
                        }}
                      >
                        Review →
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

export default function ToolApprovalInbox() {
  const [rows, setRows] = useState([])
  const [statusFilter, setStatusFilter] = useState('pending')
  const [loading, setLoading] = useState(true)
  const [listError, setListError] = useState(null)
  const [notice, setNotice] = useState(null)

  const [selectedId, setSelectedId] = useState(null)
  const [detail, setDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState(null)
  const [decisionNonce, setDecisionNonce] = useState('')
  const [comment, setComment] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [decisionError, setDecisionError] = useState(null)
  const [resuming, setResuming] = useState(false)
  const [resumeError, setResumeError] = useState(null)
  const [resumedRunId, setResumedRunId] = useState(null)

  const listSeq = useRef(0)
  const detailSeq = useRef(0)
  const resumeLock = useRef(false)

  const loadRows = useCallback(async ({ silent = false } = {}) => {
    const seq = listSeq.current + 1
    listSeq.current = seq
    if (!silent) setLoading(true)
    setListError(null)
    try {
      const data = await listApprovals({ status: statusFilter })
      if (seq !== listSeq.current) return
      setRows(Array.isArray(data) ? data : [])
    } catch (err) {
      if (seq !== listSeq.current) return
      setRows([])
      setListError(err)
    } finally {
      if (seq === listSeq.current) setLoading(false)
    }
  }, [statusFilter])

  useEffect(() => {
    loadRows()
  }, [loadRows])

  useEffect(() => () => {
    listSeq.current += 1
    detailSeq.current += 1
  }, [])

  function handleStatusChange(nextStatus) {
    setStatusFilter(nextStatus)
    setNotice(null)
    closeDetail()
  }

  function closeDetail() {
    detailSeq.current += 1
    setSelectedId(null)
    setDetail(null)
    setDetailError(null)
    setDetailLoading(false)
    setDecisionError(null)
    setResumeError(null)
    setResumedRunId(null)
    setComment('')
    setDecisionNonce('')
  }

  async function openRequest(row) {
    if (!row?.id) return
    const seq = detailSeq.current + 1
    detailSeq.current = seq
    setSelectedId(row.id)
    setDetail(null)
    setDetailError(null)
    setDetailLoading(true)
    setDecisionError(null)
    setResumeError(null)
    setResumedRunId(null)
    setComment('')
    setNotice(null)
    setDecisionNonce(generateDecisionNonce())

    try {
      const data = await getApproval(row.id)
      if (seq !== detailSeq.current) return
      setDetail(data)
    } catch (err) {
      if (seq !== detailSeq.current) return
      setDetailError(err)
    } finally {
      if (seq === detailSeq.current) setDetailLoading(false)
    }
  }

  async function handleDecide(approved) {
    if (!detail || detail.status !== 'pending' || submitting) return
    const nonce = decisionNonce || generateDecisionNonce()
    if (!decisionNonce) setDecisionNonce(nonce)

    setSubmitting(true)
    setDecisionError(null)
    setNotice(null)
    try {
      const updated = await decideApproval(detail.id, {
        approved,
        nonce,
        comment: comment.trim(),
      })
      setDetail(updated)
      setComment('')

      if (updated.status === 'pending') {
        const approvals = (updated.decision?.decisions || []).filter((item) => item.approved).length
        const remaining = Math.max(0, (updated.quorum || 1) - approvals)
        setNotice(
          remaining > 0
            ? `Decision recorded. ${remaining} more approval${remaining === 1 ? '' : 's'} required.`
            : 'Decision recorded.',
        )
      } else {
        setNotice(
          updated.status === 'approved' || updated.status === 'rejected'
            ? `Approval request ${updated.status}. Use "Resume run" below to continue the execution when you are ready.`
            : `Approval request ${updated.status}.`,
        )
      }

      await loadRows({ silent: true })
    } catch (err) {
      setDecisionError(err)
      if (err.status === 409) {
        try {
          const fresh = await getApproval(detail.id)
          setDetail(fresh)
        } catch {
          // Keep the current detail and surface the conflict below.
        }
        await loadRows({ silent: true })
      }
    } finally {
      setSubmitting(false)
    }
  }

  async function handleResume() {
    if (!detail?.run_id) return
    const statusKey = String(detail.status || '').toLowerCase()
    if (statusKey !== 'approved' && statusKey !== 'rejected') return
    if (resumeLock.current || resumedRunId === detail.run_id) return

    const runId = detail.run_id
    resumeLock.current = true
    setResuming(true)
    setResumeError(null)
    setNotice(null)
    try {
      await resumeApprovalRun(runId, statusKey === 'approved')
      setResumedRunId(runId)
      setNotice('Run queued for resume.')
      await loadRows({ silent: true })
    } catch (err) {
      setResumeError(err)
    } finally {
      resumeLock.current = false
      setResuming(false)
    }
  }

  return (
    <>
      {notice && <div className="banner-inline ok" style={{ marginBottom: 12 }}>{notice}</div>}
      <ApprovalInboxView
        rows={rows}
        loading={loading}
        error={listError}
        statusFilter={statusFilter}
        onStatusChange={handleStatusChange}
        onRefresh={() => loadRows()}
        onSelect={openRequest}
        selectedId={selectedId}
      />
      {selectedId && (
        <ApprovalDetailDrawer
          request={detail}
          loading={detailLoading}
          error={detailError}
          submitting={submitting}
          decisionError={decisionError}
          comment={comment}
          notice={notice}
          resuming={resuming}
          resumeError={resumeError}
          resumeQueued={Boolean(detail?.run_id) && resumedRunId === detail.run_id}
          onCommentChange={setComment}
          onDecide={handleDecide}
          onResume={handleResume}
          onClose={closeDetail}
        />
      )}
    </>
  )
}
