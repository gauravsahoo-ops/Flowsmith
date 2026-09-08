import React from 'react'

export default function ErrorState({ icon = '⚠️', title, description, details, action, secondaryAction }) {
  return (
    <div className="error-state" role="alert">
      <div className="es-icon" aria-hidden="true">{icon}</div>
      <div className="es-title">{title}</div>
      {description && <div className="es-desc">{description}</div>}
      {details && (
        <details className="es-details">
          <summary>Technical details</summary>
          <pre>{details}</pre>
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
