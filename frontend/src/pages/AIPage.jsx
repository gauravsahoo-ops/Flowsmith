import { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import PageHeader from '../components/shared/PageHeader'
import AIArchitectureSection from '../components/AIArchitectureSection'
import AIBuilderConsole from '../components/AIBuilderConsole'
import SmithDrawer from '../components/SmithDrawer'

export default function AIPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const tabParam = searchParams.get('tab')
  const [activeTab, setActiveTab] = useState(
    tabParam === 'capabilities' ? 'capabilities' : 'builder'
  )
  const [smithOpen, setSmithOpen] = useState(false)

  useEffect(() => {
    if (tabParam === 'chat') {
      setSmithOpen(true)
      setActiveTab('builder')
      setSearchParams({ tab: 'builder' })
    } else if (tabParam === 'copilot') {
      setActiveTab('builder')
      setSearchParams({ tab: 'builder' })
    } else if (tabParam === 'capabilities') {
      setActiveTab('capabilities')
    } else {
      setActiveTab('builder')
    }
  }, [tabParam, setSearchParams])

  const [statusInfo, setStatusInfo] = useState({
    configured: false,
    loading: true,
    active: null,
    credentials: [],
  })
  const [selectedCredentialId, setSelectedCredentialId] = useState(null)

  useEffect(() => {
    api.aiStatus()
      .then((res) => {
        setStatusInfo({
          configured: Boolean(res?.configured),
          loading: false,
          active: res?.active || null,
          credentials: res?.credentials || [],
        })
        if (res?.active?.id) {
          setSelectedCredentialId((prev) => prev || res.active.id)
        }
      })
      .catch(() => {
        setStatusInfo({ configured: false, loading: false, active: null, credentials: [] })
      })
  }, [])

  return (
    <div className="page ai-page" style={{ padding: '1.5rem', maxWidth: 1400, margin: '0 auto' }}>
      <PageHeader
        title="AI Workflow Studio"
        description="Plan-to-DAG workflow synthesis, interactive topological simulation, Smith copilot, and enterprise LLM orchestration."
        actions={
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <button
              className="primary"
              onClick={() => setSmithOpen(true)}
              style={{
                fontSize: '12px',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                padding: '6px 14px',
                background: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)',
                border: 'none',
                boxShadow: '0 2px 8px rgba(99, 102, 241, 0.35)',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              <span>💬</span> Ask Smith AI Assistant
            </button>
            {statusInfo.loading ? (
              <span className="badge badge-neutral" style={{ fontSize: '12px' }}>Checking AI status...</span>
            ) : statusInfo.configured ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                    fontSize: '12px',
                    padding: '4px 10px',
                    borderRadius: '20px',
                    background: 'rgba(34, 197, 94, 0.12)',
                    color: '#4ade80',
                    border: '1px solid rgba(34, 197, 94, 0.3)',
                  }}
                >
                  <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#22c55e' }} />
                  {statusInfo.active?.provider?.toUpperCase() || 'LLM'}: {statusInfo.active?.model || 'Connected'}
                </span>
                {statusInfo.credentials?.length > 1 && (
                  <select
                    value={selectedCredentialId || statusInfo.active?.id || ''}
                    onChange={(e) => setSelectedCredentialId(e.target.value)}
                    style={{
                      padding: '4px 8px',
                      fontSize: '12px',
                      borderRadius: '6px',
                      background: 'var(--input-bg, #18181b)',
                      color: 'inherit',
                      border: '1px solid var(--border-color, #3f3f46)',
                    }}
                  >
                    {statusInfo.credentials.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name} ({c.provider} · {c.model})
                      </option>
                    ))}
                  </select>
                )}
              </div>
            ) : (
              <button
                className="ghost"
                onClick={() => navigate('/credentials')}
                style={{
                  fontSize: '12px',
                  color: '#f59e0b',
                  borderColor: 'rgba(245, 158, 11, 0.4)',
                  background: 'rgba(245, 158, 11, 0.08)',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                }}
              >
                <span>⚠️</span> Add LLM Credential
              </button>
            )}
          </div>
        }
      />

      {/* Tabs */}
      <div
        style={{
          display: 'flex',
          gap: '0.5rem',
          borderBottom: '1px solid var(--border-color, #27272a)',
          marginBottom: '1.5rem',
          paddingBottom: '0.5rem',
          flexWrap: 'wrap',
        }}
      >
        <button
          className={activeTab === 'builder' ? 'primary' : 'ghost'}
          onClick={() => { setActiveTab('builder'); setSearchParams({ tab: 'builder' }) }}
          style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.5rem 1rem' }}
        >
          <span>✨</span> AI Workflow Builder (Plan · Simulate · Repair)
        </button>
        <button
          className={activeTab === 'capabilities' ? 'primary' : 'ghost'}
          onClick={() => { setActiveTab('capabilities'); setSearchParams({ tab: 'capabilities' }) }}
          style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.5rem 1rem' }}
        >
          <span>⚡</span> AI Architecture & MCP
        </button>
      </div>

      {/* TAB 1: AI BUILDER CONSOLE */}
      {activeTab === 'builder' && (
        <AIBuilderConsole
          statusInfo={statusInfo}
          selectedCredentialId={selectedCredentialId}
          onSelectCredential={setSelectedCredentialId}
        />
      )}

      {/* TAB 2: AI ARCHITECTURE & MCP */}
      {activeTab === 'capabilities' && <AIArchitectureSection />}

      {/* Universal Smith AI Assistant Drawer */}
      <SmithDrawer isOpen={smithOpen} onClose={() => setSmithOpen(false)} />
    </div>
  )
}
