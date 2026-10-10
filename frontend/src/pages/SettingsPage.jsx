import { useEffect, useState } from 'react'
import { api, getToken } from '../api'
import { useBrandingStore } from '../stores/brandingStore'
import PageHeader from '../components/shared/PageHeader'
import LoadingSkeleton from '../components/shared/LoadingSkeleton'
import FlowsmithBrandMark from '../components/FlowsmithBrandMark'
import { useUiStore } from '../stores/uiStore'
import { playChime } from '../utils/soundEffects'

function Section({ title, description, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className="settings-section">
      <button className="settings-section-head" onClick={() => setOpen(v => !v)} aria-expanded={open}>
        <span style={{ fontSize: 13, color: '#818cf8', transition: 'transform 0.2s', display: 'inline-block', transform: open ? 'rotate(90deg)' : 'none' }}>
          ▶
        </span>
        <span className="settings-section-title">{title}</span>
      </button>
      {description && <p className="hint" style={{ margin: '4px 0 0 20px', fontSize: 12.5, lineHeight: 1.5 }}>{description}</p>}
      {open && <div className="settings-section-body">{children}</div>}
    </section>
  )
}

const BRAND_COLOR_PRESETS = [
  { name: 'Flowsmith Indigo', hex: '#6366f1' },
  { name: 'Electric Blue', hex: '#3b82f6' },
  { name: 'Emerald Green', hex: '#10b981' },
  { name: 'Royal Violet', hex: '#8b5cf6' },
  { name: 'Amber Glow', hex: '#f59e0b' },
  { name: 'Crimson Rose', hex: '#f43f5e' },
  { name: 'Cyan Sky', hex: '#06b6d4' },
]

export default function SettingsPage() {
  const [profile, setProfile] = useState(null)
  const [workspaces, setWorkspaces] = useState([])
  const [orgs, setOrgs] = useState([])
  const [apikeys, setApikeys] = useState([])
  const [health, setHealth] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [newKeyName, setNewKeyName] = useState('')
  const [newKey, setNewKey] = useState(null)
  const [keyBusy, setKeyBusy] = useState(false)

  const branding = useBrandingStore()
  const soundEffects = useUiStore((s) => s.soundEffects)
  const toggleSoundEffects = useUiStore((s) => s.toggleSoundEffects)
  const showMiniMap = useUiStore((s) => s.showMiniMap)
  const toggleMiniMap = useUiStore((s) => s.toggleMiniMap)
  const [brandForm, setBrandForm] = useState({
    appName: branding.appName || 'Flowsmith',
    tagline: branding.tagline || 'Next-Gen Workflow Automation',
    logoUrl: branding.logoUrl || '',
    logoData: branding.logoData || '',
    primaryColor: branding.primaryColor || '#6366f1',
    documentationUrl: branding.documentationUrl || '',
    supportEmail: branding.supportEmail || '',
    copyrightText: branding.copyrightText || '',
    customCss: branding.customCss || '',
  })
  const [brandNotice, setBrandNotice] = useState(null)
  const [brandBusy, setBrandBusy] = useState(false)

  // Error Monitoring & Notification Preferences state
  const [notifPrefs, setNotifPrefs] = useState({
    email_enabled: true,
    notify_on_failure: true,
    notify_on_auth_expired: true,
    notify_on_rate_limit: true,
    notify_on_warning: false,
    cooldown_minutes: 15,
    custom_email: '',
    default_email: '',
  })
  const [notifBusy, setNotifBusy] = useState(false)
  const [notifNotice, setNotifNotice] = useState(null)
  const [testEmailBusy, setTestEmailBusy] = useState(false)
  const [testEmailNotice, setTestEmailNotice] = useState(null)

  useEffect(() => {
    setBrandForm({
      appName: branding.appName || 'Flowsmith',
      tagline: branding.tagline || 'Next-Gen Workflow Automation',
      logoUrl: branding.logoUrl || '',
      logoData: branding.logoData || '',
      primaryColor: branding.primaryColor || '#6366f1',
      documentationUrl: branding.documentationUrl || '',
      supportEmail: branding.supportEmail || '',
      copyrightText: branding.copyrightText || '',
      customCss: branding.customCss || '',
    })
  }, [branding.appName, branding.tagline, branding.logoUrl, branding.logoData, branding.primaryColor, branding.documentationUrl, branding.supportEmail, branding.copyrightText, branding.customCss])

  function handleLogoFile(e) {
    const file = e.target.files?.[0]
    if (!file) return
    if (file.size > 2 * 1024 * 1024) {
      setError('Logo image must be smaller than 2MB.')
      return
    }
    const reader = new FileReader()
    reader.onload = () => {
      setBrandForm(f => ({ ...f, logoData: reader.result, logoUrl: '' }))
    }
    reader.readAsDataURL(file)
  }

  async function handleSaveBranding(e) {
    e.preventDefault()
    setBrandBusy(true)
    setError(null)
    setBrandNotice(null)
    try {
      await branding.updateBranding(brandForm)
      setBrandNotice('Branding configuration saved and applied across the entire platform!')
      setTimeout(() => setBrandNotice(null), 4000)
    } catch (err) {
      setError(err.message || 'Failed to update branding.')
    } finally {
      setBrandBusy(false)
    }
  }

  async function handleResetBranding() {
    if (!window.confirm('Reset software name, logo, and colors back to Flowsmith defaults?')) return
    setBrandBusy(true)
    setError(null)
    setBrandNotice(null)
    try {
      const defs = await branding.resetBranding()
      setBrandForm({
        appName: defs.appName,
        tagline: defs.tagline,
        logoUrl: '',
        logoData: '',
        primaryColor: defs.primaryColor,
      })
      setBrandNotice('Branding restored to default Flowsmith settings.')
      setTimeout(() => setBrandNotice(null), 4000)
    } catch (err) {
      setError(err.message || 'Failed to reset branding.')
    } finally {
      setBrandBusy(false)
    }
  }

  async function handleSaveNotifPrefs(e) {
    if (e) e.preventDefault()
    setNotifBusy(true)
    setNotifNotice(null)
    try {
      const res = await api.updateNotificationPreferences({
        email_enabled: notifPrefs.email_enabled,
        notify_on_failure: notifPrefs.notify_on_failure,
        notify_on_auth_expired: notifPrefs.notify_on_auth_expired,
        notify_on_rate_limit: notifPrefs.notify_on_rate_limit,
        notify_on_warning: notifPrefs.notify_on_warning,
        cooldown_minutes: Number(notifPrefs.cooldown_minutes),
        custom_email: notifPrefs.custom_email,
      })
      if (res) {
        setNotifPrefs(prev => ({ ...prev, ...res }))
        setNotifNotice({ ok: true, text: 'Notification preferences saved successfully.' })
        setTimeout(() => setNotifNotice(null), 4000)
      }
    } catch (err) {
      setNotifNotice({ ok: false, text: err.message || 'Failed to update preferences.' })
    } finally {
      setNotifBusy(false)
    }
  }

  async function handleSendTestEmail() {
    setTestEmailBusy(true)
    setTestEmailNotice(null)
    try {
      const res = await api.sendTestNotificationEmail()
      setTestEmailNotice({
        ok: true,
        text: res?.message || 'Test email dispatched successfully! Check your inbox.',
      })
      setTimeout(() => setTestEmailNotice(null), 6000)
    } catch (err) {
      setTestEmailNotice({
        ok: false,
        text: err.message || 'Failed to send test email.',
      })
    } finally {
      setTestEmailBusy(false)
    }
  }

  useEffect(() => {
    let alive = true
    setLoading(true)
    Promise.allSettled([
      api.getHealth().catch(() => null),
      api.getMe().catch(() => null),
      api.listWorkspaces().catch(() => []),
      api.listOrganizations().catch(() => []),
      api.listApiKeys().catch(() => []),
      api.getNotificationPreferences().catch(() => null),
    ]).then(([hl, me, ws, og, ak, np]) => {
      if (!alive) return
      if (hl.status === 'fulfilled' && hl.value) setHealth(hl.value)
      if (ws.status === 'fulfilled') setWorkspaces(Array.isArray(ws.value) ? ws.value : [])
      if (og.status === 'fulfilled') setOrgs(Array.isArray(og.value) ? og.value : [])
      if (ak.status === 'fulfilled') setApikeys(Array.isArray(ak.value) ? ak.value : [])
      if (np.status === 'fulfilled' && np.value) setNotifPrefs(np.value)

      if (me.status === 'fulfilled' && me.value) {
        setProfile(me.value)
      } else {
        try {
          const token = getToken()
          if (token) {
            const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')))
            setProfile(payload)
          }
        } catch (err) { console.error('[flowsmith] pages/SettingsPage.jsx', err) }
      }
      setLoading(false)
    })
    return () => { alive = false }
  }, [])

  async function createKey(e) {
    e.preventDefault()
    if (!newKeyName.trim()) return
    setError(null)
    setKeyBusy(true)
    try {
      const res = await api.createApiKey(newKeyName.trim())
      if (res?.key) {
        setNewKey(res)
        setNewKeyName('')
      }
      const updated = await api.listApiKeys().catch(() => [])
      setApikeys(updated || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setKeyBusy(false)
    }
  }

  async function revokeKey(id) {
    if (!window.confirm('Revoke this API key? Applications using it will lose access immediately.')) return
    try {
      await api.revokeApiKey(id)
      const updated = await api.listApiKeys().catch(() => [])
      setApikeys(updated || [])
    } catch (err) {
      setError(err.message)
    }
  }

  if (loading) return <div className="page settings-page"><PageHeader title="Settings" /><LoadingSkeleton rows={6} /></div>

  return (
    <div className="page settings-page">
      <PageHeader title="Settings" description="Manage your account, workspaces, organizations, and integrations." />

      {error && <div className="banner-inline err">{error}</div>}

      <Section title="General" description="Deployment and platform configuration.">
        <div className="settings-grid">
          <div className="settings-attr">
            <div className="settings-attr-label">App Version</div>
            <div className="settings-attr-value">v{health?.version || '0.3.1'}</div>
          </div>
          <div className="settings-attr">
            <div className="settings-attr-label">System Uptime</div>
            <div className="settings-attr-value">{Math.floor((health?.uptime_s || 0) / 60)} minutes</div>
          </div>
          <div className="settings-attr">
            <div className="settings-attr-label">Theme Mode</div>
            <div className="settings-attr-value">Dark (Obsidian)</div>
          </div>
          <div className="settings-attr">
            <div className="settings-attr-label">API Endpoint Base</div>
            <div className="settings-attr-value"><code>/api</code></div>
          </div>
        </div>
      </Section>

      <Section
        title="Branding & White-Labeling"
        description="Customize the software name, company logo, tagline, and brand colors for your organization or clients."
      >
        {brandNotice && <div className="banner-inline ok" style={{ marginBottom: 14 }}>{brandNotice}</div>}

        <div className="branding-grid">
          {/* Left column: Branding Form */}
          <form onSubmit={handleSaveBranding} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div>
              <label style={{ display: 'block', fontSize: 12.5, fontWeight: 600, color: '#e2e8f0', marginBottom: 6 }}>
                Software / Company Name
              </label>
              <input
                type="text"
                placeholder="e.g. Acme Corp or Flowsmith"
                value={brandForm.appName}
                onChange={e => setBrandForm(f => ({ ...f, appName: e.target.value }))}
                style={{ width: '100%', maxWidth: 440 }}
                maxLength={128}
                required
              />
              <span className="hint" style={{ fontSize: 11.5, display: 'block', marginTop: 4 }}>
                Replaces "Flowsmith" in the sidebar, navigation header, document title, and login screen.
              </span>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: 12.5, fontWeight: 600, color: '#e2e8f0', marginBottom: 6 }}>
                Tagline / Subtitle
              </label>
              <input
                type="text"
                placeholder="e.g. Next-Gen Workflow Automation"
                value={brandForm.tagline}
                onChange={e => setBrandForm(f => ({ ...f, tagline: e.target.value }))}
                style={{ width: '100%', maxWidth: 440 }}
                maxLength={255}
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: 12.5, fontWeight: 600, color: '#e2e8f0', marginBottom: 6 }}>
                Company Logo
              </label>
              <div className="branding-logo-dropzone" style={{ maxWidth: 440 }}>
                <div style={{
                  width: 52,
                  height: 52,
                  borderRadius: 10,
                  background: (brandForm.logoData || brandForm.logoUrl)
                    ? 'rgba(0,0,0,0.3)'
                    : `linear-gradient(135deg, ${brandForm.primaryColor} 0%, rgba(99,102,241,0.6) 100%)`,
                  display: 'grid',
                  placeItems: 'center',
                  overflow: 'hidden',
                  flexShrink: 0,
                  border: '1px solid rgba(255,255,255,0.1)'
                }}>
                  {(brandForm.logoData || brandForm.logoUrl) ? (
                    <img
                      src={brandForm.logoData || brandForm.logoUrl}
                      alt="Logo preview"
                      style={{ width: '100%', height: '100%', objectFit: 'contain' }}
                    />
                  ) : (
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" style={{ color: '#fff' }}>
                      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" fill="currentColor" />
                    </svg>
                  )}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <label className="button ghost small" style={{ cursor: 'pointer', margin: 0, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                        <polyline points="17 8 12 3 7 8" />
                        <line x1="12" y1="3" x2="12" y2="15" />
                      </svg>
                      <span>Upload Logo Image</span>
                      <input
                        type="file"
                        accept="image/png,image/svg+xml,image/jpeg,image/webp"
                        style={{ display: 'none' }}
                        onChange={handleLogoFile}
                      />
                    </label>
                    {(brandForm.logoData || brandForm.logoUrl) && (
                      <button
                        type="button"
                        className="ghost small"
                        style={{ color: '#ef4444' }}
                        onClick={() => setBrandForm(f => ({ ...f, logoData: '', logoUrl: '' }))}
                      >
                        Remove Logo
                      </button>
                    )}
                  </div>
                  <span className="hint" style={{ fontSize: 11, display: 'block', marginTop: 4 }}>
                    Supports PNG, SVG, JPG, WebP (max 2MB).
                  </span>
                </div>
              </div>

              <div style={{ marginTop: 8 }}>
                <input
                  type="url"
                  placeholder="Or paste an external logo URL (https://...)"
                  value={brandForm.logoUrl}
                  onChange={e => setBrandForm(f => ({ ...f, logoUrl: e.target.value, logoData: '' }))}
                  style={{ width: '100%', maxWidth: 440, fontSize: 12 }}
                />
              </div>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: 12.5, fontWeight: 600, color: '#e2e8f0', marginBottom: 4 }}>
                Brand Accent Color
              </label>
              <div className="branding-color-swatches">
                {BRAND_COLOR_PRESETS.map(preset => (
                  <button
                    key={preset.hex}
                    type="button"
                    title={preset.name}
                    className={`branding-swatch-btn ${brandForm.primaryColor.toLowerCase() === preset.hex.toLowerCase() ? 'is-active' : ''}`}
                    style={{ background: preset.hex }}
                    onClick={() => setBrandForm(f => ({ ...f, primaryColor: preset.hex }))}
                  />
                ))}
                <input
                  type="color"
                  title="Custom hex color"
                  className="branding-color-picker-input"
                  value={brandForm.primaryColor}
                  onChange={e => setBrandForm(f => ({ ...f, primaryColor: e.target.value }))}
                />
                <code style={{ fontSize: 12, padding: '3px 6px', background: 'rgba(255,255,255,0.05)', borderRadius: 4 }}>
                  {brandForm.primaryColor}
                </code>
              </div>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: 12.5, fontWeight: 600, color: '#e2e8f0', marginBottom: 6 }}>
                Documentation & Runbook URL
              </label>
              <input
                type="url"
                placeholder="e.g. https://docs.yourcompany.com"
                value={brandForm.documentationUrl}
                onChange={e => setBrandForm(f => ({ ...f, documentationUrl: e.target.value }))}
                style={{ width: '100%', maxWidth: 440 }}
                maxLength={512}
              />
              <span className="hint" style={{ fontSize: 11.5, display: 'block', marginTop: 4 }}>
                Replaces external documentation links with your organization's internal runbook.
              </span>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: 12.5, fontWeight: 600, color: '#e2e8f0', marginBottom: 6 }}>
                Support & Helpdesk Email
              </label>
              <input
                type="email"
                placeholder="e.g. it-support@yourcompany.com"
                value={brandForm.supportEmail}
                onChange={e => setBrandForm(f => ({ ...f, supportEmail: e.target.value }))}
                style={{ width: '100%', maxWidth: 440 }}
                maxLength={255}
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: 12.5, fontWeight: 600, color: '#e2e8f0', marginBottom: 6 }}>
                Footer Copyright Text
              </label>
              <input
                type="text"
                placeholder="e.g. © 2026 Your Company Inc. All rights reserved."
                value={brandForm.copyrightText}
                onChange={e => setBrandForm(f => ({ ...f, copyrightText: e.target.value }))}
                style={{ width: '100%', maxWidth: 440 }}
                maxLength={255}
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: 12.5, fontWeight: 600, color: '#e2e8f0', marginBottom: 6 }}>
                Custom CSS Stylesheet Overrides
              </label>
              <textarea
                rows={4}
                placeholder=":root { /* Custom styling rules injected live */ }"
                value={brandForm.customCss}
                onChange={e => setBrandForm(f => ({ ...f, customCss: e.target.value }))}
                style={{ width: '100%', maxWidth: 440, fontFamily: 'monospace', fontSize: 12 }}
              />
              <span className="hint" style={{ fontSize: 11.5, display: 'block', marginTop: 4 }}>
                Injects custom CSS styles into all pages in real-time.
              </span>
            </div>

            <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 8 }}>
              <button className="primary" type="submit" disabled={brandBusy} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                {!brandBusy && (
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                )}
                {brandBusy ? 'Saving…' : 'Save Branding'}
              </button>
              <button
                type="button"
                className="ghost"
                disabled={brandBusy}
                onClick={handleResetBranding}
              >
                Reset to Defaults
              </button>
            </div>
          </form>

          {/* Right column: Live Preview */}
          <div className="branding-preview-box">
            <div className="branding-preview-header">Live Brand Preview</div>
            
            {/* Sidebar header preview */}
            <div>
              <div style={{ fontSize: 11, color: '#64748b', marginBottom: 6, fontWeight: 600 }}>Sidebar Header</div>
              <div className="branding-preview-sample">
                <div style={{
                  width: 32,
                  height: 32,
                  borderRadius: 8,
                  background: (brandForm.logoData || brandForm.logoUrl)
                    ? 'transparent'
                    : `linear-gradient(135deg, ${brandForm.primaryColor} 0%, rgba(99,102,241,0.6) 100%)`,
                  boxShadow: (brandForm.logoData || brandForm.logoUrl)
                    ? 'none'
                    : `0 4px 12px ${brandForm.primaryColor}66`,
                  display: 'grid',
                  placeItems: 'center',
                  overflow: 'hidden',
                  flexShrink: 0
                }}>
                  {(brandForm.logoData || brandForm.logoUrl) ? (
                    <img
                      src={brandForm.logoData || brandForm.logoUrl}
                      alt="Logo"
                      style={{ width: '100%', height: '100%', objectFit: 'contain' }}
                    />
                  ) : (
                    <FlowsmithBrandMark size={18} variant="glyph" style={{ color: '#fff' }} />
                  )}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                  <span style={{ fontWeight: 800, fontSize: 13.5, color: '#fff', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {brandForm.appName || 'Flowsmith'}
                  </span>
                  <span style={{ fontSize: 10.5, color: '#94a3b8', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {brandForm.tagline || 'Next-Gen Workflow Automation'}
                  </span>
                </div>
              </div>
            </div>

            {/* Login card preview */}
            <div>
              <div style={{ fontSize: 11, color: '#64748b', marginBottom: 6, fontWeight: 600 }}>Login Card Header</div>
              <div className="branding-preview-sample" style={{ flexDirection: 'column', textAlign: 'center', padding: '16px 12px' }}>
                <div style={{
                  width: 40,
                  height: 40,
                  borderRadius: 10,
                  background: (brandForm.logoData || brandForm.logoUrl)
                    ? 'transparent'
                    : `linear-gradient(135deg, ${brandForm.primaryColor} 0%, rgba(99,102,241,0.6) 100%)`,
                  display: 'grid',
                  placeItems: 'center',
                  overflow: 'hidden',
                  margin: '0 auto 8px'
                }}>
                  {(brandForm.logoData || brandForm.logoUrl) ? (
                    <img
                      src={brandForm.logoData || brandForm.logoUrl}
                      alt="Logo"
                      style={{ width: '100%', height: '100%', objectFit: 'contain' }}
                    />
                  ) : (
                    <FlowsmithBrandMark size={22} variant="glyph" style={{ color: '#fff' }} />
                  )}
                </div>
                <div style={{ fontWeight: 700, fontSize: 15, color: '#fff' }}>
                  {brandForm.appName || 'Flowsmith'}
                </div>
                <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>
                  {brandForm.tagline || 'Next-Gen Workflow Automation'}
                </div>
              </div>
            </div>
          </div>
        </div>
      </Section>

      <Section title="Preferences" description="Audio cues, canvas display, and interface behavior.">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 14 }}>
          <div className="settings-attr" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 16px' }}>
            <div>
              <div style={{ fontWeight: 600, color: '#f8fafc', fontSize: 13.5 }}>Execution Audio Cues</div>
              <div className="hint" style={{ fontSize: 12, marginTop: 2 }}>
                Play subtle harmonic chime when runs complete or fail
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <button
                type="button"
                className="secondary"
                style={{ padding: '4px 10px', fontSize: 11.5 }}
                onClick={() => playChime('success')}
                title="Preview success chime"
              >
                Test Chime
              </button>
              <input
                type="checkbox"
                checked={soundEffects}
                onChange={toggleSoundEffects}
                style={{ width: 18, height: 18, accentColor: '#6366f1', cursor: 'pointer' }}
                aria-label="Toggle execution sound effects"
              />
            </div>
          </div>
          <div className="settings-attr" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 16px' }}>
            <div>
              <div style={{ fontWeight: 600, color: '#f8fafc', fontSize: 13.5 }}>Canvas MiniMap</div>
              <div className="hint" style={{ fontSize: 12, marginTop: 2 }}>
                Show canvas overview thumbnail in editor (shortcut: M)
              </div>
            </div>
            <div>
              <input
                type="checkbox"
                checked={showMiniMap}
                onChange={toggleMiniMap}
                style={{ width: 18, height: 18, accentColor: '#6366f1', cursor: 'pointer' }}
                aria-label="Toggle canvas minimap"
              />
            </div>
          </div>
        </div>
      </Section>

      <Section
        title="Error Monitoring & Email Notification Preferences"
        description="Configure automatic email delivery, failure alerts, OAuth session expiry notifications, and alert deduplication cooldown."
      >
        <form onSubmit={handleSaveNotifPrefs} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {notifNotice && (
            <div
              className={`banner-inline ${notifNotice.ok ? 'ok' : 'err'}`}
              style={{ padding: '10px 14px', borderRadius: 8 }}
            >
              {notifNotice.text}
            </div>
          )}

          {testEmailNotice && (
            <div
              className={`banner-inline ${testEmailNotice.ok ? 'ok' : 'err'}`}
              style={{ padding: '10px 14px', borderRadius: 8 }}
            >
              {testEmailNotice.text}
            </div>
          )}

          {/* Master Toggle Banner */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '16px 20px',
              borderRadius: 10,
              background: notifPrefs.email_enabled
                ? 'linear-gradient(135deg, rgba(99, 102, 241, 0.12) 0%, rgba(15, 23, 42, 0.6) 100%)'
                : 'rgba(255, 255, 255, 0.02)',
              border: notifPrefs.email_enabled
                ? '1px solid rgba(99, 102, 241, 0.3)'
                : '1px solid rgba(255, 255, 255, 0.08)',
              gap: 16,
            }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
                <div style={{ fontWeight: 650, color: '#f8fafc', fontSize: 14.5 }}>Automatic Email Alerts</div>
                <span
                  className="badge"
                  style={{
                    background: notifPrefs.email_enabled ? 'rgba(16, 185, 129, 0.15)' : 'rgba(148, 163, 184, 0.12)',
                    color: notifPrefs.email_enabled ? '#34d399' : '#94a3b8',
                    border: notifPrefs.email_enabled ? '1px solid rgba(16, 185, 129, 0.3)' : '1px solid rgba(148, 163, 184, 0.2)',
                    fontSize: 11,
                    padding: '2px 8px',
                    borderRadius: 12,
                    fontWeight: 600,
                  }}
                >
                  {notifPrefs.email_enabled ? 'Active' : 'Disabled'}
                </span>
              </div>
              <div className="hint" style={{ fontSize: 12.5, lineHeight: 1.4, color: '#94a3b8' }}>
                Automatically send diagnostic emails when errors disrupt workflows, connectors, or scheduled operations.
              </div>
            </div>
            <div>
              <input
                type="checkbox"
                checked={notifPrefs.email_enabled}
                onChange={e => setNotifPrefs(f => ({ ...f, email_enabled: e.target.checked }))}
                style={{ width: 20, height: 20, accentColor: '#6366f1', cursor: 'pointer' }}
                aria-label="Toggle email notifications"
              />
            </div>
          </div>

          {/* Alert Trigger Rules Card */}
          <div
            style={{
              borderRadius: 10,
              background: 'rgba(255, 255, 255, 0.02)',
              border: '1px solid rgba(255, 255, 255, 0.06)',
              overflow: 'hidden',
              opacity: notifPrefs.email_enabled ? 1 : 0.6,
              transition: 'opacity 0.2s ease',
            }}
          >
            <div style={{ padding: '12px 18px', borderBottom: '1px solid rgba(255, 255, 255, 0.06)', background: 'rgba(255, 255, 255, 0.015)' }}>
              <div style={{ fontSize: 11.5, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: '#94a3b8' }}>
                Alert Trigger Categories
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column' }}>
              {/* Workflow & Node Failures */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '14px 18px',
                  borderBottom: '1px solid rgba(255, 255, 255, 0.04)',
                  gap: 16,
                }}
              >
                <div style={{ flex: 1, minWidth: 0, paddingRight: 12 }}>
                  <div style={{ fontWeight: 600, color: '#f8fafc', fontSize: 13.5 }}>Workflow &amp; Node Execution Failures</div>
                  <div className="hint" style={{ fontSize: 12, marginTop: 3 }}>
                    Alert when executions fail, retries are exhausted, or runtime steps crash
                  </div>
                </div>
                <div>
                  <input
                    type="checkbox"
                    checked={notifPrefs.notify_on_failure}
                    disabled={!notifPrefs.email_enabled}
                    onChange={e => setNotifPrefs(f => ({ ...f, notify_on_failure: e.target.checked }))}
                    style={{ width: 18, height: 18, accentColor: '#6366f1', cursor: 'pointer' }}
                    aria-label="Toggle failure alerts"
                  />
                </div>
              </div>

              {/* Expired Credentials & OAuth Sessions */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '14px 18px',
                  borderBottom: '1px solid rgba(255, 255, 255, 0.04)',
                  gap: 16,
                }}
              >
                <div style={{ flex: 1, minWidth: 0, paddingRight: 12 }}>
                  <div style={{ fontWeight: 600, color: '#f8fafc', fontSize: 13.5 }}>OAuth Session &amp; Credential Expiry</div>
                  <div className="hint" style={{ fontSize: 12, marginTop: 3 }}>
                    Actionable re-authorization alert when external connectors (Salesforce, Dynamics 365, HubSpot, Google) fail token refresh
                  </div>
                </div>
                <div>
                  <input
                    type="checkbox"
                    checked={notifPrefs.notify_on_auth_expired}
                    disabled={!notifPrefs.email_enabled}
                    onChange={e => setNotifPrefs(f => ({ ...f, notify_on_auth_expired: e.target.checked }))}
                    style={{ width: 18, height: 18, accentColor: '#6366f1', cursor: 'pointer' }}
                    aria-label="Toggle session expiry alerts"
                  />
                </div>
              </div>

              {/* Rate Limits */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '14px 18px',
                  borderBottom: '1px solid rgba(255, 255, 255, 0.04)',
                  gap: 16,
                }}
              >
                <div style={{ flex: 1, minWidth: 0, paddingRight: 12 }}>
                  <div style={{ fontWeight: 600, color: '#f8fafc', fontSize: 13.5 }}>API Rate Limit Warnings</div>
                  <div className="hint" style={{ fontSize: 12, marginTop: 3 }}>
                    Notify when third-party connectors reject requests with HTTP 429 Too Many Requests
                  </div>
                </div>
                <div>
                  <input
                    type="checkbox"
                    checked={notifPrefs.notify_on_rate_limit}
                    disabled={!notifPrefs.email_enabled}
                    onChange={e => setNotifPrefs(f => ({ ...f, notify_on_rate_limit: e.target.checked }))}
                    style={{ width: 18, height: 18, accentColor: '#6366f1', cursor: 'pointer' }}
                    aria-label="Toggle rate limit alerts"
                  />
                </div>
              </div>

              {/* Non-fatal Warnings */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '14px 18px',
                  gap: 16,
                }}
              >
                <div style={{ flex: 1, minWidth: 0, paddingRight: 12 }}>
                  <div style={{ fontWeight: 600, color: '#f8fafc', fontSize: 13.5 }}>Non-Fatal Warnings &amp; Exceptions</div>
                  <div className="hint" style={{ fontSize: 12, marginTop: 3 }}>
                    Send email notifications for warning-level events and non-terminal retry failures
                  </div>
                </div>
                <div>
                  <input
                    type="checkbox"
                    checked={notifPrefs.notify_on_warning}
                    disabled={!notifPrefs.email_enabled}
                    onChange={e => setNotifPrefs(f => ({ ...f, notify_on_warning: e.target.checked }))}
                    style={{ width: 18, height: 18, accentColor: '#6366f1', cursor: 'pointer' }}
                    aria-label="Toggle warning alerts"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Delivery & Alert Throttling Card */}
          <div
            style={{
              borderRadius: 10,
              background: 'rgba(255, 255, 255, 0.02)',
              border: '1px solid rgba(255, 255, 255, 0.06)',
              overflow: 'hidden',
              opacity: notifPrefs.email_enabled ? 1 : 0.6,
              transition: 'opacity 0.2s ease',
            }}
          >
            <div style={{ padding: '12px 18px', borderBottom: '1px solid rgba(255, 255, 255, 0.06)', background: 'rgba(255, 255, 255, 0.015)' }}>
              <div style={{ fontSize: 11.5, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: '#94a3b8' }}>
                Alert Throttling &amp; Delivery Routing
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column' }}>
              {/* Deduplication Cooldown Window */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  flexWrap: 'wrap',
                  padding: '16px 18px',
                  borderBottom: '1px solid rgba(255, 255, 255, 0.04)',
                  gap: 16,
                }}
              >
                <div style={{ flex: '1 1 320px', minWidth: 260 }}>
                  <div style={{ fontWeight: 600, color: '#f8fafc', fontSize: 13.5 }}>Alert Deduplication Cooldown</div>
                  <div className="hint" style={{ fontSize: 12, marginTop: 3, maxWidth: 640 }}>
                    Suppresses identical failure emails within this window to prevent alert flooding.
                  </div>
                </div>
                <div style={{ flexShrink: 0 }}>
                  <select
                    value={notifPrefs.cooldown_minutes}
                    disabled={!notifPrefs.email_enabled}
                    onChange={e => setNotifPrefs(f => ({ ...f, cooldown_minutes: Number(e.target.value) }))}
                    style={{
                      minWidth: 210,
                      padding: '8px 14px',
                      borderRadius: 7,
                      background: 'var(--panel-2, #0f172a)',
                      border: '1px solid var(--border, #334155)',
                      color: 'var(--text, #f1f5f9)',
                      fontSize: 13,
                      fontWeight: 500,
                      cursor: notifPrefs.email_enabled ? 'pointer' : 'not-allowed',
                      boxShadow: '0 1px 3px rgba(0, 0, 0, 0.2)',
                    }}
                  >
                    <option value={5}>5 minutes</option>
                    <option value={15}>15 minutes (recommended)</option>
                    <option value={30}>30 minutes</option>
                    <option value={60}>60 minutes</option>
                    <option value={120}>2 hours</option>
                  </select>
                </div>
              </div>

              {/* Custom Notification Email */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  flexWrap: 'wrap',
                  padding: '16px 18px',
                  gap: 16,
                }}
              >
                <div style={{ flex: '1 1 320px', minWidth: 260 }}>
                  <div style={{ fontWeight: 600, color: '#f8fafc', fontSize: 13.5 }}>Alert Recipient Email Override</div>
                  <div className="hint" style={{ fontSize: 12, marginTop: 3, maxWidth: 640 }}>
                    Default: <code>{notifPrefs.default_email || profile?.email || 'Your account email'}</code>. Specify a different address or distribution list if desired.
                  </div>
                </div>
                <div style={{ flexShrink: 0, minWidth: 260, maxWidth: 380, width: '100%' }}>
                  <input
                    type="email"
                    placeholder="alerts@yourcompany.com"
                    value={notifPrefs.custom_email || ''}
                    disabled={!notifPrefs.email_enabled}
                    onChange={e => setNotifPrefs(f => ({ ...f, custom_email: e.target.value }))}
                    style={{
                      width: '100%',
                      padding: '8px 14px',
                      borderRadius: 7,
                      background: 'var(--panel-2, #0f172a)',
                      border: '1px solid var(--border, #334155)',
                      color: 'var(--text, #f1f5f9)',
                      fontSize: 13,
                      boxShadow: '0 1px 3px rgba(0, 0, 0, 0.2)',
                    }}
                  />
                </div>
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginTop: 4 }}>
            <button
              type="submit"
              className="primary"
              disabled={notifBusy}
              style={{ padding: '8px 20px', fontSize: 13, fontWeight: 600 }}
            >
              {notifBusy ? 'Saving…' : 'Save Notification Preferences'}
            </button>

            <button
              type="button"
              className="secondary"
              onClick={handleSendTestEmail}
              disabled={testEmailBusy || !notifPrefs.email_enabled}
              style={{ padding: '8px 16px', fontSize: 12.5, display: 'inline-flex', alignItems: 'center', gap: 6 }}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
                <polyline points="22,6 12,13 2,6" />
              </svg>
              <span>{testEmailBusy ? 'Sending…' : 'Send Test Alert Email'}</span>
            </button>
          </div>
        </form>
      </Section>

      <Section title="Account" description="Your authenticated identity.">
        <div className="settings-grid">
          <div className="settings-attr">
            <div className="settings-attr-label">User ID</div>
            <div className="settings-attr-value">{profile?.id || profile?.sub || profile?.user_id || '1'}</div>
          </div>
          <div className="settings-attr">
            <div className="settings-attr-label">Email Address</div>
            <div className="settings-attr-value">{profile?.email || 'user@example.com'}</div>
          </div>
          <div className="settings-attr">
            <div className="settings-attr-label">Account Role</div>
            <div className="settings-attr-value">
              <span className="badge" style={{ background: 'rgba(99, 102, 241, 0.15)', color: '#818cf8', border: '1px solid rgba(99, 102, 241, 0.3)', textTransform: 'capitalize' }}>
                {profile?.role || 'user'}
              </span>
            </div>
          </div>
        </div>
      </Section>

      <Section title="Workspaces" description="Workspaces scope environment variables and workflows.">
        {workspaces.length === 0 ? <p className="hint">No workspaces yet.</p> : (
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Name</th><th>Workspace ID</th><th>Created</th></tr></thead>
              <tbody>
                {workspaces.map(w => (
                  <tr key={w.id}>
                    <td><strong style={{ color: '#f8fafc' }}>{w.name}</strong></td>
                    <td><code className="exec-id-cell">{w.id}</code></td>
                    <td className="muted">{new Date(w.created_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title="Organizations" description="Organizations own workspaces and team collaboration.">
        {orgs.length === 0 ? <p className="hint">No organizations yet.</p> : (
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Name</th><th>Organization ID</th></tr></thead>
              <tbody>
                {orgs.map(o => (
                  <tr key={o.id}>
                    <td><strong style={{ color: '#f8fafc' }}>{o.name}</strong></td>
                    <td><code className="exec-id-cell">{o.id}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title="API Keys" description="Programmatic API tokens. The secret key is only revealed once upon creation.">
        <form onSubmit={createKey} className="inline-form">
          <input
            placeholder="Key name (e.g. CI/CD Pipeline)"
            value={newKeyName}
            onChange={e => setNewKeyName(e.target.value)}
            style={{ maxWidth: 300 }}
          />
          <button className="primary" type="submit" disabled={!newKeyName.trim() || keyBusy}>
            {keyBusy ? 'Creating…' : '＋ Create API Key'}
          </button>
        </form>
        {newKey && (
          <div className="banner-inline ok" style={{ marginTop: 10 }}>
            New key: <code>{newKey.key}</code> — copy it now, it will not be shown again.
          </div>
        )}
        {apikeys.length === 0 ? <p className="hint" style={{ marginTop: 10 }}>No active API keys.</p> : (
          <div className="table-wrap" style={{ marginTop: 12 }}>
            <table className="data-table">
              <thead><tr><th>Name</th><th>Prefix</th><th>Created</th><th>Actions</th></tr></thead>
              <tbody>
                {apikeys.map(k => (
                  <tr key={k.id}>
                    <td><strong style={{ color: '#f8fafc' }}>{k.name}</strong></td>
                    <td><code>{k.prefix}…</code></td>
                    <td className="muted">{k.created_at ? new Date(k.created_at).toLocaleDateString() : '—'}</td>
                    <td>
                      <button className="ghost small" style={{ color: '#ef4444' }} onClick={() => revokeKey(k.id)}>Revoke</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title="Security & Compliance" description="Security architecture and credential storage.">
        <ul className="hint" style={{ lineHeight: 1.6, paddingLeft: 18, margin: '8px 0 0' }}>
          <li>Login rate-limiting enabled per-email and client IP (with 429 Retry-After protection)</li>
          <li>All third-party credentials encrypted at rest using AES-128-CBC / Fernet envelope encryption</li>
          <li>Session authentication backed by cryptographic JWT with sliding expiration</li>
        </ul>
      </Section>

      <Section title="Execution Engine" description="Durable job queue and worker architecture.">
        <ul className="hint" style={{ lineHeight: 1.6, paddingLeft: 18, margin: '8px 0 0' }}>
          <li>Every execution is scheduled through a durable queue with atomic worker claiming</li>
          <li>Automatic crash recovery: stale heartbeats are re-queued to prevent stuck executions</li>
          <li>Real-time node step progression streamed via WebSocket with reactive UI state</li>
        </ul>
      </Section>
    </div>
  )
}
