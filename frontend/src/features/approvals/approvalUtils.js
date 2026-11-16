// Presentation helpers for the human-approval inbox. The approval broker
// redacts secret argument values before they are stored, and this module adds
// a defensive display-time redaction pass for secret-looking keys.

const RISK_META = {
  0: { label: 'Tier 0 · Read-only', tone: '#34d399' },
  1: { label: 'Tier 1 · Low-risk write', tone: '#38bdf8' },
  2: { label: 'Tier 2 · External side effect', tone: '#f59e0b' },
  3: { label: 'Tier 3 · Destructive / high-value', tone: '#f97316' },
  4: { label: 'Tier 4 · Security-sensitive', tone: '#f43f5e' },
}

const STATUS_META = {
  pending: { label: 'Pending', tone: '#f59e0b' },
  approved: { label: 'Approved', tone: '#34d399' },
  rejected: { label: 'Rejected', tone: '#f87171' },
  expired: { label: 'Expired', tone: '#fb923c' },
  cancelled: { label: 'Cancelled', tone: '#94a3b8' },
}

// Keys that commonly carry credentials. Values are replaced, never rendered.
const SECRET_KEY_PATTERN =
  /(secret|password|passwd|token|api[_-]?key|authorization|auth|credential|private[_-]?key|access[_-]?key|client[_-]?secret|cookie|session|signature)/i

export function riskTierMeta(tier) {
  const numericTier = Number(tier)
  const safeTier = Number.isFinite(numericTier) ? numericTier : 0
  return RISK_META[safeTier] || { label: `Tier ${safeTier}`, tone: '#94a3b8' }
}

export function approvalStatusMeta(status) {
  const key = String(status || '').toLowerCase()
  return STATUS_META[key] || { label: status || 'Unknown', tone: '#94a3b8' }
}

export function formatTimestamp(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function expiryMeta(value, now = Date.now()) {
  if (!value) return { text: 'No expiry', expired: false, urgent: false }
  const timestamp = new Date(value).getTime()
  if (!Number.isFinite(timestamp)) {
    return { text: 'Unknown expiry', expired: false, urgent: false }
  }
  const diffMs = timestamp - now
  if (diffMs <= 0) return { text: 'Expired', expired: true, urgent: true }

  const minutes = Math.ceil(diffMs / 60_000)
  let text
  if (minutes < 60) text = `in ${minutes} min`
  else if (minutes < 1_440) text = `in ${Math.round(minutes / 60)}h`
  else text = `in ${Math.round(minutes / 1_440)}d`

  return { text, expired: false, urgent: minutes <= 60 }
}

export function approvalActionLabel(request) {
  return request?.tool_name || request?.reason || 'Workflow action'
}

export function formatApprovers(approvers) {
  if (!Array.isArray(approvers) || approvers.length === 0) return 'Any authorized reviewer'
  return approvers
    .map((approver) => (typeof approver === 'number' ? `User #${approver}` : String(approver)))
    .join(', ')
}

export function redactForDisplay(value) {
  if (Array.isArray(value)) return value.map(redactForDisplay)
  if (value && typeof value === 'object') {
    const result = {}
    for (const [key, item] of Object.entries(value)) {
      result[key] = SECRET_KEY_PATTERN.test(key) ? '***REDACTED***' : redactForDisplay(item)
    }
    return result
  }
  return value
}

export function stringifyRedacted(value) {
  if (value == null) return ''
  try {
    return JSON.stringify(redactForDisplay(value), null, 2)
  } catch {
    return ''
  }
}

export function generateDecisionNonce(cryptoApi = globalThis.crypto) {
  try {
    if (cryptoApi && typeof cryptoApi.randomUUID === 'function') {
      return cryptoApi.randomUUID()
    }
  } catch {
    // Fall through to the deterministic-enough fallback below.
  }
  return `approval-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`
}

export function describeResumeError(error) {
  if (!error) return null
  if (error.status === 403) {
    return 'You do not have permission to resume this run. Ask a workspace owner or approver for access.'
  }
  if (error.status === 404) {
    return 'This run was not found, or you do not have access to the workflow it belongs to.'
  }
  if (error.status === 409) {
    return (
      error.message ||
      'This run cannot be resumed because it is no longer waiting for approval, the quorum is not met, or it was already resumed.'
    )
  }
  return error.message || 'The run could not be resumed. Try again.'
}

export function describeApprovalError(error, context = 'list') {
  if (!error) return null

  if (error.status === 401) {
    return {
      title: 'Session expired',
      description: 'Sign in again to review human-approval requests.',
      unauthorized: true,
    }
  }
  if (error.status === 403) {
    return {
      title: 'Not authorized',
      description:
        'You do not have permission to review this approval request. Ask a workspace owner or approver for access.',
      unauthorized: true,
    }
  }
  if (error.status === 404) {
    return {
      title: context === 'detail' ? 'Approval not available' : 'Approvals unavailable',
      description:
        'This approval request was not found, or you do not have access to the workflow it belongs to.',
      unauthorized: true,
    }
  }
  if (error.status === 409) {
    return {
      title: 'Decision conflict',
      description: error.message || 'This request was already decided or has expired.',
      unauthorized: false,
    }
  }

  return {
    title: context === 'detail' ? 'Could not load approval details' : 'Could not load approvals',
    description: error.message || 'An unexpected error occurred while talking to the approval broker.',
    unauthorized: false,
  }
}
