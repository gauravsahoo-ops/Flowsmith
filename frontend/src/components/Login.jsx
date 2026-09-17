import { useEffect, useState } from 'react'
import { api, getToken, setToken } from '../api'
import { useBrandingStore } from '../stores/brandingStore'

// Login / Register / Forgot-password / Reset-password / SSO (Phase 42 + SSO EE).
// The backend's reset email links to /reset-password?token=... — the SPA
// fallback serves this screen, which detects the path + token and jumps
// straight into the reset form.

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
    // Handle SSO callback token
    const params = new URLSearchParams(window.location.search)
    const ssoToken = params.get('sso_token')
    if (ssoToken) {
      setToken(ssoToken)
      window.history.replaceState({}, '', '/')
      onAuthed({ token: ssoToken })
      return
    }
    // Load SSO providers
    api.getSsoProviders().then(providers => {
      if (Array.isArray(providers)) setSsoProviders(providers)
    }).catch(() => { /* SSO not configured, ignore */ })
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
  const tagline = useBrandingStore((s) => s.tagline) || 'Visual workflow automation'
  const logoUrl = useBrandingStore((s) => s.logoUrl)
  const logoData = useBrandingStore((s) => s.logoData)
  const logoSrc = logoData || logoUrl

  useEffect(() => {
    useBrandingStore.getState().init().catch(() => {})
  }, [])

  function handleSsoLogin(providerId) {
    // Redirect to backend SSO login endpoint
    window.location.href = `/api/auth/sso/${providerId}/login`
  }

  if (getToken()) return null

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={submit}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10, marginBottom: 16 }}>
          <div style={{
            width: 48,
            height: 48,
            borderRadius: 12,
            background: logoSrc ? 'transparent' : 'var(--brand-gradient, linear-gradient(135deg, #6366f1 0%, #3b82f6 100%))',
            boxShadow: logoSrc ? 'none' : 'var(--brand-shadow, 0 4px 14px rgba(99, 102, 241, 0.4))',
            display: 'grid',
            placeItems: 'center',
            overflow: 'hidden',
          }}>
            {logoSrc ? (
              <img src={logoSrc} alt={appName} style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
            ) : (
              <span style={{ fontSize: 24 }}>⚡</span>
            )}
          </div>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, letterSpacing: '-0.02em' }}>{appName}</h1>
          <p className="hint" style={{ margin: 0 }}>{tagline}</p>
        </div>

        {(mode === 'login' || mode === 'register') && (
          <div className="tabs">
            <button
              type="button"
              className={mode === 'login' ? 'tab active' : 'tab'}
              onClick={() => setMode('login')}
            >
              Log in
            </button>
            <button
              type="button"
              className={mode === 'register' ? 'tab active' : 'tab'}
              onClick={() => setMode('register')}
            >
              Sign up
            </button>
          </div>
        )}
        {(mode === 'forgot' || mode === 'reset') && (
          <h2 style={{ margin: '4px 0', fontSize: 16 }}>
            {mode === 'forgot' ? 'Forgot password' : 'Choose a new password'}
          </h2>
        )}

        {/* SSO Buttons */}
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
              <span>or</span>
            </div>
          </>
        )}

        <label>
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required={mode !== 'reset'}
            autoFocus
          />
        </label>

        {mode !== 'forgot' && (
          <label>
            {mode === 'reset' ? 'New password' : 'Password'}
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={mode === 'login' ? 1 : 8}
            />
          </label>
        )}

        {error && <div className="form-error">{error}</div>}
        {notice && <div className="banner ok">{notice}</div>}

        <button type="submit" className="primary" disabled={busy}>
          {busy
            ? '...'
            : mode === 'login'
              ? 'Log in'
              : mode === 'register'
                ? 'Create account'
                : mode === 'forgot'
                  ? 'Email me a reset link'
                  : 'Save new password'}
        </button>

        {mode === 'login' && (
          <button type="button" className="ghost linklike" onClick={() => { setMode('forgot'); setError(null); setNotice(null) }}>
            Forgot password?
          </button>
        )}
        {mode !== 'login' && (
          <button
            type="button"
            className="ghost linklike"
            onClick={() => { setMode('login'); setError(null); setNotice(null) }}
          >
            ← Back to log in
          </button>
        )}
      </form>
      <p className="hint" style={{ marginTop: 12, fontSize: 12, textAlign: 'center' }}>
        Developed by Gaurav
      </p>
    </div>
  )
}
