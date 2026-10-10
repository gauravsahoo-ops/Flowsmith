/**
 * Trusted-origin check for OAuth popup postMessage traffic.
 *
 * Rejects messages from unexpected origins (and sandboxed frames with the
 * opaque origin "null").
 * Trusted:
 * 1. This app's own origin (window.location.origin).
 * 2. The configured API origin (VITE_API_BASE_URL).
 * 3. Loopback hosts (localhost, 127.0.0.1, ::1) across common dev/API ports
 *    (5173, 5174, 8000, 3000, 4173) so popup callbacks landing on backend port
 *    8000 or alternative loopback interfaces can communicate safely with the opener.
 */

export function isTrustedOAuthOrigin(origin) {
  if (!origin || origin === 'null') return false
  if (typeof window === 'undefined') return false

  // 1. Same origin as current window
  if (origin === window.location.origin) return true

  // 2. Configured API origin (VITE_API_BASE_URL)
  try {
    const apiBase = (import.meta.env?.VITE_API_BASE_URL || '').replace(/\/+$/, '')
    if (apiBase && origin === new URL(apiBase).origin) return true
  } catch {
    // malformed VITE_API_BASE_URL — fall through
  }

  // 3. Loopback cross-talk (e.g. popup on localhost:8000 to opener on 127.0.0.1:5173 or vice versa)
  try {
    const currentUrl = new URL(window.location.origin)
    const originUrl = new URL(origin)

    const isLoopback = (host) =>
      host === 'localhost' ||
      host === '127.0.0.1' ||
      host === '::1' ||
      host.endsWith('.localhost')

    if (isLoopback(currentUrl.hostname) && isLoopback(originUrl.hostname)) {
      const allowedPorts = new Set(['5173', '5174', '8000', '3000', '4173', currentUrl.port, originUrl.port])
      if (allowedPorts.has(originUrl.port) || originUrl.port === currentUrl.port) {
        return true
      }
    }

    // Matching hostname on standard UI / backend ports
    if (originUrl.hostname === currentUrl.hostname) {
      if (['8000', '5173', '5174', '4173'].includes(originUrl.port)) {
        return true
      }
    }
  } catch {
    // malformed URL
  }

  // 4. Default dev backends
  if (import.meta.env?.DEV) {
    if (origin === 'http://127.0.0.1:8000' || origin === 'http://localhost:8000') return true
  }

  return false
}
