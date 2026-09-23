import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import { api } from '../api'
import { toReactFlow, toWorkflowJson } from '../mappers'

const SUGGESTIONS = [
  'Inspect this workflow and list all canvas nodes',
  'What platform connectors and tools are available?',
  'Check system health and database status',
  'Remember that our project budget is $45,000',
]

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

function getNodeLabel(node) {
  if (!node) return 'Node'
  if (typeof node.data?.node?.name === 'string' && node.data.node.name) return node.data.node.name
  if (typeof node.data?.node?.type === 'string' && node.data.node.type) return node.data.node.type
  return String(node.id || 'Node')
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

  const [activeTab, setActiveTab] = useState(initialTab)
  const storageKey = useMemo(() => {
    return `flowsmith_smith_chat_${workflow?.id || 'default'}`
  }, [workflow?.id])

  // Chat state
  const [messages, setMessages] = useState(() => {
    try {
      if (typeof window !== 'undefined' && window.localStorage) {
        const saved = localStorage.getItem(`flowsmith_smith_chat_${workflow?.id || 'default'}`)
        if (saved) {
          const parsed = JSON.parse(saved)
          if (Array.isArray(parsed?.messages) && parsed.messages.length > 0) {
            return parsed.messages
          }
        }
      }
    } catch {}
    return [
      {
        role: 'assistant',
        content:
          "Hello! I'm Smith, your AI Copilot & Automation Assistant. I can generate workflows, add nodes to your canvas, inspect executions, or answer questions with live tools.",
        trace: [],
      },
    ]
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

  // Builder / Copilot state
  const [builderPrompt, setBuilderPrompt] = useState('')
  const [generating, setGenerating] = useState(false)
  const [builderError, setBuilderError] = useState(null)
  const [recentPrompts, setRecentPrompts] = useState(loadCopilotHistory)
  const [iterateExisting, setIterateExisting] = useState(nodes.length > 0)
  const [generationPhase, setGenerationPhase] = useState(0)
  const [generatedPreview, setGeneratedPreview] = useState(null)
  const [applySuccess, setApplySuccess] = useState(false)

  // Shared state
  const [selectedNodeId, setSelectedNodeId] = useState('')
  const [expandedTraceIndex, setExpandedTraceIndex] = useState(null)
  const [copiedSession, setCopiedSession] = useState(false)
  const [copiedMsgIdx, setCopiedMsgIdx] = useState(null)
  const [llmConfigured, setLlmConfigured] = useState(null)
  const messagesEndRef = useRef(null)
  const textareaRef = useRef(null)

  // Sync activeTab if initialTab changes
  useEffect(() => {
    if (initialTab) setActiveTab(initialTab)
  }, [initialTab])

  // Sync chat memory to localStorage
  useEffect(() => {
    try {
      if (typeof window !== 'undefined' && window.localStorage) {
        localStorage.setItem(storageKey, JSON.stringify({ messages, sessionId }))
      }
    } catch {}
  }, [messages, sessionId, storageKey])

  // Check LLM status
  useEffect(() => {
    if (!isOpen) return
    let active = true
    if (typeof api.aiStatus === 'function') {
      api
        .aiStatus()
        .then((res) => {
          if (!active) return
          const configured = Boolean(res?.configured ?? res?.data?.configured)
          setLlmConfigured(configured)
        })
        .catch(() => {
          if (active) setLlmConfigured(false)
        })
    }
    return () => {
      active = false
    }
  }, [isOpen])

  // Generation phases animation
  useEffect(() => {
    if (!generating) {
      setGenerationPhase(0)
      return
    }
    const timer = setInterval(() => {
      setGenerationPhase((p) => Math.min(p + 1, GENERATION_PHASES.length - 1))
    }, 650)
    return () => clearInterval(timer)
  }, [generating])

  // Auto scroll
  useEffect(() => {
    if (activeTab === 'chat') {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages, loading, activeTab])

  // AI nodes detection on canvas
  const aiNodes = useMemo(() => {
    return nodes.filter((n) => {
      const t = getNodeTypeString(n)
      return t === 'ai_agent' || t === 'rag_pipeline'
    })
  }, [nodes])

  useEffect(() => {
    if (aiNodes.length === 1) {
      setSelectedNodeId(aiNodes[0].id)
    } else if (aiNodes.length === 0) {
      setSelectedNodeId('')
    }
  }, [aiNodes])

  // Apply generated graph to canvas
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

  // Workflow generation logic
  const handleGenerateWorkflow = async (customPrompt) => {
    const text = (customPrompt || builderPrompt).trim()
    if (!text || generating) return

    setGenerating(true)
    setBuilderError(null)
    setGeneratedPreview(null)

    try {
      let generatedNodes = []
      let generatedEdges = []

      // 1. Try real LLM backend generation
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
          setLlmConfigured(true)
        }
      } catch (backendErr) {
        if (backendErr?.status === 422 || backendErr?.message?.toLowerCase()?.includes('credential')) {
          setLlmConfigured(false)
        }
        console.warn('Backend LLM generation fallback:', backendErr)
      }

      // 2. Intelligent fallback graph templates
      if (generatedNodes.length === 0) {
        const lower = text.toLowerCase()
        const currentCanvasNodes = useWorkflowStore.getState().nodes || []
        const startY =
          currentCanvasNodes.length > 0 ? Math.max(...currentCanvasNodes.map((n) => n.position?.y || 0)) + 220 : 160
        const now = Date.now()

        if (lower.includes('slack') || lower.includes('stripe') || lower.includes('webhook')) {
          generatedNodes = [
            {
              id: `node_${now}_1`,
              type: 'custom',
              position: { x: 100, y: startY },
              data: {
                node: {
                  id: `node_${now}_1`,
                  type: 'webhook',
                  name: 'Stripe Webhook',
                  version: 1,
                  parameters: { path: 'stripe-events', method: 'POST' },
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
                  name: 'Smith Transaction Analyst',
                  version: 1,
                  parameters: {
                    instructions: 'Analyze customer transaction details and summarize key highlights.',
                    tools: ['calculator', 'current_time'],
                    model: 'claude-3-5-sonnet',
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
                  name: 'Slack Notification',
                  version: 1,
                  parameters: {
                    url: 'https://hooks.slack.com/services/T00/B00/XXXX',
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: '{"text": "{{ $json.output }}"}',
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
        } else if (lower.includes('rag') || lower.includes('knowledge') || lower.includes('search')) {
          generatedNodes = [
            {
              id: `node_${now}_1`,
              type: 'custom',
              position: { x: 100, y: startY },
              data: {
                node: {
                  id: `node_${now}_1`,
                  type: 'webhook',
                  name: 'User Support Query',
                  version: 1,
                  parameters: { path: 'support-query', method: 'POST' },
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
                  type: 'rag_pipeline',
                  name: 'Enterprise Knowledge RAG',
                  version: 1,
                  parameters: {
                    collection_name: 'support_docs',
                    top_k: 5,
                    query: '{{ $json.query }}',
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
                  type: 'ai_agent',
                  name: 'Smith Answer Generator',
                  version: 1,
                  parameters: {
                    instructions: 'Synthesize the RAG documentation and reply clearly to the user.',
                    tools: ['knowledge_search'],
                    model: 'gpt-4o',
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
                  type: 'schedule_trigger',
                  name: 'Daily Scheduler',
                  version: 1,
                  parameters: { cron: '0 9 * * *' },
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
                  name: 'Smith Intelligent Processor',
                  version: 1,
                  parameters: {
                    instructions: `Execute automation for: ${text}`,
                    tools: ['http_request', 'current_time'],
                    model: 'gpt-4o-mini',
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
                  type: 'code',
                  name: 'Format Payload',
                  version: 1,
                  parameters: {
                    code: 'return items.map(item => ({ json: { ...item.json, processed_at: new Date().toISOString() } }));',
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

  // Handle chat submission
  const handleSendMessage = async (textToSend) => {
    const messageText = (textToSend || input).trim()
    if (!messageText || loading) return

    setInput('')
    const userMsg = { role: 'user', content: messageText }
    setMessages((prev) => [...prev, userMsg])
    setLoading(true)

    // Check if user is asking Smith to generate or build a workflow in chat
    const lower = messageText.toLowerCase()
    const isBuildRequest =
      lower.startsWith('build ') ||
      lower.startsWith('generate ') ||
      lower.startsWith('create workflow') ||
      lower.includes('make a workflow') ||
      lower.includes('generate a workflow')

    if (isBuildRequest) {
      try {
        let genNodes = []
        let genEdges = []
        const existingWf = nodes.length > 0 ? toWorkflowJson(workflow, nodes, edges) : null

        const res = await api
          .generateWorkflow(messageText, {
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
          // Generate fallback preview nodes
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
                  name: 'Webhook Trigger',
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
                    instructions: `Processed task: ${messageText}`,
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
          content: `I've generated a workflow plan tailored to your request: "${messageText}".\n\nIt includes ${genNodes.length} nodes and ${genEdges.length} connections. You can apply it directly to your canvas below.`,
          workflowPreview: { nodes: genNodes, edges: genEdges },
          trace: [
            {
              tool: 'workflow_generator',
              input: { prompt: messageText },
              output: `Generated ${genNodes.length} nodes`,
            },
          ],
        }
        setMessages((prev) => [...prev, assistantMsg])
        setLoading(false)
        return
      } catch (err) {
        console.warn('In-chat generation failed, falling back to standard chat:', err)
      }
    }

    // Standard conversational tool call
    try {
      const activeNode = selectedNodeId ? nodes.find((n) => n.id === selectedNodeId) : null
      const tools = activeNode?.data?.node?.parameters?.tools || [
        'http_request',
        'database_query',
        'current_time',
        'calculator',
        'vector_search',
        'data_table_query',
        'subworkflow_runner',
      ]
      const model = activeNode?.data?.node?.parameters?.model || 'gpt-4o'
      const instructions =
        activeNode?.data?.node?.parameters?.instructions ||
        "You are Smith, Flowsmith's autonomous AI assistant and copilot. Provide actionable answers, use tools when needed, and help users construct powerful workflows."

      const payload = {
        message: messageText,
        session_id: sessionId,
        workflow_id: workflow?.id || null,
        tools,
        model,
        instructions,
        memory_type: 'window',
      }

      const res = await api.chatWithAgent(payload)
      const data = res?.data || res
      const assistantMsg = {
        role: 'assistant',
        content: data?.response || 'Task completed successfully.',
        trace: data?.trace || [],
        tools_used: data?.tools_used || [],
        model: data?.model || model,
      }
      setMessages((prev) => [...prev, assistantMsg])
    } catch (err) {
      const fallbackResponse = `[Smith Offline Mode] ${
        err?.message || 'Unable to connect to live LLM. Check credentials or system status.'
      }`
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: fallbackResponse,
          trace: [],
          error: true,
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  // Clear memory
  const handleClearMemory = async () => {
    try {
      if (typeof api.clearAiMemory === 'function') {
        await api.clearAiMemory(sessionId, workflow?.id || null).catch(() => {})
      }
      const newSession = `session_${Math.random().toString(36).slice(2, 9)}`
      setSessionId(newSession)
      setMessages([
        {
          role: 'assistant',
          content: "Memory cleared! I'm Smith, ready for a fresh task or workflow generation.",
          trace: [],
        },
      ])
    } catch (err) {
      console.warn('Clear memory failed:', err)
    }
  }

  const handleCopySession = () => {
    if (typeof navigator !== 'undefined' && navigator.clipboard) {
      navigator.clipboard.writeText(sessionId)
      setCopiedSession(true)
      setTimeout(() => setCopiedSession(false), 2000)
    }
  }

  const handleCopyText = (text, idx) => {
    if (typeof navigator !== 'undefined' && navigator.clipboard) {
      navigator.clipboard.writeText(text)
      setCopiedMsgIdx(idx)
      setTimeout(() => setCopiedMsgIdx(null), 2000)
    }
  }

  if (!isOpen) return null

  return (
    <div className="ai-chat-drawer-overlay" onClick={onClose}>
      <div className="ai-chat-drawer" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="ai-chat-drawer-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0, flex: 1 }}>
            <div className="agent-avatar" style={{ flexShrink: 0, background: 'linear-gradient(135deg, #0284c7 0%, #38bdf8 100%)' }}>
              ⚡
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 15, fontWeight: 700, color: '#f8fafc', letterSpacing: '-0.01em' }}>Smith</span>
                <span style={{ fontSize: 11, fontWeight: 600, padding: '2px 7px', borderRadius: 4, background: 'rgba(56, 189, 248, 0.12)', border: '1px solid rgba(56, 189, 248, 0.28)', color: '#38bdf8', whiteSpace: 'nowrap' }}>
                  AI Copilot &bull; AI Agent Tester
                </span>
                {llmConfigured !== null && (
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 600,
                      padding: '2px 6px',
                      borderRadius: 4,
                      background: llmConfigured ? 'rgba(48, 209, 88, 0.15)' : 'rgba(255, 159, 10, 0.15)',
                      border: llmConfigured ? '1px solid rgba(48, 209, 88, 0.35)' : '1px solid rgba(255, 159, 10, 0.35)',
                      color: llmConfigured ? '#30d158' : '#ff9f0a',
                      whiteSpace: 'nowrap',
                    }}
                    title={
                      llmConfigured
                        ? 'LLM credentials detected and active'
                        : 'No LLM credentials configured. Running in local simulation mode.'
                    }
                  >
                    {llmConfigured ? '● Ready' : '● Simulation'}
                  </span>
                )}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#94a3b8' }}>
                <span>Session:</span>
                <code style={{ background: 'rgba(255, 255, 255, 0.05)', padding: '1px 5px', borderRadius: 4, color: '#cbd5e1', fontFamily: 'monospace' }}>
                  {sessionId.slice(0, 14)}…
                </code>
                <button
                  type="button"
                  className="ai-copy-btn"
                  onClick={handleCopySession}
                  title="Copy full session ID"
                  aria-label="Copy session ID"
                  style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer', padding: '0 2px' }}
                >
                  {copiedSession ? '✓' : '⧉'}
                </button>
              </div>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
            <button
              type="button"
              className="ai-reset-btn"
              onClick={handleClearMemory}
              title="Reset conversation memory"
              style={{ padding: '5px 9px', fontSize: 11, borderRadius: 6, cursor: 'pointer', background: 'rgba(255, 255, 255, 0.05)', border: '1px solid rgba(255, 255, 255, 0.1)', color: '#cbd5e1' }}
            >
              Reset Memory
            </button>
            <button type="button" className="ai-close-btn" onClick={onClose} aria-label="Close Smith Assistant">
              ✕
            </button>
          </div>
        </div>

        {/* Unified Tab Switcher */}
        <div
          className="smith-tab-bar"
          style={{
            display: 'flex',
            borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
            background: 'rgba(0, 0, 0, 0.2)',
          }}
        >
          <button
            type="button"
            className={`smith-tab-btn ${activeTab === 'chat' ? 'active' : ''}`}
            onClick={() => setActiveTab('chat')}
            style={{
              flex: 1,
              padding: '10px 12px',
              fontSize: '13px',
              fontWeight: 600,
              background: activeTab === 'chat' ? 'rgba(56, 189, 248, 0.12)' : 'transparent',
              color: activeTab === 'chat' ? '#38bdf8' : '#94a3b8',
              border: 'none',
              borderBottom: activeTab === 'chat' ? '2px solid #38bdf8' : '2px solid transparent',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 6,
              transition: 'all 0.15s ease',
            }}
          >
            <span>💬 Chat & Tools</span>
          </button>
          <button
            type="button"
            className={`smith-tab-btn ${activeTab === 'builder' ? 'active' : ''}`}
            onClick={() => setActiveTab('builder')}
            style={{
              flex: 1,
              padding: '10px 12px',
              fontSize: '13px',
              fontWeight: 600,
              background: activeTab === 'builder' ? 'rgba(191, 90, 242, 0.12)' : 'transparent',
              color: activeTab === 'builder' ? '#bf5af2' : '#94a3b8',
              border: 'none',
              borderBottom: activeTab === 'builder' ? '2px solid #bf5af2' : '2px solid transparent',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 6,
              transition: 'all 0.15s ease',
            }}
          >
            <span>✨ Workflow Builder</span>
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

        {/* Content Area */}
        {activeTab === 'chat' ? (
          <>
            {/* Memory & Context Banner */}
            <div className="ai-chat-context-bar">
              <div className="ai-context-indicator">
                <span className="ai-context-dot" />
                <span className="ai-context-text">
                  Stateful Memory &bull; {messages.filter((m) => m.role === 'user').length} turn(s)
                </span>
              </div>
              {aiNodes.length > 1 && (
                <div className="ai-node-selector-wrap">
                  <label htmlFor="smith-ai-node-select" className="ai-node-label">
                    Target AI Node:
                  </label>
                  <select
                    id="smith-ai-node-select"
                    className="ai-chat-node-select"
                    value={selectedNodeId}
                    onChange={(e) => setSelectedNodeId(e.target.value)}
                  >
                    <option value="">General Assistant (All Tools)</option>
                    {aiNodes.map((n) => (
                      <option key={n.id} value={n.id}>
                        {getNodeLabel(n)}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              {aiNodes.length === 1 && (
                <div className="ai-single-node-tag">
                  <span className="ai-node-icon">⚡</span>
                  <span className="ai-node-name">{getNodeLabel(aiNodes[0])}</span>
                </div>
              )}
            </div>

            {/* Chat Messages */}
            <div className="ai-chat-messages">
              {messages.map((msg, idx) => (
                <div key={idx} className={`ai-message ai-message-${msg.role}`}>
                  <div className="ai-message-bubble">
                    <div className="ai-message-content">{msg.content}</div>

                    {/* Interactive Workflow Preview Card */}
                    {msg.workflowPreview && (
                      <div
                        style={{
                          marginTop: 12,
                          padding: '12px',
                          borderRadius: 8,
                          background: 'rgba(0, 0, 0, 0.35)',
                          border: '1px solid rgba(56, 189, 248, 0.25)',
                        }}
                      >
                        <div
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            marginBottom: 8,
                          }}
                        >
                          <span style={{ fontSize: 12, fontWeight: 600, color: '#38bdf8' }}>
                            Generated Workflow Preview
                          </span>
                          <span style={{ fontSize: 11, color: '#94a3b8' }}>
                            {msg.workflowPreview.nodes.length} nodes &bull; {msg.workflowPreview.edges.length} edges
                          </span>
                        </div>
                        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
                          {msg.workflowPreview.nodes.map((n) => (
                            <span
                              key={n.id}
                              style={{
                                fontSize: 11,
                                padding: '3px 8px',
                                borderRadius: 4,
                                background: 'rgba(255, 255, 255, 0.08)',
                                border: '1px solid rgba(255, 255, 255, 0.1)',
                              }}
                            >
                              {n.data?.node?.name || n.data?.node?.type || n.id}
                            </span>
                          ))}
                        </div>
                        <div style={{ display: 'flex', gap: 8 }}>
                          <button
                            type="button"
                            onClick={() => handleApplyToCanvas(msg.workflowPreview.nodes, msg.workflowPreview.edges, false)}
                            style={{
                              flex: 1,
                              padding: '6px 12px',
                              borderRadius: 6,
                              border: 'none',
                              background: '#0284c7',
                              color: '#fff',
                              fontSize: 12,
                              fontWeight: 600,
                              cursor: 'pointer',
                            }}
                          >
                            Replace Canvas
                          </button>
                          {nodes.length > 0 && (
                            <button
                              type="button"
                              onClick={() => handleApplyToCanvas(msg.workflowPreview.nodes, msg.workflowPreview.edges, true)}
                              style={{
                                flex: 1,
                                padding: '6px 12px',
                                borderRadius: 6,
                                border: '1px solid rgba(255, 255, 255, 0.2)',
                                background: 'rgba(255, 255, 255, 0.06)',
                                color: '#e2e8f0',
                                fontSize: 12,
                                fontWeight: 500,
                                cursor: 'pointer',
                              }}
                            >
                              Append to Canvas
                            </button>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Reasoning Trace */}
                    {msg.trace && msg.trace.length > 0 && (
                      <div className="ai-message-trace">
                        <button
                          type="button"
                          className="ai-trace-toggle"
                          onClick={() => setExpandedTraceIndex(expandedTraceIndex === idx ? null : idx)}
                        >
                          <span className="ai-trace-badge">⚙ Tool Trace ({msg.trace.length})</span>
                          <span className="ai-trace-arrow">{expandedTraceIndex === idx ? '▲' : '▼'}</span>
                        </button>
                        {expandedTraceIndex === idx && (
                          <div className="ai-trace-details">
                            {msg.trace.map((step, sIdx) => (
                              <div key={sIdx} className="ai-trace-step">
                                <div className="ai-trace-tool-name">{step.tool || 'system'}</div>
                                {step.input && (
                                  <pre className="ai-trace-block">{JSON.stringify(step.input, null, 2)}</pre>
                                )}
                                {step.output && <div className="ai-trace-output">{String(step.output)}</div>}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Action Bar */}
                    <div className="ai-message-actions">
                      <button
                        type="button"
                        className="ai-msg-action-btn"
                        onClick={() => handleCopyText(msg.content, idx)}
                        title="Copy text"
                      >
                        {copiedMsgIdx === idx ? '✓ Copied' : 'Copy'}
                      </button>
                    </div>
                  </div>
                </div>
              ))}
              {loading && (
                <div className="ai-message ai-message-assistant">
                  <div className="ai-message-bubble ai-loading-bubble">
                    <span className="ai-pulse-dot" />
                    <span className="ai-loading-text">Smith is analyzing and executing tools…</span>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Quick Suggestions Chips */}
            <div className="ai-chat-suggestions">
              {SUGGESTIONS.map((s, i) => (
                <button key={i} type="button" className="ai-suggestion-chip" onClick={() => handleSendMessage(s)}>
                  {s}
                </button>
              ))}
            </div>

            {/* Chat Input Bar */}
            <div className="ai-chat-drawer-footer">
              <div className="ai-chat-input-row">
                <textarea
                  ref={textareaRef}
                  className="ai-chat-textarea"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      handleSendMessage()
                    }
                  }}
                  placeholder="Ask agent or test workflow tools (Enter to send, Shift+Enter for newline)…"
                  rows={2}
                  disabled={loading}
                />
                <button
                  type="button"
                  className="ai-chat-send-btn"
                  onClick={() => handleSendMessage()}
                  disabled={loading || !input.trim()}
                >
                  Send
                </button>
              </div>
              <div className="ai-chat-footer-hints">
                <span>Press <span className="ai-chat-hint-kbd">Enter</span> to send, <span className="ai-chat-hint-kbd">Shift+Enter</span> for newline</span>
                <span className="ai-memory-badge">Stateful Memory</span>
              </div>
            </div>
          </>
        ) : (
          /* Workflow Builder Mode */
          <div
            className="smith-builder-pane"
            style={{
              padding: '16px',
              display: 'flex',
              flexDirection: 'column',
              gap: '16px',
              overflowY: 'auto',
              flex: 1,
            }}
          >
            <div>
              <h3 style={{ fontSize: '15px', fontWeight: 600, color: '#f8fafc', margin: '0 0 6px 0' }}>
                AI Copilot &bull; Prompt to Workflow Generator
              </h3>
              <p style={{ fontSize: '12px', color: '#94a3b8', margin: 0 }}>
                Describe what you want to automate in natural language. Smith generates connectors, schemas, and
                expressions grounded in live catalog data.
              </p>
            </div>

            {/* Prompt Input */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <textarea
                value={builderPrompt}
                onChange={(e) => setBuilderPrompt(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                    e.preventDefault()
                    handleGenerateWorkflow()
                  }
                }}
                placeholder="e.g. When a Stripe webhook arrives, analyze customer churn risk with AI and alert Slack..."
                rows={4}
                style={{
                  width: '100%',
                  padding: '12px',
                  borderRadius: '8px',
                  background: 'rgba(0, 0, 0, 0.4)',
                  border: '1px solid rgba(255, 255, 255, 0.12)',
                  color: '#f8fafc',
                  fontSize: '13px',
                  fontFamily: 'inherit',
                  resize: 'vertical',
                }}
              />
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
                <label className="copilot-extend-checkbox-wrap">
                  <input
                    type="checkbox"
                    checked={iterateExisting}
                    onChange={(e) => setIterateExisting(e.target.checked)}
                  />
                  <span>Extend current canvas</span>
                </label>
                <span style={{ fontSize: '11px', color: '#64748b' }}>Ctrl / Cmd + Enter</span>
              </div>
            </div>

            {/* Example Prompt Chips */}
            <div>
              <div style={{ fontSize: '11px', fontWeight: 600, color: '#64748b', textTransform: 'uppercase', marginBottom: 6 }}>
                Try an example:
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {EXAMPLE_PROMPTS.map((ex, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => {
                      setBuilderPrompt(ex)
                      handleGenerateWorkflow(ex)
                    }}
                    style={{
                      textAlign: 'left',
                      padding: '8px 12px',
                      borderRadius: '6px',
                      background: 'rgba(255, 255, 255, 0.04)',
                      border: '1px solid rgba(255, 255, 255, 0.08)',
                      color: '#cbd5e1',
                      fontSize: '12px',
                      cursor: 'pointer',
                      transition: 'all 0.15s ease',
                    }}
                  >
                    ⚡ {ex}
                  </button>
                ))}
              </div>
            </div>

            {/* Generation Progress */}
            {generating && (
              <div
                style={{
                  padding: '16px',
                  borderRadius: '8px',
                  background: 'rgba(191, 90, 242, 0.08)',
                  border: '1px solid rgba(191, 90, 242, 0.25)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '12px',
                }}
              >
                <span className="ai-pulse-dot" style={{ background: '#bf5af2' }} />
                <span style={{ fontSize: '13px', color: '#f8fafc' }}>
                  {GENERATION_PHASES[generationPhase]}
                </span>
              </div>
            )}

            {/* Builder Error */}
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

            {/* Generated Preview Card */}
            {generatedPreview && (
              <div
                style={{
                  padding: '16px',
                  borderRadius: '8px',
                  background: 'rgba(0, 0, 0, 0.35)',
                  border: '1px solid rgba(191, 90, 242, 0.3)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '12px',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: '13px', fontWeight: 600, color: '#bf5af2' }}>
                    Generated Workflow Preview
                  </span>
                  <span style={{ fontSize: '12px', color: '#94a3b8' }}>
                    {generatedPreview.nodes.length} nodes &bull; {generatedPreview.edges.length} edges
                  </span>
                </div>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {generatedPreview.nodes.map((n) => (
                    <span
                      key={n.id}
                      style={{
                        fontSize: '11px',
                        padding: '4px 8px',
                        borderRadius: '4px',
                        background: 'rgba(255, 255, 255, 0.08)',
                        border: '1px solid rgba(255, 255, 255, 0.1)',
                      }}
                    >
                      {n.data?.node?.name || n.data?.node?.type || n.id}
                    </span>
                  ))}
                </div>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <button
                    type="button"
                    onClick={() => handleApplyToCanvas(generatedPreview.nodes, generatedPreview.edges, iterateExisting)}
                    style={{
                      flex: 1,
                      padding: '10px 16px',
                      borderRadius: '6px',
                      border: 'none',
                      background: 'linear-gradient(135deg, #a855f7 0%, #bf5af2 100%)',
                      color: '#fff',
                      fontSize: '13px',
                      fontWeight: 600,
                      cursor: 'pointer',
                    }}
                  >
                    ⚡ {iterateExisting ? 'Append to Canvas' : 'Apply to Canvas'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setGeneratedPreview(null)}
                    style={{
                      padding: '10px 16px',
                      borderRadius: '6px',
                      border: '1px solid rgba(255, 255, 255, 0.15)',
                      background: 'transparent',
                      color: '#94a3b8',
                      fontSize: '13px',
                      cursor: 'pointer',
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {/* Action Buttons */}
            <div style={{ display: 'flex', gap: '8px', marginTop: 'auto' }}>
              <button
                type="button"
                onClick={onClose}
                style={{
                  padding: '10px 16px',
                  borderRadius: '6px',
                  border: '1px solid rgba(255, 255, 255, 0.15)',
                  background: 'transparent',
                  color: '#94a3b8',
                  fontSize: '13px',
                  cursor: 'pointer',
                }}
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
                  borderRadius: '6px',
                  border: 'none',
                  background: 'linear-gradient(135deg, #0284c7 0%, #38bdf8 100%)',
                  color: '#fff',
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
      </div>
    </div>
  )
}
