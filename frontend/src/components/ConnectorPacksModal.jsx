import React, { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../api'
import './OpenApiImportModal.css'

const SAMPLE_MANIFEST = `{
  "name": "my_connector",
  "display_name": "My Connector",
  "version": "1.0.0",
  "description": "OpenAPI connector and starter workflows.",
  "category": "api",
  "spec": "https://example.com/openapi.json",
  "templates": []
}`

export default function ConnectorPacksModal({ isOpen = true, onClose, onInstalled }) {
  const [tab, setTab] = useState('url')
  const [manifestUrl, setManifestUrl] = useState('')
  const [manifestRaw, setManifestRaw] = useState('')
  const [registryUrl, setRegistryUrl] = useState('')
  const [registryName, setRegistryName] = useState('')
  const [registryPacks, setRegistryPacks] = useState([])
  const [registryLoading, setRegistryLoading] = useState(false)
  const [installing, setInstalling] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)
  const [packs, setPacks] = useState([])
  const [loadingPacks, setLoadingPacks] = useState(false)
  const [upgradeKey, setUpgradeKey] = useState('')
  const [removingKey, setRemovingKey] = useState('')

  const loadPacks = async () => {
    setLoadingPacks(true)
    try {
      const res = await api.listConnectorPacks()
      setPacks(Array.isArray(res) ? res : [])
    } catch (err) {
      setError(err.message || 'Failed to load installed packs.')
    } finally {
      setLoadingPacks(false)
    }
  }

  useEffect(() => {
    if (!isOpen) return
    loadPacks()
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose?.()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen])

  const handleInstall = async () => {
    setError(null)
    setSuccess(null)
    let payload
    if (tab === 'url') {
      if (!manifestUrl.trim()) {
        setError('Enter a manifest URL.')
        return
      }
      payload = { manifest_url: manifestUrl.trim() }
    } else {
      if (!manifestRaw.trim()) {
        setError('Paste a pack manifest as JSON.')
        return
      }
      try {
        payload = { manifest: JSON.parse(manifestRaw) }
      } catch (err) {
        setError(`Manifest is not valid JSON: ${err.message}`)
        return
      }
    }

    setInstalling(true)
    try {
      const result = upgradeKey
        ? await api.upgradeConnectorPack(upgradeKey, payload)
        : await api.installConnectorPack(payload)
      setSuccess(
        `${upgradeKey ? 'Upgraded' : 'Installed'} "${result.display_name}" with ` +
          `${result.operations_count || 0} operations and ` +
          `${result.template_count || 0} template(s).`
      )
      setManifestUrl('')
      setManifestRaw('')
      setUpgradeKey('')
      await loadPacks()
      if (typeof onInstalled === 'function') onInstalled(result)
    } catch (err) {
      setError(err.message || (upgradeKey ? 'Pack upgrade failed.' : 'Pack installation failed.'))
    } finally {
      setInstalling(false)
    }
  }

  const handleUninstall = async (pack) => {
    if (!window.confirm(
      `Uninstall "${pack.display_name}"? Its generated connector and pack-owned templates will be removed.`
    )) return
    setError(null)
    setSuccess(null)
    setRemovingKey(pack.connector_key)
    try {
      await api.uninstallConnectorPack(pack.connector_key)
      setSuccess(`Uninstalled "${pack.display_name}".`)
      if (upgradeKey === pack.connector_key) setUpgradeKey('')
      await loadPacks()
      if (typeof onInstalled === 'function') onInstalled({})
    } catch (err) {
      setError(err.message || 'Pack uninstall failed.')
    } finally {
      setRemovingKey('')
    }
  }

  const beginUpgrade = (pack) => {
    setUpgradeKey(pack.connector_key)
    setTab('url')
    setManifestUrl('')
    setManifestRaw('')
    setError(null)
    setSuccess(null)
  }

  const handleRegistryPreview = async () => {
    if (!registryUrl.trim()) {
      setError('Enter a signed registry index URL.')
      return
    }
    setError(null)
    setSuccess(null)
    setRegistryLoading(true)
    try {
      const result = await api.previewConnectorRegistry({ registry_url: registryUrl.trim() })
      setRegistryName(result.registry || 'Connector Registry')
      setRegistryPacks(Array.isArray(result.packs) ? result.packs : [])
      if (!result.packs || result.packs.length === 0) {
        setError('The registry is valid but contains no packs.')
      }
    } catch (err) {
      setError(err.message || 'Failed to load registry.')
      setRegistryPacks([])
    } finally {
      setRegistryLoading(false)
    }
  }

  const handleRegistryInstall = async (entry) => {
    setError(null)
    setSuccess(null)
    setInstalling(true)
    try {
      const isUpgrade = Boolean(upgradeKey && entry.name === upgradeKey)
      const result = isUpgrade
        ? await api.upgradeConnectorPack(entry.name, { manifest_url: entry.manifest_url })
        : await api.installConnectorPack({ manifest_url: entry.manifest_url })
      setSuccess(
        `${isUpgrade ? 'Upgraded' : 'Installed'} "${result.display_name}" from registry ` +
          `with ${result.operations_count || 0} operations.`
      )
      if (isUpgrade) setUpgradeKey('')
      await loadPacks()
      if (typeof onInstalled === 'function') onInstalled(result)
    } catch (err) {
      setError(err.message || 'Registry pack installation failed.')
    } finally {
      setInstalling(false)
    }
  }

  return createPortal(
    <div className="oai-modal-overlay" onClick={onClose}>
      <div
        className="oai-modal-window"
        style={{ width: 760 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="oai-modal-header">
          <div className="oai-header-title">
            <span className="oai-icon" style={{ display: 'flex' }}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z" />
                <path d="m3.3 7 8.7 5 8.7-5" />
                <path d="M12 22V12" />
              </svg>
            </span>
            <div>
              <h3>Connector Packs</h3>
              <span className="oai-subtitle">
                Install an OpenAPI connector plus optional workflow templates
              </span>
            </div>
          </div>
          <button type="button" className="oai-close-btn" onClick={onClose} aria-label="Close">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <div className="oai-modal-body">
          <div className="oai-hint" style={{ fontSize: 12, lineHeight: 1.5 }}>
            Packs are installed locally and admin-only. A pack manifest contains an OpenAPI spec,
            metadata, and optional templates. The installer validates generated code, graph
            structure, and strips credentials/secrets from imported templates.
          </div>

          {upgradeKey && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 10,
                padding: '8px 11px',
                background: 'rgba(99, 102, 241, 0.12)',
                border: '1px solid rgba(99, 102, 241, 0.35)',
                borderRadius: 8,
                fontSize: 12,
              }}
            >
              <span>Upgrading <code>{upgradeKey}</code>. Use a newer version manifest.</span>
              <button type="button" className="oai-btn ghost" onClick={() => setUpgradeKey('')}>
                Cancel
              </button>
            </div>
          )}

          <div className="oai-tabs">
            <button
              type="button"
              className={`oai-tab ${tab === 'url' ? 'active' : ''}`}
              onClick={() => setTab('url')}
            >
              Manifest URL
            </button>
            <button
              type="button"
              className={`oai-tab ${tab === 'raw' ? 'active' : ''}`}
              onClick={() => setTab('raw')}
            >
              Paste Manifest
            </button>
            <button
              type="button"
              className={`oai-tab ${tab === 'registry' ? 'active' : ''}`}
              onClick={() => setTab('registry')}
            >
              Signed Registry
            </button>
          </div>

          {tab === 'url' ? (
            <div className="oai-form-group">
              <label>Pack Manifest URL</label>
              <input
                type="url"
                placeholder="https://example.com/connector-pack.json"
                value={manifestUrl}
                onChange={(e) => setManifestUrl(e.target.value)}
              />
              <span className="oai-hint">
                The URL is fetched through the SSRF-safe HTTP client. Remote manifests require a
                valid Ed25519 signature; URL specs also require spec_sha256.
              </span>
            </div>
          ) : tab === 'raw' ? (
            <div className="oai-form-group">
              <label>Pack Manifest JSON</label>
              <textarea
                rows={10}
                placeholder={SAMPLE_MANIFEST}
                value={manifestRaw}
                onChange={(e) => setManifestRaw(e.target.value)}
                spellCheck={false}
              />
            </div>
          ) : (
            <div className="oai-form-group">
              <label>Signed Registry Index URL</label>
              <div className="oai-input-row">
                <input
                  type="url"
                  placeholder="https://example.com/registry.json"
                  value={registryUrl}
                  onChange={(e) => setRegistryUrl(e.target.value)}
                />
                <button
                  type="button"
                  className="oai-btn ghost"
                  onClick={handleRegistryPreview}
                  disabled={registryLoading}
                >
                  {registryLoading ? 'Loading...' : 'Load Registry'}
                </button>
              </div>
              <span className="oai-hint">
                The index is Ed25519-verified before any pack is shown. Revoked entries cannot be
                installed.
              </span>
              {registryName && (
                <div style={{ fontSize: 12, color: '#cbd5e1', marginTop: 4 }}>
                  <strong>{registryName}</strong> · {registryPacks.length} pack(s)
                </div>
              )}
              {registryPacks.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
                  {registryPacks.map((entry) => (
                    <div
                      key={`${entry.name}@${entry.version}`}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 12,
                        padding: '9px 11px',
                        background: 'rgba(255,255,255,0.03)',
                        border: '1px solid rgba(255,255,255,0.08)',
                        borderRadius: 8,
                      }}
                    >
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 600 }}>
                          {entry.display_name} <span className="oai-hint">v{entry.version}</span>
                        </div>
                        <div className="oai-hint">
                          <code>{entry.name}</code> · {entry.category}
                          {entry.description ? ` · ${entry.description}` : ''}
                        </div>
                      </div>
                      <button
                        type="button"
                        className="oai-btn primary"
                        disabled={installing || entry.revoked}
                        onClick={() => handleRegistryInstall(entry)}
                      >
                        {entry.revoked
                          ? 'Revoked'
                          : (upgradeKey === entry.name ? 'Upgrade' : 'Install')}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {error && <div className="oai-error-banner">{error}</div>}
          {success && (
            <div
              style={{
                padding: '9px 12px',
                background: 'rgba(16, 185, 129, 0.12)',
                border: '1px solid rgba(16, 185, 129, 0.35)',
                borderRadius: 8,
                color: '#34d399',
                fontSize: 12,
              }}
            >
              {success}
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <button type="button" className="oai-btn ghost" onClick={onClose}>
              Close
            </button>
            {tab !== 'registry' && (
              <button
                type="button"
                className="oai-btn primary"
                onClick={handleInstall}
                disabled={installing}
              >
                {installing
                  ? (upgradeKey ? 'Upgrading...' : 'Installing...')
                  : (upgradeKey ? 'Upgrade Pack' : 'Install Pack')}
              </button>
            )}
          </div>

          <div style={{ borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: 14 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
              <strong style={{ fontSize: 13 }}>Installed Packs</strong>
              <button type="button" className="oai-btn ghost" onClick={loadPacks} disabled={loadingPacks}>
                {loadingPacks ? 'Refreshing...' : 'Refresh'}
              </button>
            </div>
            {packs.length === 0 ? (
              <p className="oai-hint">No connector packs installed yet.</p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {packs.map((pack) => (
                  <div
                    key={pack.connector_key}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: 12,
                      padding: '9px 11px',
                      background: 'rgba(255,255,255,0.03)',
                      border: '1px solid rgba(255,255,255,0.08)',
                      borderRadius: 8,
                    }}
                  >
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 600 }}>{pack.display_name}</div>
                      <div className="oai-hint">
                        <code>{pack.connector_key}</code> · v{pack.version} ·{' '}
                        {pack.template_count} template(s) ·{' '}
                        {pack.signed
                          ? `Signed (${pack.signing_key_id || 'trusted key'})`
                          : 'Unsigned (local)'}
                        {pack.revoked ? ' · Signing key revoked' : ''}
                      </div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span className="oai-hint">{pack.category}</span>
                      <button
                        type="button"
                        className="oai-btn ghost"
                        onClick={() => beginUpgrade(pack)}
                      >
                        Upgrade
                      </button>
                      <button
                        type="button"
                        className="oai-btn ghost"
                        onClick={() => handleUninstall(pack)}
                        disabled={removingKey === pack.connector_key}
                      >
                        {removingKey === pack.connector_key ? 'Removing...' : 'Uninstall'}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}
