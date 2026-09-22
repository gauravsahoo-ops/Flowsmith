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
      expect(html).toContain('AI Copilot')
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
    })
  })

  describe('AIChatDrawer', () => {
    it('renders null when closed', () => {
      const html = renderToStaticMarkup(
        React.createElement(AIChatDrawer, { isOpen: false, onClose: () => {} })
      )
      expect(html).toBe('')
    })

    it('renders drawer header and controls with memory badge when open', () => {
      const html = renderToStaticMarkup(
        React.createElement(AIChatDrawer, {
          isOpen: true,
          onClose: () => {},
        })
      )
      expect(html).toContain('AI Agent Tester')
      expect(html).toContain('turn(s)')
      expect(html).toContain('Reset Memory')
      expect(html).toContain('Ask agent or test workflow tools')
      expect(html).toContain('Send')
      expect(html).toContain('Remember that our project budget is $45,000')
      expect(html).toContain('Stateful Memory')
      expect(html).toContain('agent-avatar')
    })

    it('renders active AI node tag when single AI node present', () => {
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
      expect(html).toContain('Support Analyst')
    })

    it('renders node select dropdown when multiple AI nodes present', () => {
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
      expect(html).toContain('ai-chat-node-select')
      expect(html).toContain('Agent Alpha')
      expect(html).toContain('Agent Beta')
    })

    it('has api.chatWithAgent and api.getAiMemory defined', async () => {
      const { api } = await import('../api.js')
      expect(typeof api.chatWithAgent).toBe('function')
      expect(typeof api.getAiMemory).toBe('function')
      expect(typeof api.clearAiMemory).toBe('function')
    })
  })
})
