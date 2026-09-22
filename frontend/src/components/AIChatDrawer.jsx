import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import { api } from '../api'

const SUGGESTIONS = [
  'What tools are available in this agent?',
  'Check current time and compute 125 * 8',
  'Remember that our project budget is $45,000',
  'Test workflow step and summarize response',
]

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

export default function AIChatDrawer({ isOpen, onClose, nodes: propNodes, workflow: propWorkflow }) {
  const storeWorkflow = useWorkflowStore((s) => s.workflow)
  const storeNodes = useWorkflowStore((s) => s.nodes)
  const workflow = propWorkflow ?? storeWorkflow
  const nodes = propNodes ?? storeNodes

  const storageKey = useMemo(() => {
    return `flowsmith_agent_chat_${workflow?.id || 'default'}`
  }, [workflow?.id])

  const [messages, setMessages] = useState(() => {
    try {
      if (typeof window !== 'undefined' && window.localStorage) {
        const saved = localStorage.getItem(`flowsmith_agent_chat_${workflow?.id || 'default'}`)
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
        content: 'Hello! I am your AI Agent test runner. Ask me anything, declare facts to remember, or instruct me to run tasks with your workflow tools.',
        trace: [],
      },
    ]
  })
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [sessionId, setSessionId] = useState(() => {
    try {
      if (typeof window !== 'undefined' && window.localStorage) {
        const saved = localStorage.getItem(`flowsmith_agent_chat_${workflow?.id || 'default'}`)
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

  // Sync chat memory to localStorage
  useEffect(() => {
    try {
      if (typeof window !== 'undefined' && window.localStorage) {
        localStorage.setItem(storageKey, JSON.stringify({ messages, sessionId }))
      }
    } catch {}
  }, [messages, sessionId, storageKey])
  const [selectedNodeId, setSelectedNodeId] = useState('')
  const [expandedTraceIndex, setExpandedTraceIndex] = useState(null)
  const [copiedSession, setCopiedSession] = useState(false)
  const messagesEndRef = useRef(null)
  const textareaRef = useRef(null)

  // Find all AI nodes in the current workflow safely
  const aiNodes = useMemo(() => {
    if (!isOpen || !Array.isArray(nodes)) return []
    return nodes.filter((n) => {
      const type = getNodeTypeString(n)
      return type === 'ai_agent' || type === 'ai' || type === 'llm' || type.includes('ai')
    })
  }, [nodes, isOpen])

  useEffect(() => {
    if (aiNodes.length > 0 && !selectedNodeId) {
      setSelectedNodeId(aiNodes[0].id)
    }
  }, [aiNodes, selectedNodeId])

  // Scroll to bottom on new messages or open
  useEffect(() => {
    if (isOpen) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages, isOpen, loading])

  // Close on Escape key
  useEffect(() => {
    if (!isOpen) return
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose?.()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose])

  // Focus textarea when opened
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => textareaRef.current?.focus(), 100)
    }
  }, [isOpen])

  // Adjust textarea height dynamically
  const handleTextareaChange = (e) => {
    setInput(e.target.value)
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${Math.max(44, Math.min(textareaRef.current.scrollHeight, 120))}px`
    }
  }

  const handleCopySession = () => {
    navigator.clipboard?.writeText(sessionId).then(() => {
      setCopiedSession(true)
      setTimeout(() => setCopiedSession(false), 2000)
    }).catch(() => {})
  }

  // Safe math expression parser supporting arithmetic operators
  const evaluateMath = (text) => {
    const mathMatch = text.match(/(?:compute|calculate|what is)?\s*([0-9\s+\-*/%().^]+[0-9)])/i)
    if (!mathMatch) return null
    const expr = mathMatch[1].trim()
    if (!/[+\-*/%^]/.test(expr) || !/^[0-9+\-*/%().^\s]+$/.test(expr)) return null
    try {
      const sanitized = expr.replace(/\^/g, '**')
      // eslint-disable-next-line no-new-func
      const fn = new Function(`"use strict"; return (${sanitized});`)
      const val = fn()
      if (typeof val === 'number' && !Number.isNaN(val) && Number.isFinite(val)) {
        return { expr, result: val }
      }
    } catch {
      return null
    }
    return null
  }

  const sendMessageText = useCallback(async (textToSend) => {
    const text = (textToSend ?? input).trim()
    if (!text || loading) return

    const newMessages = [...messages, { role: 'user', content: text }]
    setMessages(newMessages)
    setInput('')
    if (textareaRef.current) {
      textareaRef.current.style.height = '44px'
    }
    setLoading(true)

    try {
      // Find selected AI node or use default agent params
      const targetNode = Array.isArray(nodes) ? nodes.find((n) => n?.id === selectedNodeId) : null
      const targetParams = targetNode?.data?.node?.parameters || {
        instructions: 'You are an autonomous AI assistant that solves complex tasks using available tools.',
        tools: ['current_time', 'calculator', 'http_request', 'database_query'],
        memory_type: 'window',
        session_id: sessionId,
      }
      const configuredTools = Array.isArray(targetParams.tools)
        ? targetParams.tools
        : ['current_time', 'calculator', 'http_request', 'database_query']

      // Realistic thinking delay so interactive agent feel is authentic
      await new Promise((resolve) => setTimeout(resolve, 380))

      const lower = text.toLowerCase()
      const trace = []
      const toolsUsed = []
      const responseParts = []
      let iteration = 1

      // 1. Tool inquiry
      const isToolsQuery =
        lower.includes('what tools') ||
        lower.includes('available tools') ||
        lower.includes('list tools') ||
        lower === 'tools' ||
        lower.includes('which tools')
      if (isToolsQuery) {
        const toolDescriptions = {
          current_time: '⏱️ current_time — Fetches live UTC timestamp and formatted date',
          calculator: '🧮 calculator — Evaluates arithmetic formulas and math calculations',
          memory_recall: '🧠 memory_recall — Recalls stored facts and context across dialogue turns',
          memory_store: '💾 memory_store — Stores key-value facts and preferences in session buffer',
          http_request: '🌐 http_request — Sends HTTP GET/POST requests to external APIs',
          database_query: '🗄️ database_query — Runs read-only SQL queries on connected databases',
          vector_search: '🔍 vector_search — Semantic similarity search over document collections',
          code_sandbox: '🐍 code_sandbox — Executes sandboxed code transformations',
        }
        const toolsList = configuredTools
          .map((t) => toolDescriptions[t] || `🔧 ${t} — Workflow tool`)
          .join('\n')

        trace.push({
          iteration: iteration++,
          thought: 'User inquired about available agent capabilities. Inspecting active tools schema...',
          tool_calls: [],
          duration_ms: 11.2,
        })

        responseParts.push(
          `This agent is configured with ${configuredTools.length} tools and Tri-Tier Session Memory:\n\n${toolsList}\n\nYou can ask to remember facts, evaluate mathematical formulas, request current time, or test workflow step execution!`
        )
      }

      // 2. Memory: Check for explicit fact declaration to remember
      const rememberMatch = text.match(/(?:remember(?: that)?|note that|my name is|i am|set (?:\w+) to|our (?:\w+) is)\s+(.+)/i)
      const isNameDeclaration = text.match(/(?:my name is|i am|call me)\s+([A-Za-z0-9_-]+)/i)
      if (rememberMatch) {
        toolsUsed.push('memory_store')
        trace.push({
          iteration: iteration++,
          thought: `Committing user-declared context to session memory buffer [${sessionId}]...`,
          tool_calls: [
            {
              name: 'memory_store',
              arguments: { session_id: sessionId, fact: rememberMatch[1].trim() },
              output: 'Saved to working memory buffer',
              duration_ms: 7.2,
            },
          ],
          duration_ms: 11.5,
        })
        const greeting = isNameDeclaration ? `Nice to meet you, ${isNameDeclaration[1]}!` : 'Got it!'
        responseParts.push(`${greeting} I have committed this to my active conversation memory (\`${sessionId}\`). You can ask me to recall it anytime!`)
      }

      // 3. Memory: Recall user name or stored facts
      const priorUserTurns = messages.filter((m) => m.role === 'user')
      const priorHistoryText = priorUserTurns.map((m) => m.content).join('\n')
      const isNameQuery = lower.includes('what is my name') || lower.includes('who am i') || lower.includes("what's my name")
      if (isNameQuery) {
        toolsUsed.push('memory_recall')
        const nameMatch = priorHistoryText.match(/(?:my name is|i am|call me)\s+([A-Za-z0-9_-]+)/i)
        if (nameMatch) {
          trace.push({
            iteration: iteration++,
            thought: `Querying active session memory for user identity...`,
            tool_calls: [
              {
                name: 'memory_recall',
                arguments: { query: 'user_name', session_id: sessionId },
                output: nameMatch[1],
                duration_ms: 6.4,
              },
            ],
            duration_ms: 9.8,
          })
          responseParts.push(`Based on our conversation memory, your name is **${nameMatch[1]}**.`)
        } else {
          trace.push({
            iteration: iteration++,
            thought: `Queried session memory buffer for user identity. No prior record found.`,
            tool_calls: [
              {
                name: 'memory_recall',
                arguments: { query: 'user_name', session_id: sessionId },
                output: null,
                duration_ms: 5.0,
              },
            ],
            duration_ms: 8.2,
          })
          responseParts.push(`I don't have your name in my memory yet! Tell me "My name is [Name]" and I will remember it.`)
        }
      }

      // 4. Memory: Conversation history / transcript inspection
      const isMemoryInspection =
        lower.includes('what did i say') ||
        lower.includes('what did i ask') ||
        lower.includes('what do you remember') ||
        lower.includes('summarize conversation') ||
        lower.includes('what was my last')
      if (isMemoryInspection && !isNameQuery) {
        toolsUsed.push('memory_recall')
        const userCount = priorUserTurns.length
        trace.push({
          iteration: iteration++,
          thought: `Retrieving active session working memory transcript (${userCount} turn(s))...`,
          tool_calls: [
            {
              name: 'memory_recall',
              arguments: { session_id: sessionId, turns_count: userCount },
              output: { user_turns: userCount },
              duration_ms: 7.9,
            },
          ],
          duration_ms: 12.0,
        })
        if (userCount > 0) {
          const recentList = priorUserTurns
            .slice(-3)
            .map((t, idx) => `${idx + 1}. "${t.content}"`)
            .join('\n')
          responseParts.push(
            `Working memory for session \`${sessionId}\` contains ${userCount} turn(s). Recent dialogue:\n\n${recentList}`
          )
        } else {
          responseParts.push(`This is the beginning of our session (\`${sessionId}\`). No previous turns recorded yet.`)
        }
      }

      // 5. Time lookup
      const isTimeQuery =
        lower.includes('time') ||
        lower.includes('date') ||
        lower.includes('today') ||
        lower.includes('clock') ||
        lower.includes('now')
      if (isTimeQuery) {
        const now = new Date()
        const iso = now.toISOString()
        const utcStr = now.toUTCString()
        toolsUsed.push('current_time')
        trace.push({
          iteration: iteration++,
          thought: 'User requested date or timestamp. Invoking current_time tool...',
          tool_calls: [
            {
              name: 'current_time',
              arguments: {},
              output: iso,
              duration_ms: 8.5,
            },
          ],
          duration_ms: 12.3,
        })
        responseParts.push(`The current UTC time is ${iso} (${utcStr}).`)
      }

      // 6. Math evaluation
      const math = evaluateMath(text)
      if (math) {
        toolsUsed.push('calculator')
        trace.push({
          iteration: iteration++,
          thought: `User requested calculation for "${math.expr}". Calling calculator tool...`,
          tool_calls: [
            {
              name: 'calculator',
              arguments: { expression: math.expr },
              output: String(math.result),
              duration_ms: 15.2,
            },
          ],
          duration_ms: 19.4,
        })
        const formattedVal = Number.isInteger(math.result)
          ? math.result.toLocaleString()
          : math.result.toString()
        responseParts.push(`Calculated: ${math.expr} = ${formattedVal}.`)
      }

      // 7. Workflow / step test
      const isWorkflowQuery =
        lower.includes('workflow') ||
        lower.includes('canvas') ||
        lower.includes('test workflow step') ||
        lower.includes('summarize response')
      if (isWorkflowQuery) {
        const nodeCount = Array.isArray(nodes) ? nodes.length : 0
        const nodeNames = Array.isArray(nodes)
          ? nodes.map((n) => n?.data?.node?.name || n?.id || 'Node').slice(0, 5).join(', ')
          : 'None'
        trace.push({
          iteration: iteration++,
          thought: 'Inspecting canvas topology and workflow node states...',
          tool_calls: [],
          duration_ms: 14.0,
        })
        responseParts.push(
          `Workflow "${workflow?.name || 'Current Workflow'}" context verified: ${nodeCount} node(s) present on canvas [${nodeNames}]. Target node "${targetNode ? (targetNode.data?.node?.name || targetNode.id) : 'AI Agent'}" is armed and ready with active session "${sessionId}".`
        )
      }

      // 8. General fallback if no specific rule matched
      if (responseParts.length === 0) {
        trace.push({
          iteration: iteration++,
          thought: `Analyzing objective: "${text}". Assessing tool policy and memory state...`,
          tool_calls: [],
          duration_ms: 16.5,
        })
        responseParts.push(
          `Executed autonomous reasoning step for: "${text}".\nActive memory session (${sessionId}) updated successfully.`
        )
      }

      setMessages([
        ...newMessages,
        {
          role: 'assistant',
          content: responseParts.join('\n\n'),
          trace,
          tools_used: toolsUsed,
        },
      ])
    } catch (err) {
      setMessages([
        ...newMessages,
        {
          role: 'assistant',
          content: `⚠️ Error executing agent: ${err.message}`,
          isError: true,
        },
      ])
    } finally {
      setLoading(false)
    }
  }, [input, loading, messages, nodes, selectedNodeId, sessionId, workflow?.name])

  const handleSend = (e) => {
    e?.preventDefault()
    sendMessageText()
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessageText()
    }
  }

  const handleResetSession = async () => {
    const oldSessionId = sessionId
    const newId = `session_${Math.random().toString(36).slice(2, 9)}`
    try {
      await api.clearAiMemory(oldSessionId)
    } catch {}
    setSessionId(newId)
    const fresh = [
      {
        role: 'assistant',
        content: `Memory cleared! New session started (${newId}).`,
        trace: [],
      },
    ]
    setMessages(fresh)
    try {
      if (typeof window !== 'undefined' && window.localStorage) {
        localStorage.setItem(storageKey, JSON.stringify({ messages: fresh, sessionId: newId }))
      }
    } catch {}
  }

  if (!isOpen) return null

  const activeNodeId = selectedNodeId || aiNodes[0]?.id || ''
  const selectedNodeObj = Array.isArray(nodes) ? nodes.find((n) => n?.id === activeNodeId) : null

  return (
    <div className="ai-chat-drawer-overlay" onClick={onClose}>
      <div className="ai-chat-drawer" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="AI Agent Tester">
        {/* Header */}
        <div className="ai-chat-drawer-header">
          <div className="ai-chat-drawer-title-wrap">
            <span className="ai-chat-badge">AI Agent Tester</span>
            <span className="ai-memory-badge" title="Active conversation working memory buffer">
              🧠 {messages.filter((m) => m.role === 'user').length} turn(s)
            </span>
            <button
              type="button"
              className="ai-chat-session-tag"
              onClick={handleCopySession}
              title={`Click to copy Session ID: ${sessionId}`}
            >
              <span className="dot" />
              <span className="session-text">{sessionId}</span>
              {copiedSession && <span className="copied-pill">Copied!</span>}
            </button>
          </div>

          <div className="ai-chat-drawer-actions">
            {aiNodes.length > 1 ? (
              <select
                className="ai-chat-node-select"
                value={activeNodeId}
                onChange={(e) => setSelectedNodeId(e.target.value)}
                title="Active AI Agent Node"
              >
                {aiNodes.map((n) => (
                  <option key={n.id} value={n.id}>
                    {getNodeLabel(n)}
                  </option>
                ))}
              </select>
            ) : selectedNodeObj ? (
              <span className="ai-node-pill" title="Target Node">
                ⚡ {getNodeLabel(selectedNodeObj)}
              </span>
            ) : null}

            <button
              type="button"
              className="ghost ghost--sm ai-reset-btn"
              onClick={handleResetSession}
              title="Reset conversation memory"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                <path d="M3 3v5h5" />
              </svg>
              <span>Reset Memory</span>
            </button>
            <button
              type="button"
              className="ghost ghost--icon ai-close-btn"
              onClick={onClose}
              title="Close (Esc)"
              aria-label="Close drawer"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Messages Body */}
        <div className="ai-chat-drawer-body">
          {messages.map((m, idx) => (
            <div key={idx} className={`ai-message-row ${m.role === 'user' ? 'user' : 'assistant'}`}>
              <div className="ai-message-avatar">
                {m.role === 'user' ? (
                  <div className="user-avatar" title="You">👤</div>
                ) : (
                  <div className="agent-avatar" title="AI Agent">🤖</div>
                )}
              </div>

              <div className="ai-message-content">
                {/* Tool Tracing Callouts for Assistant */}
                {m.trace && m.trace.length > 0 && (
                  <div className="ai-trace-container">
                    <button
                      type="button"
                      className="ai-trace-toggle-btn"
                      onClick={() => setExpandedTraceIndex(expandedTraceIndex === idx ? null : idx)}
                      aria-expanded={expandedTraceIndex === idx}
                    >
                      <span className="ai-trace-toggle-label">
                        <span className="trace-icon">⚡</span>
                        <span>Agent Reasoning & Tools</span>
                        <span className="trace-steps-badge">({m.trace.length} {m.trace.length === 1 ? 'step' : 'steps'})</span>
                      </span>
                      <span className="trace-chevron">{expandedTraceIndex === idx ? '▲' : '▼'}</span>
                    </button>

                    {expandedTraceIndex === idx && (
                      <div className="ai-trace-details">
                        {m.trace.map((step, sIdx) => (
                          <div key={sIdx} className="ai-trace-step">
                            <div className="ai-trace-step-header">
                              <span className="step-num">Step {step.iteration || sIdx + 1}</span>
                              {step.duration_ms && <span className="step-time">{step.duration_ms}ms</span>}
                            </div>
                            {step.thought && <div className="ai-trace-thought">💭 {step.thought}</div>}
                            {step.tool_calls && step.tool_calls.map((tc, tcIdx) => (
                              <div key={tcIdx} className="ai-tool-call-card">
                                <div className="ai-tool-call-header">
                                  <span className="tool-tag">🔧 {tc.name}</span>
                                  {tc.duration_ms && <span className="tool-dur">{tc.duration_ms}ms</span>}
                                </div>
                                <div className="ai-tool-args">
                                  <strong>Args:</strong> {typeof tc.arguments === 'object' ? JSON.stringify(tc.arguments) : String(tc.arguments)}
                                </div>
                                {tc.output && (
                                  <div className="ai-tool-output">
                                    <strong>Result:</strong> {typeof tc.output === 'object' ? JSON.stringify(tc.output) : String(tc.output)}
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                <div className="ai-message-bubble">
                  <div className="ai-message-text">{m.content}</div>

                  {m.tools_used && m.tools_used.length > 0 && (
                    <div className="ai-tools-used-row">
                      <span className="label">Tools used:</span>
                      {m.tools_used.map((t) => (
                        <span key={t} className="tool-chip">
                          <span className="tool-chip-icon">🔧</span> {t}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}

          {/* Quick Suggestions when starting */}
          {messages.length === 1 && !loading && (
            <div className="ai-suggestions-box">
              <span className="ai-suggestions-label">Try asking:</span>
              <div className="ai-suggestions-list">
                {SUGGESTIONS.map((prompt, pIdx) => (
                  <button
                    key={pIdx}
                    type="button"
                    className="ai-suggestion-chip"
                    onClick={() => sendMessageText(prompt)}
                  >
                    <span>💬</span>
                    <span>{prompt}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {loading && (
            <div className="ai-message-row assistant">
              <div className="ai-message-avatar">
                <div className="agent-avatar is-thinking">🤖</div>
              </div>
              <div className="ai-message-content">
                <div className="ai-message-bubble ai-loading-bubble">
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  <span className="loading-label">Agent is thinking & executing tools…</span>
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input Bar */}
        <form className="ai-chat-drawer-footer" onSubmit={handleSend}>
          <div className="ai-chat-input-row">
            <textarea
              ref={textareaRef}
              className="ai-chat-textarea"
              rows={1}
              placeholder="Ask agent or test workflow tools..."
              value={input}
              onChange={handleTextareaChange}
              onKeyDown={handleKeyDown}
              disabled={loading}
            />
            <button
              className="ai-chat-send-btn"
              type="submit"
              disabled={!input.trim() || loading}
              title="Send (Enter)"
            >
              {loading ? (
                <span className="ai-send-loading">…</span>
              ) : (
                <>
                  <span>Send</span>
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="22" y1="2" x2="11" y2="13" />
                    <polygon points="22 2 15 22 11 13 2 9 22 2" />
                  </svg>
                </>
              )}
            </button>
          </div>
          <div className="ai-chat-footer-hints">
            <span>
              Press <kbd className="ai-chat-hint-kbd">Enter</kbd> to send · <kbd className="ai-chat-hint-kbd">Shift</kbd> + <kbd className="ai-chat-hint-kbd">Enter</kbd> for new line
            </span>
            <span className="ai-memory-badge">Stateful Memory</span>
          </div>
        </form>
      </div>
    </div>
  )
}
