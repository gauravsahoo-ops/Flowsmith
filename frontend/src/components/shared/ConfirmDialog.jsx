import { useEffect, useRef } from 'react'

export default function ConfirmDialog({ open, title = "Are you sure?", description, confirmLabel = "Confirm", cancelLabel = "Cancel", variant = "danger", onConfirm, onCancel, busy = false }) {
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') onCancel?.() }
    window.addEventListener('keydown', onKey)
    ref.current?.focus()
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onCancel])
  if (!open) return null
  return (
    <div className="overlay" onClick={onCancel}>
      <div className="confirm-dialog" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label={title} ref={ref} tabIndex={-1}>
        <h3>{title}</h3>
        {description && <p className="hint">{description}</p>}
        <div className="confirm-actions">
          <button className="ghost" onClick={onCancel} disabled={busy}>{cancelLabel}</button>
          <button className={variant === 'danger' ? 'danger' : 'primary'} onClick={onConfirm} disabled={busy}>
            {busy ? '…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
