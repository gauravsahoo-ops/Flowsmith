import { useEffect, useState } from 'react'
import { api, getToken, setToken } from '../api'

// Login / Register / Forgot-password / Reset-password (Phase 42).
// The backend's reset email links to /reset-password?token=... — the SPA
// fallback serves this screen, which detects the path + token and jumps
// straight into the reset form.

export default function Login({ onAuthed }) {
  const [mode, setMode] = useState('login') // login | register | forgot | reset
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [resetToken, setResetToken] = useState('')
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [busy, setBusy] = useState(false)

  // Detect reset links: /reset-password?token=...
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
  }, [])

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

  if (getToken()) return null

  const title = { login: 'Log in', register: 'Create account', forgot: 'Reset password', reset: 'Set new password' }[mode]

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={submit}>
        <h1>⚡ Flowsmith</h1>
        <p className="hint">Visual workflow automation</p>

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
    </div>
  )
}
