import { memo, useMemo, useState, useRef, useEffect } from 'react'
import { useReactFlow } from '@xyflow/react'
import { useWorkflowStore } from '../stores/workflowStore'
import { useUiStore } from '../stores/uiStore'
import { startNodeDrag } from '../utils/drag'
import { fuzzyScore } from '../utils/fuzzy'
import SalesforceBrowser from './SalesforceBrowser'
import SubWorkflowBrowser from './SubWorkflowBrowser'
import Input from './shared/Input'
import { NodeIcon } from './NodeIcons'
import OpenApiImportModal from './OpenApiImportModal'

function PaletteRow({ node, onCanvasCount, onJump, onClick }) {
  const isTrigger =
    node.type?.includes('trigger') ||
    node.type === 'execute_workflow_trigger' ||
    node.input_handles?.length === 0 ||
    node.category === 'Triggers'

  return (
    <div
      className="node-palette"
      draggable
      onDragStart={(e) => startNodeDrag(e, node.type)}
      onClick={onClick}
      title={node.description}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'Enter') onClick?.() }}
    >
      <span className="node-icon">
        <NodeIcon type={node.type} name={node.display_name} icon={node.icon} size={20} color="#cbd5e1" />
      </span>
      <div className="palette-info">
        <div className="palette-name">
          {node.display_name}
          {isTrigger && (
            <span className="node-trigger-bolt" title="Trigger" aria-label="Trigger">
              <img
                src="/trigger-beacon.webp"
                alt="Trigger"
                className="node-trigger-beacon-img"
                loading="lazy"
                onError={(e) => {
                  if (!e.currentTarget.dataset.fallback) {
                    e.currentTarget.dataset.fallback = '1'
                    e.currentTarget.src = '/trigger-beacon.png'
                  }
                }}
              />
            </span>
          )}
        </div>
        {node.description && <div className="palette-desc">{node.description}</div>}
      </div>
      {onCanvasCount > 0 && (
        <button
          type="button"
          className="palette-count"
          title={`${onCanvasCount} on canvas — click to zoom there`}
          onClick={(e) => {
            e.preventDefault()
            e.stopPropagation()
            onJump(node.type)
          }}
        >
          ×{onCanvasCount}
        </button>
      )}
      {(node.type === 'sub_workflow' || node.type === 'execute_sub_workflow') && (
        <span className="palette-arrow-icon" aria-hidden="true">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="5" y1="12" x2="19" y2="12" />
            <polyline points="12 5 19 12 12 19" />
          </svg>
        </span>
      )}
    </div>
  )
}

function Sidebar({ onOpenCredentials }) {
  const sidebarRef = useRef(null)
  const catalog = useWorkflowStore((s) => s.catalog)
  const nodeTypesKey = useWorkflowStore(
    (s) => s.nodes.map((n) => (n.type === 'custom' ? n.data?.node?.type : null)).filter(Boolean).sort().join(',')
  )
  const selectNode = useUiStore((s) => s.selectNode)
  const closeSidebar = useUiStore((s) => s.closeSidebar)
  const { fitView } = useReactFlow()
  const [query, setQuery] = useState('')
  const [salesforceOpen, setSalesforceOpen] = useState(false)
  const [subWorkflowOpen, setSubWorkflowOpen] = useState(false)
  const [selectedCategory, setSelectedCategory] = useState(null)
  const [openApiImportOpen, setOpenApiImportOpen] = useState(false)
  const [collapsedSubgroups, setCollapsedSubgroups] = useState({
    popular: false,
    triggers: false,
    other: false,
  })

  const toggleSubgroup = (key) => {
    setCollapsedSubgroups((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  // Hide the nodes panel when touching/clicking anywhere on screen outside the sidebar
  useEffect(() => {
    function handleScreenTouch(e) {
      if (sidebarRef.current && !sidebarRef.current.contains(e.target)) {
        // Do not close if user clicked the toggle/unhide button that re-opens it
        if (e.target.closest && e.target.closest('.sidebar-unhide-btn')) {
          return
        }
        closeSidebar()
      }
    }

    // Capture phase ensures we intercept the touch/click before ReactFlow or any canvas child suppresses it
    window.addEventListener('pointerdown', handleScreenTouch, true)
    window.addEventListener('touchstart', handleScreenTouch, true)
    return () => {
      window.removeEventListener('pointerdown', handleScreenTouch, true)
      window.removeEventListener('touchstart', handleScreenTouch, true)
    }
  }, [closeSidebar])

  // How many of each type are already on the canvas (drives the ×N chips).
  const countsByType = useMemo(() => {
    const counts = new Map()
    if (!nodeTypesKey) return counts
    for (const t of nodeTypesKey.split(',')) {
      if (t) counts.set(t, (counts.get(t) || 0) + 1)
    }
    return counts
  }, [nodeTypesKey])

  const connectorNodes = useMemo(() => {
    return catalog.filter((n) => n.icon === '🔌' || n.category === 'Connectors' || n.is_connector || n.icon === 'connector' || (n.credential_types && n.credential_types.length > 0))
  }, [catalog])

  const groups = useMemo(() => {
    const q = query.trim()
    const matches = catalog.filter((node) => {
      if (node.type === 'loop') return false
      if (!q && selectedCategory === 'Connectors') {
        return Boolean(node.icon === '🔌' || node.category === 'Connectors' || node.is_connector || node.icon === 'connector' || (node.credential_types && node.credential_types.length > 0))
      }
      if (!q && selectedCategory === 'Triggers') {
        return Boolean(node.category === 'Triggers' || node.type?.includes('trigger') || node.display_name?.toLowerCase().includes('trigger'))
      }
      if (!q && selectedCategory && (node.category || 'Other') !== selectedCategory) {
        return false
      }
      if (!q) return true
      return (
        fuzzyScore(q, `${node.display_name} ${node.type} ${node.category || ''} ${node.description || ''}`) >= 0
      )
    })
    const out = {}
    const seen = new Set()
    for (const node of matches) {
      if (node.type === 'loop') continue
      if (!q && !selectedCategory && (node.category === 'Connectors' || node.is_connector)) continue
      const key = `${node.category || 'Other'}::${node.display_name}`
      if (seen.has(key)) continue
      seen.add(key)
      const category = selectedCategory === 'Connectors' ? 'Connectors' : (node.category || 'Other')
      ;(out[category] ||= []).push(node)
    }
    const reordered = {}
    if (out['Flow']) reordered['Flow'] = out['Flow']
    for (const [k, v] of Object.entries(out)) {
      if (k !== 'Flow') reordered[k] = v
    }
    return reordered
  }, [catalog, query, selectedCategory])

  /** Jump to the first canvas instance of a node type. */
  function jumpToType(type) {
    const target = useWorkflowStore.getState().nodes.find(
      (n) => n.type === 'custom' && n.data?.node?.type === type,
    )
    if (!target) return
    selectNode(target.id)
    fitView({ nodes: [{ id: target.id }], duration: 350, maxZoom: 1.4, padding: 6 })
  }

  const searching = Boolean(query.trim())


  const flowPopularTypes = new Set(['filter', 'if_condition', 'if', 'loop_over_items', 'split_out', 'split', 'merge'])
  const flowOrder = [
    'filter',
    'if_condition',
    'if',
    'loop_over_items',
    'split_out',
    'split',
    'merge',
    'compare_datasets',
    'sub_workflow',
    'execute_sub_workflow',
    'stop_and_error',
    'switch',
    'wait',
  ]
  const sortFlow = (a, b) => {
    const ia = flowOrder.indexOf(a.type)
    const ib = flowOrder.indexOf(b.type)
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
  }

  const categoryMeta = useMemo(() => {
    const counts = {}
    for (const node of catalog) {
      const cat = node.category || 'Other'
      counts[cat] = (counts[cat] || 0) + 1
    }
    const triggerCount = catalog.filter((n) => n.category === 'Triggers' || n.type?.includes('trigger') || n.display_name?.toLowerCase().includes('trigger')).length

    return [
      {
        id: 'Flow',
        title: 'Flow',
        desc: 'Control data flow through your workflow',
        count: counts['Flow'] || 19,
        icon: (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="18" cy="5" r="3" />
            <circle cx="6" cy="12" r="3" />
            <circle cx="18" cy="19" r="3" />
            <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
            <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
          </svg>
        ),
        accent: '#38bdf8',
      },
      {
        id: 'Triggers',
        title: 'Triggers',
        desc: 'Start workflows automatically or on events',
        count: triggerCount || 8,
        icon: (
          <img
            src="/trigger-beacon.webp"
            alt="Triggers"
            width={20}
            height={20}
            style={{
              display: 'block',
              objectFit: 'contain',
              filter: 'drop-shadow(0 0 6px rgba(56, 189, 248, 0.5))',
            }}
            onError={(e) => {
              if (!e.currentTarget.dataset.fallback) {
                e.currentTarget.dataset.fallback = '1'
                e.currentTarget.src = '/trigger-beacon.png'
              }
            }}
          />
        ),
        accent: '#06b6d4',
      },
      {
        id: 'Actions',
        title: 'Actions',
        desc: 'Send HTTP requests, API calls and external actions',
        count: counts['Actions'] || 11,
        icon: (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="16 18 22 12 16 6" />
            <polyline points="8 6 2 12 8 18" />
          </svg>
        ),
        accent: '#a855f7',
      },
      {
        id: 'Transform',
        title: 'Transform',
        desc: 'Code, transform, edit and convert data payloads',
        count: counts['Transform'] || 13,
        icon: (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="16 3 21 3 21 8" />
            <line x1="4" y1="20" x2="21" y2="3" />
            <polyline points="21 16 21 21 16 21" />
            <line x1="15" y1="15" x2="21" y2="21" />
            <line x1="4" y1="4" x2="9" y2="9" />
          </svg>
        ),
        accent: '#10b981',
      },
      {
        id: 'Logic',
        title: 'Logic',
        desc: 'Human approvals, loops, splits and conditions',
        count: counts['Logic'] || 3,
        icon: (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="6" y1="3" x2="6" y2="15" />
            <circle cx="18" cy="6" r="3" />
            <circle cx="6" cy="18" r="3" />
            <path d="M18 9a9 9 0 0 1-9 9" />
          </svg>
        ),
        accent: '#f59e0b',
      },
      {
        id: 'AI',
        title: 'AI & Agents',
        desc: 'AI LLM agents, RAG pipelines and prompts',
        count: counts['AI'] || 14,
        icon: (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
          </svg>
        ),
        accent: '#ec4899',
      },
      {
        id: 'Database',
        title: 'Database & Data',
        desc: 'Database queries, SQL, and data tables',
        count: counts['Database'] || 55,
        icon: (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <ellipse cx="12" cy="5" rx="9" ry="3" />
            <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
            <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
          </svg>
        ),
        accent: '#6366f1',
      },
      {
        id: 'Communication',
        title: 'Communication',
        desc: 'Send emails, Slack, Telegram & WebSockets',
        count: counts['Communication'] || 91,
        icon: (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
        ),
        accent: '#06b6d4',
      },
      {
        id: 'Marketing',
        title: 'Marketing & Content',
        desc: 'Mailchimp, Brevo, cold outreach & campaigns',
        count: counts['Marketing'] || 40,
        icon: (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M11 5L6 9H2v6h4l5 4V5z" />
            <path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
            <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
          </svg>
        ),
        accent: '#f43f5e',
      },
      {
        id: 'CRM',
        title: 'CRM & Sales',
        desc: 'Salesforce, HubSpot, Dynamics & Pipedrive',
        count: counts['CRM'] || 35,
        icon: (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
            <circle cx="9" cy="7" r="4" />
            <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
            <path d="M16 3.13a4 4 0 0 1 0 7.75" />
          </svg>
        ),
        accent: '#f97316',
      },
      {
        id: 'Productivity',
        title: 'Productivity',
        desc: 'Notion, Jira, Asana, Trello & Calendar',
        count: counts['Productivity'] || 47,
        icon: (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
            <line x1="16" y1="2" x2="16" y2="6" />
            <line x1="8" y1="2" x2="8" y2="6" />
            <line x1="3" y1="10" x2="21" y2="10" />
          </svg>
        ),
        accent: '#8b5cf6',
      },
      {
        id: 'Developer',
        title: 'Developer & DevOps',
        desc: 'GitHub, GitLab, Docker, AWS & APIs',
        count: counts['Developer'] || 94,
        icon: (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="4 17 10 11 4 5" />
            <line x1="12" y1="19" x2="20" y2="19" />
          </svg>
        ),
        accent: '#14b8a6',
      },
      {
        id: 'Finance',
        title: 'Finance & Payments',
        desc: 'Stripe, PayPal, QuickBooks & Billing',
        count: counts['Finance'] || 19,
        icon: (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="2" y="5" width="20" height="14" rx="2" />
            <line x1="2" y1="10" x2="22" y2="10" />
          </svg>
        ),
        accent: '#10b981',
      },
      {
        id: 'Connectors',
        title: 'Connectors & Apps',
        desc: 'All third-party integrations & apps',
        count: connectorNodes.length,
        icon: (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="2" y="2" width="20" height="20" rx="4" />
            <line x1="7" y1="12" x2="17" y2="12" />
            <line x1="12" y1="7" x2="12" y2="17" />
          </svg>
        ),
        accent: '#3b82f6',
      },
    ]
  }, [catalog, connectorNodes])

  const activeCatMeta = useMemo(() => {
    return categoryMeta.find((c) => c.id === selectedCategory) || null
  }, [categoryMeta, selectedCategory])

  if (salesforceOpen) {
    return (
      <aside className="sidebar" ref={sidebarRef}>
        <SalesforceBrowser onClose={() => setSalesforceOpen(false)} />
      </aside>
    )
  }

  if (subWorkflowOpen) {
    return (
      <aside className="sidebar" ref={sidebarRef}>
        <SubWorkflowBrowser onClose={() => setSubWorkflowOpen(false)} />
      </aside>
    )
  }

  return (
    <aside className="sidebar" ref={sidebarRef}>
      {selectedCategory ? (
        <div className="sidebar-category-header">
          <button
            type="button"
            className="sidebar-back-btn"
            onClick={() => {
              setSelectedCategory(null)
              setQuery('')
            }}
            title="Back to all categories"
            aria-label="Back to all categories"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="19" y1="12" x2="5" y2="12" />
              <polyline points="12 19 5 12 12 5" />
            </svg>
          </button>
          <span className="sidebar-cat-icon" style={{ color: activeCatMeta?.accent || '#38bdf8' }}>
            {activeCatMeta?.icon || (
              <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="18" cy="5" r="3" />
                <circle cx="6" cy="12" r="3" />
                <circle cx="18" cy="19" r="3" />
                <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
                <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
              </svg>
            )}
          </span>
          <h2 className="sidebar-category-title">{activeCatMeta?.title || selectedCategory}</h2>
          {activeCatMeta?.count ? (
            <span className="category-header-badge">{activeCatMeta.count}</span>
          ) : null}
        </div>
      ) : (
        <div className="sidebar-header">
          <h2>Nodes</h2>
        </div>
      )}

      <Input
        search
        className="palette-search"
        placeholder="Search nodes..."
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onClear={() => setQuery('')}
        onKeyDown={(e) => {
          // Let the global handler own Ctrl+K; stop plain keys here.
          e.stopPropagation()
          if (e.key === 'Escape') setQuery('')
        }}
        aria-label="Search nodes"
      />

      {!selectedCategory && !query.trim() && (
        <div className="categories-directory">
          {categoryMeta.map((cat) => (
            <div
              key={cat.id}
              className="category-card"
              onClick={() => setSelectedCategory(cat.id)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => { if (e.key === 'Enter') setSelectedCategory(cat.id) }}
            >
              <div className="category-card-icon" style={{ color: cat.accent }}>
                {cat.icon}
              </div>
              <div className="category-card-info">
                <div className="category-card-header">
                  <span className="category-card-title">{cat.title}</span>
                  <span className="category-card-badge">{cat.count}</span>
                </div>
                <div className="category-card-desc" title={cat.desc}>{cat.desc}</div>
              </div>
              <div className="category-card-arrow">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="9 18 15 12 9 6" />
                </svg>
              </div>
            </div>
          ))}
        </div>
      )}

      {searching && !Object.keys(groups).length && !connectorNodes.length && (
        <p className="hint" style={{ padding: '8px 4px' }}>
          No nodes match “{query}”. Try the command palette (Ctrl+K).
        </p>
      )}

      {(selectedCategory || query.trim()) &&
        Object.entries(groups).map(([category, list]) => {
          if (category === 'Flow') {
            const triggerTypes = new Set(['execute_workflow_trigger', 'sub_workflow_trigger', 'when_executed_by_another_workflow'])
            // Keep execute_workflow_trigger inside Execute Sub-workflow drawer
            const subwfTriggerTypes = triggerTypes
            const triggerList = list.filter((n) => triggerTypes.has(n.type) && !subwfTriggerTypes.has(n.type))
            const popularList = list.filter((n) => flowPopularTypes.has(n.type) && !triggerTypes.has(n.type)).sort(sortFlow)
            const otherList = list.filter((n) => !flowPopularTypes.has(n.type) && !triggerTypes.has(n.type)).sort(sortFlow)

            return (
              <div key={category} className="node-group flow-category-group">
                {!selectedCategory && (
                  <h3
                    className="category-title-flow clickable"
                    onClick={() => setSelectedCategory('Flow')}
                    title="Click to view Flow category"
                  >
                    <span className="cat-flow-icon">
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="18" cy="5" r="3" />
                        <circle cx="6" cy="12" r="3" />
                        <circle cx="18" cy="19" r="3" />
                        <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
                        <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
                      </svg>
                    </span>
                    Flow
                  </h3>
                )}

                {popularList.length > 0 && (
                  <div className="flow-subgroup">
                    <div
                      className={`flow-subgroup-header ${collapsedSubgroups.popular ? 'is-collapsed' : ''}`}
                      onClick={() => toggleSubgroup('popular')}
                      role="button"
                      tabIndex={0}
                    >
                      <span>Popular</span>
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9" /></svg>
                    </div>
                    {!collapsedSubgroups.popular && popularList.map((node) => (
                      <PaletteRow
                        key={node.type}
                        node={node}
                        onCanvasCount={countsByType.get(node.type) || 0}
                        onJump={jumpToType}
                        onClick={node.type === 'salesforce' ? () => setSalesforceOpen(true) : (node.type === 'sub_workflow' || node.type === 'execute_sub_workflow') ? () => setSubWorkflowOpen(true) : undefined}
                      />
                    ))}
                  </div>
                )}

                {triggerList.length > 0 && (
                  <div className="flow-subgroup">
                    <div
                      className={`flow-subgroup-header ${collapsedSubgroups.triggers ? 'is-collapsed' : ''}`}
                      onClick={() => toggleSubgroup('triggers')}
                      role="button"
                      tabIndex={0}
                    >
                      <span>Triggers ({triggerList.length})</span>
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9" /></svg>
                    </div>
                    {!collapsedSubgroups.triggers && triggerList.map((node) => (
                      <PaletteRow
                        key={node.type}
                        node={node}
                        onCanvasCount={countsByType.get(node.type) || 0}
                        onJump={jumpToType}
                        onClick={node.type === 'salesforce' ? () => setSalesforceOpen(true) : (node.type === 'sub_workflow' || node.type === 'execute_sub_workflow') ? () => setSubWorkflowOpen(true) : undefined}
                      />
                    ))}
                  </div>
                )}

                {otherList.length > 0 && (
                  <div className="flow-subgroup">
                    <div
                      className={`flow-subgroup-header ${collapsedSubgroups.other ? 'is-collapsed' : ''}`}
                      onClick={() => toggleSubgroup('other')}
                      role="button"
                      tabIndex={0}
                    >
                      <span>Other</span>
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9" /></svg>
                    </div>
                    {!collapsedSubgroups.other && otherList.map((node) => (
                      <PaletteRow
                        key={node.type}
                        node={node}
                        onCanvasCount={countsByType.get(node.type) || 0}
                        onJump={jumpToType}
                        onClick={node.type === 'salesforce' ? () => setSalesforceOpen(true) : (node.type === 'sub_workflow' || node.type === 'execute_sub_workflow') ? () => setSubWorkflowOpen(true) : undefined}
                      />
                    ))}
                  </div>
                )}
              </div>
            )
          }

          return (
            <div key={category} className="node-group">
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                <h3
                  className="clickable"
                  onClick={() => setSelectedCategory(category)}
                  title={`Click to view ${category}`}
                  style={{ margin: 0 }}
                >
                  {category}
                </h3>
                {category === 'Connectors' && (
                  <button
                    type="button"
                    className="ghost small"
                    onClick={() => setOpenApiImportOpen(true)}
                    style={{ fontSize: 11, padding: '2px 8px', color: 'var(--primary, #6366f1)' }}
                    title="Import custom OpenAPI / Swagger connector"
                  >
                    + Import API
                  </button>
                )}
              </div>
              {list.map((node) => (
                <PaletteRow
                  key={node.type}
                  node={node}
                  onCanvasCount={countsByType.get(node.type) || 0}
                  onJump={jumpToType}
                  onClick={node.type === 'salesforce' ? () => setSalesforceOpen(true) : (node.type === 'sub_workflow' || node.type === 'execute_sub_workflow') ? () => setSubWorkflowOpen(true) : undefined}
                />
              ))}
            </div>
          )
        })}

      {!selectedCategory && !searching && connectorNodes.length > 0 && (
        <div className="node-group">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
            <h3
              className="clickable"
              onClick={() => setSelectedCategory('Connectors')}
              title="Click to view all Connectors"
              style={{ margin: 0, display: 'inline-flex', alignItems: 'center', gap: 6 }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ opacity: 0.8 }}>
                <rect x="2" y="2" width="20" height="8" rx="2" ry="2" />
                <rect x="2" y="14" width="20" height="8" rx="2" ry="2" />
                <line x1="6" y1="6" x2="6.01" y2="6" />
                <line x1="6" y1="18" x2="6.01" y2="18" />
              </svg>
              <span>Connector entries ({connectorNodes.length})</span>
            </h3>
            <button
              type="button"
              className="ghost small"
              onClick={() => setOpenApiImportOpen(true)}
              style={{ fontSize: 11, padding: '2px 8px', color: 'var(--primary, #6366f1)' }}
              title="Import custom OpenAPI / Swagger connector"
            >
              + Import API
            </button>
          </div>
          <p className="hint">
            First-class integrations for Salesforce, Google, HubSpot, Slack, GitHub, Jira, and more.
          </p>
          {connectorNodes.slice(0, 10).map((node) => (
            <PaletteRow
              key={node.type}
              node={node}
              onCanvasCount={countsByType.get(node.type) || 0}
              onJump={jumpToType}
              onClick={node.type === 'salesforce' ? () => setSalesforceOpen(true) : (node.type === 'sub_workflow' || node.type === 'execute_sub_workflow') ? () => setSubWorkflowOpen(true) : undefined}
            />
          ))}
          {connectorNodes.length > 10 && (
            <button
              type="button"
              className="ghost small"
              onClick={() => setSelectedCategory('Connectors')}
              style={{ marginTop: 8, width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}
            >
              View all {connectorNodes.length} connector entries →
            </button>
          )}
        </div>
      )}

      {!selectedCategory && (
        <button className="ghost creds-button" onClick={onOpenCredentials} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="7.5" cy="15.5" r="5.5" />
            <path d="M21 2l-9.6 9.6" />
            <path d="M15.5 7.5l3 3L22 7l-3-3" />
          </svg>
          <span>Credentials</span>
        </button>
      )}
      <OpenApiImportModal
        isOpen={openApiImportOpen}
        onClose={() => setOpenApiImportOpen(false)}
      />
    </aside>
  )
}

export default memo(Sidebar)
