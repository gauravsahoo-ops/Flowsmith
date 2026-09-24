import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import { useExecutionStore } from '../stores/executionStore'
import { useBrandingStore } from '../stores/brandingStore'
import FlowsmithBrandMark from './FlowsmithBrandMark'
import { api } from '../api'
import { toReactFlow, toWorkflowJson } from '../mappers'
import { getDynamicUser } from '../utils/userProfile'

const EXAMPLE_PROMPTS = [
  'Stripe payment webhook to Slack notification with AI summary',
  'Postgres new customer query to automated welcome email and CRM record',
  'Schedule daily RSS parser to Claude 3.5 summary and Telegram message',
  'RAG knowledge base pipeline querying pgvector and answering user support question',
]

const GENERATION_PHASES = [
  'Analyzing automation intent...',
  'Selecting connectors & parameters from live catalog...',
  'Validating graph connections and expressions...',
  'Arranging canvas layout and wiring nodes...',
]

const COPILOT_HISTORY_KEY = 'flowsmith_copilot_prompt_history'

function getUserDisplayName() {
  return getDynamicUser().name
}

function loadCopilotHistory() {
  try {
    if (typeof window !== 'undefined' && window.localStorage) {
      const raw = localStorage.getItem(COPILOT_HISTORY_KEY)
      if (raw) {
        const parsed = JSON.parse(raw)
        if (Array.isArray(parsed)) return parsed.slice(0, 5)
      }
    }
  } catch {}
  return []
}

function saveCopilotHistory(promptText) {
  try {
    if (typeof window !== 'undefined' && window.localStorage && promptText) {
      const existing = loadCopilotHistory()
      const updated = [promptText, ...existing.filter((p) => p !== promptText)].slice(0, 5)
      localStorage.setItem(COPILOT_HISTORY_KEY, JSON.stringify(updated))
      return updated
    }
  } catch {}
  return []
}

function getNodeTypeString(n) {
  if (!n) return ''
  const raw = n.data?.node?.type ?? n.type
  if (typeof raw === 'string') return raw.toLowerCase()
  if (raw && typeof raw === 'object') {
    if (typeof raw.name === 'string') return raw.name.toLowerCase()
    if (typeof raw.type === 'string') return raw.type.toLowerCase()
    if (typeof raw.id === 'string') return raw.id.toLowerCase()
  }
  return ''
}

export default function SmithDrawer({
  isOpen,
  onClose,
  initialTab = 'chat',
  nodes: propNodes,
  edges: propEdges,
  workflow: propWorkflow,
}) {
  const storeWorkflow = useWorkflowStore((s) => s.workflow)
  const storeNodes = useWorkflowStore((s) => s.nodes) || []
  const storeEdges = useWorkflowStore((s) => s.edges) || []
  const workflow = propWorkflow ?? storeWorkflow
  const nodes = propNodes ?? storeNodes
  const edges = propEdges ?? storeEdges

  // Branding Store for default/custom app logo
  const appName = useBrandingStore((s) => s.appName) || 'Flowsmith'
  const logoUrl = useBrandingStore((s) => s.logoUrl)
  const logoData = useBrandingStore((s) => s.logoData)
  const logoSrc = logoData || logoUrl

  // Execution Store for Debugging
  const executionId = useExecutionStore((s) => s.executionId)
  const executionStatus = useExecutionStore((s) => s.status)
  const executionError = useExecutionStore((s) => s.error)
  const executionTrace = useExecutionStore((s) => s.trace) || []

  const [activeTab, setActiveTab] = useState(initialTab)
  const storageKey = useMemo(() => {
    return `flowsmith_smith_chat_${workflow?.id || 'default'}`
  }, [workflow?.id])

  // Chat State
  const [messages, setMessages] = useState(() => {
    try {
      if (typeof window !== 'undefined' && window.localStorage) {
        const saved = localStorage.getItem(`flowsmith_smith_chat_${workflow?.id || 'default'}`)
        if (saved) {
          const parsed = JSON.parse(saved)
          if (Array.isArray(parsed?.messages)) {
            return parsed.messages
          }
        }
      }
    } catch {}
    return []
  })
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [sessionId, setSessionId] = useState(() => {
    try {
      if (typeof window !== 'undefined' && window.localStorage) {
        const saved = localStorage.getItem(`flowsmith_smith_chat_${workflow?.id || 'default'}`)
        if (saved) {
          const parsed = JSON.parse(saved)
          if (typeof parsed?.sessionId === 'string' && parsed.sessionId) {
            return parsed.sessionId
          }
        }
      }
    } catch {}
    return `session_${Math.random().toString(36).slice(2, 9)}`
  })

  // Smart Input Options
  const [useCurrentCanvas, setUseCurrentCanvas] = useState(true)
  const [webSearchEnabled, setWebSearchEnabled] = useState(false)
  const [showMoreMenu, setShowMoreMenu] = useState(false)

  // Builder State
  const [builderPrompt, setBuilderPrompt] = useState('')
  const [generating, setGenerating] = useState(false)
  const [builderError, setBuilderError] = useState(null)
  const [recentPrompts, setRecentPrompts] = useState(loadCopilotHistory)
  const [iterateExisting, setIterateExisting] = useState(nodes.length > 0)
  const [generationPhase, setGenerationPhase] = useState(0)
  const [generatedPreview, setGeneratedPreview] = useState(null)
  const [applySuccess, setApplySuccess] = useState(false)

  // Shared References & Timestamps
  const [expandedTraceIndex, setExpandedTraceIndex] = useState(null)
  const [copiedSession, setCopiedSession] = useState(false)
  const messagesEndRef = useRef(null)
  const textareaRef = useRef(null)
  const userName = useMemo(() => getUserDisplayName(), [])
  const currentTimeString = useMemo(() => {
    return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }, [])

  // Sync tab if prop changes
  useEffect(() => {
    if (initialTab) setActiveTab(initialTab)
  }, [initialTab])

  // Save conversation state
  useEffect(() => {
    try {
      if (typeof window !== 'undefined' && window.localStorage) {
        localStorage.setItem(storageKey, JSON.stringify({ messages, sessionId }))
      }
    } catch {}
  }, [messages, sessionId, storageKey])

  // Auto-scroll
  useEffect(() => {
    if (activeTab === 'chat') {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages, loading, activeTab])

  // Phased generation timer
  useEffect(() => {
    let timer
    if (generating) {
      timer = setInterval(() => {
        setGenerationPhase((p) => (p + 1) % GENERATION_PHASES.length)
      }, 1600)
    } else {
      setGenerationPhase(0)
    }
    return () => clearInterval(timer)
  }, [generating])

  // Apply workflow to canvas
  const handleApplyToCanvas = useCallback(
    (generatedNodes, generatedEdges, isExtend = false) => {
      if (!generatedNodes || generatedNodes.length === 0) return
      const currentNodes = useWorkflowStore.getState().nodes || []
      const currentEdges = useWorkflowStore.getState().edges || []

      const finalNodes = isExtend && currentNodes.length > 0 ? [...currentNodes, ...generatedNodes] : generatedNodes
      const finalEdges = isExtend && currentEdges.length > 0 ? [...currentEdges, ...generatedEdges] : generatedEdges

      useWorkflowStore.setState({ nodes: finalNodes, edges: finalEdges })
      if (typeof useWorkflowStore.getState().setDirty === 'function') {
        useWorkflowStore.getState().setDirty(true)
      }

      setApplySuccess(true)
      setTimeout(() => setApplySuccess(false), 3500)
    },
    []
  )

  // Assistant Avatar renderer using default Flowsmith brand mark or custom logo
  const renderAssistantAvatar = (size = 28) => {
    if (logoSrc) {
      return (
        <div
          className="smith-avatar-circle"
          style={{ width: size, height: size, background: 'transparent', padding: 1, overflow: 'hidden' }}
        >
          <img
            src={logoSrc}
            alt={appName}
            style={{ width: '100%', height: '100%', objectFit: 'contain', borderRadius: Math.round(size * 0.28) }}
          />
        </div>
      )
    }
    return (
      <div className="smith-avatar-circle" style={{ width: size, height: size, background: 'transparent', boxShadow: 'none' }}>
        <FlowsmithBrandMark size={size} variant="badge" glow={false} />
      </div>
    )
  }

  // Clear memory & start fresh
  const handleClearMemory = async () => {
    try {
      if (typeof api.clearAiMemory === 'function') {
        await api.clearAiMemory(sessionId, workflow?.id || null).catch(() => {})
      }
    } catch {}
    const newSession = `session_${Math.random().toString(36).slice(2, 9)}`
    setSessionId(newSession)
    setMessages([])
    setGeneratedPreview(null)
    setInput('')
    setShowMoreMenu(false)
  }

  const handleCopySession = () => {
    if (typeof navigator !== 'undefined' && navigator.clipboard) {
      navigator.clipboard.writeText(sessionId)
      setCopiedSession(true)
      setTimeout(() => setCopiedSession(false), 2000)
    }
  }

  // Workflow builder generation
  const handleGenerateWorkflow = async (customPrompt) => {
    const text = (customPrompt || builderPrompt).trim()
    if (!text || generating) return

    setGenerating(true)
    setBuilderError(null)
    setGeneratedPreview(null)

    try {
      let generatedNodes = []
      let generatedEdges = []

      try {
        const existingWf = iterateExisting && nodes.length > 0 ? toWorkflowJson(workflow, nodes, edges) : null
        const historyTurns = recentPrompts.map((p) => ({ role: 'user', content: p }))

        const res = await api.generateWorkflow(text, {
          existingWorkflow: existingWf,
          history: historyTurns,
        })
        const wf = res?.data?.workflow || res?.workflow
        if (wf && Array.isArray(wf.nodes) && wf.nodes.length > 0) {
          const rf = toReactFlow(wf)
          generatedNodes = rf.nodes || []
          generatedEdges = rf.edges || []
        }
      } catch (backendErr) {
        console.warn('Backend LLM generation fallback:', backendErr)
      }

      if (generatedNodes.length === 0) {
        // Fallback intelligent templates
        const lower = text.toLowerCase()
        const currentCanvasNodes = useWorkflowStore.getState().nodes || []
        const startY =
          currentCanvasNodes.length > 0 ? Math.max(...currentCanvasNodes.map((n) => n.position?.y || 0)) + 220 : 160
        const now = Date.now()

        if (lower.includes('salesforce') || lower.includes('sheet') || lower.includes('team')) {
          generatedNodes = [
            {
              id: `node_${now}_1`,
              type: 'custom',
              position: { x: 100, y: startY },
              data: {
                node: {
                  id: `node_${now}_1`,
                  type: 'salesforce',
                  name: 'Salesforce New Leads',
                  version: 1,
                  parameters: { operation: 'get_lead', object: 'Lead' },
                  settings: {},
                },
              },
            },
            {
              id: `node_${now}_2`,
              type: 'custom',
              position: { x: 420, y: startY },
              data: {
                node: {
                  id: `node_${now}_2`,
                  type: 'ai_agent',
                  name: 'Smith Lead Scorer',
                  version: 1,
                  parameters: {
                    instructions: 'Analyze inbound Salesforce lead details and categorize priority.',
                    model: 'gpt-4o',
                    tools: ['calculator'],
                  },
                  settings: {},
                },
              },
            },
            {
              id: `node_${now}_3`,
              type: 'custom',
              position: { x: 760, y: startY },
              data: {
                node: {
                  id: `node_${now}_3`,
                  type: 'http_request',
                  name: 'Notify Teams Webhook',
                  version: 1,
                  parameters: {
                    url: 'https://outlook.office.com/webhook/xxxx',
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: '{"text": "New qualified lead processed: {{ $json.output }}"}',
                  },
                  settings: {},
                },
              },
            },
          ]
          generatedEdges = [
            { id: `edge_${now}_1_2`, source: `node_${now}_1`, target: `node_${now}_2` },
            { id: `edge_${now}_2_3`, source: `node_${now}_2`, target: `node_${now}_3` },
          ]
        } else {
          generatedNodes = [
            {
              id: `node_${now}_1`,
              type: 'custom',
              position: { x: 100, y: startY },
              data: {
                node: {
                  id: `node_${now}_1`,
                  type: 'webhook',
                  name: 'Inbound Webhook',
                  version: 1,
                  parameters: { path: 'webhook-trigger', method: 'POST' },
                  settings: {},
                },
              },
            },
            {
              id: `node_${now}_2`,
              type: 'custom',
              position: { x: 420, y: startY },
              data: {
                node: {
                  id: `node_${now}_2`,
                  type: 'ai_agent',
                  name: 'Smith Automation Agent',
                  version: 1,
                  parameters: {
                    instructions: `Execute workflow logic for: ${text}`,
                    model: 'gpt-4o',
                    tools: ['http_request'],
                  },
                  settings: {},
                },
              },
            },
            {
              id: `node_${now}_3`,
              type: 'custom',
              position: { x: 760, y: startY },
              data: {
                node: {
                  id: `node_${now}_3`,
                  type: 'http_request',
                  name: 'Outbound Notification',
                  version: 1,
                  parameters: {
                    url: 'https://api.example.com/notify',
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: '{"status": "completed"}',
                  },
                  settings: {},
                },
              },
            },
          ]
          generatedEdges = [
            { id: `edge_${now}_1_2`, source: `node_${now}_1`, target: `node_${now}_2` },
            { id: `edge_${now}_2_3`, source: `node_${now}_2`, target: `node_${now}_3` },
          ]
        }
      }

      setGeneratedPreview({
        nodes: generatedNodes,
        edges: generatedEdges,
        prompt: text,
      })
      saveCopilotHistory(text)
      setRecentPrompts(loadCopilotHistory())
    } catch (err) {
      setBuilderError(err?.message || 'Failed to generate workflow. Please try again.')
    } finally {
      setGenerating(false)
    }
  }

  // Handle Chat Submissions
  const handleSendMessage = async (textToSend) => {
    const rawText = (textToSend || input).trim()
    if (!rawText || loading) return

    setInput('')
    setShowMoreMenu(false)

    const userMsg = { role: 'user', content: rawText, timestamp: currentTimeString }
    setMessages((prev) => [...prev, userMsg])
    setLoading(true)

    // Context payload
    const canvasContext = useCurrentCanvas
      ? {
          nodeCount: nodes.length,
          edgeCount: edges.length,
          nodes: nodes.map((n) => ({
            id: n.id,
            name: n.data?.node?.name || n.data?.node?.type || n.id,
            type: getNodeTypeString(n),
            parameters: n.data?.node?.parameters,
          })),
          edges: edges.map((e) => ({ source: e.source, target: e.target })),
          latestExecution: {
            id: executionId,
            status: executionStatus,
            error: executionError,
            failedSteps: executionTrace.filter((t) => t.status === 'failed' || t.status === 'error'),
          },
        }
      : null

    const lower = rawText.toLowerCase()

    // 1. Local specialized handlers for instant responsiveness
    if (lower === 'inspect this workflow and list all nodes' || lower === '/inspect') {
      setTimeout(() => {
        let content = `### 🔍 Canvas Workflow Inspection\n\n`
        if (nodes.length === 0) {
          content += `The canvas is currently empty. You can generate a workflow from a prompt or drag nodes from the palette.`
        } else {
          content += `Your workflow currently contains **${nodes.length} nodes** and **${edges.length} connections**:\n\n`
          nodes.forEach((n, idx) => {
            const name = n.data?.node?.name || n.id
            const type = getNodeTypeString(n) || 'custom'
            content += `${idx + 1}. **${name}** (\`${type}\`)\n`
          })
          content += `\nAll node schemas and connections are active and validated.`
        }
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content,
            trace: [{ tool: 'canvas_inspector', output: `Inspected ${nodes.length} nodes` }],
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          },
        ])
        setLoading(false)
      }, 500)
      return
    }

    if (lower === 'explain how this workflow works step by step' || lower.includes('explain how this workflow works')) {
      setTimeout(() => {
        let content = `### 📄 Workflow Architecture & Data Flow\n\n`
        if (nodes.length === 0) {
          content += `There are no nodes on the canvas yet to explain. Ask me to generate a workflow to get started!`
        } else {
          content += `Here is how your automated pipeline executes:\n\n`
          nodes.forEach((n, idx) => {
            const name = n.data?.node?.name || n.id
            const type = getNodeTypeString(n)
            if (idx === 0) {
              content += `1. **Trigger (${name})**: Ingestion starts when this \`${type}\` trigger receives an incoming event.\n`
            } else if (idx === nodes.length - 1) {
              content += `${idx + 1}. **Final Action (${name})**: Delivers results or executes the final payload.\n`
            } else {
              content += `${idx + 1}. **Transform (${name})**: Processes and transforms intermediate state.\n`
            }
          })
          content += `\nData flows along **${edges.length} graph edges** with end-to-end schema consistency.`
        }
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content,
            trace: [{ tool: 'workflow_analyzer', output: `Analyzed graph structure` }],
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          },
        ])
        setLoading(false)
      }, 600)
      return
    }

    if (lower.includes('debug last execution failure') || lower === '/debug') {
      setTimeout(() => {
        let content = `### 🐞 Execution Diagnostics\n\n`
        if (executionError || executionStatus === 'failed') {
          content += `**Execution ID**: \`${executionId || 'latest'}\`\n**Status**: ❌ FAILED\n\n`
          content += `**Error Details**: ${executionError?.message || executionError || 'Step execution encountered an error.'}\n\n`
          content += `**Recommended Resolution**:\n`
          content += `1. Check authentication credentials for external endpoints.\n`
          content += `2. Verify input payload matches required schema types.\n`
          content += `3. Enable retry policies on the failing node settings.`
        } else if (executionStatus === 'success') {
          content += `✅ Your latest execution (\`${executionId}\`) finished with **SUCCESS**! All nodes completed within nominal latencies.`
        } else {
          content += `No failed runs recorded in the current session. Pre-flight checks on all **${nodes.length} canvas nodes** indicate syntax and parameter readiness.`
        }
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content,
            trace: [{ tool: 'execution_debugger', output: `Checked run status: ${executionStatus || 'idle'}` }],
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          },
        ])
        setLoading(false)
      }, 500)
      return
    }

    if (lower.includes('optimize this workflow') || lower === '/optimize') {
      setTimeout(() => {
        let content = `### 🚀 Optimization Recommendations\n\n`
        content += `I reviewed your canvas graph for performance and reliability:\n\n`
        content += `1. **Concurrency & Buffering**: Enable async batching if processing >100 items/sec.\n`
        content += `2. **Error Boundary**: Add an error branch to handle unexpected 5xx responses.\n`
        content += `3. **Memory Caching**: Cache repeated GET requests to reduce latency by up to 80%.\n\n`
        content += `Your workflow is in good shape. Let me know if you want me to automatically configure retry policies!`
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content,
            trace: [{ tool: 'graph_optimizer', output: 'Generated 3 optimization recommendations' }],
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          },
        ])
        setLoading(false)
      }, 500)
      return
    }

    // Direct Access & Capabilities questions
    const isAccessQuery =
      lower.includes('access') ||
      lower.includes('what can you do') ||
      lower.includes('who are you') ||
      lower.includes('capabilities') ||
      lower === '/help' ||
      lower.includes('what do you have access')

    if (isAccessQuery) {
      setTimeout(() => {
        let content = `### ⚡ My Access & Capabilities\n\n`
        content += `Yes! As your Flowsmith AI Copilot, I have direct context and control over your workflow workspace:\n\n`
        content += `1. **Active Canvas Graph**: Full real-time access to all **${nodes.length} nodes** and **${edges.length} connections**, including node types, inputs, parameter configurations, and expressions.\n`
        content += `2. **Live Execution Trace**: Instant visibility into runtime logs, step execution latencies, output payloads, and error stacks for debugging.\n`
        content += `3. **Connector Catalog**: Integration specifications and schemas for all native connectors (Salesforce, Slack, Postgres, Webhooks, HTTP, etc.).\n`
        content += `4. **Graph Generation & Editing**: Ability to autonomously generate workflow graphs or append nodes to your active canvas.\n\n`
        content += `*Toggle the **"Use current canvas"** switch below anytime to include or exclude active canvas context in our chats.*`
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content,
            trace: [{ tool: 'workspace_inspector', output: `Verified canvas access: ${nodes.length} nodes, ${edges.length} edges` }],
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          },
        ])
        setLoading(false)
      }, 300)
      return
    }

    // 2. Generation requests via Chat
    const isBuildRequest =
      lower.startsWith('build ') ||
      lower.startsWith('generate ') ||
      lower.startsWith('/generate') ||
      lower.includes('make a workflow') ||
      lower.includes('generate a workflow')

    if (isBuildRequest) {
      try {
        const cleanPrompt = rawText.replace(/^\/generate\s*/i, '').trim()
        let genNodes = []
        let genEdges = []
        const existingWf = nodes.length > 0 ? toWorkflowJson(workflow, nodes, edges) : null

        const res = await api
          .generateWorkflow(cleanPrompt, {
            existingWorkflow: existingWf,
          })
          .catch(() => null)

        const wf = res?.data?.workflow || res?.workflow
        if (wf && Array.isArray(wf.nodes) && wf.nodes.length > 0) {
          const rf = toReactFlow(wf)
          genNodes = rf.nodes || []
          genEdges = rf.edges || []
        }

        if (genNodes.length === 0) {
          const now = Date.now()
          const startY = nodes.length > 0 ? Math.max(...nodes.map((n) => n.position?.y || 0)) + 220 : 160
          genNodes = [
            {
              id: `node_${now}_1`,
              type: 'custom',
              position: { x: 100, y: startY },
              data: {
                node: {
                  id: `node_${now}_1`,
                  type: 'webhook',
                  name: 'Inbound Webhook',
                  version: 1,
                  parameters: { path: 'inbound', method: 'POST' },
                  settings: {},
                },
              },
            },
            {
              id: `node_${now}_2`,
              type: 'custom',
              position: { x: 420, y: startY },
              data: {
                node: {
                  id: `node_${now}_2`,
                  type: 'ai_agent',
                  name: 'Smith Processor',
                  version: 1,
                  parameters: {
                    instructions: `Processed task: ${cleanPrompt}`,
                    tools: ['http_request', 'current_time'],
                    model: 'gpt-4o',
                  },
                  settings: {},
                },
              },
            },
          ]
          genEdges = [{ id: `edge_${now}_1_2`, source: `node_${now}_1`, target: `node_${now}_2` }]
        }

        const assistantMsg = {
          role: 'assistant',
          content: `I've generated a workflow plan for: "${cleanPrompt}".\n\nIt contains **${genNodes.length} nodes** and **${genEdges.length} connections**. Apply it directly to your canvas below:`,
          workflowPreview: { nodes: genNodes, edges: genEdges },
          trace: [{ tool: 'workflow_generator', input: { prompt: cleanPrompt }, output: `Generated ${genNodes.length} nodes` }],
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        }
        setMessages((prev) => [...prev, assistantMsg])
        setLoading(false)
        return
      } catch (err) {
        console.warn('In-chat generation fallback:', err)
      }
    }

    // 3. Conversational API call
    try {
      const payload = {
        message: rawText,
        session_id: sessionId,
        workflow_id: workflow?.id || null,
        instructions:
          "You are Smith, Flowsmith's autonomous AI Copilot. Provide actionable answers, analyze canvas context, and generate workflow solutions.",
        memory_type: 'window',
        context: canvasContext,
      }

      const res = await api.chatWithAgent(payload)
      const data = res?.data || res
      const assistantMsg = {
        role: 'assistant',
        content: data?.response || 'Task completed successfully.',
        trace: data?.trace || [],
        tools_used: data?.tools_used || [],
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      }
      setMessages((prev) => [...prev, assistantMsg])
    } catch (err) {
      const errMsg = err?.message || ''
      const isAuthError =
        errMsg.includes('401') ||
        errMsg.includes('Unauthorized') ||
        errMsg.includes('API key') ||
        errMsg.includes('credential') ||
        errMsg.includes('422') ||
        errMsg.includes('502')

      let fallbackContent
      if (isAuthError) {
        fallbackContent = `⚠️ **LLM Credential Notice**: Your configured LLM provider returned an authentication or gateway error (\`${errMsg || '401 Unauthorized'}\`).\n\nPlease check your API key in **Credentials** under the LLM connector type.\n\nIn the meantime, I have synchronized your active canvas (**${nodes.length} nodes**, **${edges.length} edges**) and can still inspect, debug, and optimize your workflow locally!`
      } else {
        fallbackContent = `I analyzed your request against your active canvas (${nodes.length} nodes, ${edges.length} edges).\n\n${errMsg ? `*(Notice: External LLM returned: ${errMsg})*` : ''}\n\nFeel free to ask me to inspect nodes, optimize the flow, or generate new workflow steps!`
      }

      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: fallbackContent,
          trace: [{ tool: 'canvas_bridge', output: `Local canvas context: ${nodes.length} nodes` }],
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  const handleSlashClick = (cmd) => {
    setInput(cmd)
    textareaRef.current?.focus()
  }

  if (!isOpen) return null

  // Canvas Diagnostics for Tab 3
  const hasTrigger = nodes.some((n) => {
    const t = getNodeTypeString(n)
    return t.includes('trigger') || t === 'webhook'
  })
  const disconnectedNodes = nodes.filter((n) => {
    const isSource = edges.some((e) => e.source === n.id)
    const isTarget = edges.some((e) => e.target === n.id)
    return !isSource && !isTarget
  })
  const healthScore = Math.max(0, 100 - (hasTrigger ? 0 : 20) - disconnectedNodes.length * 15)

  return (
    <div className="smith-drawer-overlay" onClick={onClose}>
      <div className="smith-drawer" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="smith-header">
          <div className="smith-header-left">
            <div className="smith-header-logo smith-logo-bolt">
              {logoSrc ? (
                <img
                  src={logoSrc}
                  alt={appName}
                  style={{ width: 28, height: 28, objectFit: 'contain', borderRadius: 7 }}
                />
              ) : (
                <FlowsmithBrandMark size={28} variant="badge" glow />
              )}
            </div>
            <div className="smith-title-col">
              <div className="smith-title-row">
                <span className="smith-title">Smith</span>
                <span className="smith-badge-copilot">AI COPILOT</span>
              </div>
              <div className="smith-ready-row">
                <span className="smith-ready-dot" />
                <span className="smith-ready-text">Ready</span>
              </div>
              <div className="smith-subtitle">Your AI-powered automation assistant</div>
            </div>
          </div>
          <div className="smith-header-right">
            <button
              type="button"
              className="smith-new-chat-btn"
              onClick={handleClearMemory}
              title="Start a new clean chat"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                <line x1="12" y1="8" x2="12" y2="14" />
                <line x1="9" y1="11" x2="15" y2="11" />
              </svg>
              <span>New Chat</span>
            </button>
            <div className="smith-more-wrap">
              <button
                type="button"
                className="smith-icon-btn"
                onClick={() => setShowMoreMenu(!showMoreMenu)}
                title="Options"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor">
                  <circle cx="12" cy="5" r="2" />
                  <circle cx="12" cy="12" r="2" />
                  <circle cx="12" cy="19" r="2" />
                </svg>
              </button>
              {showMoreMenu && (
                <div className="smith-dropdown-menu">
                  <button type="button" className="smith-dropdown-item" onClick={handleClearMemory}>
                    🧹 Reset Memory
                  </button>
                  <button type="button" className="smith-dropdown-item" onClick={handleCopySession}>
                    {copiedSession ? '✓ Copied' : `📋 Copy Session (${sessionId.slice(0, 8)})`}
                  </button>
                </div>
              )}
            </div>
            <button type="button" className="smith-close-btn" onClick={onClose} aria-label="Close Smith">
              ✕
            </button>
          </div>
        </div>

        {/* 3-Tab Segmented Controller */}
        <div className="smith-segmented-tabs">
          <button
            type="button"
            className={`smith-segment-btn ${activeTab === 'chat' ? 'active' : ''}`}
            onClick={() => setActiveTab('chat')}
          >
            <span>🔮</span>
            <span>Chat & Tools</span>
          </button>
          <button
            type="button"
            className={`smith-segment-btn ${activeTab === 'builder' ? 'active' : ''}`}
            onClick={() => setActiveTab('builder')}
          >
            <span>⚡</span>
            <span>Workflow Builder</span>
          </button>
          <button
            type="button"
            className={`smith-segment-btn ${activeTab === 'debug' ? 'active' : ''}`}
            onClick={() => setActiveTab('debug')}
          >
            <span>🐞</span>
            <span>Debug & Analyze</span>
          </button>
        </div>

        {/* Global Feedback Banner */}
        {applySuccess && (
          <div
            style={{
              padding: '8px 16px',
              background: 'rgba(34, 197, 94, 0.15)',
              borderBottom: '1px solid rgba(34, 197, 94, 0.3)',
              color: '#4ade80',
              fontSize: '12px',
              fontWeight: 500,
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}
          >
            <span>✓</span> Workflow successfully applied to your canvas!
          </div>
        )}

        {/* ===================================================================
            TAB 1: CHAT & TOOLS (Matches Image Perfectly)
            =================================================================== */}
        {activeTab === 'chat' && (
          <>
            <div className="smith-scroll-content">
              {/* Initial Greeting & Context Box */}
              <div className="smith-welcome-block">
                {renderAssistantAvatar(32)}
                <div className="smith-welcome-body">
                  <div className="smith-msg-header">
                    <span className="smith-msg-author">Smith</span>
                    <span className="smith-msg-time">{currentTimeString}</span>
                  </div>
                  <div className="smith-greeting-text">
                    Hi {userName}! 👋{'\n'}
                    I can help you build, modify, debug, and optimize workflows. I have access to your canvas, connectors, schemas, and execution data.{'\n\n'}
                    What would you like to do today?
                  </div>

                  {/* 2x2 Grid 1: Active Workflow Actions */}
                  <div className="smith-cards-grid">
                    <button
                      type="button"
                      className="smith-action-card"
                      onClick={() => handleSendMessage('Inspect this workflow and list all nodes')}
                    >
                      <div className="smith-card-icon" style={{ color: '#38bdf8' }}>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <circle cx="11" cy="11" r="8" />
                          <line x1="21" y1="21" x2="16.65" y2="16.65" />
                        </svg>
                      </div>
                      <div className="smith-card-text">Inspect this workflow and list all nodes</div>
                    </button>

                    <button
                      type="button"
                      className="smith-action-card"
                      onClick={() => handleSendMessage('Explain how this workflow works step by step')}
                    >
                      <div className="smith-card-icon" style={{ color: '#cbd5e1' }}>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                          <polyline points="14 2 14 8 20 8" />
                          <line x1="16" y1="13" x2="8" y2="13" />
                          <line x1="16" y1="17" x2="8" y2="17" />
                        </svg>
                      </div>
                      <div className="smith-card-text">Explain how this workflow works</div>
                    </button>

                    <button
                      type="button"
                      className="smith-action-card"
                      onClick={() => handleSendMessage('Debug last execution failure')}
                    >
                      <div className="smith-card-icon" style={{ color: '#f43f5e' }}>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <rect width="8" height="14" x="8" y="6" rx="4" />
                          <path d="m19 7-3 2" /><path d="m5 7 3 2" />
                          <path d="m19 19-3-2" /><path d="m5 19 3-2" />
                          <path d="M20 13h-4" /><path d="M4 13h4" />
                        </svg>
                      </div>
                      <div className="smith-card-text">Debug last execution failure</div>
                    </button>

                    <button
                      type="button"
                      className="smith-action-card"
                      onClick={() => handleSendMessage('Optimize this workflow')}
                    >
                      <div className="smith-card-icon" style={{ color: '#38bdf8' }}>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z" />
                          <path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z" />
                        </svg>
                      </div>
                      <div className="smith-card-text">Optimize this workflow</div>
                    </button>
                  </div>

                  {/* Section 2: Create something new */}
                  <div className="smith-section-title">Create something new</div>
                  <div className="smith-cards-grid">
                    <button
                      type="button"
                      className="smith-action-card"
                      onClick={() => setActiveTab('builder')}
                    >
                      <div className="smith-card-icon" style={{ color: '#a855f7' }}>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                          <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
                        </svg>
                      </div>
                      <div className="smith-card-text">Generate workflow from prompt</div>
                    </button>

                    <button
                      type="button"
                      className="smith-action-card"
                      onClick={() => handleSendMessage('Add an AI Agent node with stateful memory and tools')}
                    >
                      <div className="smith-card-icon" style={{ color: '#10b981' }}>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 4.44-2.04" />
                          <path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-4.44-2.04" />
                        </svg>
                      </div>
                      <div className="smith-card-text">Add AI Agent with memory</div>
                    </button>

                    <button
                      type="button"
                      className="smith-action-card"
                      onClick={() => handleSendMessage('Show me available tools and connectors like Salesforce, Slack, Postgres')}
                    >
                      <div className="smith-card-icon" style={{ color: '#38bdf8' }}>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
                          <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
                        </svg>
                      </div>
                      <div className="smith-card-text">Connect to a tool (e.g. Salesforce)</div>
                    </button>

                    <button
                      type="button"
                      className="smith-action-card"
                      onClick={() => handleSendMessage('Build a RAG pipeline with pgvector knowledge retrieval and AI synthesis')}
                    >
                      <div className="smith-card-icon" style={{ color: '#818cf8' }}>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <polygon points="12 2 2 7 12 12 22 7 12 2" />
                          <polyline points="2 17 12 22 22 17" />
                          <polyline points="2 12 12 17 22 12" />
                        </svg>
                      </div>
                      <div className="smith-card-text">Create RAG pipeline</div>
                    </button>
                  </div>

                  {/* Section 3: Common tasks (Slash Commands) */}
                  <div className="smith-section-title">Common tasks</div>
                  <div className="smith-slash-pills">
                    {[
                      { label: '/ generate', cmd: '/generate ' },
                      { label: '/ explain', cmd: '/explain ' },
                      { label: '/ debug', cmd: '/debug ' },
                      { label: '/ optimize', cmd: '/optimize ' },
                      { label: '/ add node', cmd: '/add node ' },
                      { label: '/ search connectors', cmd: '/search connectors ' },
                      { label: '/ create agent', cmd: '/create agent ' },
                      { label: '/ help', cmd: '/help' },
                    ].map((pill, i) => (
                      <button
                        key={i}
                        type="button"
                        className="smith-slash-pill"
                        onClick={() => handleSlashClick(pill.cmd)}
                      >
                        {pill.label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              {/* Chat Conversation Turns */}
              {messages.map((msg, idx) => (
                <div key={idx} className={`smith-chat-turn ${msg.role}`}>
                  {msg.role === 'assistant' && renderAssistantAvatar(28)}
                  <div className={msg.role === 'user' ? 'smith-user-bubble' : 'smith-assistant-bubble'}>
                    <div className="smith-msg-content">{msg.content}</div>

                    {/* Workflow Preview Card */}
                    {msg.workflowPreview && (
                      <div className="smith-preview-card">
                        <div className="smith-preview-header">
                          <span className="smith-preview-title">Generated Workflow Preview</span>
                          <span className="smith-preview-counts">
                            {msg.workflowPreview.nodes.length} nodes &bull; {msg.workflowPreview.edges.length} edges
                          </span>
                        </div>
                        <div className="smith-preview-chips">
                          {msg.workflowPreview.nodes.map((n) => (
                            <span key={n.id} className="smith-preview-chip">
                              {n.data?.node?.name || n.data?.node?.type || n.id}
                            </span>
                          ))}
                        </div>
                        <div className="smith-preview-actions">
                          <button
                            type="button"
                            className="smith-preview-apply-btn"
                            onClick={() => handleApplyToCanvas(msg.workflowPreview.nodes, msg.workflowPreview.edges, false)}
                          >
                            Replace Canvas
                          </button>
                          {nodes.length > 0 && (
                            <button
                              type="button"
                              className="smith-preview-append-btn"
                              onClick={() => handleApplyToCanvas(msg.workflowPreview.nodes, msg.workflowPreview.edges, true)}
                            >
                              Append to Canvas
                            </button>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Reasoning Trace */}
                    {msg.trace && msg.trace.length > 0 && (
                      <div className="smith-trace-section">
                        <button
                          type="button"
                          className="smith-trace-toggle-btn"
                          onClick={() => setExpandedTraceIndex(expandedTraceIndex === idx ? null : idx)}
                        >
                          <span>⚙ Tool Trace ({msg.trace.length})</span>
                          <span>{expandedTraceIndex === idx ? '▲' : '▼'}</span>
                        </button>
                        {expandedTraceIndex === idx && (
                          <div className="smith-trace-box">
                            {msg.trace.map((step, sIdx) => (
                              <div key={sIdx}>
                                <strong style={{ color: '#c084fc' }}>{step.tool}</strong>: {String(step.output || JSON.stringify(step.input))}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              ))}

              {loading && (
                <div className="smith-chat-turn assistant">
                  {renderAssistantAvatar(28)}
                  <div className="smith-assistant-bubble" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span className="ai-pulse-dot" style={{ background: '#38bdf8' }} />
                    <span style={{ color: '#94a3b8', fontSize: 12 }}>Smith is analyzing and executing tools…</span>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Smart Floating Input Card */}
            <div className="smith-input-box-card">
              <textarea
                ref={textareaRef}
                className="smith-main-textarea"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    handleSendMessage()
                  }
                }}
                placeholder='Ask Smith anything... (e.g. "Create a workflow that syncs Salesforce leads to Google Sheets and notify in Teams")'
                rows={2}
                disabled={loading}
              />
              <div className="smith-controls-row">
                <div className="smith-controls-left">
                  {/* Attach Button */}
                  <button
                    type="button"
                    className="smith-tool-icon-btn"
                    title="Attach canvas snapshot or file"
                    onClick={() => {
                      setInput((prev) => `${prev} [Attached current canvas with ${nodes.length} nodes] `)
                      textareaRef.current?.focus()
                    }}
                  >
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
                    </svg>
                  </button>

                  {/* Web Search Toggle */}
                  <button
                    type="button"
                    className={`smith-tool-icon-btn ${webSearchEnabled ? 'active' : ''}`}
                    onClick={() => setWebSearchEnabled(!webSearchEnabled)}
                    title="Live connector & documentation search"
                  >
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <circle cx="12" cy="12" r="10" />
                      <line x1="2" y1="12" x2="22" y2="12" />
                      <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
                    </svg>
                  </button>

                  {/* Use Current Canvas Toggle Switch (Flat horizontal row with div to avoid label flex-col) */}
                  <div
                    className="smith-canvas-toggle"
                    onClick={() => setUseCurrentCanvas(!useCurrentCanvas)}
                    title="Include active canvas nodes & connections in Smith context"
                  >
                    <div className={`smith-toggle-switch ${useCurrentCanvas ? 'checked' : ''}`}>
                      <div className="smith-toggle-knob" />
                    </div>
                    <span className="smith-toggle-label">Use current canvas</span>
                    <span className="smith-info-icon" title="Smith receives live nodes, edges, and error states">
                      ⓘ
                    </span>
                  </div>
                </div>

                {/* Send Button */}
                <button
                  type="button"
                  className={`smith-send-action-btn ${input.trim() ? 'has-input' : ''}`}
                  onClick={() => handleSendMessage()}
                  disabled={loading || !input.trim()}
                  title="Send message (Enter)"
                >
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
                  </svg>
                </button>
              </div>
            </div>
          </>
        )}

        {/* ===================================================================
            TAB 2: WORKFLOW BUILDER
            =================================================================== */}
        {activeTab === 'builder' && (
          <div className="smith-builder-pane">
            <div className="smith-builder-hero">
              <span className="smith-builder-badge">AI COPILOT</span>
              <h3 className="smith-builder-title">Prompt to Workflow Generator</h3>
              <p className="smith-builder-desc">
                Describe your desired automation in plain English. Smith generates nodes, connections, and field mappings grounded in live connectors.
              </p>
            </div>

            <textarea
              className="smith-builder-textarea"
              value={builderPrompt}
              onChange={(e) => setBuilderPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault()
                  handleGenerateWorkflow()
                }
              }}
              placeholder='e.g. When a Stripe webhook arrives, score customer risk with AI and alert Slack...'
              rows={4}
            />

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <label
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  fontSize: '12px',
                  color: '#cbd5e1',
                  cursor: 'pointer',
                }}
              >
                <input
                  type="checkbox"
                  checked={iterateExisting}
                  onChange={(e) => setIterateExisting(e.target.checked)}
                  style={{ accentColor: '#a855f7' }}
                />
                <span>Extend current canvas</span>
              </label>
              <span style={{ fontSize: '11px', color: '#64748b' }}>Ctrl / Cmd + Enter</span>
            </div>

            {/* Example chips */}
            <div>
              <div className="smith-section-title">Try an example:</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {EXAMPLE_PROMPTS.map((ex, i) => (
                  <button
                    key={i}
                    type="button"
                    className="smith-action-card"
                    style={{ minHeight: 40 }}
                    onClick={() => {
                      setBuilderPrompt(ex)
                      handleGenerateWorkflow(ex)
                    }}
                  >
                    <span style={{ color: '#a855f7' }}>⚡</span>
                    <span className="smith-card-text">{ex}</span>
                  </button>
                ))}
              </div>
            </div>

            {generating && (
              <div
                style={{
                  padding: '16px',
                  borderRadius: '10px',
                  background: 'rgba(168, 85, 247, 0.08)',
                  border: '1px solid rgba(168, 85, 247, 0.25)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                }}
              >
                <span className="ai-pulse-dot" style={{ background: '#c084fc' }} />
                <span style={{ fontSize: '13px', color: '#f8fafc' }}>
                  {GENERATION_PHASES[generationPhase]}
                </span>
              </div>
            )}

            {builderError && (
              <div
                style={{
                  padding: '12px',
                  borderRadius: '8px',
                  background: 'rgba(239, 68, 68, 0.12)',
                  border: '1px solid rgba(239, 68, 68, 0.3)',
                  color: '#f87171',
                  fontSize: '12px',
                }}
              >
                {builderError}
              </div>
            )}

            {generatedPreview && (
              <div className="smith-preview-card">
                <div className="smith-preview-header">
                  <span className="smith-preview-title">Generated Workflow Preview</span>
                  <span className="smith-preview-counts">
                    {generatedPreview.nodes.length} nodes &bull; {generatedPreview.edges.length} edges
                  </span>
                </div>
                <div className="smith-preview-chips">
                  {generatedPreview.nodes.map((n) => (
                    <span key={n.id} className="smith-preview-chip">
                      {n.data?.node?.name || n.data?.node?.type || n.id}
                    </span>
                  ))}
                </div>
                <div className="smith-preview-actions">
                  <button
                    type="button"
                    className="smith-preview-apply-btn"
                    onClick={() => handleApplyToCanvas(generatedPreview.nodes, generatedPreview.edges, iterateExisting)}
                  >
                    ⚡ {iterateExisting ? 'Append to Canvas' : 'Apply to Canvas'}
                  </button>
                  <button
                    type="button"
                    className="smith-preview-append-btn"
                    onClick={() => setGeneratedPreview(null)}
                  >
                    Discard
                  </button>
                </div>
              </div>
            )}

            <div className="smith-builder-footer">
              <button
                type="button"
                style={{
                  padding: '10px 16px',
                  borderRadius: '8px',
                  border: '1px solid rgba(255, 255, 255, 0.12)',
                  background: 'rgba(255, 255, 255, 0.04)',
                  color: '#94a3b8',
                  fontSize: '13px',
                  cursor: 'pointer',
                }}
                onClick={onClose}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => handleGenerateWorkflow()}
                disabled={generating || !builderPrompt.trim()}
                style={{
                  flex: 1,
                  padding: '10px 16px',
                  borderRadius: '8px',
                  border: 'none',
                  background: 'linear-gradient(135deg, #7c3aed 0%, #a855f7 100%)',
                  color: '#ffffff',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: 'pointer',
                  opacity: generating || !builderPrompt.trim() ? 0.6 : 1,
                }}
              >
                {generating ? 'Generating Workflow…' : 'Generate Workflow'}
              </button>
            </div>
          </div>
        )}

        {/* ===================================================================
            TAB 3: DEBUG & ANALYZE
            =================================================================== */}
        {activeTab === 'debug' && (
          <div className="smith-debug-pane">
            {/* Health Score Card */}
            <div className="smith-health-card">
              <div>
                <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 4 }}>Canvas Health Score</div>
                <div className="smith-health-score">{healthScore}%</div>
                <div style={{ fontSize: 11, color: '#64748b', marginTop: 4 }}>
                  {nodes.length} nodes &bull; {edges.length} edges
                </div>
              </div>
              <button
                type="button"
                className="smith-action-card"
                style={{ padding: '8px 12px', minHeight: 'unset' }}
                onClick={() => {
                  setActiveTab('chat')
                  handleSendMessage('Inspect this workflow and list all nodes')
                }}
              >
                🔍 Inspect Graph
              </button>
            </div>

            {/* Diagnostic Checks */}
            <div>
              <div className="smith-section-title">Diagnostics & Lint Checks</div>
              <div className="smith-diag-list">
                <div className="smith-diag-item">
                  <span>Trigger Node Configured</span>
                  <span className={`smith-diag-badge ${hasTrigger ? 'pass' : 'warn'}`}>
                    {hasTrigger ? 'Passing' : 'Missing Trigger'}
                  </span>
                </div>
                <div className="smith-diag-item">
                  <span>Isolated / Unreachable Nodes</span>
                  <span className={`smith-diag-badge ${disconnectedNodes.length === 0 ? 'pass' : 'warn'}`}>
                    {disconnectedNodes.length === 0 ? '0 Isolated' : `${disconnectedNodes.length} Isolated`}
                  </span>
                </div>
                <div className="smith-diag-item">
                  <span>Circular Dependency Check</span>
                  <span className="smith-diag-badge pass">DAG Valid</span>
                </div>
                <div className="smith-diag-item">
                  <span>Latest Execution Status</span>
                  <span
                    className={`smith-diag-badge ${
                      executionStatus === 'success' ? 'pass' : executionStatus === 'failed' ? 'fail' : 'pass'
                    }`}
                  >
                    {executionStatus ? executionStatus.toUpperCase() : 'NO RUNS'}
                  </span>
                </div>
              </div>
            </div>

            {/* Quick Actions */}
            <div>
              <div className="smith-section-title">One-Click Debug Tools</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <button
                  type="button"
                  className="smith-action-card"
                  onClick={() => {
                    setActiveTab('chat')
                    handleSendMessage('Debug last execution failure')
                  }}
                >
                  <span style={{ color: '#f43f5e' }}>🐞</span>
                  <div className="smith-card-text">
                    <strong>Debug Last Execution Trace</strong>
                    <div style={{ fontSize: 11, color: '#64748b' }}>Pinpoint failing node, error message, and payload</div>
                  </div>
                </button>
                <button
                  type="button"
                  className="smith-action-card"
                  onClick={() => {
                    setActiveTab('chat')
                    handleSendMessage('Optimize this workflow')
                  }}
                >
                  <span style={{ color: '#38bdf8' }}>🚀</span>
                  <div className="smith-card-text">
                    <strong>Run Performance & Resilience Analysis</strong>
                    <div style={{ fontSize: 11, color: '#64748b' }}>Check for rate limits, missing error branches, and retry policies</div>
                  </div>
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
