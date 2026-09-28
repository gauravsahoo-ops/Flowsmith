import React, { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { NodeIcon } from './NodeIcons'
import './DynamicsCrmOAuthModal.css'

export default function DynamicsCrmOAuthModal({
  isOpen,
  onClose,
  initialData = null,
  onConnected,
  onSave,
}) {
  const [tab, setTab] = useState('connection') // 'connection' | 'service_principal' | 'azure_guide'
  const [name, setName] = useState(initialData?.name || 'Microsoft Dynamics 365')
  const [instanceUrl, setInstanceUrl] = useState(
    initialData?.data?.instance_url || 'https://myorg.crm.dynamics.com'
  )
  const [tenantId, setTenantId] = useState(initialData?.data?.tenant_id || 'common')
  const [clientId, setClientId] = useState(initialData?.data?.client_id || '')
  const [clientSecret, setClientSecret] = useState(initialData?.data?.client_secret || '')
  const [showSecret, setShowSecret] = useState(false)
  const [showCustomApp, setShowCustomApp] = useState(false)
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [connectedUser, setConnectedUser] = useState(
    initialData?.data?.user || initialData?.data?.username || null
  )
  const [canonicalRedirectUrl, setCanonicalRedirectUrl] = useState('')

  // Derive OAuth Callback URL matching current backend host
  const fallbackRedirectUrl = typeof window !== 'undefined'
    ? `${window.location.protocol}//${window.location.hostname}${window.location.port === '5173' ? ':8000' : (window.location.port ? `:${window.location.port}` : '')}/api/auth/dynamics_crm/callback`
    : 'http://localhost:8000/api/auth/dynamics_crm/callback'
  const redirectUrl = canonicalRedirectUrl || fallbackRedirectUrl

  useEffect(() => {
    if (!isOpen) return
    import('../api').then(({ api }) => {
      api.getOAuthConfig('dynamics_crm')
        .then((res) => {
          const cfg = res?.data || res
          if (cfg) {
            if (cfg.redirect_uri) {
              setCanonicalRedirectUrl(cfg.redirect_uri)
            }
            if (cfg.configured && !initialData && cfg.client_id) {
              setClientId((prev) => prev || cfg.client_id)
            }
          }
        })
        .catch(() => {})
    })
  }, [isOpen, initialData])

  useEffect(() => {
    if (initialData) {
      setName(initialData.name || 'Microsoft Dynamics 365')
      setInstanceUrl(initialData.data?.instance_url || 'https://myorg.crm.dynamics.com')
      setTenantId(initialData.data?.tenant_id || 'common')
      setClientId(initialData.data?.client_id || '')
      setClientSecret(initialData.data?.client_secret || '')
      setConnectedUser(initialData.data?.user || initialData.data?.username || null)
    }
  }, [initialData])

  // Listen for OAuth callback popup completion
  useEffect(() => {
    function handleMessage(event) {
      if (!event.data || typeof event.data !== 'object') return
      if (event.data.provider === 'dynamics_crm' || event.data.type === 'oauth_callback') {
        if (event.data.ok || event.data.status === 'success') {
          setNotice('Microsoft Dynamics 365 account connected successfully!')
          setConnectedUser(event.data.user || event.data.username || 'Authorized User')
          if (onConnected) onConnected(event.data)
        } else if (event.data.error) {
          setError(event.data.error || 'OAuth authorization failed.')
        }
      }
    }
    window.addEventListener('message', handleMessage)
    return () => window.removeEventListener('message', handleMessage)
  }, [onConnected])

  const copyToClipboard = (text) => {
    if (navigator?.clipboard) {
      navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const handleOAuthConnect = async () => {
    setError(null)
    setNotice(null)
    setBusy(true)

    try {
      const { api } = await import('../api')
      const extra = {
        name: name.trim() || 'Microsoft Dynamics 365',
        tenant_id: tenantId.trim() || 'common',
      }
      if (clientId.trim()) {
        extra.client_id = clientId.trim()
      }
      if (clientSecret.trim()) {
        extra.client_secret = clientSecret.trim()
      }

      const res = await api.connectOAuth('dynamics_crm', instanceUrl.trim(), 'login', extra)
      const authorizeUrl = res?.data?.authorize_url || res?.authorize_url
      if (!authorizeUrl) {
        throw new Error('Server did not return an authorization URL.')
      }

      const width = 600
      const height = 700
      const left = window.screen.width / 2 - width / 2
      const top = window.screen.height / 2 - height / 2
      const popup = window.open(
        authorizeUrl,
        'dynamics_oauth_popup',
        `width=${width},height=${height},top=${top},left=${left},scrollbars=yes,status=1`
      )

      if (!popup || popup.closed || typeof popup.closed === 'undefined') {
        window.location.href = authorizeUrl
      }
    } catch (err) {
      setError(err?.message || 'Failed to initiate Microsoft Dynamics 365 OAuth authorization.')
    } finally {
      setBusy(false)
    }
  }

  const handleSaveServicePrincipal = async () => {
    setError(null)
    setNotice(null)

    if (!instanceUrl.trim()) {
      setError('Please provide your Dynamics 365 Org URL (e.g. https://org.crm.dynamics.com).')
      return
    }
    if (!clientId.trim() || !clientSecret.trim()) {
      setError('Please enter both Client ID and Client Secret for Service Principal authentication.')
      return
    }

    setBusy(true)
    try {
      if (onSave) {
        await onSave({
          name: name.trim() || 'Microsoft Dynamics 365 (S2S)',
          type: 'dynamics_crm',
          data: {
            auth_type: 'client_credentials',
            instance_url: instanceUrl.trim().replace(/\/+$/, ''),
            tenant_id: tenantId.trim() || 'common',
            client_id: clientId.trim(),
            client_secret: clientSecret.trim(),
          },
        })
        setNotice('Microsoft Dynamics 365 Service Principal credential saved successfully.')
      }
    } catch (err) {
      setError(err?.message || 'Failed to save Service Principal credential.')
    } finally {
      setBusy(false)
    }
  }

  if (!isOpen) return null

  const modalContent = (
    <div className="dynamics-modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div className="dynamics-modal-window" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="dynamics-modal-header">
          <div className="dynamics-modal-title-area">
            <div className="dynamics-modal-icon-badge">
              <NodeIcon type="dynamics_crm" size={20} />
            </div>
            <div>
              <h2>Connect Microsoft Dynamics 365</h2>
              <p>Microsoft Dataverse Web API v9.2 Integration</p>
            </div>
          </div>
          <button className="dynamics-modal-close-btn" onClick={onClose} aria-label="Close modal">
            ✕
          </button>
        </div>

        {/* Tabs */}
        <div className="dynamics-modal-tabs">
          <button
            className={`dynamics-modal-tab-btn ${tab === 'connection' ? 'active' : ''}`}
            onClick={() => setTab('connection')}
          >
            OAuth2 (1-Click)
          </button>
          <button
            className={`dynamics-modal-tab-btn ${tab === 'service_principal' ? 'active' : ''}`}
            onClick={() => setTab('service_principal')}
          >
            Service Principal (S2S)
          </button>
          <button
            className={`dynamics-modal-tab-btn ${tab === 'azure_guide' ? 'active' : ''}`}
            onClick={() => setTab('azure_guide')}
          >
            Azure App Setup
          </button>
        </div>

        {/* Body */}
        <div className="dynamics-modal-body">
          {error && <div className="dynamics-alert-error">{error}</div>}
          {notice && <div className="dynamics-alert-notice">{notice}</div>}

          {/* TAB 1: OAuth Connection */}
          {tab === 'connection' && (
            <>
              <div className="dynamics-form-group">
                <label>Credential Label</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Dynamics 365 Production"
                />
              </div>

              <div className="dynamics-form-group">
                <label>Dynamics 365 Organization URL</label>
                <input
                  type="text"
                  value={instanceUrl}
                  onChange={(e) => setInstanceUrl(e.target.value)}
                  placeholder="https://myorg.crm.dynamics.com"
                />
                <span className="dynamics-form-hint">
                  Your Dataverse web address (found in Power Apps or Dynamics 365 admin center).
                </span>
              </div>

              <div className="dynamics-form-group">
                <label>Directory (Tenant) ID (Optional)</label>
                <input
                  type="text"
                  value={tenantId}
                  onChange={(e) => setTenantId(e.target.value)}
                  placeholder="common or your Azure Tenant GUID"
                />
                <span className="dynamics-form-hint">
                  Defaults to 'common' for multi-tenant accounts. Specify your Azure AD Tenant ID for single-tenant apps.
                </span>
              </div>

              <div className="dynamics-form-group" style={{ marginBottom: 12 }}>
                <button
                  type="button"
                  style={{
                    background: 'none',
                    border: 'none',
                    color: '#38bdf8',
                    cursor: 'pointer',
                    fontSize: 12,
                    padding: 0,
                    textAlign: 'left',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                  }}
                  onClick={() => setShowCustomApp(!showCustomApp)}
                >
                  <span>{showCustomApp ? '▼' : '▶'}</span>
                  <span>{showCustomApp ? 'Hide Custom Azure App Credentials' : 'Specify Custom Azure App (Client ID & Secret)'}</span>
                </button>
              </div>

              {showCustomApp && (
                <>
                  <div className="dynamics-form-group">
                    <label>Application (Client) ID</label>
                    <input
                      type="text"
                      value={clientId}
                      onChange={(e) => setClientId(e.target.value)}
                      placeholder="Azure App Registration Client ID (GUID)"
                    />
                  </div>
                  <div className="dynamics-form-group">
                    <label>
                      Client Secret
                      <button
                        type="button"
                        style={{ background: 'none', border: 'none', color: '#38bdf8', cursor: 'pointer', fontSize: 11 }}
                        onClick={() => setShowSecret(!showSecret)}
                      >
                        {showSecret ? 'Hide' : 'Show'}
                      </button>
                    </label>
                    <input
                      type={showSecret ? 'text' : 'password'}
                      value={clientSecret}
                      onChange={(e) => setClientSecret(e.target.value)}
                      placeholder="Azure App Client Secret Value"
                    />
                    <span className="dynamics-form-hint">
                      Optional if DYNAMICS_CRM_CLIENT_ID & SECRET are configured on the server.
                    </span>
                  </div>
                </>
              )}

              <div className="dynamics-connect-card">
                <div className="dynamics-connect-header">
                  <h3>Interactive Authorization (PKCE)</h3>
                  {connectedUser && <span className="dynamics-connect-badge">Connected</span>}
                </div>
                <p style={{ margin: 0, fontSize: 13, color: '#94a3b8' }}>
                  {connectedUser
                    ? `Connected as ${connectedUser}. You can re-authorize or sign in with another account anytime.`
                    : 'Click below to securely sign in with Microsoft Entra ID. Flowsmith stores encrypted refresh tokens.'}
                </p>
                <button
                  type="button"
                  className="dynamics-connect-btn"
                  onClick={handleOAuthConnect}
                  disabled={busy}
                >
                  <NodeIcon type="dynamics_crm" size={16} />
                  {busy ? 'Opening Microsoft Login...' : connectedUser ? 'Reconnect Dynamics 365' : 'Sign in with Microsoft 365'}
                </button>
              </div>
            </>
          )}

          {/* TAB 2: Service Principal (S2S) */}
          {tab === 'service_principal' && (
            <>
              <div className="dynamics-form-group">
                <label>Credential Label</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Dynamics 365 Service Principal"
                />
              </div>

              <div className="dynamics-form-group">
                <label>Organization URL</label>
                <input
                  type="text"
                  value={instanceUrl}
                  onChange={(e) => setInstanceUrl(e.target.value)}
                  placeholder="https://myorg.crm.dynamics.com"
                />
              </div>

              <div className="dynamics-form-group">
                <label>Azure AD Tenant ID</label>
                <input
                  type="text"
                  value={tenantId}
                  onChange={(e) => setTenantId(e.target.value)}
                  placeholder="e.g. 00000000-0000-0000-0000-000000000000"
                />
              </div>

              <div className="dynamics-form-group">
                <label>Application (Client) ID</label>
                <input
                  type="text"
                  value={clientId}
                  onChange={(e) => setClientId(e.target.value)}
                  placeholder="Azure App Registration Client ID (GUID)"
                />
              </div>

              <div className="dynamics-form-group">
                <label>
                  Client Secret
                  <button
                    type="button"
                    style={{ background: 'none', border: 'none', color: '#38bdf8', cursor: 'pointer', fontSize: 11 }}
                    onClick={() => setShowSecret(!showSecret)}
                  >
                    {showSecret ? 'Hide' : 'Show'}
                  </button>
                </label>
                <input
                  type={showSecret ? 'text' : 'password'}
                  value={clientSecret}
                  onChange={(e) => setClientSecret(e.target.value)}
                  placeholder="Azure App Client Secret Value"
                />
                <span className="dynamics-form-hint">
                  Client Secrets are encrypted at rest with AES-128 Fernet and never sent back to the browser.
                </span>
              </div>
            </>
          )}

          {/* TAB 3: Azure Setup Guide */}
          {tab === 'azure_guide' && (
            <div className="dynamics-setup-steps">
              <div className="dynamics-setup-step">
                <div className="dynamics-step-number">1</div>
                <div>
                  <strong>Create an App Registration in Microsoft Entra</strong>
                  <p style={{ margin: '4px 0 0 0', color: '#94a3b8' }}>
                    Sign in to the Azure Portal (portal.azure.com) or Entra admin center. Navigate to <em>App registrations</em> and click <em>New registration</em>.
                  </p>
                </div>
              </div>

              <div className="dynamics-setup-step">
                <div className="dynamics-step-number">2</div>
                <div>
                  <strong>Set Redirect URI for OAuth2</strong>
                  <p style={{ margin: '4px 0 6px 0', color: '#94a3b8' }}>
                    Select platform <em>Web</em> and paste this exact Redirect URI:
                  </p>
                  <div className="dynamics-copy-box">
                    <input type="text" readOnly value={redirectUrl} />
                    <button type="button" className="dynamics-copy-btn" onClick={() => copyToClipboard(redirectUrl)}>
                      {copied ? 'Copied!' : 'Copy'}
                    </button>
                  </div>
                </div>
              </div>

              <div className="dynamics-setup-step">
                <div className="dynamics-step-number">3</div>
                <div>
                  <strong>Configure API Permissions</strong>
                  <p style={{ margin: '4px 0 0 0', color: '#94a3b8' }}>
                    Under <em>API permissions</em>, click <em>Add a permission</em>, choose <em>Dynamics CRM</em>, and select <code>user_impersonation</code> (Delegated). For background S2S daemons, add an Application User in Power Platform admin center.
                  </p>
                </div>
              </div>

              <div className="dynamics-setup-step">
                <div className="dynamics-step-number">4</div>
                <div>
                  <strong>Create Client Secret</strong>
                  <p style={{ margin: '4px 0 0 0', color: '#94a3b8' }}>
                    Under <em>Certificates & secrets</em>, click <em>New client secret</em>. Copy the Secret Value immediately and enter it into Flowsmith.
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="dynamics-modal-footer">
          <button type="button" className="dynamics-btn-secondary" onClick={onClose}>
            Cancel
          </button>
          {tab === 'service_principal' && (
            <button
              type="button"
              className="dynamics-connect-btn"
              onClick={handleSaveServicePrincipal}
              disabled={busy}
            >
              {busy ? 'Saving...' : 'Save Service Principal'}
            </button>
          )}
        </div>
      </div>
    </div>
  )

  if (typeof document === 'undefined') return modalContent
  return createPortal(modalContent, document.body)
}
