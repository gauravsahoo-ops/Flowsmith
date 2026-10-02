import React, { isValidElement } from 'react'

function toSafeText(val) {
  if (val == null) return null
  if (typeof val === 'string' || typeof val === 'number' || typeof val === 'boolean') return val
  if (isValidElement(val)) return val
  if (typeof val === 'object') {
    return val.message || val.error || (val.code ? `${val.code}: ${JSON.stringify(val.details || val)}` : JSON.stringify(val))
  }
  return String(val)
}

function toSafeDetails(details, description) {
  const raw = details !== undefined
    ? details
    : (typeof description === 'object' && description !== null && !isValidElement(description))
      ? (description.details || (description.code && description.message ? { code: description.code, node_id: description.node_id, retryable: description.retryable, details: description.details } : null))
      : null

  if (raw != null) {
    if (typeof raw === 'string') return raw
    return JSON.stringify(raw, null, 2)
  }
  if (typeof description === 'string' && description.trim()) {
    return description
  }
  return null
}

function getErrorIcon(icon) {
  if (isValidElement(icon)) return icon
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#f87171" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  )
}

export default function ErrorState({ icon = 'alert', title, description, details, action, secondaryAction }) {
  const safeTitle = toSafeText(title)
  const safeDesc = toSafeText(description)
  const safeDetails = toSafeDetails(details, description)
  const [copied, setCopied] = React.useState(false)

  const handleCopy = (e) => {
    e.preventDefault()
    e.stopPropagation()
    if (!safeDetails) return
    navigator.clipboard?.writeText(safeDetails)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="error-state" role="alert">
      <div className="es-icon" aria-hidden="true">{getErrorIcon(icon)}</div>
      <div className="es-title">{safeTitle}</div>
      {safeDesc && <div className="es-desc">{safeDesc}</div>}
      {safeDetails && (
        <details className="es-details" open={true}>
          <summary style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer' }}>
            <span>Technical details</span>
            <button
              type="button"
              className="ghost small"
              style={{ fontSize: 11, padding: '2px 8px', color: '#94a3b8', background: 'rgba(255,255,255,0.06)', borderRadius: 4, border: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}
              onClick={handleCopy}
              title="Copy technical details"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect width="14" height="14" x="8" y="8" rx="2" ry="2" />
                <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />
              </svg>
              <span>{copied ? 'Copied' : 'Copy'}</span>
            </button>
          </summary>
          <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 220, overflowY: 'auto' }}>{safeDetails}</pre>
        </details>
      )}
      {(action || secondaryAction) && (
        <div className="es-actions">
          {action}
          {secondaryAction}
        </div>
      )}
    </div>
  )
}
