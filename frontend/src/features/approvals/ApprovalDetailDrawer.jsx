import { useEffect } from 'react'
import ErrorState from '../../components/shared/ErrorState'
import {
  approvalActionLabel,
  approvalStatusMeta,
  describeApprovalError,
  describeResumeError,
  expiryMeta,
  formatApprovers,
  formatTimestamp,
  redactForDisplay,
  riskTierMeta,
  stringifyRedacted,
} from './approvalUtils'

const PRE_STYLE = {
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
  maxHeight: 280,
  overflow: 'auto',
  background: 'rgba(0, 0, 0, 0.28)',
  border: '1px solid rgba(255, 255, 255, 0.06)',
  borderRadius: 8,
  padding: '10px 12px',
  fontSize: 12,
  color: '#cbd5e1',
  margin: 0,
}

const TEXTAREA_STYLE = {
  width: '100%',
  resize: 'vertical',
  background: 'rgba(0, 0, 0, 0.25)',
  color: '#e2e8f0',
  border: '1px solid rgba(255, 255, 255, 0.12)',
  borderRadius: 8,
  padding: '10px 12px',
  fontFamily: 'inherit',
  fontSize: 13,
}

function Meta({ label, value }) {
  return (
    <div>
      <div
        className="hint"
        style={{ fontSize: 10.5, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 2 }}
      >
        {label}
      </div>
      <div style={{ color: '#e2e8f0', fontSize: 12.5, wordBreak: 'break-word' }}>{value ?? '—'}</div>
    </div>
  )
}

function SectionTitle({ children }) {
  return (
    <h3 style={{ margin: '0 0 8px', fontSize: 13, color: '#e2e8f0' }}>
      {children}
    </h3>
  )
}

function resourceLabel(resource) {
  if (typeof resource === 'string' || typeof resource === 'number') return String(resource)
  try {
    return JSON.stringify(redactForDisplay(resource))
  } catch {
    return '[unavailable]'
  }
}

export default function ApprovalDetailDrawer({
  request,
  loading = false,
  error = null,
  submitting = false,
  decisionError = null,
  comment = '',
  notice = null,
  resuming = false,
  resumeError = null,
  resumeQueued = false,
  onCommentChange = () => {},
  onDecide = () => {},
  onResume = () => {},
  onClose = () => {},
}) {
  useEffect(() => {
    if (typeof window === 'undefined') return undefined
    const onKeyDown = (event) => {
      if (event.key === 'Escape') onClose?.()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const errorInfo = describeApprovalError(error, 'detail')
  const risk = request ? riskTierMeta(request.risk_tier) : null
  const status = request ? approvalStatusMeta(request.status) : null
  const expiry = request ? expiryMeta(request.expires_at) : null
  const pending = request?.status === 'pending'
  const statusKey = String(request?.status || '').toLowerCase()
  const canResume =
    Boolean(request?.run_id) && (statusKey === 'approved' || statusKey === 'rejected')
  const resumeBusy = resuming || resumeQueued
  const argumentsText = request ? stringifyRedacted(request.arguments) : ''
  const previewText =
    request?.preview && Object.keys(request.preview).length > 0
      ? stringifyRedacted(request.preview)
      : ''
  const decisions = Array.isArray(request?.decision?.decisions) ? request.decision.decisions : []

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal-window"
        role="dialog"
        aria-modal="true"
        aria-labelledby="approval-detail-title"
        style={{ width: 'min(760px, 96vw)', maxHeight: '92vh', overflowY: 'auto', padding: 22 }}
        onClick={(event) => event.stopPropagation()}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            gap: 12,
            borderBottom: '1px solid var(--border, #334155)',
            paddingBottom: 12,
            marginBottom: 16,
          }}
        >
          <div>
            <h2
              id="approval-detail-title"
              style={{
                margin: 0,
                fontSize: 18,
                color: '#f8fafc',
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                flexWrap: 'wrap',
              }}
            >
              <span>Approval request</span>
              {risk && (
                <span
                  style={{
                    fontSize: 10.5,
                    fontWeight: 700,
                    color: risk.tone,
                    background: 'rgba(255, 255, 255, 0.05)',
                    border: `1px solid ${risk.tone}55`,
                    borderRadius: 5,
                    padding: '2px 7px',
                  }}
                >
                  {risk.label}
                </span>
              )}
            </h2>
            {request && (
              <p className="hint" style={{ margin: '4px 0 0', fontSize: 12 }}>
                Request <code>{request.id}</code> · Run <code>{request.run_id}</code>
              </p>
            )}
          </div>
          <button
            type="button"
            className="ghost small"
            onClick={onClose}
            aria-label="Close approval details"
            title="Close (Esc)"
            style={{ fontSize: 18, lineHeight: 1 }}
          >
            ✕
          </button>
        </div>

        {notice && <div className="banner-inline ok" style={{ marginBottom: 12 }}>{notice}</div>}
        {loading && <p className="hint" aria-live="polite">Loading approval details…</p>}

        {!loading && errorInfo && (
          <ErrorState
            title={errorInfo.title}
            description={errorInfo.description}
            action={<button type="button" className="ghost" onClick={onClose}>Close</button>}
          />
        )}

        {!loading && !errorInfo && !request && (
          <p className="hint">This approval request is no longer available.</p>
        )}

        {!loading && !errorInfo && request && (
          <>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', marginBottom: 14 }}>
              <span
                className={`status-label status-${request.status}`}
                style={{
                  color: status.tone,
                  borderColor: `${status.tone}55`,
                  background: `${status.tone}14`,
                }}
              >
                {status.label}
              </span>
              <span className="hint" style={{ fontSize: 12 }}>
                Requested {formatTimestamp(request.created_at)}
              </span>
              <span className="hint" style={{ fontSize: 12 }}>
                Expires {formatTimestamp(request.expires_at)}
                {expiry?.text && !expiry.expired ? ` (${expiry.text})` : ''}
              </span>
            </div>

            <div
              style={{
                background: 'rgba(19, 23, 34, 0.72)',
                border: '1px solid rgba(255, 255, 255, 0.08)',
                borderRadius: 10,
                padding: 14,
                marginBottom: 16,
              }}
            >
              <div
                className="hint"
                style={{ fontSize: 10.5, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 4 }}
              >
                Summary
              </div>
              <div style={{ color: '#f1f5f9', fontSize: 13.5, lineHeight: 1.5 }}>
                {request.summary || request.reason || 'No summary was provided.'}
              </div>
              {request.summary && request.reason && (
                <div className="hint" style={{ marginTop: 6, fontSize: 12 }}>
                  Reason: {request.reason}
                </div>
              )}
            </div>

            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))',
                gap: 12,
                marginBottom: 18,
              }}
            >
              <Meta label="Tool / action" value={approvalActionLabel(request)} />
              <Meta label="Node" value={request.node_id || '—'} />
              <Meta label="Risk tier" value={risk.label} />
              <Meta
                label="Requested by"
                value={request.requested_by == null ? 'System' : `User #${request.requested_by}`}
              />
              <Meta label="Approvers" value={formatApprovers(request.approvers)} />
              <Meta
                label="Quorum"
                value={`${request.quorum || 1} approval${(request.quorum || 1) === 1 ? '' : 's'}`}
              />
              <Meta
                label="Separation of duties"
                value={request.separation_of_duties ? 'Required' : 'Not required'}
              />
              <Meta label="Run" value={<code>{request.run_id || '—'}</code>} />
            </div>

            <div style={{ marginBottom: 16 }}>
              <SectionTitle>Arguments (redacted)</SectionTitle>
              {argumentsText ? (
                <pre style={PRE_STYLE}>{argumentsText}</pre>
              ) : (
                <p className="hint" style={{ margin: 0, fontSize: 12 }}>
                  No arguments were recorded.
                </p>
              )}
              <p className="hint" style={{ margin: '6px 0 0', fontSize: 11 }}>
                The approval broker redacts secret argument values before they reach this view.
              </p>
            </div>

            {previewText && (
              <div style={{ marginBottom: 16 }}>
                <SectionTitle>Preview</SectionTitle>
                <pre style={PRE_STYLE}>{previewText}</pre>
              </div>
            )}

            {Array.isArray(request.affected_resources) && request.affected_resources.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <SectionTitle>Affected resources</SectionTitle>
                <ul style={{ margin: 0, paddingLeft: 18, color: '#cbd5e1', fontSize: 12.5 }}>
                  {request.affected_resources.map((resource, index) => (
                    <li key={index} style={{ marginBottom: 4 }}>
                      <code style={{ wordBreak: 'break-word' }}>{resourceLabel(resource)}</code>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {decisions.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <SectionTitle>Decision history</SectionTitle>
                <ul style={{ margin: 0, paddingLeft: 18, color: '#cbd5e1', fontSize: 12.5 }}>
                  {decisions.map((decision, index) => (
                    <li key={index} style={{ marginBottom: 4 }}>
                      User #{decision.user_id} {decision.approved ? 'approved' : 'rejected'}
                      {decision.at ? ` · ${formatTimestamp(decision.at)}` : ''}
                      {decision.comment ? ` — ${decision.comment}` : ''}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {pending ? (
              <div style={{ borderTop: '1px solid rgba(255, 255, 255, 0.08)', paddingTop: 14 }}>
                <label
                  htmlFor="approval-comment"
                  className="hint"
                  style={{ display: 'block', fontSize: 12, marginBottom: 6 }}
                >
                  Comment (optional, stored in the audit trail)
                </label>
                <textarea
                  id="approval-comment"
                  value={comment}
                  onChange={(event) => onCommentChange(event.target.value)}
                  rows={3}
                  maxLength={2000}
                  placeholder="Add context for this decision…"
                  style={TEXTAREA_STYLE}
                />
                {decisionError && (
                  <div className="banner-inline err" style={{ marginTop: 10 }}>
                    {decisionError.message || 'The decision could not be recorded.'}
                  </div>
                )}
                <div className="approvals-actions" style={{ justifyContent: 'flex-end' }}>
                  <button
                    type="button"
                    className="danger small"
                    disabled={submitting}
                    onClick={() => onDecide(false)}
                  >
                    {submitting ? 'Submitting…' : 'Reject'}
                  </button>
                  <button
                    type="button"
                    className="primary small"
                    disabled={submitting}
                    onClick={() => onDecide(true)}
                  >
                    {submitting ? 'Submitting…' : 'Approve'}
                  </button>
                </div>
              </div>
            ) : (
              <div style={{ borderTop: '1px solid rgba(255, 255, 255, 0.08)', paddingTop: 14 }}>
                <div className="banner-inline info">
                  This request is {status.label.toLowerCase()} and can no longer be decided.
                </div>
                {canResume && (
                  <div style={{ marginTop: 12 }}>
                    <p className="hint" style={{ margin: '0 0 10px', fontSize: 12 }}>
                      The decision is recorded. Resuming the paused run is a separate action and
                      is never started automatically.
                    </p>
                    {resumeError && (
                      <div className="banner-inline err" role="alert" style={{ marginBottom: 10 }}>
                        {describeResumeError(resumeError)}
                      </div>
                    )}
                    <div className="approvals-actions" style={{ justifyContent: 'flex-end' }}>
                      <button
                        type="button"
                        className="primary small"
                        disabled={resumeBusy}
                        aria-busy={resuming || undefined}
                        onClick={onResume}
                      >
                        {resuming ? 'Resuming…' : resumeQueued ? 'Resume queued' : 'Resume run'}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
