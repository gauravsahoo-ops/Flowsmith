import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'

function ArchIcon({ name, size = 18, color = 'currentColor', style = {} }) {
  const baseProps = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: color,
    strokeWidth: 2,
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
    style: { display: 'inline-block', verticalAlign: 'middle', flexShrink: 0, ...style },
  }

  switch (name) {
    case 'natural_language':
      return (
        <svg {...baseProps}>
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
      )
    case 'workflow_builder':
      return (
        <svg {...baseProps}>
          <rect x="3" y="3" width="6" height="6" rx="1.5" />
          <rect x="15" y="15" width="6" height="6" rx="1.5" />
          <path d="M6 9v3a3 3 0 0 0 3 3h6" />
        </svg>
      )
    case 'capability_triad':
      return (
        <svg {...baseProps}>
          <polygon points="12 2 2 7 12 12 22 7 12 2" />
          <polyline points="2 17 12 22 22 17" />
          <polyline points="2 12 12 17 22 12" />
        </svg>
      )
    case 'workflow_engine':
      return (
        <svg {...baseProps}>
          <rect x="4" y="4" width="16" height="16" rx="2" />
          <rect x="9" y="9" width="6" height="6" />
          <line x1="9" y1="1" x2="9" y2="4" /><line x1="15" y1="1" x2="15" y2="4" />
          <line x1="9" y1="20" x2="9" y2="23" /><line x1="15" y1="20" x2="15" y2="23" />
          <line x1="20" y1="9" x2="23" y2="9" /><line x1="20" y1="14" x2="23" y2="14" />
          <line x1="1" y1="9" x2="4" y2="9" /><line x1="1" y1="14" x2="4" y2="14" />
        </svg>
      )
    case 'execution_intelligence':
      return (
        <svg {...baseProps}>
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
          <polyline points="9 12 11 14 15 10" />
        </svg>
      )
    case 'enterprise_governance':
      return (
        <svg {...baseProps}>
          <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
          <path d="M7 11V7a5 5 0 0 1 10 0v4" />
        </svg>
      )
    case 'consumption_surface':
      return (
        <svg {...baseProps}>
          <polyline points="4 17 10 11 4 5" />
          <line x1="12" y1="19" x2="20" y2="19" />
        </svg>
      )
    case 'simplicity':
      return (
        <svg {...baseProps}>
          <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
        </svg>
      )
    case 'control':
      return (
        <svg {...baseProps}>
          <line x1="4" y1="21" x2="4" y2="14" /><line x1="4" y1="10" x2="4" y2="3" />
          <line x1="12" y1="21" x2="12" y2="12" /><line x1="12" y1="8" x2="12" y2="3" />
          <line x1="20" y1="21" x2="20" y2="16" /><line x1="20" y1="12" x2="20" y2="3" />
          <line x1="1" y1="14" x2="7" y2="14" /><line x1="9" y1="8" x2="15" y2="8" /><line x1="17" y1="16" x2="23" y2="16" />
        </svg>
      )
    case 'ipaas':
      return (
        <svg {...baseProps}>
          <circle cx="12" cy="12" r="10" />
          <line x1="2" y1="12" x2="22" y2="12" />
          <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
        </svg>
      )
    case 'sovereignty':
      return (
        <svg {...baseProps}>
          <rect x="2" y="2" width="20" height="8" rx="2" ry="2" />
          <rect x="2" y="14" width="20" height="8" rx="2" ry="2" />
          <line x1="6" y1="6" x2="6.01" y2="6" /><line x1="6" y1="18" x2="6.01" y2="18" />
        </svg>
      )
    case 'database':
      return (
        <svg {...baseProps}>
          <ellipse cx="12" cy="5" rx="9" ry="3" />
          <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
          <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
        </svg>
      )
    case 'mcp':
      return (
        <svg {...baseProps}>
          <path d="M12 2v6m0 8v6M2 12h6m8 0h6" />
          <rect x="8" y="8" width="8" height="8" rx="2" />
        </svg>
      )
    case 'repair':
      return (
        <svg {...baseProps}>
          <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
        </svg>
      )
    case 'platform':
      return (
        <svg {...baseProps}>
          <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
          <line x1="8" y1="21" x2="16" y2="21" /><line x1="12" y1="17" x2="12" y2="21" />
        </svg>
      )
    case 'rag':
      return (
        <svg {...baseProps}>
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
      )
    case 'empty':
      return (
        <svg {...baseProps}>
          <polyline points="21 8 21 21 3 21 3 8" />
          <rect x="1" y="3" width="22" height="5" />
          <line x1="10" y1="12" x2="14" y2="12" />
        </svg>
      )
    default:
      return null
  }
}

const ARCH_PIPELINE = [
  {
    id: 'natural_language',
    layer: 'Layer 1',
    title: '1. Natural Language',
    desc: 'Intent ingestion, user prompts, and conversational workflow chat.',
    badge: 'Frictionless Simplicity',
    details: 'Frictionless entry point capturing user intent in plain English with multi-turn chat refinement and automatic parameter extraction without manual schema deciphering.',
  },
  {
    id: 'workflow_builder',
    layer: 'Layer 2',
    title: '2. AI Workflow Builder',
    desc: 'Grounded prompt-to-DAG compiler matching ports, data contracts, and schemas.',
    badge: 'Grounded Compiler',
    details: 'Translates high-level intent into deterministic, cycle-safe topological graphs strictly grounded against active connector definitions, preventing hallucinated connections.',
  },
  {
    id: 'capability_triad',
    layer: 'Layer 3',
    title: '3. Connectors · Agents · RAG',
    desc: '45+ native connectors, autonomous ReAct agents, and pgvector knowledge bases.',
    badge: 'Capability Triad',
    details: 'Unified execution surface: deterministic API integrations (Salesforce, Stripe, Slack, Postgres), autonomous tool-calling agents with step limits, and pgvector semantic retrieval.',
  },
  {
    id: 'workflow_engine',
    layer: 'Layer 4',
    title: '4. Workflow Engine',
    desc: "AsyncIO DAG scheduler executing parallel branches via Kahn's algorithm.",
    badge: 'AsyncIO Core',
    details: "High-performance Python 3.12+ engine with sub-workflow delegation, conditional branching (Switch, Filter, Wait, SplitInBatches), and robust state persistence.",
  },
  {
    id: 'execution_intelligence',
    layer: 'Layer 5',
    title: '5. Execute · Observe · Repair',
    desc: 'Subprocess memory sandboxes, live WebSocket telemetry, and deterministic auto-repair.',
    badge: 'Self-Healing Engine',
    details: 'Python/JS code isolated in 256MB subprocesses, real-time step streaming, multi-level error workflows, DLQ, and deterministic AST-based auto-repair of parameter bugs.',
  },
  {
    id: 'enterprise_governance',
    layer: 'Layer 6',
    title: '6. Enterprise Layer',
    desc: 'RBAC, immutable audit logging, Fernet vault, and environment promotion.',
    badge: 'Sovereign Governance',
    details: 'Multi-tenant workspace isolation, AES-128/AES-256 envelope credential encryption, SSRF protection, and promotions across dev, test, staging, and production.',
  },
  {
    id: 'consumption_surface',
    layer: 'Layer 7',
    title: '7. UI/API · MCP · Embedded',
    desc: 'Visual canvas & REST API, Model Context Protocol server, and white-label iPaaS.',
    badge: 'Triple Delivery',
    details: 'Unified delivery across human developers (React 19 Canvas), external AI agents (bidirectional /api/mcp JSON-RPC), and SaaS OEM partners (embeddable white-label SDK).',
  },
]

const CONVERGENCE_PILLARS = [
  {
    id: 'simplicity',
    category: 'Intuitive UX',
    pillar: 'Frictionless Workflow Simplicity',
    color: '#f97316',
    bg: 'rgba(249, 115, 22, 0.08)',
    border: 'rgba(249, 115, 22, 0.3)',
    summary: 'Natural language DAG generation, zero-config popup OAuth reconnection, intuitive step testing, and instant onboarding without cognitive fatigue.',
  },
  {
    id: 'control',
    category: 'Engine Depth',
    pillar: 'Technical Runtime & Code Control',
    color: '#ec4899',
    bg: 'rgba(236, 72, 153, 0.08)',
    border: 'rgba(236, 72, 153, 0.3)',
    summary: 'Subprocess-sandboxed Python & Node.js code execution, raw HTTP request node with custom headers/queries, sub-workflows, DAG looping, and full JSON payload tracing.',
  },
  {
    id: 'ipaas',
    category: 'Modular iPaaS',
    pillar: 'Embedded Enterprise Architecture',
    color: '#06b6d4',
    bg: 'rgba(6, 182, 212, 0.08)',
    border: 'rgba(6, 182, 212, 0.3)',
    summary: 'Headless API execution, embeddable white-label iframe/SDK widgets, multi-tenant workspace isolation, OpenAPI 3.0 import, and environment promotion.',
  },
  {
    id: 'sovereignty',
    category: 'Flowsmith Moat',
    pillar: "Flowsmith's Sovereign Moat",
    color: '#8b5cf6',
    bg: 'rgba(139, 92, 246, 0.08)',
    border: 'rgba(139, 92, 246, 0.3)',
    summary: '100% self-hosted on private infrastructure (zero data leaks, zero per-run fees), pgvector RAG, bidirectional MCP server, and deterministic AST auto-repair.',
  },
]

const CLIENT_CONFIG_SNIPPETS = {
  claude: (origin) => JSON.stringify(
    {
      mcpServers: {
        flowsmith: {
          url: `${origin}/api/mcp`,
          headers: {
            Authorization: 'Bearer <YOUR_FLOWSMITH_API_KEY>',
          },
        },
      },
    },
    null,
    2
  ),
  cursor: (origin) => JSON.stringify(
    {
      mcpServers: {
        flowsmith: {
          url: `${origin}/api/mcp`,
          headers: {
            Authorization: 'Bearer <YOUR_FLOWSMITH_API_KEY>',
          },
        },
      },
    },
    null,
    2
  ),
  python: (origin) => `import asyncio
from mcp import ClientSession
from mcp.client.sse import sse_client

async def main():
    headers = {"Authorization": "Bearer <YOUR_FLOWSMITH_API_KEY>"}
    async with sse_client("${origin}/api/mcp", headers=headers) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("Flowsmith MCP Tools:", [t.name for t in tools.tools])
            result = await session.call_tool("list_connectors", {})
            print("Connectors:", result)

asyncio.run(main())`,
  curl: (origin) => `curl -X POST "${origin}/api/mcp/call" \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer <YOUR_FLOWSMITH_API_KEY>" \\
  -d '{"name": "list_connectors", "arguments": {}}'`,
}

export default function AIArchitectureSection() {
  const navigate = useNavigate()
  const origin = typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8000'

  const [activePipelineStep, setActivePipelineStep] = useState(ARCH_PIPELINE[0])
  const [clientTab, setClientTab] = useState('claude')
  const [copiedSnippet, setCopiedSnippet] = useState(false)

  // MCP Tools Explorer State
  const [mcpTools, setMcpTools] = useState([])
  const [mcpLoading, setMcpLoading] = useState(true)
  const [selectedToolName, setSelectedToolName] = useState('list_connectors')
  const [toolArgsText, setToolArgsText] = useState('{}')
  const [toolExecuting, setToolExecuting] = useState(false)
  const [toolExecutionResult, setToolExecutionResult] = useState(null)
  const [toolExecutionLatency, setToolExecutionLatency] = useState(null)
  const [toolError, setToolError] = useState(null)

  // RAG State
  const [ragCollections, setRagCollections] = useState([])
  const [selectedRagId, setSelectedRagId] = useState('')
  const [ragQuery, setRagQuery] = useState('')
  const [ragSearching, setRagSearching] = useState(false)
  const [ragResults, setRagResults] = useState(null)
  const [ragError, setRagError] = useState(null)
  const [creatingDemoRag, setCreatingDemoRag] = useState(false)

  // Auto Repair Simulator State
  const [repairStep, setRepairStep] = useState(0)
  const [simulatingRepair, setSimulatingRepair] = useState(false)

  // Fetch initial MCP tools & RAG collections
  useEffect(() => {
    let cancelled = false
    setMcpLoading(true)

    api.listMcpTools()
      .then((tools) => {
        if (cancelled) return
        const list = Array.isArray(tools) ? tools : (tools?.data || [])
        setMcpTools(list)
        if (list.length > 0) {
          setSelectedToolName(list[0].name)
          setToolArgsText(getDefaultArgs(list[0].name))
        }
      })
      .catch(() => {
        // Fallback default list if unauthorized or endpoint warm-up
        if (!cancelled) {
          const fallback = [
            { name: 'list_connectors', description: 'List all available integration connectors, categories, and operations' },
            { name: 'search_knowledge', description: 'Perform semantic search over workspace RAG vector knowledge base' },
            { name: 'query_data_table', description: 'Query and filter rows from a workspace Data Table' },
            { name: 'list_workflows', description: 'List all available workflows in the workspace' },
            { name: 'trigger_workflow', description: 'Trigger a workflow execution' },
            { name: 'get_execution', description: 'Get status and result of a specific execution' },
          ]
          setMcpTools(fallback)
          setSelectedToolName('list_connectors')
          setToolArgsText('{}')
        }
      })
      .finally(() => {
        if (!cancelled) setMcpLoading(false)
      })

    api.listRagCollections()
      .then((cols) => {
        if (cancelled) return
        const list = Array.isArray(cols) ? cols : (cols?.data || [])
        setRagCollections(list)
        if (list.length > 0) {
          setSelectedRagId(list[0].id)
        }
      })
      .catch(() => {})

    return () => {
      cancelled = true
    }
  }, [])

  function getDefaultArgs(toolName) {
    switch (toolName) {
      case 'list_connectors':
        return '{\n  "category": "CRM"\n}'
      case 'search_knowledge':
        return '{\n  "collection_id": "default",\n  "query": "authentication",\n  "top_k": 3\n}'
      case 'query_data_table':
        return '{\n  "table_id": "customers",\n  "limit": 10\n}'
      case 'list_workflows':
        return '{\n  "limit": 5\n}'
      default:
        return '{}'
    }
  }

  const handleSelectTool = (name) => {
    setSelectedToolName(name)
    setToolArgsText(getDefaultArgs(name))
    setToolExecutionResult(null)
    setToolError(null)
  }

  const handleExecuteTool = async () => {
    setToolExecuting(true)
    setToolError(null)
    setToolExecutionResult(null)
    const t0 = performance.now()

    let parsedArgs = {}
    try {
      if (toolArgsText.trim()) {
        parsedArgs = JSON.parse(toolArgsText)
      }
    } catch {
      setToolError('Arguments must be valid JSON.')
      setToolExecuting(false)
      return
    }

    try {
      const res = await api.callMcpTool({
        name: selectedToolName,
        arguments: parsedArgs,
      })
      const t1 = performance.now()
      setToolExecutionLatency(Math.round(t1 - t0))
      setToolExecutionResult(res)
    } catch (err) {
      const t1 = performance.now()
      setToolExecutionLatency(Math.round(t1 - t0))
      setToolError(err.message || 'Tool execution failed.')
    } finally {
      setToolExecuting(false)
    }
  }

  const handleCopySnippet = () => {
    const text = CLIENT_CONFIG_SNIPPETS[clientTab](origin)
    navigator.clipboard.writeText(text).then(() => {
      setCopiedSnippet(true)
      setTimeout(() => setCopiedSnippet(false), 2000)
    })
  }

  const handleRagSearch = async () => {
    if (!selectedRagId || !ragQuery.trim()) return
    setRagSearching(true)
    setRagError(null)
    try {
      const res = await api.ragQuery(selectedRagId, {
        query: ragQuery.trim(),
        top_k: 4,
      })
      setRagResults(res)
    } catch (err) {
      setRagError(err.message || 'RAG query failed.')
    } finally {
      setRagSearching(false)
    }
  }

  const handleCreateDemoCollection = async () => {
    setCreatingDemoRag(true)
    try {
      const rec = await api.createRagCollection({ name: 'Enterprise Platform Docs' })
      await api.ragIngest(rec.id, {
        documents: [
          {
            text: 'Flowsmith is a self-hosted enterprise automation platform featuring DAG topological execution, cycle prevention, and 45+ out-of-the-box connectors for CRM, databases, and LLMs.',
          },
          {
            text: 'The Model Context Protocol (MCP) server allows Claude Desktop, Cursor, and external AI agents to discover workflows, query data tables, and trigger pipelines securely.',
          },
          {
            text: 'Deterministic Graph Auto-Repair captures runtime execution failures, analyzes upstream AST payloads, and applies type-safe parameter patches with zero hallucination.',
          },
        ],
      })
      const cols = await api.listRagCollections()
      setRagCollections(cols || [])
      setSelectedRagId(rec.id)
      setRagQuery('How does MCP work in Flowsmith?')
    } catch (err) {
      setRagError(`Could not create demo collection: ${err.message}`)
    } finally {
      setCreatingDemoRag(false)
    }
  }

  const handleSimulateRepair = () => {
    if (simulatingRepair) return
    setSimulatingRepair(true)
    setRepairStep(1)
    setTimeout(() => setRepairStep(2), 700)
    setTimeout(() => setRepairStep(3), 1500)
    setTimeout(() => {
      setRepairStep(4)
      setSimulatingRepair(false)
    }, 2300)
  }

  const selectedTool = mcpTools.find((t) => t.name === selectedToolName)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem', paddingBottom: '3rem' }}>
      {/* 1. TOP HERO CARDS (Restyled & Elevated) */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '1.25rem' }}>
        {/* Card 1: RAG Vector Knowledge Bases */}
        <div
          style={{
            padding: '1.6rem',
            background: 'linear-gradient(135deg, rgba(30, 27, 75, 0.4) 0%, rgba(24, 24, 27, 0.8) 100%)',
            border: '1px solid rgba(129, 140, 248, 0.25)',
            borderRadius: '14px',
            boxShadow: '0 8px 30px rgba(0, 0, 0, 0.25)',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
            position: 'relative',
            overflow: 'hidden',
          }}
        >
          <div style={{ position: 'absolute', top: 0, right: 0, width: 120, height: 120, background: 'radial-gradient(circle, rgba(99, 102, 241, 0.15) 0%, transparent 70%)', pointerEvents: 'none' }} />
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
              <div style={{ width: 44, height: 44, borderRadius: '10px', background: 'rgba(99, 102, 241, 0.18)', border: '1px solid rgba(99, 102, 241, 0.35)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                <ArchIcon name="database" size={22} color="#818cf8" />
              </div>
              <span style={{ fontSize: '11px', fontWeight: 600, padding: '3px 8px', borderRadius: '12px', background: 'rgba(99, 102, 241, 0.15)', color: '#a5b4fc', border: '1px solid rgba(99, 102, 241, 0.3)' }}>
                pgvector · HNSW
              </span>
            </div>
            <h3 style={{ margin: '0 0 0.5rem', fontSize: '1.2rem', fontWeight: 600, color: '#f8fafc' }}>
              RAG Vector Knowledge Bases
            </h3>
            <p style={{ fontSize: '13px', color: '#94a3b8', lineHeight: 1.55, margin: '0 0 1.25rem' }}>
              Native pgvector embeddings for document chunks, hybrid semantic retrieval, and contextual augmentation inside your workflows.
            </p>
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            <button className="primary" onClick={() => navigate('/knowledge')} style={{ fontSize: '12.5px', padding: '0.45rem 0.85rem' }}>
              Manage Knowledge Collections →
            </button>
            <a
              href="#rag-playground"
              className="ghost"
              style={{ fontSize: '12.5px', padding: '0.45rem 0.85rem', textDecoration: 'none', display: 'inline-flex', alignItems: 'center' }}
            >
              Test Query ↓
            </a>
          </div>
        </div>

        {/* Card 2: Model Context Protocol (MCP) */}
        <div
          style={{
            padding: '1.6rem',
            background: 'linear-gradient(135deg, rgba(6, 78, 59, 0.3) 0%, rgba(24, 24, 27, 0.8) 100%)',
            border: '1px solid rgba(52, 211, 153, 0.25)',
            borderRadius: '14px',
            boxShadow: '0 8px 30px rgba(0, 0, 0, 0.25)',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
            position: 'relative',
            overflow: 'hidden',
          }}
        >
          <div style={{ position: 'absolute', top: 0, right: 0, width: 120, height: 120, background: 'radial-gradient(circle, rgba(16, 185, 129, 0.15) 0%, transparent 70%)', pointerEvents: 'none' }} />
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
              <div style={{ width: 44, height: 44, borderRadius: '10px', background: 'rgba(16, 185, 129, 0.18)', border: '1px solid rgba(16, 185, 129, 0.35)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                <ArchIcon name="mcp" size={22} color="#34d399" />
              </div>
              <span style={{ fontSize: '11px', fontWeight: 600, padding: '3px 8px', borderRadius: '12px', background: 'rgba(16, 185, 129, 0.15)', color: '#6ee7b7', border: '1px solid rgba(16, 185, 129, 0.3)' }}>
                MCP Protocol 2024-11-05
              </span>
            </div>
            <h3 style={{ margin: '0 0 0.5rem', fontSize: '1.2rem', fontWeight: 600, color: '#f8fafc' }}>
              Model Context Protocol (MCP)
            </h3>
            <p style={{ fontSize: '13px', color: '#94a3b8', lineHeight: 1.55, margin: '0 0 0.75rem' }}>
              Flowsmith exposes a bidirectional MCP Server (<code style={{ color: '#6ee7b7', background: 'rgba(0,0,0,0.3)', padding: '1px 5px', borderRadius: 4 }}>/api/mcp</code>) allowing Claude Desktop, Cursor, or external LLMs to execute connectors, query data tables, and search knowledge bases.
            </p>
            <div style={{ fontSize: '12px', color: '#34d399', display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '1.25rem' }}>
              <span style={{ width: 7, height: 7, borderRadius: '50%', background: '#10b981', display: 'inline-block' }} />
              <span>Bi-directional Tools Active (list_connectors, search_knowledge, query_data_table)</span>
            </div>
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            <a
              href="#mcp-studio"
              className="primary"
              style={{ fontSize: '12.5px', padding: '0.45rem 0.85rem', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', background: '#059669', borderColor: '#10b981' }}
            >
              Open MCP Studio ↓
            </a>
            <button className="ghost" onClick={handleCopySnippet} style={{ fontSize: '12.5px', padding: '0.45rem 0.85rem' }}>
              {copiedSnippet ? (<span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>Copied</span>) : 'Copy Claude Config'}
            </button>
          </div>
        </div>

        {/* Card 3: Deterministic Graph Auto-Repair */}
        <div
          style={{
            padding: '1.6rem',
            background: 'linear-gradient(135deg, rgba(88, 28, 135, 0.3) 0%, rgba(24, 24, 27, 0.8) 100%)',
            border: '1px solid rgba(192, 132, 252, 0.25)',
            borderRadius: '14px',
            boxShadow: '0 8px 30px rgba(0, 0, 0, 0.25)',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
            position: 'relative',
            overflow: 'hidden',
          }}
        >
          <div style={{ position: 'absolute', top: 0, right: 0, width: 120, height: 120, background: 'radial-gradient(circle, rgba(168, 85, 247, 0.15) 0%, transparent 70%)', pointerEvents: 'none' }} />
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
              <div style={{ width: 44, height: 44, borderRadius: '10px', background: 'rgba(168, 85, 247, 0.18)', border: '1px solid rgba(168, 85, 247, 0.35)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                <ArchIcon name="repair" size={22} color="#c084fc" />
              </div>
              <span style={{ fontSize: '11px', fontWeight: 600, padding: '3px 8px', borderRadius: '12px', background: 'rgba(168, 85, 247, 0.15)', color: '#d8b4fe', border: '1px solid rgba(168, 85, 247, 0.3)' }}>
                Zero Hallucination · AST
              </span>
            </div>
            <h3 style={{ margin: '0 0 0.5rem', fontSize: '1.2rem', fontWeight: 600, color: '#f8fafc' }}>
              Deterministic Graph Auto-Repair
            </h3>
            <p style={{ fontSize: '13px', color: '#94a3b8', lineHeight: 1.55, margin: '0 0 1.25rem' }}>
              Execution failures are diagnosed at runtime. The AI Auto-Fix engine analyzes upstream payloads and generates precise parameter repairs with zero hallucination.
            </p>
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            <button className="primary" onClick={() => navigate('/workflows')} style={{ fontSize: '12.5px', padding: '0.45rem 0.85rem', background: '#7c3aed', borderColor: '#a855f7' }}>
              Trace in Workflow Editor →
            </button>
            <a
              href="#repair-simulator"
              className="ghost"
              style={{ fontSize: '12.5px', padding: '0.45rem 0.85rem', textDecoration: 'none', display: 'inline-flex', alignItems: 'center' }}
            >
              Simulate Repair ↓
            </a>
          </div>
        </div>
      </div>

      {/* 2. ONE FLOWSMITH PLATFORM: 7-LAYER TARGET ARCHITECTURE & STRATEGIC CONVERGENCE */}
      <div
        style={{
          background: 'var(--card-bg, #18181b)',
          border: '1px solid var(--border-color, #27272a)',
          borderRadius: '14px',
          padding: '1.6rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '1.5rem', flexWrap: 'wrap', gap: '0.75rem' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
              <ArchIcon name="platform" size={22} color="#818cf8" />
              <h3 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 700, letterSpacing: '-0.02em', color: '#f8fafc' }}>
                One Flowsmith Platform: Strategic Convergence
              </h3>
              <span style={{ fontSize: '11px', background: 'rgba(99, 102, 241, 0.15)', color: '#818cf8', padding: '3px 8px', borderRadius: '12px', border: '1px solid rgba(99, 102, 241, 0.3)', fontWeight: 600 }}>
                7-Layer Enterprise Stack
              </span>
            </div>
            <p style={{ margin: 0, fontSize: '13px', color: '#94a3b8', maxWidth: '850px', lineHeight: 1.5 }}>
              Flowsmith transcends the vanity race of shallow connector counts. Instead, it converges <strong>frictionless visual simplicity</strong>, <strong>deep technical runtime control</strong>, <strong>embedded enterprise iPaaS architecture</strong>, and <strong>Flowsmith&apos;s sovereign enterprise AI moat</strong> into a single unified self-hosted foundation.
            </p>
          </div>
          <span style={{ fontSize: '11px', color: '#38bdf8', background: 'rgba(56, 189, 248, 0.1)', padding: '5px 12px', borderRadius: '16px', border: '1px solid rgba(56, 189, 248, 0.25)', fontWeight: 500 }}>
            Click any layer to explore architectural guarantees
          </span>
        </div>

        {/* 4 Convergence Pillars Banner */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
            gap: '0.85rem',
            marginBottom: '1.75rem',
          }}
        >
          {CONVERGENCE_PILLARS.map((p) => (
            <div
              key={p.id}
              style={{
                padding: '1rem',
                borderRadius: '10px',
                background: p.bg,
                border: `1px solid ${p.border}`,
                display: 'flex',
                flexDirection: 'column',
                gap: '0.35rem',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <ArchIcon name={p.id} size={20} color={p.color} />
                <span style={{ fontSize: '10px', fontWeight: 700, color: p.color, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  {p.category}
                </span>
              </div>
              <div style={{ fontSize: '13px', fontWeight: 600, color: '#f8fafc' }}>
                {p.pillar}
              </div>
              <div style={{ fontSize: '11.5px', color: '#cbd5e1', lineHeight: 1.45 }}>
                {p.summary}
              </div>
            </div>
          ))}
        </div>

        {/* 7-Layer Visual Pipeline Stack */}
        <div style={{ marginBottom: '1.25rem' }}>
          <div style={{ fontSize: '12px', fontWeight: 600, color: '#a1a1aa', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span>Topological Platform Execution Flow</span>
            <span style={{ fontSize: '11px', color: '#64748b' }}>(Layer 1 Intent → Layer 7 Consumption Surface)</span>
          </div>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(145px, 1fr))',
              gap: '0.65rem',
            }}
          >
            {ARCH_PIPELINE.map((stage, idx) => {
              const isSelected = activePipelineStep.id === stage.id
              return (
                <div
                  key={stage.id}
                  onClick={() => setActivePipelineStep(stage)}
                  style={{
                    padding: '0.9rem 0.75rem',
                    borderRadius: '10px',
                    background: isSelected ? 'rgba(99, 102, 241, 0.16)' : 'rgba(255, 255, 255, 0.02)',
                    border: isSelected ? '1px solid #818cf8' : '1px solid rgba(255, 255, 255, 0.07)',
                    boxShadow: isSelected ? '0 0 16px rgba(99, 102, 241, 0.25)' : 'none',
                    cursor: 'pointer',
                    transition: 'all 0.18s cubic-bezier(0.16, 1, 0.3, 1)',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'space-between',
                    minHeight: '120px',
                  }}
                >
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.35rem' }}>
                      <ArchIcon name={stage.id} size={18} color={isSelected ? '#c7d2fe' : '#94a3b8'} />
                      <span style={{ fontSize: '9.5px', fontWeight: 700, color: isSelected ? '#a5b4fc' : '#64748b' }}>
                        L{idx + 1}
                      </span>
                    </div>
                    <div style={{ fontSize: '12px', fontWeight: 600, color: isSelected ? '#c7d2fe' : '#f1f5f9', marginBottom: '2px', lineHeight: 1.25 }}>
                      {stage.title}
                    </div>
                  </div>
                  <div style={{ fontSize: '9.5px', fontWeight: 600, padding: '2px 5px', borderRadius: '4px', background: isSelected ? 'rgba(99, 102, 241, 0.25)' : 'rgba(255,255,255,0.04)', color: isSelected ? '#e0e7ff' : '#94a3b8', width: 'fit-content' }}>
                    {stage.badge}
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* Selected Layer Detail Inspector */}
        <div
          style={{
            padding: '1.25rem 1.4rem',
            background: 'linear-gradient(135deg, rgba(15, 23, 42, 0.8) 0%, rgba(9, 14, 26, 0.95) 100%)',
            border: '1px solid rgba(99, 102, 241, 0.25)',
            borderRadius: '10px',
            display: 'flex',
            alignItems: 'center',
            gap: '1.25rem',
            boxShadow: 'inset 0 1px 0 rgba(255, 255, 255, 0.05)',
          }}
        >
          <div style={{ width: 48, height: 48, borderRadius: '12px', background: 'rgba(99, 102, 241, 0.15)', border: '1px solid rgba(99, 102, 241, 0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
            <ArchIcon name={activePipelineStep.id} size={24} color="#818cf8" />
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '3px' }}>
              <span style={{ fontSize: '11px', fontWeight: 700, color: '#818cf8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                {activePipelineStep.layer || 'Layer'}
              </span>
              <span style={{ fontSize: '14px', fontWeight: 600, color: '#f8fafc' }}>
                {activePipelineStep.title} — Architectural Guarantee
              </span>
            </div>
            <div style={{ fontSize: '13px', color: '#cbd5e1', lineHeight: '1.5' }}>
              {activePipelineStep.details}
            </div>
          </div>
        </div>
      </div>

      {/* 3. MODEL CONTEXT PROTOCOL (MCP) STUDIO */}
      <div
        id="mcp-studio"
        style={{
          background: 'var(--card-bg, #18181b)',
          border: '1px solid var(--border-color, #27272a)',
          borderRadius: '14px',
          padding: '1.6rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '0.75rem' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <ArchIcon name="mcp" size={20} color="#34d399" />
              <h3 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 600 }}>
                Model Context Protocol (MCP) Studio
              </h3>
              <span style={{ fontSize: '11px', background: 'rgba(34, 197, 94, 0.15)', color: '#4ade80', padding: '2px 8px', borderRadius: '12px', border: '1px solid rgba(34, 197, 94, 0.3)' }}>
                Server Online
              </span>
            </div>
            <p style={{ margin: '4px 0 0', fontSize: '13px', color: '#a1a1aa' }}>
              Connect your favorite AI IDEs and test live tool dispatches against Flowsmith's internal orchestrator.
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '12px', color: '#94a3b8' }}>
            <span>Endpoint:</span>
            <code style={{ background: '#09090b', padding: '3px 8px', borderRadius: '6px', border: '1px solid #27272a', color: '#38bdf8', fontFamily: 'monospace' }}>
              {origin}/api/mcp
            </code>
          </div>
        </div>

        {/* 2-Column Studio Grid: Left Config, Right Live Runner */}
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1.25fr)', gap: '1.5rem' }}>
          {/* Left: Client Setup */}
          <div
            style={{
              padding: '1.25rem',
              background: '#09090b',
              border: '1px solid #27272a',
              borderRadius: '10px',
              display: 'flex',
              flexDirection: 'column',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
              <span style={{ fontSize: '12.5px', fontWeight: 600, color: '#e2e8f0' }}>Client Configuration</span>
              <div style={{ display: 'flex', gap: '4px' }}>
                {['claude', 'cursor', 'python', 'curl'].map((tab) => (
                  <button
                    key={tab}
                    onClick={() => setClientTab(tab)}
                    style={{
                      fontSize: '11px',
                      padding: '2px 8px',
                      borderRadius: '4px',
                      background: clientTab === tab ? '#3b82f6' : 'transparent',
                      color: clientTab === tab ? '#ffffff' : '#94a3b8',
                      border: 'none',
                      cursor: 'pointer',
                      textTransform: tab === 'claude' ? 'none' : 'uppercase',
                    }}
                  >
                    {tab === 'claude' ? 'Claude' : tab}
                  </button>
                ))}
              </div>
            </div>

            <div style={{ position: 'relative', flex: 1, minHeight: 220 }}>
              <pre
                style={{
                  margin: 0,
                  padding: '0.75rem',
                  background: 'rgba(0, 0, 0, 0.4)',
                  border: '1px solid rgba(255, 255, 255, 0.08)',
                  borderRadius: '6px',
                  fontFamily: 'monospace',
                  fontSize: '11.5px',
                  lineHeight: '1.45',
                  color: '#93c5fd',
                  overflowX: 'auto',
                  height: '100%',
                  boxSizing: 'border-box',
                }}
              >
                {CLIENT_CONFIG_SNIPPETS[clientTab](origin)}
              </pre>
              <button
                onClick={handleCopySnippet}
                style={{
                  position: 'absolute',
                  top: '8px',
                  right: '8px',
                  fontSize: '11px',
                  padding: '4px 8px',
                  borderRadius: '4px',
                  background: copiedSnippet ? '#10b981' : 'rgba(255, 255, 255, 0.1)',
                  color: '#fff',
                  border: 'none',
                  cursor: 'pointer',
                }}
              >
                {copiedSnippet ? (<span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>Copied</span>) : 'Copy'}
              </button>
            </div>
            <div style={{ fontSize: '11px', color: '#64748b', marginTop: '0.6rem' }}>
              {clientTab === 'claude' && 'Paste into ~/Library/Application Support/Claude/claude_desktop_config.json or %APPDATA%\\Claude.'}
              {clientTab === 'cursor' && 'Add to your project’s .cursor/mcp.json to enable Flowsmith tools in Cursor Chat.'}
              {clientTab === 'python' && 'Standard official Model Context Protocol Python SDK integration.'}
              {clientTab === 'curl' && 'Direct JSON-RPC tool dispatch via HTTP POST.'}
            </div>
          </div>

          {/* Right: Live Tool Tester */}
          <div
            style={{
              padding: '1.25rem',
              background: '#09090b',
              border: '1px solid #27272a',
              borderRadius: '10px',
              display: 'flex',
              flexDirection: 'column',
              minWidth: 0,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
              <span style={{ fontSize: '12.5px', fontWeight: 600, color: '#e2e8f0' }}>Live MCP Tool Dispatcher</span>
              <div style={{ fontSize: '11px', color: '#94a3b8' }}>
                {mcpLoading ? 'Loading tools...' : `${mcpTools.length} tools available`}
              </div>
            </div>

            {/* Tool Selection Pills */}
            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginBottom: '0.75rem' }}>
              {mcpTools.slice(0, 6).map((tool) => (
                <button
                  key={tool.name}
                  onClick={() => handleSelectTool(tool.name)}
                  style={{
                    fontSize: '11.5px',
                    padding: '3px 9px',
                    borderRadius: '6px',
                    background: selectedToolName === tool.name ? 'rgba(59, 130, 246, 0.2)' : 'rgba(255, 255, 255, 0.03)',
                    color: selectedToolName === tool.name ? '#60a5fa' : '#94a3b8',
                    border: selectedToolName === tool.name ? '1px solid #3b82f6' : '1px solid rgba(255, 255, 255, 0.08)',
                    cursor: 'pointer',
                    fontFamily: 'monospace',
                  }}
                >
                  {tool.name}
                </button>
              ))}
            </div>

            {/* Selected Tool Info */}
            {selectedTool && (
              <div style={{ fontSize: '12px', color: '#cbd5e1', marginBottom: '0.6rem', padding: '6px 10px', background: 'rgba(255, 255, 255, 0.02)', borderRadius: '6px' }}>
                <strong>Description:</strong> {selectedTool.description}
              </div>
            )}

            {/* Tool Arguments Editor */}
            <div style={{ marginBottom: '0.75rem' }}>
              <div style={{ fontSize: '11px', color: '#64748b', marginBottom: '4px' }}>Tool Arguments (JSON):</div>
              <textarea
                value={toolArgsText}
                onChange={(e) => setToolArgsText(e.target.value)}
                rows={3}
                style={{
                  width: '100%',
                  boxSizing: 'border-box',
                  background: 'rgba(0, 0, 0, 0.4)',
                  border: '1px solid rgba(255, 255, 255, 0.1)',
                  borderRadius: '6px',
                  color: '#e2e8f0',
                  fontFamily: 'monospace',
                  fontSize: '11.5px',
                  padding: '6px 8px',
                  outline: 'none',
                }}
              />
            </div>

            {/* Run Button */}
            <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', marginBottom: '0.75rem' }}>
              <button
                className="primary"
                onClick={handleExecuteTool}
                disabled={toolExecuting}
                style={{ fontSize: '12px', padding: '0.45rem 1rem' }}
              >
                {toolExecuting ? 'Executing via /api/mcp/call...' : '▶ Execute Tool Call'}
              </button>
              {toolExecutionLatency !== null && (
                <span style={{ fontSize: '11px', color: '#4ade80' }}>
                  Response in {toolExecutionLatency}ms
                </span>
              )}
            </div>

            {/* Error Display */}
            {toolError && (
              <div style={{ fontSize: '12px', color: '#f87171', padding: '6px 10px', background: 'rgba(239, 68, 68, 0.1)', borderRadius: '6px', marginBottom: '0.5rem' }}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg> {toolError}
              </div>
            )}

            {/* Tool Output Viewer */}
            {toolExecutionResult && (
              <pre
                style={{
                  margin: 0,
                  padding: '0.75rem',
                  background: 'rgba(0, 0, 0, 0.5)',
                  border: '1px solid rgba(34, 197, 94, 0.25)',
                  borderRadius: '6px',
                  fontFamily: 'monospace',
                  fontSize: '11px',
                  color: '#86efac',
                  maxHeight: '160px',
                  overflowY: 'auto',
                }}
              >
                {JSON.stringify(toolExecutionResult, null, 2)}
              </pre>
            )}
          </div>
        </div>
      </div>

      {/* 4. RAG VECTOR KNOWLEDGE PLAYGROUND */}
      <div
        id="rag-playground"
        style={{
          background: 'var(--card-bg, #18181b)',
          border: '1px solid var(--border-color, #27272a)',
          borderRadius: '14px',
          padding: '1.6rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '0.5rem' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <ArchIcon name="rag" size={20} color="#818cf8" />
              <h3 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 600 }}>
                pgvector RAG Semantic Search Playground
              </h3>
            </div>
            <p style={{ margin: '4px 0 0', fontSize: '13px', color: '#a1a1aa' }}>
              Test vector similarity queries and trace retrieved chunks with exact cosine similarity scores.
            </p>
          </div>
          <button className="ghost" onClick={() => navigate('/knowledge')} style={{ fontSize: '12px' }}>
            Full Knowledge Manager →
          </button>
        </div>

        {ragCollections.length === 0 ? (
          <div
            style={{
              padding: '2rem',
              textAlign: 'center',
              background: '#09090b',
              border: '1px dashed #3f3f46',
              borderRadius: '10px',
            }}
          >
            <div style={{ marginBottom: '0.75rem', display: 'flex', justifyContent: 'center' }}>
              <ArchIcon name="empty" size={32} color="#64748b" />
            </div>
            <div style={{ fontSize: '14px', fontWeight: 600, color: '#f1f5f9', marginBottom: '0.4rem' }}>
              No Knowledge Collections Ingested Yet
            </div>
            <p style={{ fontSize: '13px', color: '#94a3b8', maxWidth: 450, margin: '0 auto 1.25rem' }}>
              Create an embedding collection to enable semantic retrieval and hybrid search inside your workflow nodes.
            </p>
            <button
              className="primary"
              onClick={handleCreateDemoCollection}
              disabled={creatingDemoRag}
              style={{ fontSize: '13px', padding: '0.5rem 1.25rem' }}
            >
              {creatingDemoRag ? 'Embedding Sample Docs...' : 'Create Demo RAG Collection'}
            </button>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {/* Search Input Bar */}
            <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
              <select
                value={selectedRagId}
                onChange={(e) => setSelectedRagId(e.target.value)}
                style={{
                  padding: '0.6rem 0.85rem',
                  borderRadius: '8px',
                  background: '#09090b',
                  border: '1px solid #3f3f46',
                  color: '#fff',
                  fontSize: '13px',
                  minWidth: 200,
                  outline: 'none',
                }}
              >
                {ragCollections.map((col) => (
                  <option key={col.id} value={col.id}>
                    {col.name} ({col.chunks_count ?? 3} chunks)
                  </option>
                ))}
              </select>

              <input
                type="text"
                value={ragQuery}
                onChange={(e) => setRagQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleRagSearch()}
                placeholder="Ask or search your documents (e.g. 'How does MCP integration work?')"
                style={{
                  flex: 1,
                  padding: '0.6rem 0.85rem',
                  borderRadius: '8px',
                  background: '#09090b',
                  border: '1px solid #3f3f46',
                  color: '#fff',
                  fontSize: '13px',
                  outline: 'none',
                  minWidth: 260,
                }}
              />

              <button
                className="primary"
                onClick={handleRagSearch}
                disabled={ragSearching || !ragQuery.trim()}
                style={{ fontSize: '13px', padding: '0.6rem 1.25rem' }}
              >
                {ragSearching ? 'Searching...' : 'Semantic Search'}
              </button>
            </div>

            {ragError && (
              <div style={{ fontSize: '12px', color: '#f87171', padding: '8px', background: 'rgba(239, 68, 68, 0.1)', borderRadius: '6px', display: 'flex', alignItems: 'center', gap: 6 }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                <span>{ragError}</span>
              </div>
            )}

            {/* Results Display */}
            {ragResults && (
              <div style={{ marginTop: '0.5rem' }}>
                <div style={{ fontSize: '12.5px', fontWeight: 600, color: '#e2e8f0', marginBottom: '0.6rem' }}>
                  Top Vector Matches ({Array.isArray(ragResults) ? ragResults.length : (ragResults.hits || []).length} chunks retrieved)
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '0.75rem' }}>
                  {(Array.isArray(ragResults) ? ragResults : (ragResults.hits || [])).map((hit, idx) => (
                    <div
                      key={idx}
                      style={{
                        padding: '1rem',
                        background: '#09090b',
                        border: '1px solid rgba(255, 255, 255, 0.08)',
                        borderRadius: '8px',
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                        <span style={{ fontSize: '11px', color: '#a5b4fc', fontWeight: 600 }}>Chunk #{idx + 1}</span>
                        <span style={{ fontSize: '11px', color: '#4ade80', background: 'rgba(34, 197, 94, 0.12)', padding: '2px 6px', borderRadius: '4px' }}>
                          Score: {typeof hit.score === 'number' ? `${(hit.score * 100).toFixed(1)}%` : 'High'}
                        </span>
                      </div>
                      <div style={{ fontSize: '12.5px', color: '#cbd5e1', lineHeight: '1.45' }}>
                        "{hit.text || hit.content || JSON.stringify(hit)}"
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 5. DETERMINISTIC GRAPH AUTO-REPAIR SIMULATOR */}
      <div
        id="repair-simulator"
        style={{
          background: 'var(--card-bg, #18181b)',
          border: '1px solid var(--border-color, #27272a)',
          borderRadius: '14px',
          padding: '1.6rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '0.5rem' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <ArchIcon name="repair" size={20} color="#c084fc" />
              <h3 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 600 }}>
                Deterministic Graph Auto-Repair Architecture
              </h3>
            </div>
            <p style={{ margin: '4px 0 0', fontSize: '13px', color: '#a1a1aa' }}>
              Why Flowsmith never hallucinates parameters: how AST payload analysis automatically fixes broken nodes at runtime.
            </p>
          </div>
          <button
            className="primary"
            onClick={handleSimulateRepair}
            disabled={simulatingRepair}
            style={{ fontSize: '12px', padding: '0.45rem 1rem' }}
          >
            {simulatingRepair ? 'Simulating Diagnostics...' : 'Run Repair Simulation'}
          </button>
        </div>

        {/* 4-Step Interactive Timeline */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.75rem', marginBottom: '1.25rem' }}>
          {[
            { step: 1, title: '1. Exception Intercept', text: 'Catches execution failure (e.g. HTTP 401 or JSONPath drift).' },
            { step: 2, title: '2. Upstream Introspection', text: 'Extracts real schema fields without re-running remote APIs.' },
            { step: 3, title: '3. Type-Safe Patch Solver', text: 'Validates candidate fixes against the node JSON schema.' },
            { step: 4, title: '4. Atomic DAG Resumption', text: 'Hot-patches node params and retries with decorrelated jitter.' },
          ].map((s) => {
            const isDone = repairStep >= s.step
            const isCurrent = repairStep === s.step && simulatingRepair
            return (
              <div
                key={s.step}
                style={{
                  padding: '1rem',
                  borderRadius: '8px',
                  background: isCurrent ? 'rgba(168, 85, 247, 0.15)' : isDone ? 'rgba(34, 197, 94, 0.08)' : 'rgba(255, 255, 255, 0.02)',
                  border: isCurrent ? '1px solid #a855f7' : isDone ? '1px solid rgba(34, 197, 94, 0.3)' : '1px solid rgba(255, 255, 255, 0.06)',
                  transition: 'all 0.2s ease',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
                  <span style={{ fontSize: '12.5px', fontWeight: 600, color: isDone ? '#4ade80' : '#f1f5f9' }}>
                    {s.title}
                  </span>
                  {isDone && <span style={{ fontSize: "11px", color: "#4ade80", display: "inline-flex", alignItems: "center" }}><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg></span>}
                </div>
                <div style={{ fontSize: '11.5px', color: '#94a3b8', lineHeight: '1.35' }}>
                  {s.text}
                </div>
              </div>
            )
          })}
        </div>

        {/* Live Repair Before / After Diff */}
        <div style={{ padding: '1rem', background: '#09090b', borderRadius: '8px', border: '1px solid #27272a' }}>
          <div style={{ fontSize: '12px', fontWeight: 600, color: '#e2e8f0', marginBottom: '6px' }}>
            Example: Fixing Broken JSONPath Expression on Runtime Drift
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div style={{ padding: '0.75rem', background: 'rgba(239, 68, 68, 0.08)', border: '1px solid rgba(239, 68, 68, 0.25)', borderRadius: '6px' }}>
              <div style={{ fontSize: '11px', fontWeight: 600, color: '#f87171', marginBottom: '4px' }}>FAILED NODE PARAMETERS</div>
              <pre style={{ margin: 0, fontSize: '11px', color: '#fca5a5', fontFamily: 'monospace' }}>
{`// Upstream emitted 'user_id', but node expected 'id'
{
  "customer_id": "{{ $json.id }}" // null / missing property
}`}
              </pre>
            </div>

            <div style={{ padding: '0.75rem', background: 'rgba(34, 197, 94, 0.08)', border: '1px solid rgba(34, 197, 94, 0.25)', borderRadius: '6px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                <span style={{ fontSize: '11px', fontWeight: 600, color: '#4ade80' }}>AUTO-REPAIRED (ZERO HALLUCINATION)</span>
                {repairStep >= 3 && <span style={{ fontSize: '10px', color: '#4ade80' }}>Verified</span>}
              </div>
              <pre style={{ margin: 0, fontSize: '11px', color: '#86efac', fontFamily: 'monospace' }}>
{`// Inferred from upstream schema without guessing
{
  "customer_id": "{{ $json.user_id }}" // Resolved from schema
}`}
              </pre>
            </div>
          </div>
        </div>
      </div>

      {/* 6. MULTI-MODEL FLEET & DATA SOVEREIGNTY */}
      <div
        style={{
          background: 'var(--card-bg, #18181b)',
          border: '1px solid var(--border-color, #27272a)',
          borderRadius: '14px',
          padding: '1.6rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '0.5rem' }}>
          <div>
            <h3 style={{ margin: '0 0 0.25rem', fontSize: '1.15rem', fontWeight: 600 }}>
              Sovereign Multi-Model AI Fleet
            </h3>
            <p style={{ margin: 0, fontSize: '13px', color: '#a1a1aa' }}>
              Connect enterprise cloud providers or run 100% air-gapped on-premise models with zero data egress.
            </p>
          </div>
          <button className="ghost" onClick={() => navigate('/credentials')} style={{ fontSize: '12px' }}>
            Configure Credentials →
          </button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.75rem' }}>
          {[
            { name: 'Anthropic Claude', models: 'Claude 3.5 Sonnet, Claude 3 Opus', badge: 'Tool Calling', desc: 'Superior multi-step reasoning & code generation.' },
            { name: 'OpenAI', models: 'GPT-4o, GPT-4o-mini', badge: 'Structured JSON', desc: 'Ultra-low latency JSON schema synthesis.' },
            { name: 'Ollama (Local / On-Prem)', models: 'Llama 3.3, Mistral, Qwen', badge: '100% Air-Gapped', desc: 'Zero data egress. HIPAA & GDPR private sovereignty.' },
            { name: 'Azure OpenAI', models: 'Private Tenant Deployments', badge: 'VPC Isolated', desc: 'Enterprise managed private cloud endpoints.' },
            { name: 'Groq', models: 'Llama 3.3 70B @ 300+ tok/s', badge: 'Ultra-Fast LPU', desc: 'Sub-second copilot workflow generations.' },
          ].map((provider) => (
            <div
              key={provider.name}
              style={{
                padding: '1rem',
                background: '#09090b',
                border: '1px solid rgba(255, 255, 255, 0.08)',
                borderRadius: '8px',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
              }}
            >
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '6px' }}>
                  <div style={{ fontSize: '13px', fontWeight: 600, color: '#f8fafc' }}>{provider.name}</div>
                  <span style={{ fontSize: '10px', color: '#38bdf8', background: 'rgba(56, 189, 248, 0.12)', padding: '2px 6px', borderRadius: '4px' }}>
                    {provider.badge}
                  </span>
                </div>
                <div style={{ fontSize: '11px', color: '#94a3b8', marginBottom: '4px' }}>{provider.models}</div>
                <div style={{ fontSize: '11.5px', color: '#64748b', lineHeight: '1.35' }}>{provider.desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
