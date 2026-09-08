import React from 'react'

const VARIANT = {
  ok: 'badge-ok',
  err: 'badge-err',
  warn: 'badge-warn',
  branch: 'badge-branch',
  conn: 'badge-conn',
  time: 'badge-time',
}

export default function Badge({ variant = 'ok', className = '', children }) {
  const cls = ['badge', VARIANT[variant] || 'badge-ok', className].filter(Boolean).join(' ')
  return <span className={cls}>{children}</span>
}
