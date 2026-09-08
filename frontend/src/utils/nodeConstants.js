export const IDEMPOTENCY_LABEL = {
  idempotent: 'idempotent',
  conditionally_idempotent: 'conditionally idempotent',
  non_idempotent: 'not idempotent',
}

export const IDEMPOTENCY_HINT = {
  idempotent: 'Safe to retry — rerunning produces the same result.',
  conditionally_idempotent: 'Safe to retry for read-only runs (GET, SELECT, …).',
  non_idempotent: 'Retrying may duplicate side effects (emails sent, model calls billed, rows written).',
}

export const NODE_COLORS = [
  { value: '', label: 'Category default' },
  { value: '#4f8cff', label: 'Blue' },
  { value: '#34c759', label: 'Green' },
  { value: '#ffd60a', label: 'Amber' },
  { value: '#ff9f0a', label: 'Orange' },
  { value: '#bf5af2', label: 'Violet' },
  { value: '#64d2ff', label: 'Cyan' },
  { value: '#8e8e93', label: 'Grey' },
]
