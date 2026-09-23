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
      expect(html).toContain('Prompt to Workflow Generator')
      expect(html).toContain('Try an example:')
      expect(html).toContain('Generate Workflow')
      expect(html).toContain('Cancel')
    })

    it('renders all example prompt chips', () => {
      const html = renderToStaticMarkup(
        React.createElement(AICopilotModal, { isOpen: true, onClose: () => {} })
      )
      expect(html).toContain('Stripe payment webhook')
      expect(html).toContain('Postgres new customer query')
      expect(html).toContain('Schedule daily RSS parser')
      expect(html).toContain('RAG knowledge base pipeline')
    })
    it('renders extend canvas option in AICopilotModal when canvas has nodes', () => {
      const mockCanvasNodes = [{ id: 'node_1', type: 'custom', data: { node: { id: 'node_1', type: 'webhook' } } }]
      const html = renderToStaticMarkup(
        React.createElement(AICopilotModal, {
          isOpen: true,
          onClose: () => {},
          nodes: mockCanvasNodes,
        })
      )
      expect(html).toContain('Extend current canvas')
      expect(html).toContain('Ctrl')
      expect(html).toContain('Enter')
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
      expect(html).toContain('Workflow Builder')
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
      expect(html).toContain('Inspect this workflow and list all nodes')
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

    it('has api.chatWithAgent and api.getAiMemory defined', async () => {
      const { api } = await import('../api.js')
      expect(typeof api.chatWithAgent).toBe('function')
      expect(typeof api.getAiMemory).toBe('function')
      expect(typeof api.clearAiMemory).toBe('function')
    })
  })
})
