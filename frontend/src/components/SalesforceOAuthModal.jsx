import React, { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { NodeIcon } from './NodeIcons'
import Button from './shared/Button'
import { isTrustedOAuthOrigin } from '../utils/oauthOrigins'
import './SalesforceOAuthModal.css'

export default function SalesforceOAuthModal({
  isOpen,
  onClose,
  initialData = null,
  onConnected,
  onSave,
}) {
  const [tab, setTab] = useState('connection') // 'connection' | 'environment' | 'details'
  const [name, setName] = useState(initialData?.name || 'Salesforce account')
  const [clientId, setClientId] = useState(initialData?.data?.client_id || '')
  const [clientSecret, setClientSecret] = useState(initialData?.data?.client_secret || '')
  const [showSecret, setShowSecret] = useState(false)
  const [envType, setEnvType] = useState(
    initialData?.data?.login_url?.includes('test.salesforce.com') ? 'sandbox' : 'production'
  )
  const [domainPolicy, setDomainPolicy] = useState(
    initialData?.data?.allowed_domains && !['all', 'none'].includes(initialData?.data?.allowed_domains)
      ? 'specific'
      : (initialData?.data?.allowed_domains || 'all')
  )
  const [specificDomains, setSpecificDomains] = useState(
    initialData?.data?.allowed_domains && !['all', 'none'].includes(initialData?.data?.allowed_domains)
      ? initialData?.data?.allowed_domains
      : ''
  )
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [connectedAccount, setConnectedAccount] = useState(
    initialData?.name?.includes('(') ? initialData.name : (initialData?.data?.account || null)
  )
  const [canonicalRedirectUrl, setCanonicalRedirectUrl] = useState('')
  const [serverConfigured, setServerConfigured] = useState(false)

  // Derive OAuth Callback URL matching current backend host
  const fallbackRedirectUrl = typeof window !== 'undefined'
    ? `${window.location.protocol}//${window.location.hostname}${window.location.port === '5173' ? ':8000' : (window.location.port ? `:${window.location.port}` : '')}/api/auth/salesforce/callback`
    : 'http://localhost:8000/api/auth/salesforce/callback'
  const redirectUrl = canonicalRedirectUrl || fallbackRedirectUrl

  useEffect(() => {
    if (!isOpen) return
    import('../api').then(({ api }) => {
      api.getOAuthConfig('salesforce')
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
      setName(initialData.name || 'Salesforce account')
      setClientId(initialData.data?.client_id || '')
      setClientSecret(initialData.data?.client_secret || '')
      setEnvType(initialData.data?.login_url?.includes('test.salesforce.com') ? 'sandbox' : 'production')
      const pol = initialData.data?.allowed_domains || 'all'
      if (!['all', 'none'].includes(pol)) {
        setDomainPolicy('specific')
        setSpecificDomains(pol)
      } else {
        setDomainPolicy(pol)
        setSpecificDomains('')
      }
      setConnectedAccount(initialData.name)
    } else {
      setName('Salesforce account')
      setClientId('')
      setClientSecret('')
      setDomainPolicy('all')
      setSpecificDomains('')
      setConnectedAccount(null)
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

    const loginUrl = envType === 'sandbox'
      ? 'https://test.salesforce.com'
      : 'https://login.salesforce.com'

    const allowedDomainsValue = domainPolicy === 'specific'
      ? specificDomains.trim()
      : domainPolicy

    const extra = {
      clientId: clientId.trim(),
      clientSecret: clientSecret.trim(),
      name: name.trim() || 'Salesforce account',
      allowedDomains: allowedDomainsValue,
    }

    if (initialData?.id) {
      extra.credentialId = initialData.id
    }

    // Open popup window immediately on click gesture to prevent browser popup blockers
    let popup = null
    try {
      popup = window.open('about:blank', 'oauth-salesforce', 'width=580,height=720,scrollbars=yes,resizable=yes')
      if (popup && popup.document) {
        popup.document.write(`
          <!DOCTYPE html>
          <html>
            <head>
              <title>Connecting to Salesforce…</title>
              <style>
                body {
                  background: #0b0e15;
                  color: #f8fafc;
                  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                  display: flex;
                  flex-direction: column;
                  align-items: center;
                  justify-content: center;
                  height: 100vh;
                  margin: 0;
                }
                .spinner {
                  width: 36px;
                  height: 36px;
                  border: 3px solid rgba(255, 255, 255, 0.12);
                  border-top-color: #6366f1;
                  border-radius: 50%;
                  animation: spin 0.8s linear infinite;
                  margin-bottom: 16px;
                }
                @keyframes spin { to { transform: rotate(360deg); } }
                h3 { margin: 0 0 6px; font-size: 16px; font-weight: 600; }
                p { margin: 0; font-size: 13px; color: #94a3b8; }
              </style>
            </head>
            <body>
              <div class="spinner"></div>
              <h3>Connecting to Salesforce</h3>
              <p>Preparing secure OAuth 2.0 authorization with PKCE…</p>
            </body>
          </html>
        `)
      }
    } catch (err) { console.error('[flowsmith] components/SalesforceOAuthModal.jsx', err) }

    if (!popup || popup.closed || typeof popup.closed === 'undefined') {
      setBusy(false)
      setError('Popup was blocked by your browser. Please allow popups for Flowsmith to connect your Salesforce account.')
      return
    }

    try {
      const { api } = await import('../api')
      const res = await api.connectOAuth('salesforce', loginUrl, 'login', extra)
      const authorizeUrl = res?.authorize_url || res?.authorizeUrl
      if (!authorizeUrl) {
        throw new Error('Failed to retrieve Salesforce authorization URL from server.')
      }

      if (popup && !popup.closed) {
        popup.location.href = authorizeUrl
      } else {
        popup = window.open(authorizeUrl, 'oauth-salesforce', 'width=580,height=720,scrollbars=yes,resizable=yes')
      }

      let bc = null
      try {
        if (typeof BroadcastChannel !== 'undefined') {
          bc = new BroadcastChannel('flowsmith_oauth')
          bc.onmessage = (ev) => handleResult(ev.data)
        }
      } catch (err) { console.error('[flowsmith] components/SalesforceOAuthModal.jsx', err) }

      const cleanupListeners = () => {
        window.removeEventListener('message', messageHandler)
        if (bc) {
          try { bc.close() } catch {}
        }
        if (timer) clearInterval(timer)
      }

      const messageHandler = (ev) => {
        if (!isTrustedOAuthOrigin(ev.origin)) {
          console.warn('[flowsmith] SalesforceOAuthModal: message from untrusted origin', ev.origin)
          return
        }
        handleResult(ev.data)
      }
      window.addEventListener('message', messageHandler)

      let handled = false
      const handleResult = async (data) => {
        if (!data || typeof data !== 'object') return
        const isOAuth = data.source === 'oauth' || data.source === 'salesforce-oauth'
        const isSuccess = data.type === 'salesforce-oauth-success' || data.ok === true
        const isError = data.type === 'salesforce-oauth-error' || data.ok === false
        if (!isOAuth || (!isSuccess && !isError)) return
        if (data.provider && data.provider !== 'salesforce') return

        handled = true
        cleanupListeners()
        setBusy(false)

        if (popup && !popup.closed) {
          try { popup.close() } catch {}
        }

        if (isSuccess || data.ok) {
          setNotice('Salesforce account authorized and connected successfully.')
          setConnectedAccount(data.account || name)
          if (onConnected) {
            onConnected(data)
          }
        } else {
          setError(data.error || 'Salesforce authorization failed.')
        }
      }

      // Detect if user manually closed the popup
      const timer = setInterval(() => {
        if (popup && popup.closed) {
          clearInterval(timer)
          if (!handled) {
            cleanupListeners()
            setBusy(false)
          }
        }
      }, 500)

    } catch (err) {
      if (popup && !popup.closed) {
        try { popup.close() } catch {}
      }
      setBusy(false)
      setError(err?.message || 'Could not initiate Salesforce authorization.')
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
        type: 'salesforce',
        data: {
          client_id: clientId.trim(),
          client_secret: clientSecret.trim(),
          login_url: envType === 'sandbox' ? 'https://test.salesforce.com' : 'https://login.salesforce.com',
          allowed_domains: domainPolicy === 'specific' ? specificDomains.trim() : domainPolicy,
        }
      })
    }
    onClose()
  }

  const modalContent = (
    <div className="sf-modal-overlay" onClick={onClose}>
      <div className="sf-modal-window" role="dialog" aria-modal="true" aria-labelledby="sf-modal-title" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="sf-modal-header">
          <div className="sf-header-title-wrap">
            <div className="sf-brand-avatar">
              <NodeIcon type="salesforce" size={24} />
            </div>
            <div className="sf-header-meta">
              <h3 id="sf-modal-title">
                {initialData?.id ? 'Edit Salesforce Credential' : 'Salesforce Connected App'}
                <span className="sf-badge-flow">OAuth 2.0 PKCE</span>
              </h3>
              <p>Configure custom Connected App or connect with Salesforce CRM</p>
            </div>
          </div>
          <button
            type="button"
            className="sf-close-btn"
            onClick={onClose}
            title="Close (Esc)"
            aria-label="Close"
            style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>

        {/* Tab Navigation */}
        <div className="sf-modal-tabs">
          <button
            type="button"
            className={`sf-tab-btn ${tab === 'connection' ? 'active' : ''}`}
            onClick={() => setTab('connection')}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m21 2-2 2m-1.5 1.5L10 13m-2-2L3.5 15.5a3.536 3.536 0 0 0 5 5L13 16m-2-2 2.5 2.5m1-1 2 2m-7-7 2 2"/><circle cx="7.5" cy="16.5" r=".5" fill="currentColor"/></svg>
            <span>App Credentials</span>
          </button>
          <button
            type="button"
            className={`sf-tab-btn ${tab === 'environment' ? 'active' : ''}`}
            onClick={() => setTab('environment')}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="2" x2="22" y1="12" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
            <span>Environment & Scope</span>
          </button>
          <button
            type="button"
            className={`sf-tab-btn ${tab === 'details' ? 'active' : ''}`}
            onClick={() => setTab('details')}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
            <span>Security & Details</span>
          </button>
        </div>

        {/* Modal Body */}
        <div className="sf-modal-body">
          {error && (
            <div className="sf-alert sf-alert-error" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
              <div>{error}</div>
            </div>
          )}

          {notice && (
            <div className="sf-alert sf-alert-success" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
              <div>{notice}</div>
            </div>
          )}

          {/* TAB 1: App Credentials */}
          {tab === 'connection' && (
            <>
              {/* Active Connection Indicator */}
              <div className="sf-status-box">
                <div className="sf-status-left">
                  <span
                    className={`sf-status-dot ${connectedAccount ? 'connected' : 'disconnected'}`}
                  />
                  <div className="sf-status-text">
                    <h4>{connectedAccount ? 'Account Authorized' : 'No Active Session'}</h4>
                    <p>
                      {connectedAccount
                        ? `Connected as ${connectedAccount}`
                        : 'Connect via OAuth 2.0 Web Server Flow to grant Flowsmith access.'}
                    </p>
                  </div>
                </div>
                <Button
                  variant={connectedAccount ? 'ghost' : 'primary'}
                  size="sm"
                  onClick={handleConnect}
                  disabled={busy}
                >
                  {busy ? (
                    <>
                      <span className="sf-spinner" />
                      <span>Authorizing…</span>
                    </>
                  ) : connectedAccount ? (
                    '↻ Re-authenticate'
                  ) : (
                    'Connect Account'
                  )}
                </Button>
              </div>

              {/* Credential Name */}
              <div className="sf-form-group">
                <label className="sf-form-label">
                  <span>Credential Name <span className="required">*</span></span>
                </label>
                <input
                  type="text"
                  className="sf-input"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Production Salesforce CRM"
                  required
                />
              </div>

              {/* OAuth Callback / Redirect URL */}
              <div className="sf-form-group">
                <label className="sf-form-label">
                  <span>OAuth Callback URL (Redirect URI)</span>
                  <span className="sf-form-hint">Paste into Salesforce Connected App</span>
                </label>
                <div className="sf-input-wrap">
                  <input
                    type="text"
                    readOnly
                    className="sf-input mono"
                    value={redirectUrl}
                  />
                  <button
                    type="button"
                    className={`sf-input-btn ${copied ? 'copied' : ''}`}
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

              {/* Client ID / Consumer Key */}
              <div className="sf-form-group">
                <label className="sf-form-label">
                  <span>
                    Consumer Key (Client ID) <span className="required">*</span>
                    {serverConfigured && (
                      <span className="sf-badge-flow" style={{ marginLeft: 8, fontSize: '10px', display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                        <span>Pre-configured in Flowsmith</span>
                      </span>
                    )}
                  </span>
                  <span className="sf-form-hint">Found under Manage Connected Apps</span>
                </label>
                <input
                  type="text"
                  className="sf-input mono"
                  value={clientId}
                  onChange={(e) => setClientId(e.target.value)}
                  placeholder="3MVG97LPWbPq6UzeixCsscpT5gtAB..."
                />
              </div>

              {/* Client Secret / Consumer Secret */}
              <div className="sf-form-group">
                <label className="sf-form-label">
                  <span>Consumer Secret (Client Secret)</span>
                  <span className="sf-form-hint">Optional if using PKCE without secret</span>
                </label>
                <div className="sf-input-wrap">
                  <input
                    type={showSecret ? 'text' : 'password'}
                    className="sf-input mono"
                    value={clientSecret}
                    onChange={(e) => setClientSecret(e.target.value)}
                    placeholder="••••••••••••••••••••••••••••••••••••••••••••"
                  />
                  <button
                    type="button"
                    className="sf-input-btn"
                    onClick={() => setShowSecret(!showSecret)}
                    title={showSecret ? 'Hide secret' : 'Show secret'}
                    style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
                  >
                    {showSecret ? (
                      <>
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"/><path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"/><path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"/><line x1="2" x2="22" y1="2" y2="22"/></svg>
                        <span>Hide</span>
                      </>
                    ) : (
                      <>
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>
                        <span>Show</span>
                      </>
                    )}
                  </button>
                </div>
              </div>

              {/* Quick Setup Instructions Guide */}
              <div className="sf-info-guide">
                <div className="sf-info-guide-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
                  <span>Salesforce Connected App Quick Setup</span>
                </div>
                <ol>
                  <li>In Salesforce Setup, navigate to <strong>App Manager</strong> &gt; <strong>New Connected App</strong>.</li>
                  <li>Check <strong>Enable OAuth Settings</strong> and paste the Callback URL above.</li>
                  <li>Add OAuth Scopes: <code>api</code>, <code>refresh_token, offline_access</code>, <code>id</code>.</li>
                  <li>Enable <strong>Require Proof Key for Code Exchange (PKCE)</strong>.</li>
                  <li>Copy the <strong>Consumer Key</strong> and <strong>Consumer Secret</strong> into the fields above.</li>
                </ol>
              </div>
            </>
          )}

          {/* TAB 2: Environment & Scope */}
          {tab === 'environment' && (
            <>
              <div className="sf-form-group">
                <label className="sf-form-label">Salesforce Environment</label>
                <div className="sf-env-selector">
                  <div
                    className={`sf-env-card ${envType === 'production' ? 'active' : ''}`}
                    onClick={() => setEnvType('production')}
                  >
                    <div className="sf-env-card-title">
                      <span>Production / Developer</span>
                      {envType === 'production' && (
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                      )}
                    </div>
                    <span className="sf-env-card-url">https://login.salesforce.com</span>
                  </div>

                  <div
                    className={`sf-env-card ${envType === 'sandbox' ? 'active' : ''}`}
                    onClick={() => setEnvType('sandbox')}
                  >
                    <div className="sf-env-card-title">
                      <span>Sandbox / Test</span>
                      {envType === 'sandbox' && (
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                      )}
                    </div>
                    <span className="sf-env-card-url">https://test.salesforce.com</span>
                  </div>
                </div>
              </div>

              <div className="sf-form-group">
                <label className="sf-form-label">Allowed Request Domains</label>
                <div className="sf-input-wrap">
                  <select
                    className="sf-input"
                    value={domainPolicy}
                    onChange={(e) => setDomainPolicy(e.target.value)}
                  >
                    <option value="all">All Domains (Standard Salesforce API &amp; Custom My Domains)</option>
                    <option value="specific">Specific Whitelisted Domains</option>
                    <option value="none">Block Generic HTTP Requests (Salesforce node only)</option>
                  </select>
                </div>
                <div className="sf-form-hint">
                  Controls where this OAuth token can be dispatched if referenced by HTTP Request nodes.
                </div>
              </div>

              {domainPolicy === 'specific' && (
                <div className="sf-form-group">
                  <label className="sf-form-label">Whitelisted Domains</label>
                  <input
                    type="text"
                    className="sf-input mono"
                    value={specificDomains}
                    onChange={(e) => setSpecificDomains(e.target.value)}
                    placeholder="e.g. *.my.salesforce.com, yourcompany.my.salesforce.com"
                  />
                  <div className="sf-form-hint">Separate multiple domains with commas. Wildcards (*) are supported.</div>
                </div>
              )}
            </>
          )}

          {/* TAB 3: Security & Details */}
          {tab === 'details' && (
            <div className="sf-info-guide" style={{ gap: 12 }}>
              <div className="sf-info-guide-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                <span>Security &amp; Encryption Architecture</span>
              </div>
              <p style={{ margin: 0, fontSize: 13, lineHeight: 1.6 }}>
                Salesforce OAuth tokens are protected by enterprise security standards within Flowsmith:
              </p>
              <ul style={{ margin: 0, paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12 }}>
                <li><strong>PKCE Protection:</strong> Uses RFC 7636 Proof Key for Code Exchange (SHA-256 code challenge) preventing authorization code interception.</li>
                <li><strong>Zero-Plaintext Storage:</strong> Access and refresh tokens are encrypted at rest with AES-256 (Fernet) encryption before database commit.</li>
                <li><strong>Automatic Rotation:</strong> Expired session tokens are refreshed silently in the background without interrupting running workflows.</li>
                <li><strong>Workspace Isolation:</strong> Credentials are partitioned and inaccessible outside your authorized tenant workspace.</li>
              </ul>
              {initialData?.id && (
                <div style={{ marginTop: 8, paddingTop: 10, borderTop: '1px solid var(--border)' }}>
                  <span style={{ fontSize: 11, color: 'var(--muted)' }}>Credential ID: </span>
                  <code style={{ fontSize: 11 }}>{initialData.id}</code>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div className="sf-modal-footer">
          <div>
            {connectedAccount && (
              <span className="status-pill status-success" style={{ fontSize: 11 }}>
                <span className="dot" style={{ width: 6, height: 6 }} />
                <span>Connected</span>
              </span>
            )}
          </div>
          <div className="sf-footer-actions">
            <Button variant="ghost" onClick={onClose} type="button">
              Cancel
            </Button>
            <Button variant="primary" onClick={handleSaveModal} type="button">
              Save Credential
            </Button>
          </div>
        </div>
      </div>
    </div>
  )

  if (typeof document === 'undefined') return modalContent
  return createPortal(modalContent, document.body)
}
