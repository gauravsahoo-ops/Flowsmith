import React, { useState } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import { api } from '../api'
import { toReactFlow } from '../mappers'

const EXAMPLE_PROMPTS = [
  'Stripe payment webhook to Slack notification with AI summary',
  'Postgres new customer query to automated welcome email and CRM record',
  'Schedule daily RSS parser to Claude 3.5 summary and Telegram message',
  'RAG knowledge base pipeline querying pgvector and answering user support question',
]

export default function AICopilotModal({ isOpen, onClose }) {
  const [prompt, setPrompt] = useState('')
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState(null)

  if (!isOpen) return null

  const handleGenerate = async () => {
    const text = prompt.trim()
    if (!text || generating) return

    setGenerating(true)
    setError(null)

    try {
      let generatedNodes = []
      let generatedEdges = []

      // 1. Try real LLM workflow generation via backend API
      try {
        const res = await api.generateWorkflow(text)
        const wf = res?.data?.workflow || res?.workflow
        if (wf && Array.isArray(wf.nodes) && wf.nodes.length > 0) {
          const rf = toReactFlow(wf)
          generatedNodes = rf.nodes || []
          generatedEdges = rf.edges || []
        }
      } catch (backendErr) {
        console.warn('Backend LLM generation fallback:', backendErr)
      }

      // 2. If backend didn't return nodes, use intelligent curated graph templates
      if (generatedNodes.length === 0) {
        const lower = text.toLowerCase()
        const currentNodes = useWorkflowStore.getState().nodes || []
        const startY = currentNodes.length > 0
          ? Math.max(...currentNodes.map((n) => n.position?.y || 0)) + 220
          : 160
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
                  name: 'AI Transaction Analyst',
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
                  type: 'slack',
                  name: 'Notify Slack',
                  version: 1,
                  parameters: {
                    webhook_url: 'https://hooks.slack.com/services/YOUR/WEBHOOK/URL',
                    channel: '#finance-alerts',
                    text: '{{ $json.output }}',
                  },
                  settings: {},
                },
              },
            },
          ]
          generatedEdges = [
            { id: `e_${generatedNodes[0].id}_${generatedNodes[1].id}`, source: generatedNodes[0].id, sourceHandle: 'main', target: generatedNodes[1].id, targetHandle: 'main' },
            { id: `e_${generatedNodes[1].id}_${generatedNodes[2].id}`, source: generatedNodes[1].id, sourceHandle: 'main', target: generatedNodes[2].id, targetHandle: 'main' },
          ]
        } else if (lower.includes('postgres') || lower.includes('customer') || lower.includes('email') || lower.includes('crm')) {
          generatedNodes = [
            {
              id: `node_${now}_1`,
              type: 'custom',
              position: { x: 80, y: startY },
              data: {
                node: {
                  id: `node_${now}_1`,
                  type: 'schedule',
                  name: 'Daily Schedule Trigger',
                  version: 1,
                  parameters: { rules: [{ interval: 'hours', value: 24, timezone: 'UTC' }] },
                  settings: {},
                },
              },
            },
            {
              id: `node_${now}_2`,
              type: 'custom',
              position: { x: 380, y: startY },
              data: {
                node: {
                  id: `node_${now}_2`,
                  type: 'database_query',
                  name: 'Query New Customers',
                  version: 1,
                  parameters: {
                    sql: "SELECT id, name, email, created_at FROM customers WHERE created_at >= NOW() - INTERVAL '1 day'",
                  },
                  settings: {},
                },
              },
            },
            {
              id: `node_${now}_3`,
              type: 'custom',
              position: { x: 680, y: startY },
              data: {
                node: {
                  id: `node_${now}_3`,
                  type: 'ai_agent',
                  name: 'Personalization Agent',
                  version: 1,
                  parameters: {
                    instructions: 'Craft a warm, personalized welcome message based on customer profile.',
                    tools: ['calculator', 'current_time'],
                    model: 'gpt-4o',
                  },
                  settings: {},
                },
              },
            },
            {
              id: `node_${now}_4`,
              type: 'custom',
              position: { x: 980, y: startY },
              data: {
                node: {
                  id: `node_${now}_4`,
                  type: 'send_email',
                  name: 'Send Welcome Email',
                  version: 1,
                  parameters: {
                    to: '{{ $json.email }}',
                    subject: 'Welcome to Flowsmith!',
                    body: '{{ $json.output }}',
                    from_address: 'welcome@flowsmith.io',
                  },
                  settings: {},
                },
              },
            },
          ]
          generatedEdges = [
            { id: `e_${generatedNodes[0].id}_${generatedNodes[1].id}`, source: generatedNodes[0].id, sourceHandle: 'main', target: generatedNodes[1].id, targetHandle: 'main' },
            { id: `e_${generatedNodes[1].id}_${generatedNodes[2].id}`, source: generatedNodes[1].id, sourceHandle: 'main', target: generatedNodes[2].id, targetHandle: 'main' },
            { id: `e_${generatedNodes[2].id}_${generatedNodes[3].id}`, source: generatedNodes[2].id, sourceHandle: 'main', target: generatedNodes[3].id, targetHandle: 'main' },
          ]
        } else if (lower.includes('rss') || lower.includes('telegram') || lower.includes('news')) {
          generatedNodes = [
            {
              id: `node_${now}_1`,
              type: 'custom',
              position: { x: 80, y: startY },
              data: {
                node: {
                  id: `node_${now}_1`,
                  type: 'schedule',
                  name: 'Hourly Feed Trigger',
                  version: 1,
                  parameters: { rules: [{ interval: 'hours', value: 1, timezone: 'UTC' }] },
                  settings: {},
                },
              },
            },
            {
              id: `node_${now}_2`,
              type: 'custom',
              position: { x: 380, y: startY },
              data: {
                node: {
                  id: `node_${now}_2`,
                  type: 'rss_feed',
                  name: 'Fetch Tech News RSS',
                  version: 1,
                  parameters: { url: 'https://news.ycombinator.com/rss', limit: 10 },
                  settings: {},
                },
              },
            },
            {
              id: `node_${now}_3`,
              type: 'custom',
              position: { x: 680, y: startY },
              data: {
                node: {
                  id: `node_${now}_3`,
                  type: 'ai',
                  name: 'Claude 3.5 Digest',
                  version: 1,
                  parameters: {
                    prompt: 'Summarize the following tech articles into a 3-bullet daily brief:\n{{ $json.title }}\n{{ $json.link }}',
                    model: 'claude-3-5-sonnet',
                  },
                  settings: {},
                },
              },
            },
            {
              id: `node_${now}_4`,
              type: 'custom',
              position: { x: 980, y: startY },
              data: {
                node: {
                  id: `node_${now}_4`,
                  type: 'telegram',
                  name: 'Telegram Channel Alert',
                  version: 1,
                  parameters: {
                    bot_token: 'YOUR_TELEGRAM_BOT_TOKEN',
                    chat_id: '@tech_digest_channel',
                    text: '🚀 *Daily Tech Brief:*\n\n{{ $json.output }}',
                  },
                  settings: {},
                },
              },
            },
          ]
          generatedEdges = [
            { id: `e_${generatedNodes[0].id}_${generatedNodes[1].id}`, source: generatedNodes[0].id, sourceHandle: 'main', target: generatedNodes[1].id, targetHandle: 'main' },
            { id: `e_${generatedNodes[1].id}_${generatedNodes[2].id}`, source: generatedNodes[1].id, sourceHandle: 'main', target: generatedNodes[2].id, targetHandle: 'main' },
            { id: `e_${generatedNodes[2].id}_${generatedNodes[3].id}`, source: generatedNodes[2].id, sourceHandle: 'main', target: generatedNodes[3].id, targetHandle: 'main' },
          ]
        } else if (lower.includes('rag') || lower.includes('vector') || lower.includes('knowledge')) {
          generatedNodes = [
            {
              id: `node_${now}_1`,
              type: 'custom',
              position: { x: 100, y: startY },
              data: {
                node: {
                  id: `node_${now}_1`,
                  type: 'chat_trigger',
                  name: 'User Chat Question',
                  version: 1,
                  parameters: {},
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
                  name: 'PGVector Knowledge Search',
                  version: 1,
                  parameters: {
                    collection_name: 'company_docs',
                    top_k: 4,
                    query: '{{ $json.message }}',
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
                  type: 'ai',
                  name: 'Synthesis & Response',
                  version: 1,
                  parameters: {
                    prompt: 'Answer user question: {{ $json.message }}\nUsing context:\n{{ $json.context }}',
                    model: 'gpt-4o',
                  },
                  settings: {},
                },
              },
            },
          ]
          generatedEdges = [
            { id: `e_${generatedNodes[0].id}_${generatedNodes[1].id}`, source: generatedNodes[0].id, sourceHandle: 'main', target: generatedNodes[1].id, targetHandle: 'main' },
            { id: `e_${generatedNodes[1].id}_${generatedNodes[2].id}`, source: generatedNodes[1].id, sourceHandle: 'main', target: generatedNodes[2].id, targetHandle: 'main' },
          ]
        } else {
          // General autonomous workflow
          generatedNodes = [
            {
              id: `node_${now}_1`,
              type: 'custom',
              position: { x: 100, y: startY },
              data: {
                node: {
                  id: `node_${now}_1`,
                  type: 'manual_trigger',
                  name: 'Manual Start',
                  version: 1,
                  parameters: {},
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
                  name: 'Autonomous Assistant',
                  version: 1,
                  parameters: {
                    instructions: `Solve the following objective: ${text}`,
                    tools: ['http_request', 'database_query', 'calculator', 'current_time'],
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
                  name: 'Export / Webhook',
                  version: 1,
                  parameters: { method: 'POST', url: 'https://api.example.com/results' },
                  settings: {},
                },
              },
            },
          ]
          generatedEdges = [
            { id: `e_${generatedNodes[0].id}_${generatedNodes[1].id}`, source: generatedNodes[0].id, sourceHandle: 'main', target: generatedNodes[1].id, targetHandle: 'main' },
            { id: `e_${generatedNodes[1].id}_${generatedNodes[2].id}`, source: generatedNodes[1].id, sourceHandle: 'main', target: generatedNodes[2].id, targetHandle: 'main' },
          ]
        }
      }

      // 3. Add nodes and edges to the workflow store atomically
      useWorkflowStore.getState().pushHistory()
      useWorkflowStore.setState((state) => ({
        nodes: [...(state.nodes || []), ...generatedNodes],
        edges: [...(state.edges || []), ...generatedEdges],
      }))
      useWorkflowStore.getState().scheduleSave?.()

      onClose()
    } catch (err) {
      setError(err.message || 'Failed to generate workflow.')
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="ai-copilot-overlay modal-backdrop" onClick={onClose}>
      <div className="ai-copilot-modal modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="ai-copilot-header modal-header">
          <div className="title-with-badge">
            <span className="copilot-badge">✨ AI Copilot</span>
            <h3>Prompt to Workflow Generator</h3>
          </div>
          <button className="ai-copilot-close-btn ghost ghost--icon" type="button" onClick={onClose} title="Close">✕</button>
        </div>

        <div className="ai-copilot-body modal-body">
          <p className="ai-copilot-description description-text">
            Describe the workflow automation you want to create in plain language.
            Flowsmith will assemble, configure, and connect the nodes on your canvas automatically.
          </p>

          <textarea
            className="ai-copilot-textarea"
            rows={4}
            placeholder="e.g. When a new customer signs up in Postgres, summarize their company using Claude 3.5 Sonnet, search our pgvector docs, and send an alert to Slack..."
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            disabled={generating}
          />

          <div className="example-chips-wrap">
            <span className="chips-label">Try an example:</span>
            <div className="chips-list">
              {EXAMPLE_PROMPTS.map((ex, i) => (
                <button
                  key={i}
                  type="button"
                  className="example-chip"
                  onClick={() => setPrompt(ex)}
                  disabled={generating}
                >
                  ✨ {ex}
                </button>
              ))}
            </div>
          </div>

          {error && (
            <div className="ai-copilot-error banner-inline err" style={{ marginTop: 12 }}>
              {error}
            </div>
          )}
        </div>

        <div className="ai-copilot-footer modal-footer">
          <button className="ghost" type="button" onClick={onClose} disabled={generating}>
            Cancel
          </button>
          <button
            className="primary"
            type="button"
            onClick={handleGenerate}
            disabled={!prompt.trim() || generating}
          >
            {generating ? 'Generating Workflow…' : 'Generate Workflow'}
          </button>
        </div>
      </div>
    </div>
  )
}
