import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import AICopilotModal from './AICopilotModal'
import AIChatDrawer from './AIChatDrawer'

describe('AI Components Suite', () => {
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
  })

  describe('AIChatDrawer', () => {
    it('renders null when closed', () => {
      const html = renderToStaticMarkup(
        React.createElement(AIChatDrawer, { isOpen: false, onClose: () => {} })
      )
      expect(html).toBe('')
    })

    it('renders drawer header and controls when open', () => {
      const html = renderToStaticMarkup(
        React.createElement(AIChatDrawer, {
          isOpen: true,
          onClose: () => {},
          nodes: [],
          selectedNodeId: null,
          workflow: { id: 'wf_test', name: 'Test Workflow' },
        })
      )
      expect(html).toContain('AI Agent Tester')
      expect(html).toContain('Reset Memory')
      expect(html).toContain('Ask agent or test workflow tools')
      expect(html).toContain('Send')
      expect(html).toContain('Try asking:')
      expect(html).toContain('Stateful Memory')
      expect(html).toContain('agent-avatar')
    })
  })
})
