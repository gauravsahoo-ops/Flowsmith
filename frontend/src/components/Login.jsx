import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, setToken } from '../api'
import { useBrandingStore } from '../stores/brandingStore'
import FlowsmithBrandMark from './FlowsmithBrandMark'
import {
  passkeysSupported,
  prepareRequestOptions,
  serializeCredential,
} from '../utils/webauthn'

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
  const navigate = useNavigate()
  const [mode, setMode] = useState('login') // login | register | forgot | reset
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [resetToken, setResetToken] = useState('')
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [busy, setBusy] = useState(false)
  const [ssoProviders, setSsoProviders] = useState([])
  const [mfaChallenge, setMfaChallenge] = useState(null)
  const [mfaEnrollment, setMfaEnrollment] = useState(null)
  const [mfaRecovery, setMfaRecovery] = useState(null)
  const [webauthnChallenge, setWebauthnChallenge] = useState(null)
  const [passkeyLogin, setPasskeyLogin] = useState(null)
  const [passkeyLoginBusy, setPasskeyLoginBusy] = useState(false)
  const [mfaCode, setMfaCode] = useState('')

  // Detect reset links: /reset-password?token=...
  // Detect SSO callback: /#sso_token=... (fragment: never in logs/Referer)
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
    const ssoToken = new URLSearchParams(window.location.hash.replace(/^#/, '')).get('sso_token')
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

  function finishAuth(result) {
    setToken(result.token)
    if (result.user) {
      try {
        localStorage.setItem('flowsmith_user', JSON.stringify(result.user))
        window.dispatchEvent(new Event('flowsmith_user_updated'))
      } catch (err) { console.error('[flowsmith] components/Login.jsx', err) }
    }
    onAuthed(result)
    // Reset links keep the browser on /reset-password; move cleanly into the
    // workspace after any successful auth instead of leaving a stale URL.
    navigate('/overview', { replace: true })
  }

  function cancelMfa() {
    setMfaChallenge(null)
    setMfaEnrollment(null)
    setMfaRecovery(null)
    setWebauthnChallenge(null)
    setMfaCode('')
    setPassword('')
    setMode('login')
    setError(null)
    setNotice(null)
  }

  async function handlePasskey() {
    if (!webauthnChallenge) return
    if (!passkeysSupported()) {
      setError('This browser does not support passkeys.')
      return
    }
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const assertion = await navigator.credentials.get({
        publicKey: prepareRequestOptions(webauthnChallenge.options),
      })
      const result = await api.webauthnAuthenticateComplete(
        webauthnChallenge.token,
        serializeCredential(assertion)
      )
      finishAuth(result)
    } catch (err) {
      if (err?.name === 'NotAllowedError' || err?.name === 'AbortError') {
        setError('Passkey request was cancelled or timed out. Try again.')
      } else {
        setError(err.message || 'Passkey authentication failed.')
      }
    } finally {
      setBusy(false)
    }
  }

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      if (mfaRecovery) {
        finishAuth(mfaRecovery.result)
        return
      }
      if (mfaEnrollment) {
        const result = await api.completeMfaEnrollment(mfaEnrollment.token, mfaCode)
        if (Array.isArray(result.recovery_codes) && result.recovery_codes.length) {
          setMfaRecovery({ result, codes: result.recovery_codes })
          setMfaCode('')
          return
        }
        finishAuth(result)
        return
      }
      if (webauthnChallenge && !mfaChallenge) {
        await handlePasskey()
        return
      }
      if (mfaChallenge) {
        const result = await api.verifyMfa(mfaChallenge, mfaCode)
        finishAuth(result)
        return
      }
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
      if (result.mfa_required || result.webauthn_required) {
        setMfaChallenge(result.mfa_required ? result.challenge_token : null)
        setWebauthnChallenge(result.webauthn_required ? {
          token: result.webauthn_token,
          options: result.webauthn_options,
        } : null)
        setMfaCode('')
        setNotice(
          result.webauthn_required
            ? 'Use your passkey to continue.'
            : 'Enter the 6-digit code from your authenticator app, or a recovery code.'
        )
        return
      }
      if (result.mfa_enrollment_required) {
        const setup = await api.startMfaEnrollment(result.enrollment_token)
        setMfaEnrollment({ token: result.enrollment_token, ...setup })
        setMfaCode('')
        setNotice('Your organization requires MFA. Add Flowsmith to your authenticator app to continue.')
        return
      }
      finishAuth(result)
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
  const mfaFlow = Boolean(mfaChallenge || mfaEnrollment || mfaRecovery || webauthnChallenge)

  useEffect(() => {
    useBrandingStore.getState().init().catch(() => {})
  }, [])

  useEffect(() => {
    if (mode !== 'login' || mfaFlow || !passkeysSupported()) {
      setPasskeyLogin(null)
      return undefined
    }
    let cancelled = false
    const controller = new AbortController()
    ;(async () => {
      try {
        let conditional = false
        try {
          conditional = Boolean(
            await window.PublicKeyCredential.isConditionalMediationAvailable?.()
          )
        } catch {
          conditional = false
        }
        if (cancelled || !conditional) return
        const data = await api.webauthnConditionalOptions()
        if (cancelled) return
        setPasskeyLogin(data)
        const assertion = await navigator.credentials.get({
          publicKey: prepareRequestOptions(data.options),
          mediation: 'conditional',
          signal: controller.signal,
        })
        if (!assertion || cancelled) return
        const result = await api.webauthnConditionalComplete(
          data.webauthn_token,
          serializeCredential(assertion)
        )
        finishAuth(result)
      } catch (err) {
        if (!cancelled && !['AbortError', 'NotAllowedError'].includes(err?.name)) {
          console.debug('[flowsmith] conditional passkey unavailable', err)
        }
      }
    })()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [mode, mfaFlow]) // eslint-disable-line react-hooks/exhaustive-deps

  async function handlePasskeyLogin() {
    if (!passkeyLogin) return
    setPasskeyLoginBusy(true)
    setError(null)
    try {
      const assertion = await navigator.credentials.get({
        publicKey: prepareRequestOptions(passkeyLogin.options),
      })
      const result = await api.webauthnConditionalComplete(
        passkeyLogin.webauthn_token,
        serializeCredential(assertion)
      )
      finishAuth(result)
    } catch (err) {
      if (err?.name === 'NotAllowedError' || err?.name === 'AbortError') {
        setError('Passkey sign-in was cancelled or timed out.')
      } else {
        setError(err.message || 'Passkey sign-in failed.')
      }
    } finally {
      setPasskeyLoginBusy(false)
    }
  }

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
          <div className="login-hero-brand">
            <span className="login-hero-brand-mark">
              {logoSrc ? (
                <img src={logoSrc} alt={appName} />
              ) : (
                <FlowsmithBrandMark size={22} variant="glyph" style={{ color: '#fff' }} />
              )}
            </span>
            <span className="login-hero-brand-copy">
              <strong>{appName}</strong>
              <small>Enterprise Automation Cloud</small>
            </span>
            <span className="login-hero-brand-chip">
              <span className="dot" />
              Self-hosted
            </span>
          </div>

          <h1 className="hero-heading">
            Automation with <span className="gradient-text">engineering discipline.</span>
          </h1>

          <p className="hero-subheading">
            Design, run, and observe workflows across APIs, databases, AI agents, and human approvals from one precise workspace.
          </p>

          {/* Interactive Visual Flow Diagram Preview */}
          <div className="hero-flow-card">
            <div className="flow-card-header">
              <div className="flow-card-header-left">
                <div className="flow-card-dots">
                  <span className="dot dot-red" />
                  <span className="dot dot-yellow" />
                  <span className="dot dot-green" />
                </div>
                <span className="flow-card-title">Workflow preview</span>
              </div>
              <div className="flow-card-header-right">
                <span className="flow-status-pill">
                  <span className="flow-status-beacon" />
                  Example run
                </span>
              </div>
            </div>

            <div className="flow-canvas-grid">
              <div className="flow-nodes-track">
                {/* Node 1: Webhook Trigger */}
                <div className="flow-node node-trigger">
                  <div className="node-card-top">
                    <span className="node-type-tag">TRIGGER</span>
                    <span className="node-badge-status status-ok">200 OK</span>
                  </div>
                  <div className="node-body">
                    <div className="node-icon">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                        <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                      </svg>
                    </div>
                    <div className="node-info">
                      <span className="node-name">Webhook</span>
                      <span className="node-sub">POST /v1/ingest</span>
                    </div>
                  </div>
                  <span className="node-handle handle-out" aria-hidden="true" />
                </div>

                <div className="flow-connector">
                  <span className="connector-wire" />
                  <span className="connector-pulse" />
                </div>

                {/* Node 2: Salesforce Sync */}
                <div className="flow-node node-salesforce">
                  <span className="node-handle handle-in" aria-hidden="true" />
                  <div className="node-card-top">
                    <span className="node-type-tag">CONNECTOR</span>
                    <span className="node-badge-status status-sync">Streamed</span>
                  </div>
                  <div className="node-body">
                    <div className="node-icon">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z" />
                      </svg>
                    </div>
                    <div className="node-info">
                      <span className="node-name">Salesforce</span>
                      <span className="node-sub">Sync Record</span>
                    </div>
                  </div>
                  <span className="node-handle handle-out" aria-hidden="true" />
                </div>

                <div className="flow-connector">
                  <span className="connector-wire" />
                  <span className="connector-pulse" style={{ animationDelay: '0.9s' }} />
                </div>

                {/* Node 3: AI Agent */}
                <div className="flow-node node-ai">
                  <span className="node-handle handle-in" aria-hidden="true" />
                  <div className="node-card-top">
                    <span className="node-type-tag">AI RUNTIME</span>
                    <span className="node-badge-status status-ai">Complete</span>
                  </div>
                  <div className="node-body">
                    <div className="node-icon">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
                      </svg>
                    </div>
                    <div className="node-info">
                      <span className="node-name">AI Agent</span>
                      <span className="node-sub">Enrich Data</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

          </div>

          <div className="hero-features-list">
            <div className="feature-chip">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
              <span>Visual DAG builder</span>
            </div>
            <div className="feature-chip">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
              <span>Native connectors</span>
            </div>
            <div className="feature-chip">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
              <span>AI agents</span>
            </div>
            <div className="feature-chip">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
              <span>Human approvals</span>
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
            {!mfaFlow && (mode === 'login' || mode === 'register') && (
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

            {(mode === 'forgot' || mode === 'reset') && !mfaFlow && (
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

            {mfaChallenge && (
              <div className="login-subheading-box">
                <h3 className="login-subheading-title">Two-factor authentication</h3>
                <p className="login-subheading-desc">
                  {webauthnChallenge
                    ? <>Use your passkey or enter the code for <strong>{email}</strong>.</>
                    : <>Enter the current 6-digit code or a recovery code for <strong>{email}</strong>.</>}
                </p>
              </div>
            )}

            {webauthnChallenge && !mfaChallenge && (
              <div className="login-subheading-box">
                <h3 className="login-subheading-title">Passkey required</h3>
                <p className="login-subheading-desc">
                  Use the passkey registered for <strong>{email}</strong> to finish signing in.
                </p>
              </div>
            )}

            {mfaEnrollment && (
              <div className="login-subheading-box">
                <h3 className="login-subheading-title">Two-factor authentication required</h3>
                <p className="login-subheading-desc">
                  Your organization requires MFA. Add the secret below to your authenticator app, then enter a code to finish signing in.
                </p>
              </div>
            )}

            {mfaRecovery && (
              <div className="login-subheading-box">
                <h3 className="login-subheading-title">Save your recovery codes</h3>
                <p className="login-subheading-desc">
                  MFA is now enabled for <strong>{email}</strong>. Each recovery code works once if you lose your authenticator.
                </p>
              </div>
            )}

            {/* SSO Providers */}
            {!mfaFlow && ssoProviders.length > 0 && (mode === 'login' || mode === 'register') && (
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

            {passkeyLogin && !mfaFlow && mode === 'login' && (
              <button
                type="button"
                className="sso-btn"
                onClick={handlePasskeyLogin}
                disabled={passkeyLoginBusy || busy}
                style={{ marginBottom: 12 }}
              >
                <span className="sso-icon">{SSO_ICONS.shield}</span>
                <span>{passkeyLoginBusy ? 'Waiting for passkey…' : 'Sign in with a passkey'}</span>
              </button>
            )}

            {/* Form Fields */}
            {mfaFlow ? (
              mfaRecovery ? (
                <div className="login-fields-group">
                  <pre style={{ margin: 0, padding: '12px 14px', borderRadius: 10, background: 'rgba(2, 6, 23, 0.72)', border: '1px solid rgba(245, 158, 11, 0.35)', color: '#e2e8f0', fontSize: 12.5, lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>
                    {mfaRecovery.codes.join('\n')}
                  </pre>
                  <button
                    type="button"
                    className="ghost small"
                    style={{ alignSelf: 'flex-start' }}
                    onClick={async () => {
                      try {
                        await navigator.clipboard.writeText(mfaRecovery.codes.join('\n'))
                        setNotice('Recovery codes copied to clipboard.')
                      } catch (err) {
                        setError(`Could not copy recovery codes: ${err.message}`)
                      }
                    }}
                  >
                    Copy Recovery Codes
                  </button>
                </div>
              ) : (
                <div className="login-fields-group">
                  {mfaEnrollment && (
                    <>
                      <div className="hint" style={{ fontSize: 12.5, lineHeight: 1.55 }}>
                        Enter this secret in your authenticator app:
                      </div>
                      <code style={{ padding: '9px 11px', borderRadius: 8, background: 'rgba(2, 6, 23, 0.7)', border: '1px solid rgba(99, 102, 241, 0.25)', color: '#c7d2fe', letterSpacing: 1.1, wordBreak: 'break-all' }}>
                        {mfaEnrollment.secret}
                      </code>
                      <div className="hint" style={{ fontSize: 11, wordBreak: 'break-all' }}>
                        {mfaEnrollment.otpauth_uri}
                      </div>
                    </>
                  )}
                  {webauthnChallenge && (
                    <button
                      type="button"
                      className="secondary small"
                      onClick={handlePasskey}
                      disabled={busy || !passkeysSupported()}
                    >
                      Use passkey
                    </button>
                  )}
                  {(mfaChallenge || mfaEnrollment) && (
                    <label className="input-field-label">
                      <span className="label-text">{mfaEnrollment ? 'Authenticator code' : 'Authenticator or recovery code'}</span>
                      <div className="input-with-icon">
                        <svg className="input-prefix-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <rect width="18" height="11" x="3" y="11" rx="2" ry="2" />
                          <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                        </svg>
                        <input
                          type="text"
                          className="styled-input"
                          value={mfaCode}
                          onChange={(e) => setMfaCode(
                            mfaEnrollment
                              ? e.target.value.replace(/[^0-9]/g, '').slice(0, 6)
                              : e.target.value.slice(0, 32)
                          )}
                          required
                          placeholder={mfaEnrollment ? '000000' : '000000 or XXXX-XXXX-XXXX-XXXX'}
                          autoComplete="one-time-code"
                          maxLength={mfaEnrollment ? 6 : 32}
                          autoFocus
                          aria-label={mfaEnrollment ? 'Six-digit authenticator code' : 'Authenticator or recovery code'}
                        />
                      </div>
                    </label>
                  )}
                </div>
              )
            ) : (
            <div className="login-fields-group">
              {mode !== 'reset' && (
                <label className="input-field-label">
                  <span className="label-text">{mode === 'login' ? 'Email or username' : 'Email address'}</span>
                  <div className="input-with-icon">
                    <svg className="input-prefix-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <rect width="20" height="16" x="2" y="4" rx="2" />
                      <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
                    </svg>
                    <input
                      type={mode === 'login' ? 'text' : 'email'}
                      className="styled-input"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      required
                      placeholder={mode === 'login' ? 'name@company.com or username' : 'name@company.com'}
                      autoComplete={mode === 'login' ? 'username' : 'email'}
                      autoFocus
                    />
                  </div>
                </label>
              )}

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
                        Forgot password?
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
                      className="styled-input has-toggle"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      required
                      placeholder="••••••••••••"
                      minLength={mode === 'login' ? 1 : 8}
                      autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                      autoFocus={mode === 'reset'}
                    />
                    <button
                      type="button"
                      className="password-toggle-btn"
                      onClick={() => setShowPassword(!showPassword)}
                      aria-label={showPassword ? 'Hide password' : 'Show password'}
                      aria-pressed={showPassword}
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
            )}

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
                    {mfaRecovery
                      ? 'Continue to Workspace'
                      : mfaEnrollment
                      ? 'Enable MFA & Sign In'
                      : webauthnChallenge && !mfaChallenge
                      ? 'Use Passkey'
                      : mfaChallenge
                      ? 'Verify & Sign In'
                      : mode === 'login'
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

            {(mode !== 'login' || mfaFlow) && (
              <button
                type="button"
                className="login-back-btn"
                onClick={() => {
                  if (mfaFlow) {
                    cancelMfa()
                    return
                  }
                  setMode('login')
                  setError(null)
                  setNotice(null)
                }}
              >
                ← Back to sign in
              </button>
            )}

            <div className="login-trust-row" aria-label="Security features">
              <span>256-bit encryption</span>
              <span>SSO + MFA</span>
              <span>Passkeys</span>
            </div>

            {/* Footer Credit */}
            <div className="login-card-footer">
              <span className="footer-credit">
                {appName} · Secure workspace
              </span>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}
