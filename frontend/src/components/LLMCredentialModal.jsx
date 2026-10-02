import { useEffect, useState, useMemo } from 'react'
import { api } from '../api'
import { useCredentialStore } from '../stores/credentialStore'
import SearchableSelect from './SearchableSelect'

const CAPABILITY_TAGS = [
  { id: 'all', label: 'All Models' },
  { id: 'reasoning', label: 'Reasoning' },
  { id: 'vision', label: 'Vision' },
  { id: 'tools', label: 'Tool Calling' },
  { id: 'streaming', label: 'Streaming' },
  { id: '128k', label: '128K+ Context' },
]

export default function LLMCredentialModal({
  open,
  onClose,
  initialData = null,
  onSuccess = null,
}) {
  const createCredential = useCredentialStore(s => s.create)
  const loadCredentials = useCredentialStore(s => s.load)

  // Providers list
  const [providers, setProviders] = useState([])
  const [providersLoading, setProvidersLoading] = useState(false)
  const [providerCategory, setProviderCategory] = useState('all')

  // Selected provider & variant
  const [providerId, setProviderId] = useState(initialData?.data?.provider || 'openai')
  const [variant, setVariant] = useState(initialData?.data?.variant || '')

  // Credential fields
  const [name, setName] = useState(initialData?.name || '')
  const [fields, setFields] = useState(initialData?.data || {})
  const [showSecrets, setShowSecrets] = useState({})

  // Connection testing state
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState(null)

  // Model discovery state
  const [models, setModels] = useState([])
  const [modelsLoading, setModelsLoading] = useState(false)
  const [modelsSource, setModelsSource] = useState(null)
  const [selectedModel, setSelectedModel] = useState(initialData?.data?.selected_model || '')
  const [customModelMode, setCustomModelMode] = useState(false)
  const [modelFilter, setModelFilter] = useState('all')

  // Save state
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)

  // Fetch providers on open
  useEffect(() => {
    if (!open) return
    setProvidersLoading(true)
    api.listLLMProviders()
      .then(res => {
        const rawList = Array.isArray(res)
          ? res
          : (res?.providers || res?.data?.providers || res?.data || [])
        const list = rawList.map(p => ({
          ...p,
          id: p.id || p.provider_id,
          name: p.name || p.display_name || p.id || p.provider_id,
        }))
        setProviders(list)
      })
      .catch(err => {
        console.error('Failed to load LLM providers', err)
      })
      .finally(() => setProvidersLoading(false))
  }, [open])

  // Current provider object
  const currentProvider = useMemo(() => {
    return providers.find(p => (p.id || p.provider_id) === providerId) || null
  }, [providers, providerId])

  // Update default fields & variant when provider changes
  useEffect(() => {
    if (!currentProvider) return

    // If initialData matches this provider, restore its values
    if (initialData?.data?.provider === providerId) {
      setFields(initialData.data)
      setVariant(initialData.data.variant || '')
      setSelectedModel(initialData.data.selected_model || '')
      return
    }

    // Set default variant if available
    if (currentProvider.variants && currentProvider.variants.length > 0) {
      setVariant(currentProvider.variants[0].id)
    } else {
      setVariant('')
    }

    // Default credential fields
    const initialFieldVals = {}
    if (currentProvider.credential_fields) {
      for (const f of currentProvider.credential_fields) {
        if (f.default !== undefined) initialFieldVals[f.key] = f.default
      }
    }
    if (currentProvider.base_url) {
      initialFieldVals.base_url = currentProvider.base_url
    }
    setFields(initialFieldVals)

    // Suggest default name if empty or default
    if (!name || name.includes('Credential') || name.includes('OpenAI')) {
      setName(`${currentProvider.name} Credential`)
    }

    // Reset models & test results
    setTestResult(null)
    setModels([])
    setSelectedModel('')
    setModelsSource(null)
  }, [currentProvider, providerId])

  // If initialData has models or saved credentials, load discovered models
  useEffect(() => {
    if (open && initialData?.id && initialData?.type === 'llm') {
      api.getLLMCredentialModels(initialData.id)
        .then(res => {
          const list = Array.isArray(res) ? res : (res?.data || [])
          if (list.length > 0) {
            setModels(list)
            setModelsSource('cache')
          }
        })
        .catch(() => {})
    }
  }, [open, initialData])

  // Categories list
  const _categories = useMemo(() => {
    const set = new Set()
    for (const p of providers) {
      if (p.category) set.add(p.category)
    }
    return ['all', ...Array.from(set).sort()]
  }, [providers])

  // Provider options for SearchableSelect
  const providerOptions = useMemo(() => {
    return providers
      .filter(p => providerCategory === 'all' || p.category === providerCategory)
      .map(p => {
        const id = p.id || p.provider_id
        const name = p.name || p.display_name || id
        return {
          value: id,
          label: name,
          category: p.category,
          hint: p.aliases?.length ? `Also: ${p.aliases.slice(0, 3).join(', ')}` : '',
          meta: p.status === 'SUPPORTED' ? 'Supported' : p.status === 'CUSTOM_ONLY' ? 'Custom' : p.status,
          aliases: p.aliases || [],
        }
      })
  }, [providers, providerCategory])

  // Test Connection
  const handleTestConnection = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const payload = {
        provider: providerId,
        provider_id: providerId,
        variant,
        data: { ...fields },
        ...fields,
        ...(initialData?.id ? { credential_id: initialData.id } : {}),
      }
      const res = await api.testLLMConnection(payload)
      const data = res?.data || res
      setTestResult(data)

      // If connection succeeded and we don't have models yet, auto-fetch models
      if (data.ok && models.length === 0) {
        handleFetchModels(false)
      }
    } catch (err) {
      setTestResult({
        ok: false,
        error_code: 'CONNECTION_FAILED',
        message: err.message || 'Connection test failed. Please verify your credentials.',
      })
    } finally {
      setTesting(false)
    }
  }

  // Fetch / Refresh Models
  const handleFetchModels = async (forceRefresh = true) => {
    setModelsLoading(true)
    try {
      const payload = {
        provider: providerId,
        provider_id: providerId,
        variant,
        data: { ...fields },
        ...fields,
        refresh: forceRefresh,
        ...(initialData?.id ? { credential_id: initialData.id } : {}),
      }
      const res = await api.discoverLLMModels(payload)
      const data = res?.data || res
      const modelList = data.models || []
      setModels(modelList)
      setModelsSource(data.source || 'api')

      // Select first model if none selected
      if (!selectedModel && modelList.length > 0) {
        setSelectedModel(modelList[0].id)
      }
    } catch (err) {
      console.error('Failed to discover models', err)
      // If error, fall back to manual entry
      setCustomModelMode(true)
    } finally {
      setModelsLoading(false)
    }
  }

  // Model options for SearchableSelect
  const modelOptions = useMemo(() => {
    return models.map(m => {
      const tags = []
      if (m.capabilities?.reasoning) tags.push('Reasoning')
      if (m.capabilities?.vision) tags.push('Vision')
      if (m.capabilities?.tools) tags.push('Tools')
      if (m.capabilities?.streaming) tags.push('Streaming')

      let ctx = ''
      if (m.contextWindow) {
        if (m.contextWindow >= 1000000) ctx = `${Math.round(m.contextWindow / 1000000)}M context`
        else if (m.contextWindow >= 1000) ctx = `${Math.round(m.contextWindow / 1000)}K context`
        else ctx = `${m.contextWindow} context`
      }

      return {
        value: m.id,
        label: m.name || m.id,
        hint: m.description || m.id,
        tags,
        meta: ctx,
        capabilities: {
          reasoning: !!m.capabilities?.reasoning,
          vision: !!m.capabilities?.vision,
          tools: !!m.capabilities?.tools,
          streaming: !!m.capabilities?.streaming,
          '128k': (m.contextWindow || 0) >= 128000,
        },
      }
    })
  }, [models])

  // Save Credential
  const handleSave = async (e) => {
    e?.preventDefault()
    if (!name.trim()) {
      setSaveError('Please enter a credential name.')
      return
    }

    setSaving(true)
    setSaveError(null)

    try {
      const credPayload = {
        name: name.trim(),
        type: 'llm',
        data: {
          provider: providerId,
          variant: variant || undefined,
          selected_model: selectedModel || undefined,
          ...fields,
        },
      }

      if (initialData?.id) {
        await api.updateCredential(initialData.id, credPayload)
      } else {
        await createCredential(credPayload)
      }

      await loadCredentials()
      if (onSuccess) onSuccess()
      onClose()
    } catch (err) {
      setSaveError(err.message || 'Failed to save credential.')
    } finally {
      setSaving(false)
    }
  }

  if (!open) return null

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="llm-cred-modal-title"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'rgba(0, 0, 0, 0.75)',
        backdropFilter: 'blur(6px)',
        padding: 16,
      }}
      onClick={onClose}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: '100%',
          maxWidth: 680,
          maxHeight: '92vh',
          background: 'var(--panel, #1e293b)',
          border: '1px solid var(--border, rgba(255, 255, 255, 0.15))',
          borderRadius: 14,
          boxShadow: '0 24px 60px rgba(0, 0, 0, 0.6)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          color: 'var(--text, #f8fafc)',
        }}
      >
        {/* Modal Header */}
        <header
          style={{
            padding: '16px 20px',
            borderBottom: '1px solid var(--border, rgba(255, 255, 255, 0.1))',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: 'linear-gradient(180deg, rgba(99, 102, 241, 0.08) 0%, transparent 100%)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div
              style={{
                width: 38,
                height: 38,
                borderRadius: 8,
                background: 'rgba(255, 255, 255, 0.06)',
                border: '1px solid var(--border, rgba(255, 255, 255, 0.1))',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--text)',
              }}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
            </div>
            <div>
              <h2 id="llm-cred-modal-title" style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>
                {initialData ? 'Configure LLM Provider Credential' : 'Create LLM Provider Credential'}
              </h2>
              <div style={{ fontSize: 12, color: 'var(--muted, #94a3b8)', marginTop: 2 }}>
                Connect to 180+ LLM providers with automatic model discovery and live testing.
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--muted, #94a3b8)',
              cursor: 'pointer',
              padding: 6,
              borderRadius: 6,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
            aria-label="Close modal"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </header>

        {/* Modal Body */}
        <div style={{ padding: '20px', overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: 20 }}>
          {/* STEP 1: Select Provider */}
          <section>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <label style={{ fontSize: 13, fontWeight: 600 }}>1. LLM Provider</label>
              <div style={{ display: 'flex', gap: 4 }}>
                {['all', 'Major Providers', 'LLM Gateways', 'Inference Providers'].map(cat => (
                  <button
                    key={cat}
                    type="button"
                    onClick={() => setProviderCategory(cat)}
                    style={{
                      padding: '2px 8px',
                      fontSize: 11,
                      borderRadius: 10,
                      background: providerCategory === cat ? 'rgba(99, 102, 241, 0.2)' : 'transparent',
                      border: providerCategory === cat ? '1px solid var(--accent, #6366f1)' : '1px solid transparent',
                      color: providerCategory === cat ? 'var(--accent, #818cf8)' : 'var(--muted, #94a3b8)',
                      cursor: 'pointer',
                    }}
                  >
                    {cat === 'all' ? 'All' : cat}
                  </button>
                ))}
              </div>
            </div>

            <SearchableSelect
              value={providerId}
              onChange={val => setProviderId(val)}
              options={providerOptions}
              placeholder="Search 180+ LLM providers (e.g. OpenAI, DeepSeek, Groq, Ollama)…"
              searchPlaceholder="Search providers by name, alias, category, or region…"
              loading={providersLoading}
              clearable={false}
            />

            {/* Provider Variant Selector (if applicable) */}
            {currentProvider?.variants?.length > 0 && (
              <div style={{ marginTop: 10 }}>
                <label style={{ display: 'block', fontSize: 12, color: 'var(--muted, #94a3b8)', marginBottom: 4 }}>
                  Regional / Plan Variant
                </label>
                <select
                  value={variant}
                  onChange={e => setVariant(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 10px',
                    fontSize: 12.5,
                    borderRadius: 6,
                    background: 'var(--bg, #0f172a)',
                    border: '1px solid var(--border, rgba(255, 255, 255, 0.12))',
                    color: 'var(--text, #f8fafc)',
                  }}
                >
                  {currentProvider.variants.map(v => (
                    <option key={v.id} value={v.id}>
                      {v.name} ({v.region || 'Standard'}) — {v.endpoint}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </section>

          {/* STEP 2: Credential Fields */}
          <section style={{ background: 'var(--panel-2, rgba(255, 255, 255, 0.03))', padding: 14, borderRadius: 8, border: '1px solid var(--border, rgba(255, 255, 255, 0.08))' }}>
            <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 12 }}>
              2. Credentials & Authentication ({currentProvider?.name || 'Provider'})
            </label>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {/* Dynamic fields from provider schema */}
              {currentProvider?.credential_fields?.map(field => {
                const isSecret = field.secret
                const showSec = showSecrets[field.key]
                return (
                  <div key={field.key}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                      <label style={{ fontSize: 12, fontWeight: 500 }}>
                        {field.label} {field.required && <span style={{ color: 'var(--red, #f87171)' }}>*</span>}
                      </label>
                      {isSecret && (
                        <button
                          type="button"
                          onClick={() => setShowSecrets(prev => ({ ...prev, [field.key]: !showSec }))}
                          style={{
                            background: 'transparent',
                            border: 'none',
                            color: 'var(--muted, #94a3b8)',
                            fontSize: 11,
                            cursor: 'pointer',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 4,
                          }}
                        >
                          {showSec ? (
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
                      )}
                    </div>

                    <div style={{ position: 'relative' }}>
                      <input
                        type={isSecret && !showSec ? 'password' : 'text'}
                        value={fields[field.key] || ''}
                        placeholder={field.placeholder || ''}
                        onChange={e => setFields(prev => ({ ...prev, [field.key]: e.target.value }))}
                        style={{
                          width: '100%',
                          padding: '8px 10px',
                          fontSize: 12.5,
                          borderRadius: 6,
                          background: 'var(--bg, #0f172a)',
                          border: '1px solid var(--border, rgba(255, 255, 255, 0.12))',
                          color: 'var(--text, #f8fafc)',
                          boxSizing: 'border-box',
                        }}
                      />
                    </div>
                    {field.description && (
                      <div style={{ fontSize: 11, color: 'var(--muted, #94a3b8)', marginTop: 3 }}>
                        {field.description}
                      </div>
                    )}
                  </div>
                )
              })}

              {/* If custom provider, provide extra configurable fields */}
              {providerId === 'custom' && (
                <>
                  <div>
                    <label style={{ display: 'block', fontSize: 12, fontWeight: 500, marginBottom: 4 }}>
                      Models Discovery Endpoint (Optional)
                    </label>
                    <input
                      value={fields.models_endpoint || ''}
                      placeholder="/v1/models"
                      onChange={e => setFields(prev => ({ ...prev, models_endpoint: e.target.value }))}
                      style={{
                        width: '100%',
                        padding: '8px 10px',
                        fontSize: 12.5,
                        borderRadius: 6,
                        background: 'var(--bg, #0f172a)',
                        border: '1px solid var(--border, rgba(255, 255, 255, 0.12))',
                        color: 'var(--text, #f8fafc)',
                      }}
                    />
                  </div>
                  <div>
                    <label style={{ display: 'block', fontSize: 12, fontWeight: 500, marginBottom: 4 }}>
                      Chat Completion Endpoint (Optional)
                    </label>
                    <input
                      value={fields.chat_endpoint || ''}
                      placeholder="/v1/chat/completions"
                      onChange={e => setFields(prev => ({ ...prev, chat_endpoint: e.target.value }))}
                      style={{
                        width: '100%',
                        padding: '8px 10px',
                        fontSize: 12.5,
                        borderRadius: 6,
                        background: 'var(--bg, #0f172a)',
                        border: '1px solid var(--border, rgba(255, 255, 255, 0.12))',
                        color: 'var(--text, #f8fafc)',
                      }}
                    />
                  </div>
                </>
              )}
            </div>

            {/* Test Connection Button & Status Banner */}
            <div style={{ marginTop: 14, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <button
                type="button"
                onClick={handleTestConnection}
                disabled={testing}
                style={{
                  padding: '7px 14px',
                  borderRadius: 6,
                  background: 'var(--panel, #1e293b)',
                  border: '1px solid var(--border, rgba(255, 255, 255, 0.2))',
                  color: 'var(--text, #f8fafc)',
                  fontSize: 12.5,
                  fontWeight: 600,
                  cursor: testing ? 'not-allowed' : 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  transition: 'background 0.15s',
                }}
              >
                {testing ? (
                  <>
                    <span className="spinner-sm" style={{ width: 12, height: 12 }} />
                    <span>Testing Connection…</span>
                  </>
                ) : (
                  <>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
                    <span>Test Connection</span>
                  </>
                )}
              </button>

              <button
                type="button"
                onClick={() => handleFetchModels(true)}
                disabled={modelsLoading}
                style={{
                  padding: '7px 14px',
                  borderRadius: 6,
                  background: 'rgba(99, 102, 241, 0.15)',
                  border: '1px solid var(--accent, #6366f1)',
                  color: 'var(--accent, #818cf8)',
                  fontSize: 12.5,
                  fontWeight: 600,
                  cursor: modelsLoading ? 'not-allowed' : 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                }}
              >
                {modelsLoading ? (
                  <>
                    <span className="spinner-sm" style={{ width: 12, height: 12 }} />
                    <span>Fetching Models…</span>
                  </>
                ) : (
                  <>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/></svg>
                    <span>{models.length > 0 ? 'Refresh Models' : 'Fetch Models'}</span>
                  </>
                )}
              </button>
            </div>

            {/* Test result output */}
            {testResult && (
              <div
                style={{
                  marginTop: 12,
                  padding: '10px 12px',
                  borderRadius: 6,
                  fontSize: 12,
                  background: testResult.ok ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                  border: testResult.ok ? '1px solid rgba(16, 185, 129, 0.3)' : '1px solid rgba(239, 68, 68, 0.3)',
                  color: testResult.ok ? '#34d399' : '#f87171',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    {testResult.ok ? (
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                    ) : (
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                    )}
                  </span>
                  <div>
                    <strong>{testResult.ok ? 'Connection Verified' : (testResult.error_code || 'Test Failed')}</strong>
                    <div style={{ color: 'var(--text, #f8fafc)', opacity: 0.9, marginTop: 1 }}>
                      {testResult.message}
                    </div>
                  </div>
                </div>
                {testResult.latency_ms && (
                  <span style={{ fontSize: 11, opacity: 0.75, flexShrink: 0 }}>
                    {testResult.latency_ms}ms
                  </span>
                )}
              </div>
            )}
          </section>

          {/* STEP 3: Model Selection & Discovery */}
          <section>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <label style={{ fontSize: 13, fontWeight: 600 }}>
                3. Preferred Model
              </label>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {modelsSource && (
                  <span
                    style={{
                      fontSize: 10.5,
                      padding: '2px 7px',
                      borderRadius: 10,
                      background: modelsSource === 'api' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(245, 158, 11, 0.15)',
                      color: modelsSource === 'api' ? '#34d399' : '#fbbf24',
                      border: modelsSource === 'api' ? '1px solid rgba(16, 185, 129, 0.3)' : '1px solid rgba(245, 158, 11, 0.3)',
                    }}
                  >
                    Source: {modelsSource === 'api' ? 'Live Provider API' : 'FlowSmith Catalog'}
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => setCustomModelMode(!customModelMode)}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: 'var(--accent, #818cf8)',
                    fontSize: 11.5,
                    cursor: 'pointer',
                    textDecoration: 'underline',
                  }}
                >
                  {customModelMode ? 'Choose from list' : '+ Enter custom model ID'}
                </button>
              </div>
            </div>

            {customModelMode ? (
              <div>
                <input
                  value={selectedModel}
                  onChange={e => setSelectedModel(e.target.value)}
                  placeholder="e.g. gpt-4o, claude-3-5-sonnet, deepseek-r1, llama-3.3-70b…"
                  style={{
                    width: '100%',
                    padding: '8px 10px',
                    fontSize: 13,
                    borderRadius: 6,
                    background: 'var(--bg, #0f172a)',
                    border: '1px solid var(--border, rgba(255, 255, 255, 0.12))',
                    color: 'var(--text, #f8fafc)',
                  }}
                />
                <div style={{ fontSize: 11, color: 'var(--muted, #94a3b8)', marginTop: 4 }}>
                  Enter any valid model identifier supported by your provider endpoint.
                </div>
              </div>
            ) : (
              <SearchableSelect
                value={selectedModel}
                onChange={val => setSelectedModel(val)}
                options={modelOptions}
                placeholder={modelsLoading ? 'Loading models…' : models.length > 0 ? 'Select a model…' : 'Click "Fetch Models" or enter custom ID'}
                searchPlaceholder="Search models (e.g. reasoning, vision, 70b, 128k)…"
                loading={modelsLoading}
                filterTags={CAPABILITY_TAGS}
                activeFilter={modelFilter}
                onFilterChange={f => setModelFilter(f)}
                clearable={true}
                allowCustom={true}
                customLabel="Use Model ID"
                onCustomAdd={customId => setSelectedModel(customId)}
                emptyMessage={models.length === 0 ? 'No models loaded yet. Click "Fetch Models" above.' : 'No models match your search.'}
              />
            )}
          </section>

          {/* STEP 4: Credential Name */}
          <section>
            <label style={{ display: 'block', fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
              4. Credential Name
            </label>
            <input
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="e.g. Production OpenAI, Client Dev OpenRouter…"
              style={{
                width: '100%',
                padding: '8px 10px',
                fontSize: 13,
                borderRadius: 6,
                background: 'var(--bg, #0f172a)',
                border: '1px solid var(--border, rgba(255, 255, 255, 0.12))',
                color: 'var(--text, #f8fafc)',
              }}
            />
          </section>

          {saveError && (
            <div style={{ padding: '8px 12px', borderRadius: 6, background: 'rgba(239, 68, 68, 0.1)', color: '#f87171', fontSize: 12, border: '1px solid rgba(239, 68, 68, 0.3)' }}>
              {saveError}
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <footer
          style={{
            padding: '14px 20px',
            borderTop: '1px solid var(--border, rgba(255, 255, 255, 0.1))',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: 'var(--panel-2, #182234)',
          }}
        >
          <div style={{ fontSize: 11.5, color: 'var(--muted, #94a3b8)', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
            <span>Credentials are encrypted at rest with AES-256 / Fernet.</span>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              type="button"
              onClick={onClose}
              style={{
                padding: '8px 16px',
                borderRadius: 6,
                background: 'transparent',
                border: '1px solid var(--border, rgba(255, 255, 255, 0.2))',
                color: 'var(--text, #f8fafc)',
                fontSize: 13,
                cursor: 'pointer',
              }}
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              style={{
                padding: '8px 20px',
                borderRadius: 6,
                background: 'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)',
                border: 'none',
                color: '#ffffff',
                fontSize: 13,
                fontWeight: 600,
                cursor: saving ? 'not-allowed' : 'pointer',
                boxShadow: '0 2px 8px rgba(99, 102, 241, 0.4)',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              {saving ? 'Saving…' : 'Save Credential'}
            </button>
          </div>
        </footer>
      </div>
    </div>
  )
}
