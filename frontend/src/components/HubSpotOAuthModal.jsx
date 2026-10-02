import React, { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { NodeIcon } from './NodeIcons'
import './HubSpotOAuthModal.css'

export default function HubSpotOAuthModal({
  isOpen,
  onClose,
  initialData = null,
  onConnected,
  onSave,
}) {
  const [tab, setTab] = useState('connection') // 'connection' | 'private_app' | 'guide'
  const [name, setName] = useState(initialData?.name || 'HubSpot account')
  const [clientId, setClientId] = useState(initialData?.data?.client_id || '')
  const [clientSecret, setClientSecret] = useState(initialData?.data?.client_secret || '')
  const [privateToken, setPrivateToken] = useState(initialData?.data?.private_token || '')
  const [showSecret, setShowSecret] = useState(false)
  const [showPrivateToken, setShowPrivateToken] = useState(false)
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [connectedUser, setConnectedUser] = useState(initialData?.data?.user || null)
  const [connectedHubId, setConnectedHubId] = useState(initialData?.data?.hub_id || null)
  const [canonicalRedirectUrl, setCanonicalRedirectUrl] = useState('')
  const [serverConfigured, setServerConfigured] = useState(false)

  // Derive OAuth Callback URL matching current backend host
  const fallbackRedirectUrl = typeof window !== 'undefined'
    ? `${window.location.protocol}//${window.location.hostname}${window.location.port === '5173' ? ':8000' : (window.location.port ? `:${window.location.port}` : '')}/api/auth/hubspot/callback`
    : 'http://localhost:8000/api/auth/hubspot/callback'
  const redirectUrl = canonicalRedirectUrl || fallbackRedirectUrl

  useEffect(() => {
    if (!isOpen) return
    import('../api').then(({ api }) => {
      api.getOAuthConfig('hubspot')
        .then((res) => {
          const cfg = res?.data || res
          if (cfg) {
            if (cfg.redirect_uri) {
              setCanonicalRedirectUrl(cfg.redirect_uri)
            }
            if (cfg.configured) {
              setServerConfigured(true)
              if (!initialData && cfg.client_id) {
                setClientId((prev) => prev || cfg.client_id)
              }
            }
          }
        })
        .catch(() => {})
    })
  }, [isOpen, initialData])

  useEffect(() => {
    if (initialData) {
      setName(initialData.name || 'HubSpot account')
      setClientId(initialData.data?.client_id || '')
      setClientSecret(initialData.data?.client_secret || '')
      setPrivateToken(initialData.data?.private_token || '')
      setConnectedUser(initialData.data?.user || null)
      setConnectedHubId(initialData.data?.hub_id || null)
    } else {
      setName('HubSpot account')
      setClientId('')
      setClientSecret('')
      setPrivateToken('')
      setConnectedUser(null)
      setConnectedHubId(null)
    }
  }, [initialData])

  useEffect(() => {
    if (!isOpen) return
    const onKey = (e) => {
      if (e.key === 'Escape') onClose?.()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [isOpen, onClose])

  if (!isOpen) return null

  const handleCopyRedirect = () => {
    if (navigator?.clipboard) {
      navigator.clipboard.writeText(redirectUrl)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const handleConnect = async () => {
    setError(null)
    setNotice(null)
    setBusy(true)

    let popup = null
    try {
      popup = window.open('about:blank', 'oauth-hubspot', 'width=560,height=680')
      if (popup && popup.document) {
        popup.document.write(`
          <!DOCTYPE html>
          <html>
            <head>
              <title>Connecting to HubSpot…</title>
              <style>
                body { font-family: system-ui, -apple-system, sans-serif; background: #0b0e17; color: #f8fafc; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; margin: 0; }
                .spinner { width: 36px; height: 36px; border: 3px solid rgba(255,255,255,0.15); border-top-color: #ff7a59; border-radius: 50%; animation: spin 1s linear infinite; margin-bottom: 16px; }
                @keyframes spin { to { transform: rotate(360deg); } }
                h3 { margin: 0 0 8px; font-size: 16px; }
                p { font-size: 13px; color: #94a3b8; margin: 0; }
              </style>
            </head>
            <body>
              <div class="spinner"></div>
              <h3>Opening HubSpot Authorization…</h3>
              <p>Please log in and grant portal access in the opened window.</p>
            </body>
          </html>
        `)
      }
    } catch {}

    try {
      const { api } = await import('../api')
      const extra = {}
      if (clientId.trim()) extra.client_id = clientId.trim()
      if (clientSecret.trim()) extra.client_secret = clientSecret.trim()
      if (name.trim()) extra.name = name.trim()

      const res = await api.connectOAuth('hubspot', undefined, 'consent', extra)
      const authorizeUrl = res?.data?.authorize_url || res?.authorize_url

      if (!authorizeUrl) {
        throw new Error('Server did not return an authorization URL.')
      }

      if (!popup || popup.closed || typeof popup.closed === 'undefined') {
        setBusy(false)
        setError('Popup was blocked by your browser. Please allow popups or use the direct authorize link.')
        return
      }

      popup.location.href = authorizeUrl

      let resolved = false
      const messageHandler = (e) => {
        if (e.data === 'hubspot_connected' || e.data === 'oauth_connected') {
          resolved = true
          cleanup()
          setNotice('HubSpot account authorized and connected successfully.')
          setBusy(false)
          try { popup.close() } catch {}
          onConnected?.()
          setTimeout(() => onClose(), 1200)
        } else if (e.data === 'hubspot_connect_failed' || e.data === 'oauth_connect_failed') {
          resolved = true
          cleanup()
          setError('HubSpot authorization failed or was declined.')
          setBusy(false)
          try { popup.close() } catch {}
        }
      }

      const storageHandler = (e) => {
        if (e.key === 'oauth_success' && e.newValue) {
          try {
            const parsed = JSON.parse(e.newValue)
            if (parsed.provider === 'hubspot') {
              resolved = true
              cleanup()
              setNotice('HubSpot account authorized successfully.')
              setBusy(false)
              try { popup.close() } catch {}
              onConnected?.()
              setTimeout(() => onClose(), 1200)
            }
          } catch {}
        }
      }

      const pollClosed = setInterval(() => {
        if (popup && popup.closed) {
          if (!resolved) {
            setBusy(false)
            setTimeout(() => onConnected?.(), 1000)
          }
          cleanup()
        }
      }, 500)

      const cleanup = () => {
        window.removeEventListener('message', messageHandler)
        window.removeEventListener('storage', storageHandler)
        clearInterval(pollClosed)
      }

      window.addEventListener('message', messageHandler)
      window.addEventListener('storage', storageHandler)
    } catch (err) {
      setBusy(false)
      if (popup && !popup.closed) {
        try { popup.close() } catch {}
      }
      setError(err?.message || 'Failed to initiate HubSpot connection.')
    }
  }

  const handleSaveModal = async () => {
    if (!name.trim()) {
      setError('Please provide a credential name.')
      return
    }

    if (tab === 'private_app') {
      if (!privateToken.trim()) {
        setError('Please enter a HubSpot Private App token.')
        return
      }
      if (onSave) {
        onSave({
          name: name.trim(),
          type: 'hubspot',
          data: {
            private_token: privateToken.trim(),
          },
        })
      }
      onClose()
      return
    }

    if (onSave) {
      onSave({
        name: name.trim(),
        type: 'hubspot',
        data: {
          client_id: clientId.trim(),
          client_secret: clientSecret.trim(),
        },
      })
    }
    onClose()
  }

  const modalContent = (
    <div className="hs-modal-overlay" onClick={onClose}>
      <div
        className="hs-modal-window"
        role="dialog"
        aria-modal="true"
        aria-labelledby="hs-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="hs-modal-header">
          <div className="hs-header-title-wrap">
            <div className="hs-brand-avatar">
              <NodeIcon type="hubspot" size={24} />
            </div>
            <div className="hs-header-meta">
              <h3 id="hs-modal-title">
                {initialData?.id ? 'Edit HubSpot Credential' : 'HubSpot App & Authentication'}
                <span className="hs-badge-flow">OAuth 2.0</span>
              </h3>
              <p>Configure custom HubSpot Developer App or connect with CRM</p>
            </div>
          </div>
          <button
            type="button"
            className="hs-close-btn"
            onClick={onClose}
            title="Close (Esc)"
            aria-label="Close"
            style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>

        {/* Tab Navigation */}
        <div className="hs-modal-tabs">
          <button
            type="button"
            className={`hs-tab-btn ${tab === 'connection' ? 'active' : ''}`}
            onClick={() => setTab('connection')}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m21 2-2 2m-1.5 1.5L10 13m-2-2L3.5 15.5a3.536 3.536 0 0 0 5 5L13 16m-2-2 2.5 2.5m1-1 2 2m-7-7 2 2"/><circle cx="7.5" cy="16.5" r=".5" fill="currentColor"/></svg>
            <span>OAuth App Credentials</span>
          </button>
          <button
            type="button"
            className={`hs-tab-btn ${tab === 'private_app' ? 'active' : ''}`}
            onClick={() => setTab('private_app')}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
            <span>Private App Token</span>
          </button>
          <button
            type="button"
            className={`hs-tab-btn ${tab === 'guide' ? 'active' : ''}`}
            onClick={() => setTab('guide')}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z"/><path d="M6 6h10"/><path d="M6 10h10"/></svg>
            <span>Setup Guide</span>
          </button>
        </div>

        {/* Body */}
        <div className="hs-modal-body">
          {error && (
            <div className="hs-alert error" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
              <span>{error}</span>
            </div>
          )}
          {notice && (
            <div className="hs-alert notice" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
              <span>{notice}</span>
            </div>
          )}

          {connectedUser && (
            <div className="hs-active-account-card">
              <div className="hs-account-info">
                <span className="hs-status-dot" />
                <div>
                  <div className="hs-account-label">Active Connection</div>
                  <div className="hs-account-user">
                    {connectedUser} {connectedHubId ? `(Portal: ${connectedHubId})` : ''}
                  </div>
                </div>
              </div>
              <button
                type="button"
                className="hs-btn-connect"
                style={{ padding: '6px 12px', fontSize: '12px' }}
                onClick={handleConnect}
                disabled={busy}
              >
                Reconnect
              </button>
            </div>
          )}

          {tab === 'connection' && (
            <>
              {/* Credential Name */}
              <div className="hs-form-group">
                <label className="hs-form-label">
                  <span>Credential Name <span style={{ color: '#ef4444' }}>*</span></span>
                  <span className="hs-form-hint">Display name inside Flowsmith</span>
                </label>
                <input
                  type="text"
                  className="hs-input"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Production HubSpot CRM"
                  required
                />
              </div>

              {/* OAuth Callback / Redirect URL */}
              <div className="hs-form-group">
                <label className="hs-form-label">
                  <span>OAuth Callback URL (Redirect URI)</span>
                  <span className="hs-form-hint">Paste into HubSpot Developer App</span>
                </label>
                <div className="hs-input-wrap">
                  <input
                    type="text"
                    readOnly
                    className="hs-input mono"
                    value={redirectUrl}
                  />
                  <button
                    type="button"
                    className={`hs-input-btn ${copied ? 'copied' : ''}`}
                    onClick={handleCopyRedirect}
                    style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
                  >
                    {copied ? (
                      <>
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                        <span>Copied</span>
                      </>
                    ) : (
                      <>
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>
                        <span>Copy</span>
                      </>
                    )}
                  </button>
                </div>
              </div>

              {/* Client ID */}
              <div className="hs-form-group">
                <label className="hs-form-label">
                  <span>
                    Client ID (App ID) <span style={{ color: '#ef4444' }}>*</span>
                    {serverConfigured && (
                      <span className="hs-badge-flow" style={{ marginLeft: 8, fontSize: '10px', display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                        <span>Pre-configured in Flowsmith</span>
                      </span>
                    )}
                  </span>
                  <span className="hs-form-hint">Found under HubSpot Developer App Auth</span>
                </label>
                <input
                  type="text"
                  className="hs-input mono"
                  value={clientId}
                  onChange={(e) => setClientId(e.target.value)}
                  placeholder="e.g. 8b67f1b2-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                />
              </div>

              {/* Client Secret */}
              <div className="hs-form-group">
                <label className="hs-form-label">
                  <span>Client Secret <span style={{ color: '#ef4444' }}>*</span></span>
                  <span className="hs-form-hint">Securely encrypted in database</span>
                </label>
                <div className="hs-input-wrap">
                  <input
                    type={showSecret ? 'text' : 'password'}
                    className="hs-input mono"
                    value={clientSecret}
                    onChange={(e) => setClientSecret(e.target.value)}
                    placeholder="••••••••••••••••••••••••••••••••"
                  />
                  <button
                    type="button"
                    className="hs-input-btn"
                    onClick={() => setShowSecret(!showSecret)}
                  >
                    {showSecret ? 'Hide' : 'Show'}
                  </button>
                </div>
              </div>
            </>
          )}

          {tab === 'private_app' && (
            <>
              <div className="hs-form-group">
                <label className="hs-form-label">
                  <span>Credential Name <span style={{ color: '#ef4444' }}>*</span></span>
                  <span className="hs-form-hint">Display name inside Flowsmith</span>
                </label>
                <input
                  type="text"
                  className="hs-input"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. HubSpot Private App"
                  required
                />
              </div>

              <div className="hs-form-group">
                <label className="hs-form-label">
                  <span>Private App Access Token <span style={{ color: '#ef4444' }}>*</span></span>
                  <span className="hs-form-hint">Starts with pat-na1- or similar</span>
                </label>
                <div className="hs-input-wrap">
                  <input
                    type={showPrivateToken ? 'text' : 'password'}
                    className="hs-input mono"
                    value={privateToken}
                    onChange={(e) => setPrivateToken(e.target.value)}
                    placeholder="pat-na1-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                  />
                  <button
                    type="button"
                    className="hs-input-btn"
                    onClick={() => setShowPrivateToken(!showPrivateToken)}
                  >
                    {showPrivateToken ? 'Hide' : 'Show'}
                  </button>
                </div>
              </div>

              <div className="hs-step-card" style={{ marginTop: 8 }}>
                <div className="hs-step-title" style={{ fontSize: 13, display: 'flex', alignItems: 'center', gap: 6 }}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
                  <span>What is a Private App Token?</span>
                </div>
                <p className="hs-step-body" style={{ paddingLeft: 0, fontSize: 12 }}>
                  Private Apps allow you to connect Flowsmith to a single HubSpot portal without creating a developer app or going through OAuth redirects.
                  Generate one in your HubSpot portal under <strong>Settings &gt; Integrations &gt; Private Apps</strong>.
                </p>
              </div>
            </>
          )}

          {tab === 'guide' && (
            <div className="hs-guide-wrap">
              <div className="hs-step-card">
                <div className="hs-step-header">
                  <span className="hs-step-num">1</span>
                  <span className="hs-step-title">Create a HubSpot Developer App</span>
                </div>
                <p className="hs-step-body">
                  Log into your HubSpot Developer account at <a href="https://developers.hubspot.com" target="_blank" rel="noopener noreferrer" style={{ color: '#ff7a59' }}>developers.hubspot.com</a>, navigate to <strong>Apps</strong>, and click <strong>Create App</strong>.
                </p>
              </div>

              <div className="hs-step-card">
                <div className="hs-step-header">
                  <span className="hs-step-num">2</span>
                  <span className="hs-step-title">Configure Auth &amp; Redirect URL</span>
                </div>
                <p className="hs-step-body">
                  In your App's <strong>Auth</strong> tab, paste the Flowsmith Callback URL into <strong>Redirect URLs</strong>:
                  <br />
                  <code style={{ background: 'rgba(0,0,0,0.3)', padding: '2px 6px', borderRadius: 4, display: 'inline-block', marginTop: 4, color: '#ff7a59' }}>
                    {redirectUrl}
                  </code>
                </p>
              </div>

              <div className="hs-step-card">
                <div className="hs-step-header">
                  <span className="hs-step-num">3</span>
                  <span className="hs-step-title">Enable Required Scopes</span>
                </div>
                <p className="hs-step-body">
                  Add the required CRM scopes under <strong>Scopes</strong>:
                  <div className="hs-scope-tags">
                    <span className="hs-scope-tag">crm.objects.contacts.read</span>
                    <span className="hs-scope-tag">crm.objects.contacts.write</span>
                    <span className="hs-scope-tag">crm.objects.companies.read</span>
                    <span className="hs-scope-tag">crm.objects.companies.write</span>
                    <span className="hs-scope-tag">crm.objects.deals.read</span>
                    <span className="hs-scope-tag">crm.objects.deals.write</span>
                  </div>
                </p>
              </div>

              <div className="hs-step-card">
                <div className="hs-step-header">
                  <span className="hs-step-num">4</span>
                  <span className="hs-step-title">Copy Credentials to Flowsmith</span>
                </div>
                <p className="hs-step-body">
                  Copy your <strong>Client ID</strong> and <strong>Client Secret</strong> into the App Credentials tab, then click <strong>Connect with HubSpot</strong>.
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="hs-modal-footer">
          <div className="hs-footer-left">
            <button
              type="button"
              className="hs-btn-cancel"
              onClick={onClose}
              disabled={busy}
            >
              Cancel
            </button>
          </div>
          <div className="hs-footer-right">
            <button
              type="button"
              className="hs-btn-save"
              onClick={handleSaveModal}
              disabled={busy}
            >
              Save Configuration
            </button>
            {tab !== 'private_app' && (
              <button
                type="button"
                className="hs-btn-connect"
                onClick={handleConnect}
                disabled={busy}
              >
                {busy ? 'Connecting…' : 'Connect with HubSpot'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )

  return typeof document !== 'undefined'
    ? createPortal(modalContent, document.body)
    : modalContent
}
