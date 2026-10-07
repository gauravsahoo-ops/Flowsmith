import { useEffect, useState, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useCredentialStore } from '../stores/credentialStore'
import PageHeader from '../components/shared/PageHeader'
import LoadingSkeleton from '../components/shared/LoadingSkeleton'
import EmptyState from '../components/shared/EmptyState'
import { NodeIcon } from '../components/NodeIcons'
import OpenApiImportModal from '../components/OpenApiImportModal'
import CoverageDashboard from '../components/CoverageDashboard'

export const CATEGORIES = [
  { id: 'all', label: 'All Integrations' },
  { id: 'crm', label: 'CRM & Sales' },
  { id: 'database', label: 'Databases & Storage' },
  { id: 'communication', label: 'Communication' },
  { id: 'developer', label: 'Developer & DevOps' },
  { id: 'ai', label: 'AI & Knowledge' },
  { id: 'productivity', label: 'Productivity' },
  { id: 'finance', label: 'Finance & Payments' },
]

export const CONNECTOR_CATEGORY_MAP = {
  // CRM & Sales
  salesforce: ['crm'],
  hubspot: ['crm'],
  dynamics_crm: ['crm'],
  freshsales: ['crm'],
  zoho_crm: ['crm'],
  pipedrive: ['crm', 'productivity'],
  activecampaign: ['crm', 'communication'],
  workday: ['crm'],
  zendesk: ['crm', 'communication'],
  freshdesk: ['crm', 'communication'],
  intercom: ['crm', 'communication'],

  // Databases & Storage
  postgres: ['database'],
  mysql: ['database'],
  mongodb: ['database'],
  redis: ['database'],
  supabase: ['database'],
  snowflake: ['database'],
  bigquery: ['database'],
  s3: ['database'],
  google_drive: ['database', 'productivity'],
  dropbox: ['database', 'productivity'],
  box: ['database', 'productivity'],
  pinecone: ['database', 'ai'],
  airtable: ['database', 'productivity'],

  // Communication
  slack: ['communication'],
  discord: ['communication'],
  msteams: ['communication'],
  whatsapp: ['communication'],
  twilio: ['communication'],
  zoom: ['communication'],
  gmail: ['communication'],
  outlook: ['communication'],
  resend: ['communication'],
  sendgrid: ['communication'],
  mailchimp: ['communication', 'crm'],
  brevo: ['communication', 'crm'],

  // Developer & DevOps
  github: ['developer'],
  gitlab: ['developer'],
  bitbucket: ['developer'],
  sentry: ['developer'],
  pagerduty: ['developer'],
  http: ['developer'],
  httpbin: ['developer'],
  dummy_json: ['developer'],
  json_placeholder: ['developer'],
  poke_api: ['developer'],
  open_notify: ['developer'],
  schedule: ['developer'],
  webhook: ['developer'],

  // AI & Knowledge
  openai: ['ai'],
  anthropic: ['ai'],
  gemini: ['ai'],
  open_router: ['ai'],

  // Productivity
  notion: ['productivity'],
  jira: ['productivity', 'developer'],
  linear: ['productivity', 'developer'],
  asana: ['productivity'],
  clickup: ['productivity'],
  monday: ['productivity'],
  trello: ['productivity'],
  todoist: ['productivity'],
  coda: ['productivity'],
  google_docs: ['productivity'],
  google_sheets: ['productivity'],
  google_calendar: ['productivity'],
  calendly: ['productivity'],
  docusign: ['productivity'],
  servicenow: ['productivity'],
  typeform: ['productivity'],

  // Finance & Payments
  stripe: ['finance'],
  shopify: ['finance'],
  quickbooks: ['finance'],
  xero: ['finance'],
  netsuite: ['finance'],
  sap: ['finance'],
  frankfurter: ['finance'],
  coin_gecko: ['finance'],
}

export function matchesCategory(conn, catId) {
  if (!catId || catId === 'all') return true
  const key = (conn.connector_key || '').toLowerCase()
  const mapped = CONNECTOR_CATEGORY_MAP[key]
  if (mapped && mapped.includes(catId)) return true
  if (key.startsWith('open_meteo') && catId === 'developer') return true

  const cat = (conn.category || '').toLowerCase()
  if (catId === 'crm') return cat.includes('crm') || cat.includes('sales') || cat.includes('support')
  if (catId === 'database') return cat.includes('data') || cat.includes('storage') || cat.includes('sql')
  if (catId === 'communication') return cat.includes('comm') || cat.includes('message') || cat.includes('mail') || cat.includes('marketing')
  if (catId === 'developer') return cat.includes('dev') || cat.includes('git') || cat.includes('code') || cat.includes('api') || cat.includes('devops')
  if (catId === 'ai') return cat.includes('ai') || cat.includes('rag') || cat.includes('llm')
  if (catId === 'productivity') return cat.includes('prod') || cat.includes('task') || cat.includes('work') || cat.includes('doc')
  if (catId === 'finance') return cat.includes('finance') || cat.includes('payment') || cat.includes('billing')
  return cat.includes(catId)
}

export default function IntegrationsPage() {
  const navigate = useNavigate()
  const [connectors, setConnectors] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('all')
  const [selectedConnector, setSelectedConnector] = useState(null)
  const [openApiModalOpen, setOpenApiModalOpen] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [fullDetail, setFullDetail] = useState(null)
  const [mainTab, setMainTab] = useState('marketplace')

  const credentials = useCredentialStore((s) => s.credentials)
  const loadCredentials = useCredentialStore((s) => s.load)

  useEffect(() => {
    loadCredentials().catch(() => {})
    api
      .listConnectors()
      .then((res) => {
        const list = Array.isArray(res) ? res : (res && res.data) || []
        setConnectors(list)
      })
      .catch((err) => {
        setError(err.message || 'Failed to load connectors.')
      })
      .finally(() => setLoading(false))
  }, [loadCredentials])

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        setSelectedConnector(null)
        setOpenApiModalOpen(false)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  // Map user credential types to know which connectors have active connections
  const connectedTypes = useMemo(() => {
    const s = new Set()
    for (const c of credentials || []) {
      if (c.type) s.add(c.type.toLowerCase())
    }
    return s
  }, [credentials])

  const categoryCounts = useMemo(() => {
    const counts = { all: connectors.length }
    for (const cat of CATEGORIES) {
      if (cat.id === 'all') continue
      counts[cat.id] = connectors.filter((c) => matchesCategory(c, cat.id)).length
    }
    return counts
  }, [connectors])

  const filtered = useMemo(() => {
    let list = connectors
    if (category !== 'all') {
      list = list.filter((c) => matchesCategory(c, category))
    }
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      list = list.filter(
        (c) =>
          (c.display_name || '').toLowerCase().includes(q) ||
          (c.connector_key || '').toLowerCase().includes(q) ||
          (c.description || '').toLowerCase().includes(q) ||
          (Array.isArray(c.operations) && c.operations.some((op) => op.toLowerCase().includes(q)))
      )
    }
    return list
  }, [connectors, category, search])

  const handleSelectConnector = (conn) => {
    setSelectedConnector(conn)
    setDetailLoading(true)
    api
      .getConnector(conn.connector_key)
      .then((data) => setFullDetail(data))
      .catch(() => setFullDetail(null))
      .finally(() => setDetailLoading(false))
  }

  const isConnected = (conn) => {
    const key = (conn.connector_key || '').toLowerCase()
    if (connectedTypes.has(key)) return true
    if (conn.credential_types && Array.isArray(conn.credential_types)) {
      return conn.credential_types.some((ct) => connectedTypes.has(ct.toLowerCase()))
    }
    return false
  }

  return (
    <div className="page integrations-page" style={{ padding: '1.5rem', maxWidth: 1400, margin: '0 auto' }}>
      <PageHeader
        title="Integrations & Marketplace"
        subtitle="Discover, configure, and connect 45+ enterprise integrations, APIs, and custom OpenAPI endpoints."
        actions={
          <div style={{ display: 'flex', gap: '0.75rem' }}>
            <button
              className="ghost"
              onClick={() => setOpenApiModalOpen(true)}
              style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
              Import OpenAPI / Swagger
            </button>
            <button
              className="primary"
              onClick={() => navigate('/credentials')}
              style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 2l-2 2m-1.5 1.5L14 9l-3-3 2.5-2.5a2.12 2.12 0 0 1 3 0l4.5 4.5" />
                <path d="M15.5 10.5L8 18l-3-1-1 3 3 1 1-3 7.5-7.5" />
              </svg>
              Manage Credentials
            </button>
          </div>
        }
      />

      {/* Primary View Switcher */}
      <div style={{ display: 'flex', gap: '0.5rem', margin: '1.25rem 0 1rem 0', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '0.75rem' }}>
        <button
          className={mainTab === 'marketplace' ? 'primary' : 'ghost'}
          onClick={() => setMainTab('marketplace')}
          style={{ fontSize: '13px', padding: '0.5rem 1.1rem', borderRadius: 8, display: 'inline-flex', alignItems: 'center', gap: '6px' }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="2" y="2" width="20" height="8" rx="2" ry="2" />
            <rect x="2" y="14" width="20" height="8" rx="2" ry="2" />
            <line x1="6" y1="6" x2="6.01" y2="6" />
            <line x1="6" y1="18" x2="6.01" y2="18" />
          </svg>
          Connectors Directory ({connectors.length})
        </button>
        <button
          className={mainTab === 'coverage' ? 'primary' : 'ghost'}
          onClick={() => setMainTab('coverage')}
          style={{ fontSize: '13px', padding: '0.5rem 1.1rem', borderRadius: 8, display: 'inline-flex', alignItems: 'center', gap: '6px' }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="20" x2="18" y2="10" />
            <line x1="12" y1="20" x2="12" y2="4" />
            <line x1="6" y1="20" x2="6" y2="14" />
          </svg>
          Enterprise Capability & Coverage Matrix
        </button>
      </div>

      {mainTab === 'coverage' ? (
        <CoverageDashboard />
      ) : (
        <>
          {/* Filter Toolbar */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '1rem', alignItems: 'center', margin: '1.5rem 0' }}>
        <div className="marketplace-search" style={{ flex: '1 1 320px', minWidth: 260 }}>
          <input
            type="search"
            className="input marketplace-search-input"
            placeholder="Search by name, action, or provider (e.g. Salesforce, Slack, Postgres)..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ width: '100%', padding: '0.65rem 1rem', borderRadius: 8 }}
          />
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
          {CATEGORIES.map((cat) => (
            <button
              key={cat.id}
              onClick={() => setCategory(cat.id)}
              className={category === cat.id ? 'primary' : 'ghost'}
              style={{
                fontSize: '12px',
                padding: '0.4rem 0.8rem',
                borderRadius: '20px',
                transition: 'all 0.15s ease',
              }}
            >
              {cat.label}
              {categoryCounts[cat.id] !== undefined && (
                <span
                  style={{
                    marginLeft: '6px',
                    opacity: category === cat.id ? 0.9 : 0.6,
                    fontSize: '11px',
                    fontWeight: 500,
                  }}
                >
                  ({categoryCounts[cat.id]})
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Loading & Error States */}
      {loading && <LoadingSkeleton lines={8} />}
      {error && (
        <div className="card" style={{ padding: '2rem', textAlign: 'center', borderColor: '#ef4444' }}>
          <p style={{ color: '#ef4444', fontWeight: 600 }}>{error}</p>
          <button className="ghost" onClick={() => window.location.reload()} style={{ marginTop: '1rem' }}>
            Retry Loading
          </button>
        </div>
      )}

      {/* Empty State */}
      {!loading && !error && filtered.length === 0 && (
        <EmptyState
          title="No integrations matched your query"
          message="Try searching for another service or import any custom REST API using our OpenAPI importer."
          actionLabel="Import Custom API"
          onAction={() => setOpenApiModalOpen(true)}
        />
      )}

      {/* Grid of Connectors */}
      {!loading && !error && filtered.length > 0 && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(310px, 1fr))',
            gap: '1.25rem',
          }}
        >
          {filtered.map((conn) => {
            const connected = isConnected(conn)
            const opCount = Array.isArray(conn.operations) ? conn.operations.length : 0
            const trigCount = Array.isArray(conn.triggers) ? conn.triggers.length : 0
            return (
              <div
                key={conn.connector_key}
                className="card connector-card"
                onClick={() => handleSelectConnector(conn)}
                style={{
                  padding: '1.25rem',
                  display: 'flex',
                  flexDirection: 'column',
                  cursor: 'pointer',
                  borderRadius: 10,
                  border: '1px solid rgba(255, 255, 255, 0.08)',
                  background: 'rgba(255, 255, 255, 0.02)',
                  transition: 'all 0.2s ease',
                  position: 'relative',
                  overflow: 'hidden',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.transform = 'translateY(-2px)'
                  e.currentTarget.style.borderColor = 'rgba(16, 185, 129, 0.4)'
                  e.currentTarget.style.background = 'rgba(255, 255, 255, 0.04)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.transform = 'translateY(0)'
                  e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.08)'
                  e.currentTarget.style.background = 'rgba(255, 255, 255, 0.02)'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    <div
                      style={{
                        width: 44,
                        height: 44,
                        borderRadius: 10,
                        background: 'rgba(255, 255, 255, 0.06)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        border: '1px solid rgba(255, 255, 255, 0.1)',
                      }}
                    >
                      <NodeIcon type={conn.connector_key} name={conn.display_name} icon={conn.icon} size={28} />
                    </div>
                    <div>
                      <h3 style={{ margin: 0, fontSize: '15px', fontWeight: 600, color: '#f8fafc' }}>
                        {conn.display_name}
                      </h3>
                      <span style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'capitalize' }}>
                        {conn.category || 'General'}
                      </span>
                    </div>
                  </div>
                  {connected ? (
                    <span
                      style={{
                        fontSize: '11px',
                        padding: '2px 8px',
                        borderRadius: '12px',
                        background: 'rgba(16, 185, 129, 0.15)',
                        color: '#34d399',
                        border: '1px solid rgba(16, 185, 129, 0.3)',
                        fontWeight: 600,
                      }}
                    >
                      Connected
                    </span>
                  ) : (
                    <span
                      style={{
                        fontSize: '11px',
                        padding: '2px 8px',
                        borderRadius: '12px',
                        background: 'rgba(148, 163, 184, 0.1)',
                        color: '#94a3b8',
                      }}
                    >
                      v{conn.connector_version || '1.0'}
                    </span>
                  )}
                </div>

                <p
                  style={{
                    fontSize: '13px',
                    color: '#94a3b8',
                    lineHeight: '1.45',
                    margin: '0 0 1rem 0',
                    flex: '1 1 auto',
                    display: '-webkit-box',
                    WebkitLineClamp: 2,
                    WebkitBoxOrient: 'vertical',
                    overflow: 'hidden',
                  }}
                >
                  {conn.description || `Integrate with ${conn.display_name} to trigger workflows and run automated operations.`}
                </p>

                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    paddingTop: '0.75rem',
                    borderTop: '1px solid rgba(255, 255, 255, 0.05)',
                    fontSize: '12px',
                    color: '#64748b',
                  }}
                >
                  <div style={{ display: 'flex', gap: '0.85rem', alignItems: 'center' }}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ opacity: 0.7 }}>
                        <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                      </svg>
                      {opCount} action{opCount !== 1 ? 's' : ''}
                    </span>
                    {trigCount > 0 && (
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ opacity: 0.7 }}>
                          <polyline points="22 12 16 12 14 15 10 15 8 12 2 12" />
                          <path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
                        </svg>
                        {trigCount} trigger{trigCount !== 1 ? 's' : ''}
                      </span>
                    )}
                  </div>
                  <span style={{ color: '#38bdf8', fontWeight: 500 }}>Trace →</span>
                </div>
              </div>
            )
          })}
        </div>
      )}
        </>
      )}

      {/* Detail Modal / Drawer */}
      {selectedConnector && createPortal(
        <div
          className="modal-overlay"
          onClick={() => setSelectedConnector(null)}
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.75)',
            backdropFilter: 'blur(8px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 99999,
            padding: '1.5rem',
          }}
        >
          <div
            className="card connector-drawer"
            onClick={(e) => e.stopPropagation()}
            style={{
              width: '100%',
              maxWidth: 720,
              maxHeight: '85vh',
              overflowY: 'auto',
              borderRadius: 12,
              padding: '2rem',
              background: '#0d0e12',
              border: '1px solid rgba(255, 255, 255, 0.12)',
              boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.7)',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1.5rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                <div
                  style={{
                    width: 52,
                    height: 52,
                    borderRadius: 12,
                    background: 'rgba(255, 255, 255, 0.06)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    border: '1px solid rgba(255, 255, 255, 0.1)',
                  }}
                >
                  <NodeIcon type={selectedConnector.connector_key} name={selectedConnector.display_name} icon={selectedConnector.icon} size={36} />
                </div>
                <div>
                  <h2 style={{ margin: 0, fontSize: '20px', fontWeight: 700, color: '#f8fafc' }}>
                    {selectedConnector.display_name}
                  </h2>
                  <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.25rem', alignItems: 'center' }}>
                    <span style={{ fontSize: '12px', color: '#94a3b8', textTransform: 'capitalize' }}>
                      {selectedConnector.category}
                    </span>
                    <span style={{ color: '#475569' }}>•</span>
                    <span style={{ fontSize: '12px', color: '#38bdf8' }}>v{selectedConnector.connector_version || '1.0'}</span>
                    <span style={{ color: '#475569' }}>•</span>
                    <span style={{ fontSize: '12px', color: '#10b981' }}>{selectedConnector.lifecycle_status || 'Production'}</span>
                  </div>
                </div>
              </div>
              <button className="ghost drawer-close" onClick={() => setSelectedConnector(null)} style={{ padding: '0.4rem 0.6rem', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>

            <p style={{ fontSize: '14px', color: '#cbd5e1', lineHeight: '1.6', marginBottom: '1.5rem' }}>
              {selectedConnector.description ||
                `Connect Flowsmith to ${selectedConnector.display_name} to execute authenticated actions, automate tasks, and listen for events in real time.`}
            </p>

            <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '1.75rem' }}>
              <button
                className="primary"
                onClick={() => {
                  setSelectedConnector(null)
                  navigate('/credentials')
                }}
                style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem' }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 2l-2 2m-1.5 1.5L14 9l-3-3 2.5-2.5a2.12 2.12 0 0 1 3 0l4.5 4.5" />
                  <path d="M15.5 10.5L8 18l-3-1-1 3 3 1 1-3 7.5-7.5" />
                </svg>
                Configure Credentials
              </button>
              <button
                className="ghost"
                onClick={() => {
                  setSelectedConnector(null)
                  navigate('/workflows')
                }}
                style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem' }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                </svg>
                Use in Workflow
              </button>
            </div>

            {detailLoading ? (
              <LoadingSkeleton lines={4} />
            ) : (
              <div>
                <h4 style={{ fontSize: '14px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#94a3b8', marginBottom: '0.75rem' }}>
                  Supported Actions ({Object.keys((fullDetail && fullDetail.operations) || selectedConnector.operations || {}).length})
                </h4>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginBottom: '1.5rem' }}>
                  {Object.entries((fullDetail && fullDetail.operations) || {}).length > 0 ? (
                    Object.entries(fullDetail.operations).map(([k, op]) => (
                      <div
                        key={k}
                        style={{
                          padding: '0.75rem 1rem',
                          background: 'rgba(255, 255, 255, 0.03)',
                          borderRadius: 8,
                          border: '1px solid rgba(255, 255, 255, 0.06)',
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span style={{ fontWeight: 600, color: '#f1f5f9', fontSize: '13px' }}>
                            {op.display_name || k}
                          </span>
                          <span style={{ fontSize: '11px', color: '#64748b', fontFamily: 'monospace' }}>{k}</span>
                        </div>
                        {op.description && (
                          <p style={{ margin: '0.25rem 0 0 0', fontSize: '12px', color: '#94a3b8' }}>{op.description}</p>
                        )}
                      </div>
                    ))
                  ) : (
                    (Array.isArray(selectedConnector.operations) ? selectedConnector.operations : []).map((op) => (
                      <div
                        key={op}
                        style={{
                          padding: '0.5rem 1rem',
                          background: 'rgba(255, 255, 255, 0.03)',
                          borderRadius: 6,
                          fontSize: '13px',
                          color: '#e2e8f0',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '6px',
                        }}
                      >
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ opacity: 0.6 }}>
                          <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                        </svg>
                        {op}
                      </div>
                    ))
                  )}
                </div>

                {Array.isArray(selectedConnector.triggers) && selectedConnector.triggers.length > 0 && (
                  <div>
                    <h4 style={{ fontSize: '14px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#94a3b8', marginBottom: '0.75rem' }}>
                      Supported Triggers ({selectedConnector.triggers.length})
                    </h4>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                      {selectedConnector.triggers.map((trig) => (
                        <div
                          key={trig}
                          style={{
                            padding: '0.5rem 1rem',
                            background: 'rgba(255, 255, 255, 0.03)',
                            borderRadius: 6,
                            fontSize: '13px',
                            color: '#e2e8f0',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '6px',
                          }}
                        >
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ opacity: 0.6 }}>
                            <polyline points="22 12 16 12 14 15 10 15 8 12 2 12" />
                            <path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
                          </svg>
                          {trig}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>,
        document.body
      )}

      {/* OpenAPI Importer Modal */}
      {openApiModalOpen && (
        <OpenApiImportModal
          isOpen={openApiModalOpen}
          onClose={() => setOpenApiModalOpen(false)}
          onImportSuccess={() => {
            api.listConnectors().then((res) => setConnectors(Array.isArray(res) ? res : (res && res.data) || []))
          }}
        />
      )}
    </div>
  )
}
