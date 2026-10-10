import { useEffect, useState } from 'react'

function parseOAuthParams() {
  if (typeof window === 'undefined') {
    return { provider: 'oauth', isSuccess: false, error: null }
  }

  // Support query in search or hash
  let searchStr = window.location.search || ''
  if (!searchStr && window.location.hash) {
    const h = window.location.hash.replace(/^#\/?/, '')
    if (h.includes('?') || h.includes('=')) {
      searchStr = h.includes('?') ? h.slice(h.indexOf('?')) : '?' + h
    }
  }

  const params = new URLSearchParams(searchStr)

  // 1. Determine provider
  let provider = (params.get('provider') || '').trim()
  if (!provider) {
    // Check path /oauth/callback/:provider
    try {
      const pathParts = window.location.pathname.split('/').filter(Boolean)
      const callbackIdx = pathParts.indexOf('callback')
      if (callbackIdx !== -1 && pathParts[callbackIdx + 1]) {
        provider = pathParts[callbackIdx + 1]
      }
    } catch {}
  }
  if (!provider) {
    // Check for provider-specific marker in query params
    for (const [key] of params.entries()) {
      if (key.endsWith('_connected') || key.endsWith('_connect_failed')) {
        const candidate = key.replace(/_(connected|connect_failed)$/, '')
        if (candidate && candidate !== 'oauth') {
          provider = candidate
          break
        }
      }
    }
  }
  if (!provider) {
    provider = 'oauth'
  }

  // 2. Evaluate success vs failure
  const okParam = (params.get('ok') || '').trim().toLowerCase()
  const statusParam = (params.get('status') || '').trim().toLowerCase()
  const successParam = (params.get('success') || '').trim().toLowerCase()

  const isOkTruthy = ['1', 'true', 'yes', 'ok', 'success'].includes(okParam)
  const isStatusSuccess = ['success', 'ok', 'connected'].includes(statusParam)
  const isSuccessTruthy = ['1', 'true', 'yes'].includes(successParam)

  const legacyOk =
    params.get('oauth_connected') === '1' ||
    params.get(`${provider}_connected`) === '1' ||
    params.get('salesforce_connected') === '1'

  const legacyFail =
    params.get('oauth_connect_failed') === '1' ||
    params.get(`${provider}_connect_failed`) === '1' ||
    params.get('salesforce_connect_failed') === '1'

  const errorParam = params.get('error') || params.get('error_description')

  const isExplicitFail =
    ['0', 'false', 'no', 'error', 'failed', 'fail'].includes(okParam) ||
    Boolean(legacyFail) ||
    Boolean(errorParam)

  const isSuccess =
    !isExplicitFail && (isOkTruthy || isStatusSuccess || isSuccessTruthy || legacyOk)

  const error = isSuccess
    ? null
    : (errorParam || (legacyFail ? 'Authorization failed' : (isExplicitFail ? 'Authorization was declined or failed' : 'No authorization parameters found')))

  return { provider, isSuccess, error }
}

export default function OAuthCallbackPage() {
  // Parse query parameters once on initial mount and hold in state.
  // This guarantees that any subsequent effects or re-renders (such as React 18/19
  // StrictMode double-mounting in development) NEVER re-parse an empty URL if
  // history.replaceState or popstate cleared the query string.
  const [parsed] = useState(parseOAuthParams)
  const [status, setStatus] = useState(() => (parsed.isSuccess ? 'success' : 'error'))
  const [errorDetail, setErrorDetail] = useState(() => parsed.error)

  useEffect(() => {
    const { provider, isSuccess, error } = parsed

    if (error) {
      setErrorDetail(error)
    }

    // Post to opener using '*' so cross-origin popups (e.g. backend port 8000 to Vite port 5173,
    // or localhost vs 127.0.0.1) securely communicate without throwing DOM SecurityError.
    const targetOrigin = '*'

    const payload = {
      source: 'oauth',
      type: `${provider}-oauth-${isSuccess ? 'success' : 'error'}`,
      status: isSuccess ? 'success' : 'error',
      ok: isSuccess,
      provider,
      error: isSuccess ? null : (error || 'Authorization failed'),
    }

    // Legacy shape for backward compatibility with older listeners
    const legacyPayload = {
      source: provider === 'salesforce' ? 'salesforce-oauth' : 'oauth',
      type: isSuccess ? 'salesforce-oauth-success' : 'salesforce-oauth-error',
      status: isSuccess ? 'success' : 'error',
      ok: isSuccess,
      provider,
      error: isSuccess ? null : (error || 'Authorization failed'),
    }

    if (window.opener) {
      try {
        window.opener.postMessage(payload, targetOrigin)
        window.opener.postMessage(legacyPayload, targetOrigin)
        if (isSuccess) {
          window.opener.postMessage('oauth_connected', targetOrigin)
          window.opener.postMessage(`${provider}_connected`, targetOrigin)
          if (provider === 'salesforce') {
            window.opener.postMessage('salesforce_connected', targetOrigin)
          }
        } else {
          window.opener.postMessage('oauth_connect_failed', targetOrigin)
          window.opener.postMessage(`${provider}_connect_failed`, targetOrigin)
          if (provider === 'salesforce') {
            window.opener.postMessage('salesforce_connect_failed', targetOrigin)
          }
        }
      } catch (err) {
        console.error('[flowsmith] pages/OAuthCallbackPage.jsx opener error', err)
      }
    }

    // BroadcastChannel fallback: communicates across tabs/windows even if window.opener was severed by COOP
    try {
      if (typeof BroadcastChannel !== 'undefined') {
        const bc = new BroadcastChannel('flowsmith_oauth')
        bc.postMessage(payload)
        bc.postMessage({ provider, ok: isSuccess, source: 'oauth', status: isSuccess ? 'success' : 'error' })
        bc.close()
      }
    } catch (err) {
      console.error('[flowsmith] pages/OAuthCallbackPage.jsx BroadcastChannel error', err)
    }

    // LocalStorage fallback: triggers storage event in parent window
    try {
      localStorage.setItem('flowsmith_oauth_result', JSON.stringify({ ...payload, _ts: Date.now() }))
      if (isSuccess) {
        localStorage.setItem('oauth_success', JSON.stringify({ provider, ok: true, _ts: Date.now() }))
      } else {
        localStorage.setItem('oauth_error', JSON.stringify({ provider, ok: false, error: error || 'Authorization failed', _ts: Date.now() }))
      }
    } catch (err) {
      console.error('[flowsmith] pages/OAuthCallbackPage.jsx localStorage error', err)
    }

    if (isSuccess) {
      setStatus('success')
      // Auto-close after short delay
      const t = setTimeout(() => {
        try { window.close() } catch {}
      }, 1000)

      // Clean up URL parameters after messages have been safely dispatched
      const cleanTimer = setTimeout(() => {
        try {
          window.history.replaceState({}, '', window.location.pathname)
        } catch {}
      }, 1500)

      return () => {
        clearTimeout(t)
        clearTimeout(cleanTimer)
      }
    } else {
      setStatus('error')
    }
  }, [parsed])

  const friendlyProvider = (() => {
    const p = parsed.provider
    if (p === 'dynamics_crm') return 'Microsoft Dynamics 365'
    if (p === 'google_calendar') return 'Google Calendar'
    if (p === 'google_sheets') return 'Google Sheets'
    if (p === 'salesforce') return 'Salesforce'
    if (p === 'hubspot') return 'HubSpot'
    if (p && p !== 'oauth') return p.replace(/_/g, ' ')
    return 'Account'
  })()

  if (status === 'processing') {
    return (
      <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: '#0e0f14', color: '#e6e9ef', fontFamily: 'system-ui, sans-serif' }}>
        <div style={{ textAlign: 'center', padding: 24 }}>
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 16 }}>
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--accent, #6366f1)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ animation: 'spin 1s linear infinite', display: 'inline-block' }}>
              <circle cx="12" cy="12" r="10" strokeOpacity="0.25" />
              <path d="M12 2a10 10 0 0 1 10 10" />
            </svg>
          </div>
          <div style={{ fontWeight: 600, fontSize: 16, marginBottom: 6, color: '#f8fafc' }}>Processing connection…</div>
          <div style={{ color: '#94a3b8', fontSize: 13 }}>Finalizing authorization for {friendlyProvider}…</div>
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
          <div style={{ fontWeight: 600, fontSize: 16, marginBottom: 6, color: '#f8fafc' }}>
            Connection successful — {friendlyProvider} connected
          </div>
          <div style={{ color: '#94a3b8', fontSize: 13 }}>Closing this window…</div>
          <div style={{ color: '#64748b', fontSize: 12, marginTop: 8 }}>You can close this window if it doesn't close automatically.</div>
        </div>
      </div>
    )
  }

  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: '#0e0f14', color: '#e6e9ef', fontFamily: 'system-ui, sans-serif' }}>
      <div style={{ textAlign: 'center', padding: 24, maxWidth: 420 }}>
        <div style={{ width: 48, height: 48, borderRadius: '50%', background: 'rgba(239, 68, 68, 0.12)', border: '1px solid rgba(239, 68, 68, 0.3)', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', marginBottom: 16 }}>
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#f87171" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </div>
        <div style={{ fontWeight: 600, fontSize: 16, marginBottom: 6, color: '#f8fafc' }}>Connection failed</div>
        <div style={{ color: '#94a3b8', fontSize: 13, marginBottom: 12 }}>
          {errorDetail || 'Authorization was cancelled or could not be completed.'}
        </div>
        <div style={{ color: '#64748b', fontSize: 12 }}>You can close this window and try connecting again from Flowsmith.</div>
      </div>
    </div>
  )
}
