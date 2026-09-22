import React, { useState } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'

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
  const addNode = useWorkflowStore((s) => s.addNode)
  const addEdge = useWorkflowStore((s) => s.addEdge)

  if (!isOpen) return null

  const handleGenerate = async () => {
    const text = prompt.trim()
    if (!text || generating) return

    setGenerating(true)
    setError(null)

    try {
      // In production, calls /api/ai/assistant/generate
      // We parse the prompt or generate a curated visual graph
      const lower = text.toLowerCase()
      let generatedNodes = []
      let generatedEdges = []

      if (lower.includes('slack') || lower.includes('stripe') || lower.includes('webhook')) {
        generatedNodes = [
          {
            id: `node_${Date.now()}_1`,
            type: 'custom',
            position: { x: 100, y: 200 },
            data: {
              node: {
                id: `node_${Date.now()}_1`,
                type: 'webhook',
                name: 'Stripe Webhook',
                parameters: { path: 'stripe-events', method: 'POST' },
              },
            },
          },
          {
            id: `node_${Date.now()}_2`,
            type: 'custom',
            position: { x: 400, y: 200 },
            data: {
              node: {
                id: `node_${Date.now()}_2`,
                type: 'ai_agent',
                name: 'AI Transaction Analyst',
                parameters: {
                  instructions: 'Analyze customer transaction details and summarize key highlights.',
                  tools: ['calculator', 'current_time'],
                  model: 'claude-3-5-sonnet',
                },
              },
            },
          },
          {
            id: `node_${Date.now()}_3`,
            type: 'custom',
            position: { x: 750, y: 200 },
            data: {
              node: {
                id: `node_${Date.now()}_3`,
                type: 'slack',
                name: 'Notify Slack',
                parameters: { channel: '#finance-alerts', message: '{{ $json.output }}' },
              },
            },
          },
        ]
        generatedEdges = [
          { id: `e_${generatedNodes[0].id}_${generatedNodes[1].id}`, source: generatedNodes[0].id, target: generatedNodes[1].id },
          { id: `e_${generatedNodes[1].id}_${generatedNodes[2].id}`, source: generatedNodes[1].id, target: generatedNodes[2].id },
        ]
      } else if (lower.includes('rag') || lower.includes('vector') || lower.includes('knowledge')) {
        generatedNodes = [
          {
            id: `node_${Date.now()}_1`,
            type: 'custom',
            position: { x: 100, y: 200 },
            data: {
              node: {
                id: `node_${Date.now()}_1`,
                type: 'chat_trigger',
                name: 'User Chat Question',
                parameters: {},
              },
            },
          },
          {
            id: `node_${Date.now()}_2`,
            type: 'custom',
            position: { x: 420, y: 200 },
            data: {
              node: {
                id: `node_${Date.now()}_2`,
                type: 'rag_pipeline',
                name: 'PGVector Knowledge Search',
                parameters: {
                  collection_name: 'company_docs',
                  top_k: 4,
                  query: '{{ $json.message }}',
                },
              },
            },
          },
          {
            id: `node_${Date.now()}_3`,
            type: 'custom',
            position: { x: 780, y: 200 },
            data: {
              node: {
                id: `node_${Date.now()}_3`,
                type: 'ai',
                name: 'Synthesis & Response',
                parameters: {
                  prompt: 'Answer user question: {{ $json.message }}\nUsing context:\n{{ $json.context }}',
                  model: 'gpt-4o',
                },
              },
            },
          },
        ]
        generatedEdges = [
          { id: `e_${generatedNodes[0].id}_${generatedNodes[1].id}`, source: generatedNodes[0].id, target: generatedNodes[1].id },
          { id: `e_${generatedNodes[1].id}_${generatedNodes[2].id}`, source: generatedNodes[1].id, target: generatedNodes[2].id },
        ]
      } else {
        // General workflow generator
        generatedNodes = [
          {
            id: `node_${Date.now()}_1`,
            type: 'custom',
            position: { x: 100, y: 200 },
            data: {
              node: {
                id: `node_${Date.now()}_1`,
                type: 'schedule',
                name: 'Schedule Trigger',
                parameters: { rules: [{ mode: 'everyHour' }] },
              },
            },
          },
          {
            id: `node_${Date.now()}_2`,
            type: 'custom',
            position: { x: 420, y: 200 },
            data: {
              node: {
                id: `node_${Date.now()}_2`,
                type: 'ai_agent',
                name: 'Autonomous Assistant',
                parameters: {
                  instructions: `Solve the following objective: ${text}`,
                  tools: ['http_request', 'database_query', 'calculator', 'current_time'],
                },
              },
            },
          },
          {
            id: `node_${Date.now()}_3`,
            type: 'custom',
            position: { x: 780, y: 200 },
            data: {
              node: {
                id: `node_${Date.now()}_3`,
                type: 'http_request',
                name: 'Export / Webhook',
                parameters: { method: 'POST', url: 'https://api.example.com/results' },
              },
            },
          },
        ]
        generatedEdges = [
          { id: `e_${generatedNodes[0].id}_${generatedNodes[1].id}`, source: generatedNodes[0].id, target: generatedNodes[1].id },
          { id: `e_${generatedNodes[1].id}_${generatedNodes[2].id}`, source: generatedNodes[1].id, target: generatedNodes[2].id },
        ]
      }

      // Add nodes and edges to the workflow store
      for (const n of generatedNodes) {
        addNode(n)
      }
      for (const e of generatedEdges) {
        addEdge(e)
      }

      onClose()
    } catch (err) {
      setError(err.message || 'Failed to generate workflow.')
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card ai-copilot-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="title-with-badge">
            <span className="copilot-badge">✨ AI Copilot</span>
            <h3>Prompt to Workflow Generator</h3>
          </div>
          <button className="ghost ghost--icon" onClick={onClose}>✕</button>
        </div>

        <div className="modal-body">
          <p className="description-text">
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
                  className="example-chip"
                  type="button"
                  onClick={() => setPrompt(ex)}
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>

          {error && <div className="banner-inline err" style={{ marginTop: 12 }}>{error}</div>}
        </div>

        <div className="modal-footer">
          <button className="ghost" onClick={onClose} disabled={generating}>Cancel</button>
          <button
            className="primary"
            onClick={handleGenerate}
            disabled={!prompt.trim() || generating}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            {generating ? (
              <>
                <span className="spinner-sm" />
                <span>Generating Nodes…</span>
              </>
            ) : (
              <>
                <span>✨ Generate Workflow</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
