import React, { useState, useRef, useEffect } from 'react'
import { useWorkflowStore } from '../stores/workflowStore'
import { api } from '../api'
import { toWorkflowJson } from '../mappers'

const QUICK_ACTIONS = [
  { id: 'layout', label: '📐 Auto-Layout', prompt: 'Auto-layout the canvas graph' },
  { id: 'slack', label: '💬 Add Slack Alert', prompt: 'Add a Slack notification step on failure' },
  { id: 'retry', label: '🛡️ Add Retry Policy', prompt: 'Add exponential backoff retries to network calls' },
  { id: 'explain', label: '💡 Explain Workflow', prompt: 'Explain this workflow in business and technical terms' },
  { id: 'optimize', label: '⚡ Optimize Reliability', prompt: 'Optimize this workflow for reliability and fault tolerance' },
]

export default function InCanvasCopilot({ open, onClose, onAutoLayout, fitView }) {
  const [prompt, setPrompt] = useState('')
  const [loading, setLoading] = useState(false)
  const [feedback, setFeedback] = useState(null) // { type: 'success'|'info'|'error', text: '', details: null }
  const inputRef = useRef(null)

  const workflow = useWorkflowStore((s) => s.workflow)
  const nodes = useWorkflowStore((s) => s.nodes)
  const edges = useWorkflowStore((s) => s.edges)
  const canUndo = useWorkflowStore((s) => s.canUndo)
  const undo = useWorkflowStore((s) => s.undo)
  const applyWorkflowModification = useWorkflowStore((s) => s.applyWorkflowModification)

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 50)
      setFeedback(null)
    }
  }, [open])

  if (!open) return null

  const handleExecute = async (overridePrompt) => {
    const text = (overridePrompt || prompt).trim()
    if (!text) return

    setLoading(true)
    setFeedback(null)

    // 1. Direct local command interception
    const lower = text.toLowerCase()
    if (lower.includes('layout') || lower.includes('tidy') || lower.includes('clean up graph')) {
      if (onAutoLayout) onAutoLayout()
      setFeedback({
        type: 'success',
        text: 'Canvas auto-layout applied smoothly.',
      })
      setLoading(false)
      setPrompt('')
      return
    }

    if (lower.startsWith('explain') || lower.includes('what does this workflow do')) {
      try {
        const currentJson = toWorkflowJson(workflow, nodes, edges)
        const exp = await api.aiExplainDraft(currentJson)
        setFeedback({
          type: 'info',
          text: exp.summary || 'Workflow explanation generated.',
          details: exp,
        })
      } catch (err) {
        setFeedback({
          type: 'error',
          text: err.message || 'Failed to generate explanation.',
        })
      } finally {
        setLoading(false)
      }
      return
    }

    if (lower.startsWith('optimize')) {
      try {
        const currentJson = toWorkflowJson(workflow, nodes, edges)
        const opt = await api.aiOptimizeDraft(currentJson, 'reliability')
        if (opt.modified_workflow) {
          applyWorkflowModification(opt.modified_workflow)
          if (fitView) setTimeout(() => fitView({ duration: 300, padding: 0.15 }), 100)
        }
        setFeedback({
          type: 'success',
          text: opt.summary || 'Optimizations applied to draft workflow.',
          savings: opt.estimated_savings,
        })
      } catch (err) {
        setFeedback({
          type: 'error',
          text: err.message || 'Failed to optimize workflow.',
        })
      } finally {
        setLoading(false)
      }
      return
    }

    // 2. Surgical Natural Language Modification
    try {
      const currentJson = toWorkflowJson(workflow, nodes, edges)
      const res = await api.aiModifyWorkflow(currentJson, text)
      if (res && res.modified_workflow) {
        applyWorkflowModification(res.modified_workflow)
        const addedCount = (res.added_nodes || []).length
        const modCount = (res.modified_nodes || []).length
        const connCount = (res.added_connections || []).length

        let summaryMsg = res.summary || 'Workflow updated.'
        if (addedCount || modCount || connCount) {
          summaryMsg += ` (${[
            addedCount ? `+${addedCount} node${addedCount > 1 ? 's' : ''}` : null,
            connCount ? `+${connCount} connection${connCount > 1 ? 's' : ''}` : null,
            modCount ? `~${modCount} updated` : null,
          ].filter(Boolean).join(', ')})`
        }

        setFeedback({
          type: 'success',
          text: summaryMsg,
          canRevert: true,
        })
        setPrompt('')
        if (fitView) setTimeout(() => fitView({ duration: 350, padding: 0.15 }), 80)
      } else {
        setFeedback({
          type: 'info',
          text: res?.summary || 'No modifications required for this workflow.',
        })
      }
    } catch (err) {
      setFeedback({
        type: 'error',
        text: err.message || 'Failed to modify workflow. Please refine your instruction.',
      })
    } finally {
      setLoading(false)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleExecute()
    } else if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
    }
  }

  return (
    <div
      className="in-canvas-copilot-container"
      role="dialog"
      aria-label="In-Canvas AI Copilot"
      style={{
        position: 'absolute',
        top: 60,
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 15,
        width: 'min(640px, 94vw)',
        animation: 'modalPopIn 0.2s cubic-bezier(0.16, 1, 0.3, 1) forwards',
      }}
    >
      <div
        className="in-canvas-copilot-card"
        style={{
          background: 'var(--panel, rgba(15, 20, 32, 0.95))',
          backdropFilter: 'blur(20px)',
          WebkitBackdropFilter: 'blur(20px)',
          border: '1px solid rgba(99, 102, 241, 0.35)',
          borderRadius: 14,
          padding: '12px 14px',
          boxShadow: '0 20px 50px rgba(0,0,0,0.5), 0 0 25px rgba(99, 102, 241, 0.2)',
        }}
      >
        {/* Header row */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                width: 22,
                height: 22,
                borderRadius: 6,
                background: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)',
                color: '#fff',
                boxShadow: '0 2px 8px rgba(99, 102, 241, 0.4)',
              }}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                <path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z" />
              </svg>
            </span>
            <span style={{ fontSize: 13, fontWeight: 700, letterSpacing: '-0.01em', color: 'var(--text, #f8fafc)' }}>
              In-Canvas AI Copilot
            </span>
            <span
              style={{
                fontSize: 10,
                fontWeight: 600,
                padding: '1px 6px',
                borderRadius: 4,
                background: 'rgba(99, 102, 241, 0.15)',
                color: 'var(--accent, #818cf8)',
                border: '1px solid rgba(99, 102, 241, 0.3)',
                textTransform: 'uppercase',
                letterSpacing: '0.04em',
              }}
            >
              Surgical Diff
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 11, color: 'var(--text-muted, #64748b)' }}>ESC to close</span>
            <button
              type="button"
              className="ghost small"
              onClick={onClose}
              style={{ width: 24, height: 24, padding: 0, display: 'grid', placeItems: 'center', borderRadius: 6 }}
              aria-label="Close copilot"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
        </div>

        {/* Input bar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, position: 'relative' }}>
          <input
            ref={inputRef}
            type="text"
            className="copilot-input"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={loading}
            placeholder="Describe what to add or modify (e.g. 'Add Slack alert on error', 'Filter rows where score > 80')…"
            style={{
              flex: 1,
              background: 'rgba(0, 0, 0, 0.25)',
              border: '1px solid var(--border, rgba(255, 255, 255, 0.14))',
              borderRadius: 8,
              padding: '9px 12px',
              fontSize: 13,
              color: 'var(--text, #f8fafc)',
              outline: 'none',
              transition: 'border-color 0.15s ease',
            }}
          />
          <button
            type="button"
            className="primary small"
            onClick={() => handleExecute()}
            disabled={loading || !prompt.trim()}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              height: 36,
              padding: '0 14px',
              fontWeight: 600,
              fontSize: 12.5,
              flexShrink: 0,
            }}
          >
            {loading ? (
              <>
                <span className="app-topbar-context-dot" />
                <span>Applying…</span>
              </>
            ) : (
              <>
                <span>Apply</span>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <line x1="5" y1="12" x2="19" y2="12" />
                  <polyline points="12 5 19 12 12 19" />
                </svg>
              </>
            )}
          </button>
        </div>

        {/* Quick action chips */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginTop: 10 }}>
          <span style={{ fontSize: 11, color: 'var(--text-muted, #64748b)', fontWeight: 600 }}>Suggested:</span>
          {QUICK_ACTIONS.map((action) => (
            <button
              key={action.id}
              type="button"
              className="ghost small"
              onClick={() => handleExecute(action.prompt)}
              disabled={loading}
              style={{
                fontSize: 11,
                padding: '2px 8px',
                borderRadius: 999,
                background: 'rgba(255, 255, 255, 0.04)',
                border: '1px solid var(--border, rgba(255, 255, 255, 0.08))',
                color: 'var(--text, #cbd5e1)',
                cursor: 'pointer',
                transition: 'all 0.12s ease',
              }}
            >
              {action.label}
            </button>
          ))}
        </div>

        {/* Feedback / Results banner */}
        {feedback && (
          <div
            style={{
              marginTop: 10,
              padding: '9px 12px',
              borderRadius: 8,
              fontSize: 12.5,
              display: 'flex',
              alignItems: 'flex-start',
              justifyContent: 'space-between',
              gap: 10,
              background:
                feedback.type === 'success'
                  ? 'rgba(16, 185, 129, 0.12)'
                  : feedback.type === 'error'
                  ? 'rgba(244, 63, 94, 0.12)'
                  : 'rgba(99, 102, 241, 0.12)',
              border: `1px solid ${
                feedback.type === 'success'
                  ? 'rgba(16, 185, 129, 0.3)'
                  : feedback.type === 'error'
                  ? 'rgba(244, 63, 94, 0.3)'
                  : 'rgba(99, 102, 241, 0.3)'
              }`,
              color:
                feedback.type === 'success'
                  ? '#34d399'
                  : feedback.type === 'error'
                  ? '#fb7185'
                  : '#a5b4fc',
            }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 600 }}>{feedback.text}</div>
              {feedback.savings && (
                <div style={{ fontSize: 11.5, opacity: 0.9, marginTop: 2 }}>
                  Estimated efficiency impact: {feedback.savings}
                </div>
              )}
              {feedback.details && (
                <div style={{ marginTop: 6, fontSize: 11.5, color: 'var(--text-muted, #94a3b8)', lineHeight: 1.4 }}>
                  <div><strong>Trigger:</strong> {feedback.details.trigger}</div>
                  <div><strong>Data path:</strong> {feedback.details.data_flow}</div>
                </div>
              )}
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
              {feedback.canRevert && canUndo && (
                <button
                  type="button"
                  className="ghost small"
                  onClick={() => {
                    undo()
                    setFeedback({ type: 'info', text: 'Reverted last AI change.' })
                  }}
                  style={{
                    fontSize: 11,
                    padding: '2px 8px',
                    borderRadius: 4,
                    border: '1px solid rgba(255, 255, 255, 0.15)',
                    color: '#ffffff',
                    fontWeight: 600,
                  }}
                >
                  ↩ Undo
                </button>
              )}
              <button
                type="button"
                className="ghost small"
                onClick={() => setFeedback(null)}
                style={{ width: 20, height: 20, padding: 0, display: 'grid', placeItems: 'center' }}
                aria-label="Dismiss feedback"
              >
                ✕
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
