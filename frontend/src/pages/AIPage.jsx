import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import PageHeader from '../components/shared/PageHeader'
import { NodeIcon } from '../components/NodeIcons'
import FlowsmithBrandMark from '../components/FlowsmithBrandMark'
import AIArchitectureSection from '../components/AIArchitectureSection'

const EXAMPLE_PROMPTS = [
  {
    icon: '⚡',
    title: 'Enterprise Lead Qualification (End-to-End)',
    prompt: 'Connect Salesforce to our CRM, watch for new opportunities, enrich them with AI, retrieve company knowledge, score the lead, route it according to rules, ask a human for approval, update Salesforce, send Slack notification, and expose this workflow as an API.',
  },
  {
    icon: '💳',
    title: 'Stripe to Slack with AI',
    prompt: 'When a new Stripe payment webhook arrives, summarize the transaction details with Claude and post a rich message to #sales-notifications in Slack.',
  },
  {
    icon: '🐘',
    title: 'Postgres Customer Sync',
    prompt: 'Query active customers from Postgres every Monday at 9 AM, check if they exist in Salesforce, and create a lead record if missing.',
  },
  {
    icon: '🧠',
    title: 'RAG Knowledge Pipeline',
    prompt: 'Ingest customer support tickets from an incoming webhook, query our pgvector RAG collection for matching solutions, and generate a draft reply.',
  },
  {
    icon: '🚨',
    title: 'Error Fallback & PagerDuty',
    prompt: 'Create a global error handler workflow that receives failed execution payload, parses the root cause, and triggers a high-urgency incident.',
  },
]

const QUICK_AGENT_ACTIONS = [
  {
    icon: '🔍',
    title: 'Explore Connectors',
    desc: 'List all available connectors, triggers, and operations.',
    prompt: 'List the active connectors in our catalog, their categories, and key operations.',
  },
  {
    icon: '⚡',
    title: 'Design Pipeline',
    desc: 'Draft an automated workflow for lead qualification.',
    prompt: 'Design an automation pipeline that receives lead webhooks, enriches them via HTTP, and saves to database.',
  },
  {
    icon: '🧠',
    title: 'Search Knowledge Bases',
    desc: 'Query vector collections with semantic search.',
    prompt: 'Search our knowledge base for platform integration guides and best practices.',
  },
  {
    icon: '🛠️',
    title: 'Execution Diagnostics',
    desc: 'Analyze common workflow execution errors.',
    prompt: 'Explain how Flowsmith auto-diagnoses and repairs node execution failures.',
  },
]

const GENERATION_PHASES = [
  'Analyzing automation intent & triggers...',
  'Matching operations against 45+ connectors...',
  'Validating DAG topology & parameter bindings...',
  'Constructing visual canvas layout & blueprint...',
]

export default function AIPage() {
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState('copilot') // 'copilot' | 'chat' | 'capabilities'
  const [statusInfo, setStatusInfo] = useState({ configured: false, loading: true })

  // --- Copilot State ---
  const [prompt, setPrompt] = useState('')
  const [generating, setGenerating] = useState(false)
  const [currentPhase, setCurrentPhase] = useState(0)
  const [generationError, setGenerationError] = useState(null)
  const [generatedResult, setGeneratedResult] = useState(null)
  const [importing, setImporting] = useState(false)
  const phaseTimerRef = useRef(null)

  // --- Agent Chat State ---
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content:
        'Hello! I am your Flowsmith Autonomous AI Orchestrator. I am grounded in your live connector catalog, workspace databases, and vector knowledge bases. How can I assist your automations today?',
    },
  ])
  const [chatInput, setChatInput] = useState('')
  const [chatSending, setChatSending] = useState(false)
  const [chatError, setChatError] = useState(null)
  const chatBottomRef = useRef(null)
  const sessionId = 'default_ai_console'

  useEffect(() => {
    api.aiStatus()
      .then((res) => {
        setStatusInfo({ configured: Boolean(res?.configured), loading: false })
      })
      .catch(() => {
        setStatusInfo({ configured: false, loading: false })
      })
  }, [])

  useEffect(() => {
    if (activeTab === 'chat') {
      chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages, activeTab])

  // --- Copilot Handlers ---
  const handleGenerate = async (textToUse) => {
    const text = (textToUse || prompt).trim()
    if (!text || generating) return
    setGenerationError(null)
    setGeneratedResult(null)
    setGenerating(true)
    setCurrentPhase(0)

    phaseTimerRef.current = setInterval(() => {
      setCurrentPhase((p) => (p < GENERATION_PHASES.length - 1 ? p + 1 : p))
    }, 1200)

    try {
      const res = await api.generateWorkflow(text)
      clearInterval(phaseTimerRef.current)
      if (res?.workflow) {
        setGeneratedResult(res)
      } else if (res?.id) {
        navigate(`/workflows/${res.id}`)
      } else {
        throw new Error('AI generation did not return a valid workflow structure.')
      }
    } catch (err) {
      clearInterval(phaseTimerRef.current)
      setGenerationError(err.message || 'Failed to generate workflow.')
    } finally {
      setGenerating(false)
    }
  }

  const handleOpenInCanvas = async () => {
    if (!generatedResult?.workflow || importing) return
    setImporting(true)
    try {
      const imported = await api.importWorkflow(generatedResult.workflow)
      navigate(`/workflows/${imported.id}`)
    } catch (err) {
      setGenerationError(`Failed to import to canvas: ${err.message}`)
      setImporting(false)
    }
  }

  // --- Agent Chat Handlers ---
  const handleSendChat = async (msgToSend) => {
    const text = (msgToSend || chatInput).trim()
    if (!text || chatSending) return

    setChatInput('')
    setChatError(null)
    const newHistory = [...messages, { role: 'user', content: text }]
    setMessages(newHistory)
    setChatSending(true)

    try {
      const res = await api.chatWithAgent({
        message: text,
        session_id: sessionId,
      })
      const answer = res?.response || res?.output || 'Execution completed.'
      setMessages([
        ...newHistory,
        {
          role: 'assistant',
          content: answer,
          trace: res?.trace || [],
          toolsUsed: res?.tools_used || [],
        },
      ])
    } catch (err) {
      setChatError(err.message || 'Failed to communicate with AI agent.')
      setMessages([
        ...newHistory,
        {
          role: 'assistant',
          content: `⚠️ Error executing agent: ${err.message}. Please verify an LLM credential is configured.`,
          isError: true,
        },
      ])
    } finally {
      setChatSending(false)
    }
  }

  const handleClearMemory = async () => {
    try {
      await api.clearAiMemory(sessionId)
      setMessages([
        {
          role: 'assistant',
          content: 'Session memory cleared. How can I assist you with your automations now?',
        },
      ])
    } catch (err) {
      setChatError(`Could not clear memory: ${err.message}`)
    }
  }

  return (
    <div className="page ai-page" style={{ padding: '1.5rem', maxWidth: 1400, margin: '0 auto' }}>
      <PageHeader
        title="AI Copilot & Autonomous Agents"
        description="Prompt-to-DAG workflow synthesis, multi-tool ReAct agents, and enterprise RAG orchestration."
        actions={
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            {statusInfo.loading ? (
              <span className="badge badge-neutral" style={{ fontSize: '12px' }}>Checking AI status...</span>
            ) : statusInfo.configured ? (
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
                LLM Provider Connected
              </span>
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
        }}
      >
        <button
          className={activeTab === 'copilot' ? 'primary' : 'ghost'}
          onClick={() => setActiveTab('copilot')}
          style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.5rem 1rem' }}
        >
          <span>✨</span> Workflow Copilot (Prompt to DAG)
        </button>
        <button
          className={activeTab === 'chat' ? 'primary' : 'ghost'}
          onClick={() => setActiveTab('chat')}
          style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.5rem 1rem' }}
        >
          <span>🤖</span> Autonomous Agent Console
        </button>
        <button
          className={activeTab === 'capabilities' ? 'primary' : 'ghost'}
          onClick={() => setActiveTab('capabilities')}
          style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.5rem 1rem' }}
        >
          <span>⚡</span> AI Architecture & MCP
        </button>
      </div>

      {/* TAB 1: COPILOT */}
      {activeTab === 'copilot' && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'minmax(0, 1.15fr) minmax(0, 1fr)',
            gap: '1.5rem',
            alignItems: 'stretch',
          }}
        >
          {/* Left: Prompt Input & Starters */}
          <div
            style={{
              padding: '1.5rem',
              background: 'var(--card-bg, #18181b)',
              border: '1px solid var(--border-color, #27272a)',
              borderRadius: '12px',
              display: 'flex',
              flexDirection: 'column',
              minWidth: 0,
            }}
          >
            <h3 style={{ margin: '0 0 0.4rem', fontSize: '1.1rem', fontWeight: 600 }}>
              Describe Your Automation Intent
            </h3>
            <p
              style={{
                margin: '0 0 1rem',
                fontSize: '13px',
                color: 'var(--text-muted, #a1a1aa)',
                lineHeight: 1.45,
              }}
            >
              Flowsmith’s grounding engine matches your prompt against the live 45+ connector catalog and constructs a cycle-safe, executable DAG.
            </p>

            <div style={{ position: 'relative', marginBottom: '1rem' }}>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                    e.preventDefault()
                    handleGenerate()
                  }
                }}
                placeholder="e.g. When a new customer signs up in Stripe, create a contact in HubSpot, verify their domain with an HTTP call, and notify our team on Discord..."
                rows={5}
                style={{
                  width: '100%',
                  boxSizing: 'border-box',
                  padding: '0.75rem',
                  borderRadius: '8px',
                  background: 'var(--input-bg, #09090b)',
                  border: '1px solid var(--border-color, #3f3f46)',
                  color: 'inherit',
                  fontSize: '13.5px',
                  lineHeight: '1.5',
                  resize: 'vertical',
                  fontFamily: 'inherit',
                  outline: 'none',
                }}
              />
              <div
                style={{
                  position: 'absolute',
                  bottom: '10px',
                  right: '12px',
                  fontSize: '11px',
                  color: '#71717a',
                  pointerEvents: 'none',
                }}
              >
                Ctrl + Enter to run
              </div>
            </div>

            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: '1.5rem',
              }}
            >
              <button
                className="primary"
                onClick={() => handleGenerate()}
                disabled={generating || !prompt.trim()}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  minWidth: 160,
                  justifyContent: 'center',
                  padding: '0.6rem 1.2rem',
                }}
              >
                {generating ? (
                  <>
                    <span
                      style={{
                        width: 14,
                        height: 14,
                        border: '2px solid rgba(255,255,255,0.3)',
                        borderTopColor: '#fff',
                        borderRadius: '50%',
                        display: 'inline-block',
                        animation: 'spin 0.8s linear infinite',
                      }}
                    />
                    Synthesizing...
                  </>
                ) : (
                  <>
                    <span>✨</span> Generate Workflow
                  </>
                )}
              </button>
              {prompt && (
                <button
                  className="ghost"
                  onClick={() => {
                    setPrompt('')
                    setGeneratedResult(null)
                    setGenerationError(null)
                  }}
                  style={{ fontSize: '13px' }}
                >
                  Clear
                </button>
              )}
            </div>

            {/* Blueprint Starters Grid */}
            <div style={{ marginTop: 'auto' }}>
              <div
                style={{
                  fontSize: '11px',
                  fontWeight: 600,
                  textTransform: 'uppercase',
                  letterSpacing: '0.06em',
                  color: '#71717a',
                  marginBottom: '0.65rem',
                }}
              >
                Enterprise Blueprint Starters
              </div>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
                  gap: '0.65rem',
                  minWidth: 0,
                }}
              >
                {EXAMPLE_PROMPTS.map((ex, i) => (
                  <div
                    key={i}
                    onClick={() => {
                      setPrompt(ex.prompt)
                      handleGenerate(ex.prompt)
                    }}
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'flex-start',
                      padding: '0.75rem 0.85rem',
                      borderRadius: '8px',
                      background: 'rgba(255, 255, 255, 0.02)',
                      border: '1px solid rgba(255, 255, 255, 0.08)',
                      cursor: 'pointer',
                      transition: 'all 0.15s ease',
                      minWidth: 0,
                      boxSizing: 'border-box',
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = 'rgba(255, 255, 255, 0.06)'
                      e.currentTarget.style.borderColor = 'rgba(99, 102, 241, 0.4)'
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = 'rgba(255, 255, 255, 0.02)'
                      e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.08)'
                    }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        fontWeight: 600,
                        fontSize: '12.5px',
                        color: '#f4f4f5',
                        marginBottom: '4px',
                        width: '100%',
                      }}
                    >
                      <span>{ex.icon}</span>
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {ex.title}
                      </span>
                    </div>
                    <div
                      style={{
                        fontSize: '11.5px',
                        color: '#94a3b8',
                        lineHeight: '1.4',
                        display: '-webkit-box',
                        WebkitLineClamp: 2,
                        lineClamp: 2,
                        WebkitBoxOrient: 'vertical',
                        overflow: 'hidden',
                      }}
                    >
                      {ex.prompt}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Right: Synthesis Preview & Blueprint */}
          <div
            style={{
              padding: '1.5rem',
              background: 'var(--card-bg, #18181b)',
              border: '1px solid var(--border-color, #27272a)',
              borderRadius: '12px',
              display: 'flex',
              flexDirection: 'column',
              minWidth: 0,
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: '1rem',
              }}
            >
              <h3 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 600 }}>
                Workflow Blueprint & Validation
              </h3>
              {generatedResult && (
                <span
                  style={{
                    fontSize: '11.5px',
                    color: '#4ade80',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '4px',
                    padding: '2px 8px',
                    borderRadius: '12px',
                    background: 'rgba(34, 197, 94, 0.1)',
                  }}
                >
                  ✓ Ready to Deploy
                </span>
              )}
            </div>

            {generating && (
              <div style={{ padding: '3rem 1rem', textAlign: 'center', margin: 'auto 0' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', maxWidth: 360, margin: '0 auto', textAlign: 'left' }}>
                  {GENERATION_PHASES.map((phase, idx) => (
                    <div
                      key={idx}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.75rem',
                        opacity: idx <= currentPhase ? 1 : 0.3,
                        transition: 'opacity 0.3s ease',
                      }}
                    >
                      <div
                        style={{
                          width: 22,
                          height: 22,
                          borderRadius: '50%',
                          background: idx < currentPhase ? '#22c55e' : idx === currentPhase ? '#6366f1' : '#27272a',
                          color: '#fff',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontSize: '11px',
                          fontWeight: 'bold',
                        }}
                      >
                        {idx < currentPhase ? '✓' : idx + 1}
                      </div>
                      <span style={{ fontSize: '13px', color: idx === currentPhase ? '#f4f4f5' : '#a1a1aa' }}>
                        {phase}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {generationError && !generating && (
              <div
                style={{
                  padding: '1.25rem',
                  borderRadius: '8px',
                  background: 'rgba(239, 68, 68, 0.1)',
                  border: '1px solid rgba(239, 68, 68, 0.3)',
                  color: '#fca5a5',
                  fontSize: '13px',
                  lineHeight: '1.5',
                }}
              >
                <strong>Generation Error:</strong> {generationError}
                {!statusInfo.configured && (
                  <div style={{ marginTop: '0.75rem' }}>
                    <button
                      className="primary"
                      onClick={() => navigate('/credentials')}
                      style={{ fontSize: '12px', padding: '0.4rem 0.8rem' }}
                    >
                      Configure LLM Credential →
                    </button>
                  </div>
                )}
              </div>
            )}

            {!generating && !generationError && generatedResult && (
              <div style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'flex-start',
                    marginBottom: '1rem',
                  }}
                >
                  <div>
                    <h4 style={{ margin: '0 0 4px', fontSize: '16px', fontWeight: 600 }}>
                      {generatedResult.workflow?.name || 'Generated Automation'}
                    </h4>
                    <span style={{ fontSize: '12px', color: '#94a3b8' }}>
                      {generatedResult.workflow?.nodes?.length || 0} nodes &bull;{' '}
                      {generatedResult.workflow?.connections?.length || 0} edges
                    </span>
                  </div>
                  <button
                    className="primary"
                    onClick={handleOpenInCanvas}
                    disabled={importing}
                    style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem' }}
                  >
                    <span>🚀</span> {importing ? 'Importing...' : 'Open in Canvas'}
                  </button>
                </div>

                <div
                  style={{
                    background: 'var(--input-bg, #09090b)',
                    padding: '1rem',
                    borderRadius: '8px',
                    border: '1px solid #27272a',
                    marginBottom: '1rem',
                  }}
                >
                  <div style={{ fontSize: '12px', color: '#a1a1aa', marginBottom: '0.5rem' }}>
                    <strong>Nodes Sequence:</strong>
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                    {(generatedResult.workflow?.nodes || []).map((node, nIdx) => (
                      <div
                        key={nIdx}
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '6px',
                          padding: '5px 9px',
                          borderRadius: '6px',
                          background: 'rgba(255, 255, 255, 0.05)',
                          border: '1px solid rgba(255, 255, 255, 0.1)',
                          fontSize: '12px',
                        }}
                      >
                        <NodeIcon type={node.type} size={14} />
                        <span>{node.name || node.type}</span>
                      </div>
                    ))}
                  </div>
                </div>

                {generatedResult.validation?.warnings?.length > 0 && (
                  <div
                    style={{
                      padding: '0.75rem',
                      borderRadius: '6px',
                      background: 'rgba(245, 158, 11, 0.1)',
                      border: '1px solid rgba(245, 158, 11, 0.3)',
                      color: '#fbbf24',
                      fontSize: '12px',
                      marginTop: 'auto',
                    }}
                  >
                    <strong>Advisories:</strong> {generatedResult.validation.warnings.join('; ')}
                  </div>
                )}
              </div>
            )}

            {!generating && !generationError && !generatedResult && (
              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flex: 1,
                  textAlign: 'center',
                  padding: '2.5rem 1rem',
                  color: '#71717a',
                }}
              >
                {/* Visual Placeholder Nodes */}
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',
                    marginBottom: '1.5rem',
                    opacity: 0.5,
                  }}
                >
                  <div
                    style={{
                      padding: '6px 12px',
                      borderRadius: '6px',
                      background: '#27272a',
                      fontSize: '12px',
                      color: '#a1a1aa',
                    }}
                  >
                    ⚡ Webhook
                  </div>
                  <span style={{ color: '#52525b' }}>──→</span>
                  <div
                    style={{
                      padding: '6px 12px',
                      borderRadius: '6px',
                      background: '#27272a',
                      fontSize: '12px',
                      color: '#a1a1aa',
                    }}
                  >
                    🤖 AI Reasoning
                  </div>
                  <span style={{ color: '#52525b' }}>──→</span>
                  <div
                    style={{
                      padding: '6px 12px',
                      borderRadius: '6px',
                      background: '#27272a',
                      fontSize: '12px',
                      color: '#a1a1aa',
                    }}
                  >
                    📤 Slack Action
                  </div>
                </div>

                <div style={{ fontWeight: 600, color: '#e4e4e7', marginBottom: '6px', fontSize: '15px' }}>
                  No Workflow Generated Yet
                </div>
                <div style={{ fontSize: '13px', maxWidth: 360, lineHeight: 1.5 }}>
                  Enter an automation description on the left or click one of the blueprint starters to synthesize an end-to-end executable graph.
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* TAB 2: AUTONOMOUS AGENT CHAT */}
      {activeTab === 'chat' && (
        <div
          style={{
            background: 'var(--card-bg, #18181b)',
            border: '1px solid var(--border-color, #27272a)',
            borderRadius: '12px',
            display: 'flex',
            flexDirection: 'column',
            height: '660px',
            overflow: 'hidden',
          }}
        >
          {/* Chat Header Bar */}
          <div
            style={{
              padding: '0.75rem 1.25rem',
              borderBottom: '1px solid #27272a',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              background: 'rgba(0, 0, 0, 0.25)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
              <FlowsmithBrandMark size={24} variant="badge" glow={false} />
              <div>
                <strong style={{ fontSize: '14px', color: '#f8fafc' }}>Flowsmith Autonomous ReAct Agent</strong>
                <span style={{ fontSize: '12px', color: '#71717a', marginLeft: '10px' }}>
                  Session: <code>{sessionId}</code>
                </span>
              </div>
            </div>
            <button
              className="ghost"
              onClick={handleClearMemory}
              style={{ fontSize: '12px', padding: '4px 10px', height: 'auto' }}
            >
              Clear Session Memory
            </button>
          </div>

          {/* Missing Credential Notice */}
          {!statusInfo.configured && (
            <div
              style={{
                padding: '0.75rem 1.25rem',
                background: 'rgba(245, 158, 11, 0.08)',
                borderBottom: '1px solid rgba(245, 158, 11, 0.25)',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                fontSize: '13px',
                color: '#fbbf24',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span>⚠️</span>
                <span>
                  <strong>LLM Credential Required:</strong> Add an OpenAI, Anthropic, or Ollama credential under Credentials to unlock live agent tool-calling.
                </span>
              </div>
              <button
                className="primary"
                onClick={() => navigate('/credentials')}
                style={{ fontSize: '12px', padding: '4px 10px', height: 'auto', background: '#d97706' }}
              >
                Add Credential →
              </button>
            </div>
          )}

          {/* Messages Scroll Area */}
          <div
            style={{
              flex: 1,
              padding: '1.25rem',
              overflowY: 'auto',
              display: 'flex',
              flexDirection: 'column',
              gap: '1rem',
            }}
          >
            {/* Show Starter Cards if only initial assistant greeting is present */}
            {messages.length === 1 && (
              <div style={{ margin: 'auto 0', padding: '1rem 0', textAlign: 'center' }}>
                <div style={{ marginBottom: '1.25rem' }}>
                  <FlowsmithBrandMark size={44} variant="badge" glow={true} />
                  <h4 style={{ margin: '0.75rem 0 0.25rem', fontSize: '16px', fontWeight: 600 }}>
                    What would you like to build or automate?
                  </h4>
                  <p style={{ margin: 0, fontSize: '13px', color: '#94a3b8' }}>
                    Select a quick task below or type a natural language prompt.
                  </p>
                </div>

                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
                    gap: '0.75rem',
                    maxWidth: 720,
                    margin: '0 auto',
                    textAlign: 'left',
                  }}
                >
                  {QUICK_AGENT_ACTIONS.map((act, aIdx) => (
                    <div
                      key={aIdx}
                      onClick={() => handleSendChat(act.prompt)}
                      style={{
                        padding: '0.85rem 1rem',
                        borderRadius: '10px',
                        background: 'rgba(255, 255, 255, 0.03)',
                        border: '1px solid rgba(255, 255, 255, 0.08)',
                        cursor: 'pointer',
                        transition: 'all 0.15s ease',
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.background = 'rgba(255, 255, 255, 0.06)'
                        e.currentTarget.style.borderColor = 'rgba(139, 92, 246, 0.35)'
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.background = 'rgba(255, 255, 255, 0.03)'
                        e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.08)'
                      }}
                    >
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '6px',
                          fontWeight: 600,
                          fontSize: '13px',
                          color: '#f8fafc',
                          marginBottom: '3px',
                        }}
                      >
                        <span>{act.icon}</span>
                        <span>{act.title}</span>
                      </div>
                      <div style={{ fontSize: '12px', color: '#94a3b8', lineHeight: '1.35' }}>
                        {act.desc}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Conversation Messages */}
            {messages.map((m, idx) => (
              <div
                key={idx}
                style={{
                  alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                  maxWidth: '78%',
                  display: 'flex',
                  gap: '10px',
                }}
              >
                {m.role === 'assistant' && (
                  <div style={{ marginTop: '2px', flexShrink: 0 }}>
                    <FlowsmithBrandMark size={26} variant="badge" glow={false} />
                  </div>
                )}
                <div
                  style={{
                    background: m.role === 'user' ? 'linear-gradient(135deg, #4f46e5 0%, #3b82f6 100%)' : 'rgba(255, 255, 255, 0.04)',
                    color: m.role === 'user' ? '#ffffff' : 'var(--text-bright, #f4f4f5)',
                    border: m.role === 'user' ? 'none' : '1px solid rgba(255, 255, 255, 0.08)',
                    padding: '0.85rem 1.1rem',
                    borderRadius: m.role === 'user' ? '14px 14px 2px 14px' : '14px 14px 14px 2px',
                    fontSize: '13.5px',
                    lineHeight: '1.5',
                  }}
                >
                  <div style={{ whiteSpace: 'pre-wrap' }}>{m.content}</div>

                  {/* Show Tools Invoked */}
                  {m.toolsUsed && m.toolsUsed.length > 0 && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: '0.6rem' }}>
                      {m.toolsUsed.map((tool, tIdx) => (
                        <span
                          key={tIdx}
                          style={{
                            fontSize: '11px',
                            padding: '2px 6px',
                            borderRadius: '4px',
                            background: 'rgba(99, 102, 241, 0.2)',
                            color: '#a5b4fc',
                            border: '1px solid rgba(99, 102, 241, 0.3)',
                          }}
                        >
                          🛠️ {tool}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* Reasoning Trace Accordion */}
                  {m.trace && m.trace.length > 0 && (
                    <details
                      style={{
                        marginTop: '0.75rem',
                        paddingTop: '0.5rem',
                        borderTop: '1px solid rgba(255, 255, 255, 0.1)',
                        fontSize: '12px',
                        color: '#93c5fd',
                      }}
                    >
                      <summary style={{ cursor: 'pointer', userSelect: 'none' }}>
                        View Reasoning Trace ({m.trace.length} steps)
                      </summary>
                      <div
                        style={{
                          marginTop: '0.5rem',
                          padding: '0.6rem',
                          background: 'rgba(0, 0, 0, 0.35)',
                          borderRadius: '6px',
                          fontFamily: 'monospace',
                          fontSize: '11px',
                          whiteSpace: 'pre-wrap',
                          color: '#cbd5e1',
                          maxHeight: '180px',
                          overflowY: 'auto',
                        }}
                      >
                        {m.trace.map((t, tIdx) => (
                          <div key={tIdx} style={{ marginBottom: '6px' }}>
                            <strong>[{t.type || 'Step'}]</strong> {typeof t === 'string' ? t : JSON.stringify(t)}
                          </div>
                        ))}
                      </div>
                    </details>
                  )}
                </div>
              </div>
            ))}

            {chatSending && (
              <div
                style={{
                  alignSelf: 'flex-start',
                  display: 'flex',
                  gap: '10px',
                  alignItems: 'center',
                }}
              >
                <FlowsmithBrandMark size={26} variant="badge" glow={false} />
                <div
                  style={{
                    background: 'rgba(255, 255, 255, 0.04)',
                    border: '1px solid rgba(255, 255, 255, 0.08)',
                    padding: '0.75rem 1rem',
                    borderRadius: '14px 14px 14px 2px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                    color: '#94a3b8',
                    fontSize: '13px',
                  }}
                >
                  <span
                    style={{
                      width: 12,
                      height: 12,
                      border: '2px solid rgba(255,255,255,0.2)',
                      borderTopColor: '#60a5fa',
                      borderRadius: '50%',
                      animation: 'spin 0.8s linear infinite',
                    }}
                  />
                  Agent reasoning with live catalog & tools...
                </div>
              </div>
            )}
            <div ref={chatBottomRef} />
          </div>

          {/* Chat Input Bar */}
          <form
            onSubmit={(e) => {
              e.preventDefault()
              handleSendChat()
            }}
            style={{
              padding: '0.75rem 1.25rem',
              borderTop: '1px solid #27272a',
              background: 'rgba(0, 0, 0, 0.25)',
              display: 'flex',
              gap: '0.75rem',
              alignItems: 'center',
            }}
          >
            <input
              type="text"
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              placeholder="Ask the agent to construct an automation, analyze data, or query connectors..."
              style={{
                flex: 1,
                padding: '0.65rem 0.95rem',
                borderRadius: '8px',
                background: 'var(--input-bg, #09090b)',
                border: '1px solid var(--border-color, #3f3f46)',
                color: 'inherit',
                fontSize: '13.5px',
                outline: 'none',
              }}
            />
            <button
              className="primary"
              type="submit"
              disabled={chatSending || !chatInput.trim()}
              style={{ padding: '0.65rem 1.25rem' }}
            >
              Send
            </button>
          </form>
        </div>
      )}

      {/* TAB 3: AI ARCHITECTURE & MCP */}
      {activeTab === 'capabilities' && <AIArchitectureSection />}
    </div>
  )
}
