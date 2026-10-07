/**
 * Trusted-origin check for OAuth popup postMessage traffic.
 *
 * Rejects messages from unexpected origins (and sandboxed frames with the
 * opaque origin "null"). Trusted: this app's own origin, the configured
 * API origin (VITE_API_BASE_URL), and — in dev only — the local backend
 * addresses the Vite proxy targets (popup callbacks can land there).
 */

export function isTrustedOAuthOrigin(origin) {
  if (!origin || origin === 'null') return false
  if (origin === window.location.origin) return true
  try {
    const apiBase = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')
    if (apiBase && origin === new URL(apiBase).origin) return true
  } catch {
    // malformed VITE_API_BASE_URL — fall through
  }
  if (import.meta.env.DEV) {
    if (origin === 'http://127.0.0.1:8000' || origin === 'http://localhost:8000') return true
  }
  return false
}
