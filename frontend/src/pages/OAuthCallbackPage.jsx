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
      } catch (err) { console.error('[flowsmith] pages/OAuthCallbackPage.jsx', err) }
    }

    // BroadcastChannel fallback: communicates across tabs/windows even if window.opener was severed by COOP
    try {
      if (typeof BroadcastChannel !== 'undefined') {
        const bc = new BroadcastChannel('flowsmith_oauth')
        bc.postMessage(payload)
        bc.close()
      }
    } catch (err) { console.error('[flowsmith] pages/OAuthCallbackPage.jsx', err) }

    // LocalStorage fallback: triggers storage event in parent window
    try {
      localStorage.setItem('flowsmith_oauth_result', JSON.stringify({ ...payload, _ts: Date.now() }))
    } catch (err) { console.error('[flowsmith] pages/OAuthCallbackPage.jsx', err) }

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
          <div style={{ display: "flex", justifyContent: "center", marginBottom: 16 }}><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ animation: "spin 1s linear infinite", display: "inline-block" }}><circle cx="12" cy="12" r="10" strokeOpacity="0.25"/><path d="M12 2a10 10 0 0 1 10 10"/></svg></div>
          <div>Processing connection…</div>
        </div>
      </div>
    )
  }

  if (status === 'success') {
    return (
      <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: '#0e0f14', color: '#e6e9ef', fontFamily: 'system-ui, sans-serif' }}>
        <div style={{ textAlign: 'center', padding: 24 }}>
          <div style={{ width: 48, height: 48, borderRadius: '50%', background: 'rgba(16, 185, 129, 0.12)', border: '1px solid rgba(16, 185, 129, 0.3)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', marginBottom: 16 }}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#34d399" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="20 6 9 17 4 12" />
            </svg>
          </div>
          <div style={{ fontWeight: 600, fontSize: 16, marginBottom: 6, color: '#f8fafc' }}>Connection successful</div>
          <div style={{ color: '#94a3b8', fontSize: 13 }}>Closing this window…</div>
          <div style={{ color: '#64748b', fontSize: 12, marginTop: 8 }}>You can close this window if it doesn't close automatically.</div>
        </div>
      </div>
    )
  }

  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: '#0e0f14', color: '#e6e9ef', fontFamily: 'system-ui, sans-serif' }}>
      <div style={{ textAlign: 'center', padding: 24 }}>
        <div style={{ width: 48, height: 48, borderRadius: '50%', background: 'rgba(239, 68, 68, 0.12)', border: '1px solid rgba(239, 68, 68, 0.3)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', marginBottom: 16 }}>
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#f87171" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </div>
        <div style={{ fontWeight: 600, fontSize: 16, marginBottom: 6, color: '#f8fafc' }}>Connection failed</div>
        <div style={{ color: '#94a3b8', fontSize: 13 }}>You can close this window and try again.</div>
      </div>
    </div>
  )
}
