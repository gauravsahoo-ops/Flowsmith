import { useEffect, useState } from 'react'

export default function OAuthCallbackPage() {
  const [status, setStatus] = useState('processing') // processing | success | error

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    // Support both new dedicated format (?provider=salesforce&ok=1) and legacy marker format (?oauth_connected=1&provider=... or ?salesforce_connected=1)
    const provider = params.get('provider') || 'salesforce'
    const okParam = params.get('ok')
    const legacyOk = params.get('oauth_connected') === '1' || params.get('salesforce_connected') === '1'
    const legacyFail = params.get('oauth_connect_failed') === '1' || params.get('salesforce_connect_failed') === '1'
    const ok = okParam === '1' || legacyOk
    const error = params.get('error') || (legacyFail ? params.get('error') || 'Authorization failed' : null)
    const isSuccess = ok && !legacyFail && !error

    // Determine opener origin for secure postMessage
    let targetOrigin = '*'
    try {
      if (window.opener && window.opener.location && window.opener.location.origin) {
        targetOrigin = window.opener.location.origin
      }
    } catch {
      // Cross-origin opener, keep *
    }

    const payload = isSuccess
      ? { source: 'oauth', type: 'salesforce-oauth-success', ok: true, provider }
      : { source: 'oauth', type: 'salesforce-oauth-error', ok: false, provider, error: error || 'Authorization failed' }

    if (window.opener) {
      // Also send legacy shape for backward compat
      const legacyMessage = isSuccess
        ? { source: provider === 'salesforce' ? 'salesforce-oauth' : 'oauth', ok: true, provider }
        : { source: provider === 'salesforce' ? 'salesforce-oauth' : 'oauth', ok: false, provider, error: error || 'Authorization failed' }
      try {
        window.opener.postMessage(payload, targetOrigin)
        window.opener.postMessage(legacyMessage, targetOrigin)
      } catch {}
    }

    // BroadcastChannel fallback: communicates across tabs/windows even if window.opener was severed by COOP
    try {
      if (typeof BroadcastChannel !== 'undefined') {
        const bc = new BroadcastChannel('flowsmith_oauth')
        bc.postMessage(payload)
        bc.close()
      }
    } catch {}

    // LocalStorage fallback: triggers storage event in parent window
    try {
      localStorage.setItem('flowsmith_oauth_result', JSON.stringify({ ...payload, _ts: Date.now() }))
    } catch {}

    if (isSuccess) {
      setStatus('success')
      // Auto-close after short delay
      const t = setTimeout(() => {
        try { window.close() } catch {}
        // If close blocked, keep success message
      }, 800)
      return () => clearTimeout(t)
    } else {
      setStatus('error')
    }
  }, [])

  if (status === 'processing') {
    return (
      <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: '#16181d', color: '#e6e9ef', fontFamily: 'system-ui, sans-serif' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 24, marginBottom: 12 }}>⏳</div>
          <div>Processing connection…</div>
        </div>
      </div>
    )
  }

  if (status === 'success') {
    return (
      <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: '#16181d', color: '#e6e9ef', fontFamily: 'system-ui, sans-serif' }}>
        <div style={{ textAlign: 'center', padding: 24 }}>
          <div style={{ fontSize: 32, marginBottom: 12, color: '#34c759' }}>✓</div>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>Connection successful</div>
          <div style={{ color: '#9aa3b2', fontSize: 13 }}>Closing this window…</div>
          <div style={{ color: '#9aa3b2', fontSize: 12, marginTop: 8 }}>You can close this window if it doesn't close automatically.</div>
        </div>
      </div>
    )
  }

  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: '#16181d', color: '#e6e9ef', fontFamily: 'system-ui, sans-serif' }}>
      <div style={{ textAlign: 'center', padding: 24 }}>
        <div style={{ fontSize: 32, marginBottom: 12, color: '#ff453a' }}>✕</div>
        <div style={{ fontWeight: 600, marginBottom: 6 }}>Connection failed</div>
        <div style={{ color: '#9aa3b2', fontSize: 13 }}>You can close this window and try again.</div>
      </div>
    </div>
  )
}
