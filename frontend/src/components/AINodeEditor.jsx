import { useEffect, useState, useMemo, useCallback } from 'react'
import { api } from '../api'
import SearchableSelect from './SearchableSelect'
import LLMCredentialModal from './LLMCredentialModal'

const CAPABILITY_TAGS = [
  { id: 'all', label: 'All Models' },
  { id: 'reasoning', label: '🧠 Reasoning' },
  { id: 'vision', label: '👁 Vision' },
  { id: 'tools', label: '🛠 Tools' },
  { id: 'streaming', label: '⚡ Streaming' },
  { id: '128k', label: '📚 128K+' },
]

export default function AINodeEditor({
  node,
  onParamsChange,
  credentials = [],
  onCredentialChange,
  _mapping = [],
  _onPreview = null,
}) {
  const params = node?.parameters || {}

  // Providers list
  const [providers, setProviders] = useState([])
  const [providersLoading, setProvidersLoading] = useState(false)

  // Selected values
  const currentProviderId = params.provider || 'openai'
  const currentCredentialId = node?.credentials?.llm || ''
  const currentModel = params.model || 'gpt-4o-mini'

  // Model discovery state
  const [models, setModels] = useState([])
  const [modelsLoading, setModelsLoading] = useState(false)
  const [modelFilter, setModelFilter] = useState('all')
  const [_modelsSource, setModelsSource] = useState(null)
  const [customModelMode, setCustomModelMode] = useState(false)

  // Sub-modal state for creating new LLM credential
  const [credModalOpen, setCredModalOpen] = useState(false)

  // Advanced section
  const [showAdvanced, setShowAdvanced] = useState(false)

  // Fetch providers list on mount
  useEffect(() => {
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
  }, [])

  // Filter credentials to matching provider credentials
  const providerCredentials = useMemo(() => {
    return credentials.filter(c => {
      if (c.type !== 'llm') return false
      // Match provider if set in credential data
      if (c.data?.provider && c.data.provider !== currentProviderId) return false
      return true
    })
  }, [credentials, currentProviderId])

  // Load models whenever provider or credential changes
  const fetchModelsForNode = useCallback(async (refresh = false) => {
    setModelsLoading(true)
    try {
      if (currentCredentialId) {
        // Discovered models for saved credential
        const res = await api.getLLMCredentialModels(currentCredentialId, refresh)
        const list = Array.isArray(res) ? res : (res?.data || [])
        if (list.length > 0) {
          setModels(list)
          setModelsSource('credential')
          return
        }
      }

      // If no credential or credential discovery returned empty, discover from provider defaults/catalog
      const res = await api.discoverLLMModels({
        provider: currentProviderId,
        provider_id: currentProviderId,
        refresh,
      })
      const data = res?.data || res
      setModels(data.models || [])
      setModelsSource(data.source || 'catalog')
    } catch (err) {
      console.warn('Failed to load models for AI node', err)
      setCustomModelMode(true)
    } finally {
      setModelsLoading(false)
    }
  }, [currentProviderId, currentCredentialId])

  useEffect(() => {
    fetchModelsForNode(false)
  }, [fetchModelsForNode])

  // Provider options
  const providerOptions = useMemo(() => {
    return providers.map(p => {
      const id = p.id || p.provider_id
      const name = p.name || p.display_name || id
      return {
        value: id,
        label: name,
        category: p.category,
        hint: p.aliases?.slice(0, 2).join(', '),
        meta: p.status === 'SUPPORTED' ? '✓' : p.status,
        aliases: p.aliases || [],
      }
    })
  }, [providers])

  // Credential options
  const credentialOptions = useMemo(() => {
    return providerCredentials.map(c => ({
      value: c.id,
      label: c.name,
      hint: c.data?.selected_model ? `Default model: ${c.data.selected_model}` : '',
      meta: 'LLM Key',
    }))
  }, [providerCredentials])

  // Model options
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

  // Handlers
  const handleProviderChange = (newProviderId) => {
    // Check if current credential belongs to new provider
    const matchingCred = credentials.find(c => c.type === 'llm' && c.data?.provider === newProviderId)
    const newCredId = matchingCred ? matchingCred.id : ''

    if (onCredentialChange) {
      onCredentialChange('llm', newCredId)
    }

    onParamsChange({
      ...params,
      provider: newProviderId,
      model: '', // Clear model so user chooses a valid model for the new provider
    })
  }

  const handleCredentialChange = (newCredId) => {
    if (onCredentialChange) {
      onCredentialChange('llm', newCredId)
    }
    const cred = credentials.find(c => c.id === newCredId)
    if (cred?.data?.selected_model) {
      onParamsChange({
        ...params,
        model: cred.data.selected_model,
      })
    }
  }

  const handleModelChange = (newModel) => {
    onParamsChange({
      ...params,
      model: newModel,
    })
  }

  return (
    <div className="ai-node-editor" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* 1. Provider Selector */}
      <div>
        <label style={{ display: 'block', fontSize: 12.5, fontWeight: 600, marginBottom: 6 }}>
          LLM Provider
        </label>
        <SearchableSelect
          value={currentProviderId}
          onChange={handleProviderChange}
          options={providerOptions}
          placeholder="Search 180+ LLM providers…"
          searchPlaceholder="Search providers by name, category, or alias…"
          loading={providersLoading}
          clearable={false}
        />
      </div>

      {/* 2. Credential Selector */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
          <label style={{ fontSize: 12.5, fontWeight: 600 }}>
            Credential
          </label>
          <button
            type="button"
            onClick={() => setCredModalOpen(true)}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--accent, #818cf8)',
              fontSize: 11.5,
              fontWeight: 500,
              cursor: 'pointer',
              textDecoration: 'underline',
            }}
          >
            + Create New LLM Credential
          </button>
        </div>

        <SearchableSelect
          value={currentCredentialId}
          onChange={handleCredentialChange}
          options={credentialOptions}
          placeholder={providerCredentials.length === 0 ? `No ${currentProviderId} credentials found` : 'Select credential…'}
          searchPlaceholder="Search credentials by name…"
          clearable={true}
          emptyMessage={`No credentials found for ${currentProviderId}. Click "+ Create New" above.`}
          actionLabel="Create new credential"
          onAction={() => setCredModalOpen(true)}
        />
      </div>

      {/* 3. Model Selector & Search */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
          <label style={{ fontSize: 12.5, fontWeight: 600 }}>
            Model
          </label>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <button
              type="button"
              onClick={() => fetchModelsForNode(true)}
              disabled={modelsLoading}
              title="Refresh models from provider"
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--muted, #94a3b8)',
                fontSize: 11.5,
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
              }}
            >
              <span>↻</span>
              <span>{modelsLoading ? 'Loading…' : 'Refresh'}</span>
            </button>
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
              {customModelMode ? 'Select from catalog' : 'Custom model ID'}
            </button>
          </div>
        </div>

        {customModelMode ? (
          <div>
            <input
              value={currentModel}
              onChange={e => handleModelChange(e.target.value)}
              placeholder="e.g. gpt-4o, claude-3-5-sonnet, deepseek-chat…"
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
        ) : (
          <SearchableSelect
            value={currentModel}
            onChange={handleModelChange}
            options={modelOptions}
            placeholder={modelsLoading ? 'Loading models…' : 'Search models…'}
            searchPlaceholder="Search models (e.g. reasoning, vision, 70b, 128k)…"
            loading={modelsLoading}
            filterTags={CAPABILITY_TAGS}
            activeFilter={modelFilter}
            onFilterChange={f => setModelFilter(f)}
            clearable={false}
            allowCustom={true}
            customLabel="Use Model ID"
            onCustomAdd={customId => handleModelChange(customId)}
            emptyMessage={models.length === 0 ? 'No models available. Click refresh or enter custom model ID.' : 'No matching models.'}
          />
        )}
      </div>

      {/* 4. System Prompt */}
      <div>
        <label style={{ display: 'block', fontSize: 12.5, fontWeight: 600, marginBottom: 6 }}>
          System Instructions (Optional)
        </label>
        <textarea
          rows={3}
          value={params.system_prompt || ''}
          placeholder="You are an expert enterprise automation assistant..."
          onChange={e => onParamsChange({ ...params, system_prompt: e.target.value })}
          style={{
            width: '100%',
            padding: '8px 10px',
            fontSize: 12.5,
            borderRadius: 6,
            background: 'var(--bg, #0f172a)',
            border: '1px solid var(--border, rgba(255, 255, 255, 0.12))',
            color: 'var(--text, #f8fafc)',
            resize: 'vertical',
            fontFamily: 'inherit',
            boxSizing: 'border-box',
          }}
        />
      </div>

      {/* 5. User Prompt */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
          <label style={{ fontSize: 12.5, fontWeight: 600 }}>
            Prompt <span style={{ color: 'var(--red, #f87171)' }}>*</span>
          </label>
          <span style={{ fontSize: 11, color: 'var(--muted, #94a3b8)' }}>
            Supports <code>{'{{ $json.fieldName }}'}</code> expressions
          </span>
        </div>
        <textarea
          rows={5}
          value={params.prompt || ''}
          placeholder="Summarize the incoming data: {{ $json.body }}..."
          onChange={e => onParamsChange({ ...params, prompt: e.target.value })}
          style={{
            width: '100%',
            padding: '8px 10px',
            fontSize: 12.5,
            borderRadius: 6,
            background: 'var(--bg, #0f172a)',
            border: '1px solid var(--border, rgba(255, 255, 255, 0.12))',
            color: 'var(--text, #f8fafc)',
            resize: 'vertical',
            fontFamily: 'inherit',
            boxSizing: 'border-box',
          }}
        />
      </div>

      {/* 6. Parameters (Temperature & Max Tokens) */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div>
          <label style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, fontWeight: 500, marginBottom: 4 }}>
            <span>Temperature</span>
            <span style={{ color: 'var(--muted, #94a3b8)' }}>{params.temperature ?? 0.7}</span>
          </label>
          <input
            type="range"
            min="0"
            max="2"
            step="0.1"
            value={params.temperature ?? 0.7}
            onChange={e => onParamsChange({ ...params, temperature: parseFloat(e.target.value) })}
            style={{ width: '100%', accentColor: 'var(--accent, #6366f1)' }}
          />
        </div>

        <div>
          <label style={{ display: 'block', fontSize: 12, fontWeight: 500, marginBottom: 4 }}>
            Max Output Tokens (Optional)
          </label>
          <input
            type="number"
            value={params.max_tokens ?? ''}
            placeholder="e.g. 2048"
            onChange={e => onParamsChange({
              ...params,
              max_tokens: e.target.value ? parseInt(e.target.value, 10) : undefined,
            })}
            style={{
              width: '100%',
              padding: '6px 10px',
              fontSize: 12,
              borderRadius: 6,
              background: 'var(--bg, #0f172a)',
              border: '1px solid var(--border, rgba(255, 255, 255, 0.12))',
              color: 'var(--text, #f8fafc)',
              boxSizing: 'border-box',
            }}
          />
        </div>
      </div>

      {/* 7. Advanced Accordion */}
      <div>
        <button
          type="button"
          onClick={() => setShowAdvanced(!showAdvanced)}
          style={{
            background: 'transparent',
            border: 'none',
            color: 'var(--muted, #94a3b8)',
            fontSize: 12,
            fontWeight: 500,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            padding: 0,
          }}
        >
          <span>{showAdvanced ? '▾' : '▸'}</span>
          <span>Advanced Settings (Response Format, Tools, Base URL)</span>
        </button>

        {showAdvanced && (
          <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 12, padding: 12, borderRadius: 6, background: 'var(--panel-2, rgba(255,255,255,0.03))' }}>
            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 500, marginBottom: 4 }}>
                Response Format
              </label>
              <select
                value={params.response_format?.type || 'text'}
                onChange={e => onParamsChange({
                  ...params,
                  response_format: e.target.value === 'json_object' ? { type: 'json_object' } : undefined,
                })}
                style={{
                  width: '100%',
                  padding: '6px 10px',
                  fontSize: 12,
                  borderRadius: 6,
                  background: 'var(--bg, #0f172a)',
                  border: '1px solid var(--border, rgba(255, 255, 255, 0.12))',
                  color: 'var(--text, #f8fafc)',
                }}
              >
                <option value="text">Text (Default)</option>
                <option value="json_object">JSON Object (Enforce JSON output)</option>
              </select>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 500, marginBottom: 4 }}>
                Custom Base URL Override (Optional)
              </label>
              <input
                value={params.base_url || ''}
                placeholder="Overrides provider default endpoint"
                onChange={e => onParamsChange({ ...params, base_url: e.target.value })}
                style={{
                  width: '100%',
                  padding: '6px 10px',
                  fontSize: 12,
                  borderRadius: 6,
                  background: 'var(--bg, #0f172a)',
                  border: '1px solid var(--border, rgba(255, 255, 255, 0.12))',
                  color: 'var(--text, #f8fafc)',
                  boxSizing: 'border-box',
                }}
              />
            </div>
          </div>
        )}
      </div>

      {/* Embedded LLM Credential Modal */}
      {credModalOpen && (
        <LLMCredentialModal
          open={credModalOpen}
          onClose={() => setCredModalOpen(false)}
          onSuccess={() => {
            setCredModalOpen(false)
            fetchModelsForNode(true)
          }}
        />
      )}
    </div>
  )
}
