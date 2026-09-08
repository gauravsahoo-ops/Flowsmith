import { useState } from 'react'

export function CollapsibleSection({ title, defaultOpen = true, badge, children }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className={`cfg-section ${open ? 'open' : ''}`}>
      <button type="button" className="cfg-section-head" onClick={() => setOpen((v) => !v)}>
        <span className="cfg-caret">{open ? '▾' : '▸'}</span>
        {title}
        {badge != null && badge !== '' && <span className="cfg-badge">{badge}</span>}
      </button>
      {open && <div className="cfg-section-body">{children}</div>}
    </section>
  )
}

export function OpSafetyHint({ operation, operations }) {
  const opMeta = operations?.[operation]
  if (!opMeta) return null
  if (opMeta.idempotency === 'non_idempotent' || opMeta.retryable === false) {
    return (
      <p className="hint retry-risky">
        Operation &quot;{operation}&quot; is never auto-retried — a re-run could duplicate records.
      </p>
    )
  }
  return (
    <p className="hint">
      Operation &quot;{operation}&quot; is {opMeta.idempotency === 'idempotent' ? 'idempotent' : 'conditionally idempotent'} and safe to auto-retry.
    </p>
  )
}

export default CollapsibleSection
