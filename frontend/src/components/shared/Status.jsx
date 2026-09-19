import React from 'react'

const STATUS_MAP = {
  idle: { cls: 'status-idle', label: 'Idle' },
  queued: { cls: 'status-queued', label: 'Queued' },
  waiting: { cls: 'status-waiting', label: 'Waiting' },
  running: { cls: 'status-running', label: 'Running…' },
  success: { cls: 'status-success', label: 'Success' },
  failed: { cls: 'status-failed', label: 'Failed' },
  cancelled: { cls: 'status-cancelled', label: 'Cancelled' },
  error: { cls: 'status-error', label: 'Error' },
  skipped: { cls: 'status-skipped', label: 'Skipped' },
  retry: { cls: 'status-retry', label: 'Retrying' },
  waiting_approval: { cls: 'status-waiting_approval', label: 'Approval' },
}

export default function Status({ status, label, dot = true, live = false, className = '' }) {
  const s = STATUS_MAP[status] || STATUS_MAP.idle
  const text = label || s.label
  return (
    <span className={['status-badge', s.cls, className].filter(Boolean).join(' ')} role={live ? 'status' : undefined} aria-live={live ? 'polite' : undefined}>
      {dot && <span className="status-dot" aria-hidden="true" />}
      <span className="status-text">{text}</span>
    </span>
  )
}
