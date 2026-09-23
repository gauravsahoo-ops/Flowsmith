import { useEffect, useState } from 'react'
import { api, setToken } from '../api'
import { useBrandingStore } from '../stores/brandingStore'
import FlowsmithBrandMark from './FlowsmithBrandMark'

// Login / Register / Forgot-password / Reset-password / SSO (Phase 42 + SSO EE).
// Premium Enterprise Grade Auth UI with interactive workflow showcase.

const SSO_ICONS = {
  google: (
    <svg width="18" height="18" viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#34A853" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#FBBC05" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>
  ),
  github: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/></svg>
  ),
  shield: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
  ),
}

export default function Login({ onAuthed }) {
  const [mode, setMode] = useState('login') // login | register | forgot | reset
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [resetToken, setResetToken] = useState('')
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [busy, setBusy] = useState(false)
  const [ssoProviders, setSsoProviders] = useState([])

  // Detect reset links: /reset-password?token=...
  // Detect SSO callback: /?sso_token=...
  useEffect(() => {
    if (window.location.pathname === '/reset-password') {
      const params = new URLSearchParams(window.location.search)
      const t = params.get('token')
      if (t) {
        setResetToken(t)
        setMode('reset')
        window.history.replaceState({}, '', window.location.pathname)
      }
    }
    const params = new URLSearchParams(window.location.search)
    const ssoToken = params.get('sso_token')
    if (ssoToken) {
      setToken(ssoToken)
      window.history.replaceState({}, '', '/')
      onAuthed({ token: ssoToken })
      return
    }
    api.getSsoProviders().then(providers => {
      if (Array.isArray(providers)) setSsoProviders(providers)
    }).catch(() => {})
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      if (mode === 'forgot') {
        const data = await api.forgotPassword(email)
        if (data.dev_reset_link) {
          const t = data.dev_reset_link.split('token=')[1]
          setResetToken(t)
          setMode('reset')
          setNotice('SMTP is not configured — use the link below (dev mode).')
        } else {
          setNotice('If that account exists, a reset link has been emailed.')
        }
        return
      }
      if (mode === 'reset') {
        await api.resetPassword(resetToken, password)
        setNotice('Password updated. Log in with your new password.')
        setMode('login')
        return
      }
      const result =
        mode === 'login'
          ? await api.login(email, password)
          : await api.register(email, password)
      setToken(result.token)
      onAuthed(result)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const appName = useBrandingStore((s) => s.appName) || 'Flowsmith'
  const tagline = useBrandingStore((s) => s.tagline) || 'Next-Gen Workflow Automation'
  const logoUrl = useBrandingStore((s) => s.logoUrl)
  const logoData = useBrandingStore((s) => s.logoData)
  const logoSrc = logoData || logoUrl

  useEffect(() => {
    useBrandingStore.getState().init().catch(() => {})
  }, [])

  function handleSsoLogin(providerId) {
    window.location.href = `/api/auth/sso/${providerId}/login`
  }

  return (
    <div className="login-screen">
      {/* Background Ambient Glow Orbs */}
      <div className="login-ambient-orb orb-1" aria-hidden="true" />
      <div className="login-ambient-orb orb-2" aria-hidden="true" />
      <div className="login-ambient-orb orb-3" aria-hidden="true" />

      <div className="login-container">
        {/* Left Side: Enterprise Feature Showcase */}
        <div className="login-hero">
          <div className="login-badge">
            <span className="badge-pulse-dot" />
            <span>FLOWSMITH PLATFORM</span>
            <span className="badge-pill">v2.4 Live</span>
          </div>

          <h1 className="hero-heading">
            Automate at the <span className="gradient-text">speed of thought.</span>
          </h1>

          <p className="hero-subheading">
            The next-generation visual workflow engine connecting Salesforce, enterprise databases, AI models, and real-time APIs in milliseconds.
          </p>

          {/* Interactive Visual Flow Diagram Preview */}
          <div className="hero-flow-card">
            <div className="flow-card-header">
              <div className="flow-card-dots">
                <span className="dot dot-red" />
                <span className="dot dot-yellow" />
                <span className="dot dot-green" />
              </div>
              <span className="flow-card-title">Live Pipeline • sync-crm-contacts</span>
              <span className="flow-status-pill">Active</span>
            </div>

            <div className="flow-nodes-track">
              <div className="flow-node node-trigger">
                <div className="node-icon">⚡</div>
                <div className="node-info">
                  <span className="node-name">Webhook</span>
                  <span className="node-sub">Trigger</span>
                </div>
              </div>

              <div className="flow-connector">
                <span className="connector-line" />
                <span className="connector-pulse" />
              </div>

              <div className="flow-node node-salesforce">
                <div className="node-icon">☁️</div>
                <div className="node-info">
                  <span className="node-name">Salesforce</span>
                  <span className="node-sub">Sync Record</span>
                </div>
              </div>

              <div className="flow-connector">
                <span className="connector-line" />
                <span className="connector-pulse" style={{ animationDelay: '0.8s' }} />
              </div>

              <div className="flow-node node-ai">
                <div className="node-icon">🤖</div>
                <div className="node-info">
                  <span className="node-name">AI Agent</span>
                  <span className="node-sub">Enrich Data</span>
                </div>
              </div>
            </div>

            <div className="flow-metrics-bar">
              <div className="metric-item">
                <span className="metric-label">Execution Time</span>
                <span className="metric-val text-green">14ms</span>
              </div>
              <div className="metric-divider" />
              <div className="metric-item">
                <span className="metric-label">Security</span>
                <span className="metric-val text-blue">AES-128 Fernet</span>
              </div>
              <div className="metric-divider" />
              <div className="metric-item">
                <span className="metric-label">Engine</span>
                <span className="metric-val text-purple">Async SSE</span>
              </div>
            </div>
          </div>

          <div className="hero-features-list">
            <div className="feature-chip">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
              <span>100+ Visual Connectors</span>
            </div>
            <div className="feature-chip">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
              <span>Self-Healing Graph Execution</span>
            </div>
            <div className="feature-chip">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
              <span>Zero-Config OAuth Engine</span>
            </div>
          </div>
        </div>

        {/* Right Side: Sleek Glassmorphic Login Card */}
        <div className="login-card-container">
          <form className="login-card" onSubmit={submit}>
            {/* Header / Brand */}
            <div className="login-card-header">
              <div
                className="login-logo-badge"
                style={logoSrc ? { background: 'transparent', boxShadow: 'none', padding: 2 } : undefined}
              >
                {logoSrc ? (
                  <img src={logoSrc} alt={appName} className="login-logo-img" />
                ) : (
                  <FlowsmithBrandMark size={28} variant="glyph" style={{ color: '#fff' }} />
                )}
              </div>
              <h2 className="login-brand-title">{appName}</h2>
              <p className="login-brand-tagline">{tagline}</p>
            </div>

            {/* Segmented Tab Switch */}
            {(mode === 'login' || mode === 'register') && (
              <div className="login-tabs-segmented" role="tablist">
                <button
                  type="button"
                  role="tab"
                  aria-selected={mode === 'login'}
                  className={`segmented-tab ${mode === 'login' ? 'active' : ''}`}
                  onClick={() => { setMode('login'); setError(null); setNotice(null); }}
                >
                  Log in
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={mode === 'register'}
                  className={`segmented-tab ${mode === 'register' ? 'active' : ''}`}
                  onClick={() => { setMode('register'); setError(null); setNotice(null); }}
                >
                  Sign up
                </button>
              </div>
            )}

            {(mode === 'forgot' || mode === 'reset') && (
              <div className="login-subheading-box">
                <h3 className="login-subheading-title">
                  {mode === 'forgot' ? 'Reset your password' : 'Create new password'}
                </h3>
                <p className="login-subheading-desc">
                  {mode === 'forgot'
                    ? 'Enter your email address to receive password reset instructions.'
                    : 'Choose a strong password with at least 8 characters.'}
                </p>
              </div>
            )}

            {/* SSO Providers */}
            {ssoProviders.length > 0 && (mode === 'login' || mode === 'register') && (
              <>
                <div className="sso-providers">
                  {ssoProviders.map(p => (
                    <button
                      key={p.id}
                      type="button"
                      className="sso-btn"
                      onClick={() => handleSsoLogin(p.id)}
                    >
                      <span className="sso-icon">{SSO_ICONS[p.icon] || SSO_ICONS.shield}</span>
                      <span>Continue with {p.name}</span>
                    </button>
                  ))}
                </div>
                <div className="sso-divider">
                  <span>or continue with email</span>
                </div>
              </>
            )}

            {/* Form Fields */}
            <div className="login-fields-group">
              <label className="input-field-label">
                <span className="label-text">Email address</span>
                <div className="input-with-icon">
                  <svg className="input-prefix-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <rect width="20" height="16" x="2" y="4" rx="2" />
                    <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
                  </svg>
                  <input
                    type="email"
                    className="styled-input"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required={mode !== 'reset'}
                    placeholder="name@company.com"
                    autoComplete="email"
                    autoFocus
                  />
                </div>
              </label>

              {mode !== 'forgot' && (
                <label className="input-field-label">
                  <div className="label-row">
                    <span className="label-text">{mode === 'reset' ? 'New password' : 'Password'}</span>
                    {mode === 'login' && (
                      <button
                        type="button"
                        className="forgot-link"
                        onClick={() => { setMode('forgot'); setError(null); setNotice(null); }}
                      >
                        Forgot?
                      </button>
                    )}
                  </div>
                  <div className="input-with-icon">
                    <svg className="input-prefix-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <rect width="18" height="11" x="3" y="11" rx="2" ry="2" />
                      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                    </svg>
                    <input
                      type={showPassword ? 'text' : 'password'}
                      className="styled-input"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      required
                      placeholder="••••••••••••"
                      minLength={mode === 'login' ? 1 : 8}
                      autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                    />
                    <button
                      type="button"
                      className="password-toggle-btn"
                      onClick={() => setShowPassword(!showPassword)}
                      tabIndex="-1"
                      aria-label={showPassword ? 'Hide password' : 'Show password'}
                    >
                      {showPassword ? (
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"/><path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"/><path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"/><line x1="2" x2="22" y1="2" y2="22"/></svg>
                      ) : (
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>
                      )}
                    </button>
                  </div>
                </label>
              )}
            </div>

            {error && (
              <div className="login-alert-banner alert-error" role="alert">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/></svg>
                <span>{error}</span>
              </div>
            )}

            {notice && (
              <div className="login-alert-banner alert-notice" role="alert">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
                <span>{notice}</span>
              </div>
            )}

            {/* Primary Submit Button */}
            <button type="submit" className="login-submit-btn" disabled={busy}>
              {busy ? (
                <span className="btn-spinner-content">
                  <span className="btn-spinner" />
                  <span>Processing…</span>
                </span>
              ) : (
                <span className="btn-label-content">
                  <span>
                    {mode === 'login'
                      ? 'Sign In to Workspace'
                      : mode === 'register'
                        ? 'Create Account'
                        : mode === 'forgot'
                          ? 'Send Password Reset Link'
                          : 'Update Password & Login'}
                  </span>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>
                </span>
              )}
            </button>

            {mode !== 'login' && (
              <button
                type="button"
                className="login-back-btn"
                onClick={() => { setMode('login'); setError(null); setNotice(null); }}
              >
                ← Back to sign in
              </button>
            )}

            {/* Footer Credit Pill */}
            <div className="login-card-footer">
              <span className="footer-credit">
                Designed & Engineered with precision by <strong className="credit-name">Gaurav</strong>
              </span>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}
