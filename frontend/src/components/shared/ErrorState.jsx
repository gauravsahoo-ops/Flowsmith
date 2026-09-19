import React from 'react'

function toSafeText(val) {
  if (val == null) return null
  if (typeof val === 'string' || typeof val === 'number' || typeof val === 'boolean') return val
  if (React.isValidElement(val)) return val
  if (typeof val === 'object') {
    return val.message || val.error || (val.code ? `${val.code}: ${JSON.stringify(val.details || val)}` : JSON.stringify(val))
  }
  return String(val)
}

function toSafeDetails(details, description) {
  const raw = details !== undefined
    ? details
    : (typeof description === 'object' && description !== null && !React.isValidElement(description))
      ? (description.details || (description.code && description.message ? { code: description.code, node_id: description.node_id, retryable: description.retryable, details: description.details } : null))
      : null

  if (raw == null) return null
  if (typeof raw === 'string') return raw
  return JSON.stringify(raw, null, 2)
}

export default function ErrorState({ icon = '⚠️', title, description, details, action, secondaryAction }) {
  const safeTitle = toSafeText(title)
  const safeDesc = toSafeText(description)
  const safeDetails = toSafeDetails(details, description)

  return (
    <div className="error-state" role="alert">
      <div className="es-icon" aria-hidden="true">{icon}</div>
      <div className="es-title">{safeTitle}</div>
      {safeDesc && <div className="es-desc">{safeDesc}</div>}
      {safeDetails && (
        <details className="es-details">
          <summary>Technical details</summary>
          <pre>{safeDetails}</pre>
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
