import { describe, it, expect, beforeEach } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import AICopilotModal from './AICopilotModal'
import AIChatDrawer from './AIChatDrawer'
import { useWorkflowStore } from '../stores/workflowStore'

describe('AI Components Suite', () => {
  beforeEach(() => {
    useWorkflowStore.setState({ nodes: [], edges: [], workflow: { id: 'wf_test', name: 'Test Workflow' } })
  })

  describe('AICopilotModal', () => {
    it('renders null when closed', () => {
      const html = renderToStaticMarkup(
        React.createElement(AICopilotModal, { isOpen: false, onClose: () => {} })
      )
      expect(html).toBe('')
    })

    it('renders modal content when open', () => {
      const html = renderToStaticMarkup(
        React.createElement(AICopilotModal, { isOpen: true, onClose: () => {} })
      )
      expect(html).toContain('AI COPILOT')
      expect(html).toContain('Smith')
      expect(html).toContain('Chat &amp; Tools')
      expect(html).toContain('Debug &amp; Analyze')
      expect(html).not.toContain('Workflow Builder')
    })

    it('renders all quick action cards', () => {
      const html = renderToStaticMarkup(
        React.createElement(AICopilotModal, { isOpen: true, onClose: () => {} })
      )
      expect(html).toContain('Trace this workflow and list all nodes')
      expect(html).toContain('Explain how this workflow works')
      expect(html).toContain('Debug last execution failure')
      expect(html).toContain('Optimize this workflow')
    })
    it('renders canvas context option in AICopilotModal when canvas has nodes', () => {
      const mockCanvasNodes = [{ id: 'node_1', type: 'custom', data: { node: { id: 'node_1', type: 'webhook' } } }]
      const html = renderToStaticMarkup(
        React.createElement(AICopilotModal, {
          isOpen: true,
          onClose: () => {},
          nodes: mockCanvasNodes,
        })
      )
      expect(html).toContain('Use current canvas')
    })
  })

  describe('AIChatDrawer', () => {
    it('renders null when closed', () => {
      const html = renderToStaticMarkup(
        React.createElement(AIChatDrawer, { isOpen: false, onClose: () => {} })
      )
      expect(html).toBe('')
    })

    it('renders drawer header, copy button, and controls with memory badge when open', () => {
      const html = renderToStaticMarkup(
        React.createElement(AIChatDrawer, {
          isOpen: true,
          onClose: () => {},
        })
      )
      expect(html).toContain('Smith')
      expect(html).toContain('AI COPILOT')
      expect(html).toContain('Ready')
      expect(html).toContain('New Chat')
      expect(html).toContain('Chat &amp; Tools')
      expect(html).not.toContain('Workflow Builder')
      expect(html).toContain('Debug &amp; Analyze')
      expect(html).toContain('Use current canvas')
      expect(html).toContain('Ask Smith anything...')
      expect(html).toContain('smith-avatar-circle')
    })

    it('renders active workflow canvas context when nodes present', () => {
      const mockNodes = [
        {
          id: 'node_ai_1',
          type: 'custom',
          data: {
            node: { id: 'node_ai_1', type: 'ai_agent', name: 'Support Analyst' },
          },
        },
      ]

      const html = renderToStaticMarkup(
        React.createElement(AIChatDrawer, {
          isOpen: true,
          onClose: () => {},
          nodes: mockNodes,
        })
      )
      expect(html).toContain('Smith')
      expect(html).toContain('Use current canvas')
      expect(html).toContain('Trace this workflow and list all nodes')
    })

    it('renders diagnostics and smart tools when multi-node workflow loaded', () => {
      const mockNodes = [
        {
          id: 'node_ai_1',
          type: 'custom',
          data: {
            node: { id: 'node_ai_1', type: 'ai_agent', name: 'Agent Alpha' },
          },
        },
        {
          id: 'node_ai_2',
          type: 'custom',
          data: {
            node: { id: 'node_ai_2', type: 'ai_agent', name: 'Agent Beta' },
          },
        },
      ]

      const html = renderToStaticMarkup(
        React.createElement(AIChatDrawer, {
          isOpen: true,
          onClose: () => {},
          nodes: mockNodes,
        })
      )
      expect(html).toContain('smith-drawer')
      expect(html).toContain('/ generate')
      expect(html).toContain('/ debug')
    })

    it('chatWithAgent posts the payload to /api/ai/chat and unwraps the envelope', async () => {
      const { api } = await import('../api.js')
      const calls = []
      const originalFetch = globalThis.fetch
      globalThis.fetch = async (url, opts = {}) => {
        calls.push({ url, opts })
        return new Response(JSON.stringify({ data: { reply: 'ok' } }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      try {
        const res = await api.chatWithAgent({ message: 'hi', session_id: 's1' })
        expect(calls).toHaveLength(1)
        expect(String(calls[0].url)).toContain('/api/ai/chat')
        expect(calls[0].opts.method).toBe('POST')
        expect(String(calls[0].opts.body)).toContain('"hi"')
        expect(res).toEqual({ reply: 'ok' })
      } finally {
        globalThis.fetch = originalFetch
      }
    })
  })
})
