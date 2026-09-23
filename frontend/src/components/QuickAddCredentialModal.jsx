import { useState, useEffect } from 'react'
import { useCredentialStore } from '../stores/credentialStore'
import Button from './shared/Button'

export default function QuickAddCredentialModal({
  open,
  onClose,
  defaultType = 'bearer_auth',
  onCreated,
}) {
  const types = useCredentialStore((s) => s.types)
  const createCredential = useCredentialStore((s) => s.create)

  const [type, setType] = useState(defaultType)
  const [name, setName] = useState('')
  const [fields, setFields] = useState({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (open) {
      setType(defaultType || 'bearer_auth')
      setName(`My ${defaultType ? defaultType.replace('_', ' ') : 'Credential'}`)
      setFields({})
      setError(null)
    }
  }, [open, defaultType])

  if (!open) return null

  const handleFieldChange = (key, val) => {
    setFields((prev) => ({ ...prev, [key]: val }))
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!name.trim()) {
      setError('Please provide a credential name.')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const created = await createCredential({
        name: name.trim(),
        type,
        data: fields,
      })
      if (onCreated) {
        onCreated(created)
      }
      onClose()
    } catch (err) {
      setError(err.message || 'Failed to create credential')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="node-editor-overlay"
      style={{
        zIndex: 1000,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'rgba(0, 0, 0, 0.65)',
        backdropFilter: 'blur(4px)',
      }}
      onClick={onClose}
    >
      <div
        className="node-editor-modal"
        style={{
          width: '100%',
          maxWidth: 520,
          maxHeight: '90vh',
          height: 'auto',
          background: 'var(--panel, #181d2a)',
          border: '1px solid var(--border, #2e384d)',
          borderRadius: 12,
          boxShadow: '0 24px 64px rgba(0,0,0,0.6)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '14px 18px',
            borderBottom: '1px solid var(--border)',
            background: 'var(--panel-2, #11141d)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 16 }}>🔑</span>
            <span style={{ fontWeight: 600, fontSize: 14, color: 'var(--text)' }}>
              Add New Credential
            </span>
          </div>
          <button
            type="button"
            className="ghost"
            onClick={onClose}
            style={{ fontSize: 16, padding: '4px 8px', cursor: 'pointer' }}
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 14 }}>
          {error && (
            <div
              style={{
                padding: '8px 12px',
                borderRadius: 6,
                background: 'rgba(239, 68, 68, 0.15)',
                border: '1px solid #ef4444',
                color: '#fca5a5',
                fontSize: 12,
              }}
            >
              {error}
            </div>
          )}

          <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--muted)' }}>Credential Type</span>
            <select
              value={type}
              onChange={(e) => {
                setType(e.target.value)
                setFields({})
              }}
              style={{ padding: '8px 10px', fontSize: 13, background: 'var(--bg)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 6 }}
            >
              {types.length > 0 ? (
                types.map((t) => (
                  <option key={t.type} value={t.type}>
                    {t.name || t.type}
                  </option>
                ))
              ) : (
                <>
                  <option value="bearer_auth">Bearer Token</option>
                  <option value="basic_auth">Basic Auth</option>
                  <option value="header_auth">Header Auth</option>
                  <option value="query_auth">Query Auth</option>
                  <option value="oauth2">OAuth2</option>
                </>
              )}
            </select>
          </label>

          <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--muted)' }}>Credential Name *</span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Production API Token"
              required
              style={{ padding: '8px 10px', fontSize: 13, background: 'var(--bg)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 6 }}
            />
          </label>

          {/* Dynamic fields based on type */}
          {(type === 'bearer_auth' || type === 'bearer') && (
            <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--muted)' }}>Bearer Token *</span>
              <input
                type="password"
                value={fields.token || fields.api_key || ''}
                onChange={(e) => {
                  handleFieldChange('token', e.target.value)
                  handleFieldChange('api_key', e.target.value)
                }}
                placeholder="eyJhbGci..."
                required
                style={{ padding: '8px 10px', fontSize: 13, background: 'var(--bg)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 6 }}
              />
            </label>
          )}

          {(type === 'basic_auth' || type === 'basic') && (
            <>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--muted)' }}>Username *</span>
                <input
                  type="text"
                  value={fields.username || ''}
                  onChange={(e) => handleFieldChange('username', e.target.value)}
                  placeholder="admin or user@example.com"
                  required
                  style={{ padding: '8px 10px', fontSize: 13, background: 'var(--bg)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 6 }}
                />
              </label>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--muted)' }}>Password</span>
                <input
                  type="password"
                  value={fields.password || ''}
                  onChange={(e) => handleFieldChange('password', e.target.value)}
                  placeholder="••••••••"
                  style={{ padding: '8px 10px', fontSize: 13, background: 'var(--bg)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 6 }}
                />
              </label>
            </>
          )}

          {(type === 'header_auth' || type === 'header') && (
            <>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--muted)' }}>Header Name *</span>
                <input
                  type="text"
                  value={fields.header_name || fields.name || 'X-API-Key'}
                  onChange={(e) => handleFieldChange('header_name', e.target.value)}
                  placeholder="X-API-Key or Authorization"
                  required
                  style={{ padding: '8px 10px', fontSize: 13, background: 'var(--bg)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 6 }}
                />
              </label>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--muted)' }}>Header Value / Token *</span>
                <input
                  type="password"
                  value={fields.header_value || fields.value || fields.api_key || ''}
                  onChange={(e) => {
                    handleFieldChange('header_value', e.target.value)
                    handleFieldChange('value', e.target.value)
                    handleFieldChange('api_key', e.target.value)
                  }}
                  placeholder="api_key_12345"
                  required
                  style={{ padding: '8px 10px', fontSize: 13, background: 'var(--bg)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 6 }}
                />
              </label>
            </>
          )}

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 12 }}>
            <Button variant="ghost" onClick={onClose} type="button">
              Cancel
            </Button>
            <Button variant="primary" type="submit" disabled={saving}>
              {saving ? 'Saving…' : 'Save & Select'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
