import React, { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { NodeIcon } from './NodeIcons'
import { escapeHtml } from '../utils/escapeHtml'
import { isTrustedOAuthOrigin } from '../utils/oauthOrigins'
import './GoogleOAuthModal.css'

const GOOGLE_SERVICES = [
  { key: 'google_calendar', name: 'Google Calendar' },
  { key: 'google_sheets', name: 'Google Sheets' },
  { key: 'gmail', name: 'Gmail' },
  { key: 'google_drive', name: 'Google Drive' },
  { key: 'google_docs', name: 'Google Docs' },
]

export default function GoogleOAuthModal({
  isOpen,
  onClose,
  serviceType = 'google_calendar',
  initialData = null,
  onConnected,
  onSave,
}) {
  const [tab, setTab] = useState('connection') // 'connection' | 'guide'
  const activeService = GOOGLE_SERVICES.find((s) => s.key === serviceType) || GOOGLE_SERVICES[0]
  const [name, setName] = useState(initialData?.name || `${activeService.name} account`)
  const [clientId, setClientId] = useState(initialData?.data?.client_id || '')
  const [clientSecret, setClientSecret] = useState(initialData?.data?.client_secret || '')
  const [showSecret, setShowSecret] = useState(false)
  const [copiedKey, setCopiedKey] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [connectedUser, setConnectedUser] = useState(initialData?.data?.user || null)
  const [canonicalRedirectUrl, setCanonicalRedirectUrl] = useState('')
  const [serverConfigured, setServerConfigured] = useState(false)
  const [showAllCallbacks, setShowAllCallbacks] = useState(false)

  // Derive current service Callback URL
  const backendBase = typeof window !== 'undefined'
    ? `${window.location.protocol}//${window.location.hostname}${window.location.port === '5173' ? ':8000' : (window.location.port ? `:${window.location.port}` : '')}`
    : 'http://localhost:8000'

  const fallbackRedirectUrl = `${backendBase}/api/auth/${serviceType}/callback`
  const redirectUrl = canonicalRedirectUrl || fallbackRedirectUrl

  useEffect(() => {
    if (!isOpen) return
    import('../api').then(({ api }) => {
      api.getOAuthConfig(serviceType)
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
  }, [isOpen, serviceType, initialData])

  useEffect(() => {
    if (initialData) {
      setName(initialData.name || `${activeService.name} account`)
      setClientId(initialData.data?.client_id || '')
      setClientSecret(initialData.data?.client_secret || '')
      setConnectedUser(initialData.data?.user || null)
    } else {
      setName(`${activeService.name} account`)
      setClientId('')
      setClientSecret('')
      setConnectedUser(null)
    }
  }, [initialData, activeService])

  useEffect(() => {
    if (!isOpen) return
    const onKey = (e) => {
      if (e.key === 'Escape') onClose?.()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [isOpen, onClose])

  // Abort any in-flight OAuth watcher when the modal closes or unmounts so
  // window listeners and poll intervals never outlive it.
  const activeFlowRef = React.useRef(null)
  useEffect(() => {
    if (isOpen) return
    activeFlowRef.current?.()
    activeFlowRef.current = null
    setBusy(false)
  }, [isOpen])
  useEffect(() => () => {
    activeFlowRef.current?.()
    activeFlowRef.current = null
  }, [])

  if (!isOpen) return null

  const handleCopyText = (text, key) => {
    if (navigator?.clipboard) {
      navigator.clipboard.writeText(text)
      setCopiedKey(key)
      setTimeout(() => setCopiedKey(null), 2000)
    }
  }

  const handleConnect = async () => {
    setError(null)
    setNotice(null)
    setBusy(true)

    let popup = null
    try {
      popup = window.open('about:blank', `oauth-${serviceType}`, 'width=560,height=680')
      if (popup && popup.document) {
        popup.document.write(`
          <!DOCTYPE html>
          <html>
            <head>
              <title>Connecting to ${escapeHtml(activeService.name)}…</title>
              <style>
                body { font-family: system-ui, -apple-system, sans-serif; background: #0b0e17; color: #f8fafc; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; margin: 0; }
                .spinner { width: 36px; height: 36px; border: 3px solid rgba(255,255,255,0.15); border-top-color: #3b82f6; border-radius: 50%; animation: spin 1s linear infinite; margin-bottom: 16px; }
                @keyframes spin { to { transform: rotate(360deg); } }
                h3 { margin: 0 0 8px; font-size: 16px; }
                p { font-size: 13px; color: #94a3b8; margin: 0; }
              </style>
            </head>
            <body>
              <div class="spinner"></div>
              <h3>Connecting to Google…</h3>
              <p>Please authorize ${escapeHtml(activeService.name)} permissions in the opened window.</p>
            </body>
          </html>
        `)
      }
    } catch (err) { console.error('[flowsmith] components/GoogleOAuthModal.jsx', err) }

    try {
      const { api } = await import('../api')
      const extra = {}
      if (clientId.trim()) extra.client_id = clientId.trim()
      if (clientSecret.trim()) extra.client_secret = clientSecret.trim()
      if (name.trim()) extra.name = name.trim()

      const res = await api.connectOAuth(serviceType, undefined, 'consent', extra)
      const authorizeUrl = res?.data?.authorize_url || res?.authorize_url

      if (!authorizeUrl) {
        throw new Error('Server did not return an authorization URL.')
      }
      if (!/^https?:\/\//i.test(authorizeUrl)) {
        throw new Error('Server returned an invalid authorization URL.')
      }

      if (!popup || popup.closed || typeof popup.closed === 'undefined') {
        setBusy(false)
        setError('Popup was blocked by your browser. Please allow popups or use the direct link.')
        return
      }

      popup.location.href = authorizeUrl

      let resolved = false
      let bc = null

      const handleResult = (data) => {
        if (!data) return
        let isSuccess = false
        let isFail = false
        let errorMsg = ''

        if (typeof data === 'string') {
          if (data === 'oauth_connected' || data === `${serviceType}_connected`) {
            isSuccess = true
          } else if (data === 'oauth_connect_failed' || data === `${serviceType}_connect_failed`) {
            isFail = true
            errorMsg = 'Google authorization was cancelled or failed.'
          }
        } else if (typeof data === 'object') {
          const isOAuth = data.source === 'oauth' || data.source === 'salesforce-oauth' || data.provider
          if (isOAuth) {
            const matchesProvider = !data.provider || data.provider === serviceType || data.provider?.startsWith('google')
            if (matchesProvider) {
              if (data.ok === true || data.type === 'salesforce-oauth-success') {
                isSuccess = true
              } else if (data.ok === false || data.type === 'salesforce-oauth-error') {
                isFail = true
                errorMsg = data.error || 'Google authorization was cancelled or failed.'
              }
            }
          }
        }

        if (isSuccess && !resolved) {
          resolved = true
          cleanup()
          setNotice(`${activeService.name} authorized and connected successfully.`)
          setBusy(false)
          try { popup.close() } catch {}
          onConnected?.()
          setTimeout(() => onClose?.(), 1200)
        } else if (isFail && !resolved) {
          import('../api').then(async ({ api }) => {
            try {
              const creds = await api.listCredentials()
              const found = Array.isArray(creds) && creds.find(c => c.type === serviceType || (serviceType.startsWith('google_') && c.type.startsWith('google_')))
              if (found) {
                resolved = true
                cleanup()
                setNotice(`${activeService.name} authorized and connected successfully.`)
                setBusy(false)
                try { popup.close() } catch {}
                onConnected?.()
                setTimeout(() => onClose?.(), 1200)
                return
              }
            } catch {}
            resolved = true
            cleanup()
            setError(errorMsg || 'Google authorization was cancelled or failed.')
            setBusy(false)
            try { popup.close() } catch {}
          })
          return
        }
      }

      const messageHandler = (e) => {
        if (!isTrustedOAuthOrigin(e.origin)) {
          console.warn('[flowsmith] GoogleOAuthModal: message from untrusted origin', e.origin)
          return
        }
        handleResult(e.data)
      }

      const storageHandler = (e) => {
        if ((e.key === 'oauth_success' || e.key === 'flowsmith_oauth_result') && e.newValue) {
          try {
            handleResult(JSON.parse(e.newValue))
          } catch (err) { console.error('[flowsmith] components/GoogleOAuthModal.jsx', err) }
        }
      }

      try {
        if (typeof BroadcastChannel !== 'undefined') {
          bc = new BroadcastChannel('flowsmith_oauth')
          bc.onmessage = (ev) => handleResult(ev.data)
        }
      } catch (err) { console.error('[flowsmith] components/GoogleOAuthModal.jsx', err) }

      const pollClosed = setInterval(() => {
        if (popup && popup.closed) {
          if (!resolved) {
            setTimeout(async () => {
              if (resolved) return
              try {
                const { api } = await import('../api')
                const creds = await api.listCredentials()
                const found = Array.isArray(creds) && creds.find(c => c.type === serviceType || (serviceType.startsWith('google_') && c.type.startsWith('google_')))
                if (found) {
                  resolved = true
                  setNotice(`${activeService.name} authorized and connected successfully.`)
                  setBusy(false)
                  onConnected?.()
                  setTimeout(() => onClose?.(), 1200)
                  return
                }
              } catch {}
              setBusy(false)
              setError('Popup was closed before authorization completed. Please try connecting again.')
            }, 800)
          }
          cleanup()
        }
      }, 500)

      const cleanup = () => {
        window.removeEventListener('message', messageHandler)
        window.removeEventListener('storage', storageHandler)
        if (bc) {
          try { bc.close() } catch {}
          bc = null
        }
        clearInterval(pollClosed)
      }

      window.addEventListener('message', messageHandler)
      window.addEventListener('storage', storageHandler)

      activeFlowRef.current = () => {
        cleanup()
        if (popup && !popup.closed) {
          try { popup.close() } catch {}
        }
      }
    } catch (err) {
      setBusy(false)
      if (popup && !popup.closed) {
        try { popup.close() } catch {}
      }
      setError(err?.message || `Failed to initiate ${activeService.name} connection.`)
    }
  }

  const handleSaveModal = async () => {
    if (!name.trim()) {
      setError('Please provide a credential name.')
      return
    }

    if (onSave) {
      onSave({
        name: name.trim(),
        type: serviceType,
        data: {
          client_id: clientId.trim(),
          client_secret: clientSecret.trim(),
        },
      })
    }
    onClose()
  }

  const modalContent = (
    <div className="goog-modal-overlay" onClick={onClose}>
      <div
        className="goog-modal-window"
        role="dialog"
        aria-modal="true"
        aria-labelledby="google-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="goog-modal-header">
          <div className="goog-header-title-wrap">
            <div className="goog-brand-avatar">
              <NodeIcon type={serviceType} size={24} />
            </div>
            <div className="goog-header-meta">
              <h3 id="google-modal-title">
                {initialData?.id ? `Edit ${activeService.name}` : `Google Cloud App (${activeService.name})`}
                <span className="goog-badge-flow">OAuth 2.0</span>
              </h3>
              <p>Configure Google Cloud OAuth 2.0 credentials for all Google services</p>
            </div>
          </div>
          <button
            type="button"
            className="goog-close-btn"
            onClick={onClose}
            title="Close (Esc)"
            aria-label="Close"
            style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>

        {/* Tab Navigation */}
        <div className="goog-modal-tabs">
          <button
            type="button"
            className={`goog-tab-btn ${tab === 'connection' ? 'active' : ''}`}
            onClick={() => setTab('connection')}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m21 2-2 2m-1.5 1.5L10 13m-2-2L3.5 15.5a3.536 3.536 0 0 0 5 5L13 16m-2-2 2.5 2.5m1-1 2 2m-7-7 2 2"/><circle cx="7.5" cy="16.5" r=".5" fill="currentColor"/></svg>
            <span>OAuth Client Credentials</span>
          </button>
          <button
            type="button"
            className={`goog-tab-btn ${tab === 'guide' ? 'active' : ''}`}
            onClick={() => setTab('guide')}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z"/><path d="M6 6h10"/><path d="M6 10h10"/></svg>
            <span>Google Cloud Guide</span>
          </button>
        </div>

        {/* Body */}
        <div className="goog-modal-body">
          {error && (
            <div className="goog-alert error" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
              <span>{error}</span>
            </div>
          )}
          {notice && (
            <div className="goog-alert notice" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
              <span>{notice}</span>
            </div>
          )}

          {connectedUser && (
            <div className="goog-active-account-card">
              <div className="goog-account-info">
                <span className="goog-status-dot" />
                <div>
                  <div className="goog-account-label">Active Connection</div>
                  <div className="goog-account-user">{connectedUser}</div>
                </div>
              </div>
              <button
                type="button"
                className="goog-btn-connect"
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
              <div className="goog-form-group">
                <label className="goog-form-label">
                  <span>Credential Name <span style={{ color: '#ef4444' }}>*</span></span>
                  <span className="goog-form-hint">Display name inside Flowsmith</span>
                </label>
                <input
                  type="text"
                  className="goog-input"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={`e.g. Work ${activeService.name}`}
                  required
                />
              </div>

              {/* Authorized Redirect URI */}
              <div className="goog-form-group">
                <label className="goog-form-label">
                  <span>Authorized Redirect URI ({activeService.name})</span>
                  <span className="goog-form-hint">Add to Google Cloud Web Client</span>
                </label>
                <div className="goog-input-wrap">
                  <input
                    type="text"
                    readOnly
                    className="goog-input mono"
                    value={redirectUrl}
                  />
                  <button
                    type="button"
                    className={`goog-input-btn ${copiedKey === 'current' ? 'copied' : ''}`}
                    onClick={() => handleCopyText(redirectUrl, 'current')}
                    style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
                  >
                    {copiedKey === 'current' ? (
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

              {/* All Google Callbacks expandable */}
              <div className="goog-callbacks-box">
                <div
                  className="goog-callbacks-header"
                  onClick={() => setShowAllCallbacks(!showAllCallbacks)}
                >
                  <h4 style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0 }}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="2" x2="22" y1="12" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                    <span>All Google Service Callback URLs</span>
                  </h4>
                  <span style={{ fontSize: '12px', color: '#60a5fa', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                    {showAllCallbacks ? (
                      <>
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="18 15 12 9 6 15"/></svg>
                        <span>Hide</span>
                      </>
                    ) : (
                      <>
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="6 9 12 15 18 9"/></svg>
                        <span>Show all 5</span>
                      </>
                    )}
                  </span>
                </div>
                {showAllCallbacks && (
                  <div className="goog-callbacks-list">
                    {GOOGLE_SERVICES.map((s) => {
                      const url = `${backendBase}/api/auth/${s.key}/callback`
                      const isCur = s.key === serviceType
                      return (
                        <div key={s.key} className="goog-callback-row">
                          <span className="goog-callback-name">
                            {s.name} {isCur ? '(current)' : ''}
                          </span>
                          <span className="goog-callback-url">{url}</span>
                          <button
                            type="button"
                            className={`goog-input-btn ${copiedKey === s.key ? 'copied' : ''}`}
                            style={{ position: 'static', display: 'inline-flex', alignItems: 'center', gap: 4 }}
                            onClick={() => handleCopyText(url, s.key)}
                          >
                            {copiedKey === s.key ? (
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
                      )
                    })}
                  </div>
                )}
              </div>

              {/* Client ID */}
              <div className="goog-form-group">
                <label className="goog-form-label">
                  <span>
                    Google Client ID <span style={{ color: '#ef4444' }}>*</span>
                    {serverConfigured && (
                      <span className="goog-badge-flow" style={{ marginLeft: 8, fontSize: '10px', display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                        <span>Pre-configured in Flowsmith</span>
                      </span>
                    )}
                  </span>
                  <span className="goog-form-hint">Ends with apps.googleusercontent.com</span>
                </label>
                <input
                  type="text"
                  className="goog-input mono"
                  value={clientId}
                  onChange={(e) => setClientId(e.target.value)}
                  placeholder="xxxx-xxxxxxxx.apps.googleusercontent.com"
                />
              </div>

              {/* Client Secret */}
              <div className="goog-form-group">
                <label className="goog-form-label">
                  <span>Google Client Secret <span style={{ color: '#ef4444' }}>*</span></span>
                  <span className="goog-form-hint">Stored encrypted in database</span>
                </label>
                <div className="goog-input-wrap">
                  <input
                    type={showSecret ? 'text' : 'password'}
                    className="goog-input mono"
                    value={clientSecret}
                    onChange={(e) => setClientSecret(e.target.value)}
                    placeholder="GOCSPX-••••••••••••••••••••••••"
                  />
                  <button
                    type="button"
                    className="goog-input-btn"
                    onClick={() => setShowSecret(!showSecret)}
                  >
                    {showSecret ? 'Hide' : 'Show'}
                  </button>
                </div>
              </div>
            </>
          )}

          {tab === 'guide' && (
            <div className="goog-guide-wrap">
              <div className="goog-step-card">
                <div className="goog-step-header">
                  <span className="goog-step-num">1</span>
                  <span className="goog-step-title">Create or Select a Google Cloud Project</span>
                </div>
                <p className="goog-step-body">
                  Open <a href="https://console.cloud.google.com" target="_blank" rel="noopener noreferrer" style={{ color: '#60a5fa' }}>Google Cloud Console</a> and create or select a project for your organization or personal workspace.
                </p>
              </div>

              <div className="goog-step-card">
                <div className="goog-step-header">
                  <span className="goog-step-num">2</span>
                  <span className="goog-step-title">Configure OAuth Consent Screen</span>
                </div>
                <p className="goog-step-body">
                  Under <strong>APIs &amp; Services &gt; OAuth consent screen</strong>, choose <strong>Internal</strong> (for Google Workspace) or <strong>External</strong>. Fill in the App Name (e.g. Flowsmith) and Support Email.
                </p>
              </div>

              <div className="goog-step-card">
                <div className="goog-step-header">
                  <span className="goog-step-num">3</span>
                  <span className="goog-step-title">Enable Google APIs</span>
                </div>
                <p className="goog-step-body">
                  Go to <strong>APIs &amp; Services &gt; Library</strong> and enable the APIs you plan to use:
                  <br />
                  • Google Calendar API
                  <br />
                  • Google Sheets API
                  <br />
                  • Gmail API
                  <br />
                  • Google Drive API
                  <br />
                  • Google Docs API
                </p>
              </div>

              <div className="goog-step-card">
                <div className="goog-step-header">
                  <span className="goog-step-num">4</span>
                  <span className="goog-step-title">Create OAuth 2.0 Web Client ID</span>
                </div>
                <p className="goog-step-body">
                  Navigate to <strong>Credentials &gt; Create Credentials &gt; OAuth client ID</strong>.
                  Select <strong>Web application</strong> as Application type.
                  Under <strong>Authorized redirect URIs</strong>, paste the Flowsmith callback URL:
                  <br />
                  <code style={{ background: 'rgba(0,0,0,0.3)', padding: '2px 6px', borderRadius: 4, display: 'inline-block', marginTop: 4, color: '#60a5fa' }}>
                    {redirectUrl}
                  </code>
                </p>
              </div>

              <div className="goog-step-card">
                <div className="goog-step-header">
                  <span className="goog-step-num">5</span>
                  <span className="goog-step-title">Copy Client ID &amp; Secret into Flowsmith</span>
                </div>
                <p className="goog-step-body">
                  Save your credentials in Flowsmith. Configuring this once enables authorization across all 5 Google Suite connectors.
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="goog-modal-footer">
          <div className="goog-footer-left">
            <button
              type="button"
              className="goog-btn-cancel"
              onClick={onClose}
              disabled={busy}
            >
              Cancel
            </button>
          </div>
          <div className="goog-footer-right">
            <button
              type="button"
              className="goog-btn-save"
              onClick={handleSaveModal}
              disabled={busy}
            >
              Save Configuration
            </button>
            <button
              type="button"
              className="goog-btn-connect"
              onClick={handleConnect}
              disabled={busy}
            >
              {busy ? 'Connecting…' : `Connect ${activeService.name}`}
            </button>
          </div>
        </div>
      </div>
    </div>
  )

  return typeof document !== 'undefined'
    ? createPortal(modalContent, document.body)
    : modalContent
}
