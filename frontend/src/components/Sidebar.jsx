import { useMemo, useState, useRef, useEffect } from 'react'
import { useReactFlow } from '@xyflow/react'
import { useWorkflowStore } from '../stores/workflowStore'
import { useUiStore } from '../stores/uiStore'
import { startNodeDrag } from '../utils/drag'
import { fuzzyScore } from '../utils/fuzzy'
import SalesforceBrowser from './SalesforceBrowser'
import Input from './shared/Input'
import { NodeIcon } from './NodeIcons'

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
        <NodeIcon type={node.type} icon={node.icon} size={20} color="#cbd5e1" />
      </span>
      <div className="palette-info">
        <div className="palette-name">
          {node.display_name}
          {isTrigger && (
            <span className="node-trigger-bolt" title="Trigger" aria-label="Trigger">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="#f97316" stroke="#ea580c" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round">
                <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
              </svg>
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

export default function Sidebar({ onOpenCredentials }) {
  const sidebarRef = useRef(null)
  const catalog = useWorkflowStore((s) => s.catalog)
  const nodes = useWorkflowStore((s) => s.nodes)
  const generateWorkflow = useWorkflowStore((s) => s.generateWorkflow)
  const selectNode = useUiStore((s) => s.selectNode)
  const toggleSidebar = useUiStore((s) => s.toggleSidebar)
  const closeSidebar = useUiStore((s) => s.closeSidebar)
  const { fitView } = useReactFlow()
  const [prompt, setPrompt] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [query, setQuery] = useState('')
  const [salesforceOpen, setSalesforceOpen] = useState(false)
  const [selectedCategory, setSelectedCategory] = useState(null)
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
    for (const n of nodes) {
      if (n.type !== 'custom') continue
      const t = n.data?.node?.type
      counts.set(t, (counts.get(t) || 0) + 1)
    }
    return counts
  }, [nodes])

  const groups = useMemo(() => {
    const q = query.trim()
    const matches = catalog.filter((node) => {
      if (selectedCategory && (node.category || 'Other') !== selectedCategory) {
        return false
      }
      if (!q) return true
      return (
        fuzzyScore(q, `${node.display_name} ${node.type} ${node.category || ''}`) >= 0
      )
    })
    const out = {}
    const seen = new Set()
    for (const node of matches) {
      if (node.icon === '🔌') continue
      const key = `${node.category || 'Other'}::${node.display_name}`
      if (seen.has(key)) continue
      seen.add(key)
      const category = node.category || 'Other'
      ;(out[category] ||= []).push(node)
    }
    const reordered = {}
    if (out['Flow']) reordered['Flow'] = out['Flow']
    for (const [k, v] of Object.entries(out)) {
      if (k !== 'Flow') reordered[k] = v
    }
    return reordered
  }, [catalog, query, selectedCategory])

  const connectorNodes = useMemo(() => {
    if (!query.trim()) {
      return catalog.filter((n) => n.icon === '🔌')
    }
    const q = query.trim().toLowerCase()
    return catalog.filter(
      (n) =>
        n.icon === '🔌' &&
        (`${n.display_name} ${n.type}`.toLowerCase().includes(q)),
    )
  }, [catalog, query])

  /** Jump to the first canvas instance of a node type. */
  function jumpToType(type) {
    const target = nodes.find(
      (n) => n.type === 'custom' && n.data?.node?.type === type,
    )
    if (!target) return
    selectNode(target.id)
    fitView({ nodes: [{ id: target.id }], duration: 350, maxZoom: 1.4, padding: 6 })
  }

  async function onGenerate() {
    if (!prompt.trim() || busy) return
    setBusy(true)
    setError(null)
    try {
      await generateWorkflow(prompt.trim())
      setPrompt('')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const searching = Boolean(query.trim())
  const generated = useWorkflowStore((s) => s.generated)
  const approveGenerated = useWorkflowStore((s) => s.approveGenerated)
  const discardGenerated = useWorkflowStore((s) => s.discardGenerated)
  const [approving, setApproving] = useState(false)


  const flowPopularTypes = new Set(['filter', 'if_condition', 'if', 'loop_over_items', 'loop', 'split_out', 'split', 'merge'])
  const flowOrder = [
    'filter',
    'if_condition',
    'if',
    'loop_over_items',
    'loop',
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
      if (node.icon === '🔌') continue
      const cat = node.category || 'Other'
      counts[cat] = (counts[cat] || 0) + 1
    }
    return [
      {
        id: 'Flow',
        title: 'Flow',
        desc: `Control the flow of data through your workflow (${counts['Flow'] || 10} nodes)`,
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
        desc: `Start workflows automatically or manually (${counts['Triggers'] || 4} nodes)`,
        icon: (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="#f97316" stroke="#ea580c" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round">
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
          </svg>
        ),
        accent: '#f97316',
      },
      {
        id: 'Actions',
        title: 'Actions',
        desc: `Send HTTP requests, API calls and external actions (${counts['Actions'] || 2} nodes)`,
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
        desc: `Transform, edit and convert data payloads (${counts['Transform'] || 3} nodes)`,
        icon: (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
            <polyline points="22,6 12,13 2,6" />
          </svg>
        ),
        accent: '#10b981',
      },
      {
        id: 'Logic',
        title: 'Logic',
        desc: `Human approvals, loops, splits and pagination (${counts['Logic'] || 5} nodes)`,
        icon: (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
            <circle cx="9" cy="7" r="4" />
          </svg>
        ),
        accent: '#f59e0b',
      },
      {
        id: 'AI',
        title: 'AI & Agents',
        desc: `AI LLM agents, RAG pipelines and prompts (${counts['AI'] || 3} nodes)`,
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
        desc: `Database queries, SQL, and data tables (${counts['Database'] || 2} nodes)`,
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
        desc: `Send emails, Slack and Telegram messages (${counts['Communication'] || 3} nodes)`,
        icon: (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
        ),
        accent: '#06b6d4',
      },
    ]
  }, [catalog])

  if (salesforceOpen) {
    return (
      <aside className="sidebar" ref={sidebarRef}>
        <SalesforceBrowser onClose={() => setSalesforceOpen(false)} />
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
            title="Back to all nodes"
            aria-label="Back to all nodes"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="19" y1="12" x2="5" y2="12" />
              <polyline points="12 19 5 12 12 5" />
            </svg>
          </button>
          <span className="sidebar-cat-icon">
            <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="18" cy="5" r="3" />
              <circle cx="6" cy="12" r="3" />
              <circle cx="18" cy="19" r="3" />
              <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
              <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
            </svg>
          </span>
          <h2 className="sidebar-category-title">{selectedCategory}</h2>
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
                <div className="category-card-title">{cat.title}</div>
                <div className="category-card-desc">{cat.desc}</div>
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
            const triggerList = list.filter((n) => triggerTypes.has(n.type))
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
                      />
                    ))}
                  </div>
                )}
              </div>
            )
          }

          return (
            <div key={category} className="node-group">
              <h3
                className="clickable"
                onClick={() => setSelectedCategory(category)}
                title={`Click to view ${category}`}
              >
                {category}
              </h3>
              {list.map((node) => (
                <PaletteRow
                  key={node.type}
                  node={node}
                  onCanvasCount={countsByType.get(node.type) || 0}
                  onJump={jumpToType}
                />
              ))}
            </div>
          )
        })}

      {!selectedCategory && connectorNodes.length > 0 && (
        <div className="node-group">
          <h3>🔌 Connectors</h3>
          {!searching && (
            <p className="hint">
              Connector node types have no built-in node class — they execute through the connector framework.
            </p>
          )}
          {connectorNodes.map((node) => (
            <PaletteRow
              key={node.type}
              node={node}
              onCanvasCount={countsByType.get(node.type) || 0}
              onJump={jumpToType}
              onClick={node.type === 'salesforce' ? () => setSalesforceOpen(true) : undefined}
            />
          ))}
        </div>
      )}

      {!selectedCategory && (
        <div className="node-group ai-generate">
          <h3>✨ AI assistant</h3>
        {!generated && (
          <>
            <textarea
              className="gen-input"
              rows={3}
              placeholder="Describe a workflow… e.g. ‘poll the weather API every 10 minutes and log it’"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => e.stopPropagation()}
            />
            <button className="ghost gen-button" disabled={busy || !prompt.trim()} onClick={onGenerate}>
              {busy ? 'Generating…' : '🤖 Generate workflow'}
            </button>
            {error && <p className="banner-inline err">{error}</p>}
            <p className="hint">Generates a preview you can review before anything is saved. Requires an llm credential.</p>
          </>
        )}

        {generated && (
          <div className="gen-preview">
            <div className="gen-preview-head">
              <strong>{generated.workflow.name}</strong>
              <span className={`gen-verdict ${generated.validation.ok ? 'ok' : 'err'}`}>
                {generated.validation.ok ? '✓ valid' : '✗ invalid'}
              </span>
            </div>
            <ul className="gen-nodes">
              {generated.workflow.nodes.map((n) => (
                <li key={n.id}>
                  <code>{n.type}</code>
                  {n.parameters?.operation ? ` · ${n.parameters.operation}` : ''}
                </li>
              ))}
            </ul>
            {generated.validation.errors.map((e, i) => (
              <p key={`e${i}`} className="banner-inline err">
                {e.code}: {e.message}
              </p>
            ))}
            {generated.validation.warnings.map((w, i) => (
              <p key={`w${i}`} className="banner-inline info">
                ⚠ {w.message}
              </p>
            ))}
            <p className="hint">
              Nothing is saved yet. Creating adds it as an inactive draft — activation stays manual.
            </p>
            <div className="gen-actions">
              <button
                className="primary"
                disabled={approving || !generated.validation.ok}
                onClick={async () => {
                  setApproving(true)
                  setError(null)
                  try {
                    await approveGenerated()
                    setPrompt('')
                  } catch (err) {
                    setError(err.message)
                  } finally {
                    setApproving(false)
                  }
                }}
                title="Create the workflow as an inactive draft"
              >
                {approving ? 'Creating…' : '✓ Create workflow'}
              </button>
            </div>
          </div>
        )}
      </div>
      )}
      {!selectedCategory && (
        <button className="ghost creds-button" onClick={onOpenCredentials}>
          🔑 Credentials
        </button>
      )}
    </aside>
  )
}
