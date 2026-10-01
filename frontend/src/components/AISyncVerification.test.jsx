import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import SmithDrawer from './SmithDrawer'
import AICopilotModal from './AICopilotModal'
import AIChatDrawer from './AIChatDrawer'
import { api } from '../api'

describe('AI Copilot, Agents Tab, and Smith Multi-Provider Synchronization', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('SmithDrawer syncs with multi-provider LLM status and displays active provider and model', async () => {
    vi.spyOn(api, 'aiStatus').mockResolvedValue({
      configured: true,
      active: {
        id: 'cred_534988e132d5',
        name: 'OpenRouter Credential',
        provider: 'openrouter',
        model: 'z-ai/glm-5.3',
      },
      credentials: [
        {
          id: 'cred_534988e132d5',
          name: 'OpenRouter Credential',
          provider: 'openrouter',
          model: 'z-ai/glm-5.3',
        },
      ],
    })

    const html = renderToStaticMarkup(
      React.createElement(SmithDrawer, {
        isOpen: true,
        onClose: () => {},
      })
    )

    expect(html).toContain('Smith')
    expect(html).toContain('AI COPILOT')
    expect(html).toContain('Ready')
    expect(html).toContain('Chat &amp; Tools')
    expect(html).toContain('Debug &amp; Analyze')
    expect(html).not.toContain('Workflow Builder')
  })

  it('AICopilotModal delegates to SmithDrawer in chat mode', () => {
    const html = renderToStaticMarkup(
      React.createElement(AICopilotModal, {
        isOpen: true,
        onClose: () => {},
      })
    )
    expect(html).toContain('Chat &amp; Tools')
  })

  it('AIChatDrawer delegates to SmithDrawer in chat mode', () => {
    const html = renderToStaticMarkup(
      React.createElement(AIChatDrawer, {
        isOpen: true,
        onClose: () => {},
      })
    )
    expect(html).toContain('Chat &amp; Tools')
  })

  it('generateWorkflow API call includes credentialId option', async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: { get: () => 'application/json' },
      text: async () =>
        JSON.stringify({
          data: {
            workflow: { nodes: [], connections: [] },
            validation: { errors: [], warnings: [] },
          },
        }),
    })
    global.fetch = fetchSpy

    await api.generateWorkflow('Build a lead pipeline', {
      credentialId: 'cred_534988e132d5',
    })

    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining('/api/ai/generate-workflow'),
      expect.objectContaining({
        method: 'POST',
        body: expect.stringContaining('"credential_id":"cred_534988e132d5"'),
      })
    )
  })

  it('chatWithAgent API call sends credential_id and model overrides', async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: { get: () => 'application/json' },
      text: async () =>
        JSON.stringify({
          data: {
            response: 'Workflow analyzed.',
            trace: [],
            tools_used: [],
            model: 'z-ai/glm-5.3',
            provider: 'openrouter',
          },
        }),
    })
    global.fetch = fetchSpy

    const payload = {
      message: 'Analyze active canvas',
      session_id: 'test_session',
      credential_id: 'cred_534988e132d5',
      model: 'z-ai/glm-5.3',
    }

    await api.chatWithAgent(payload)

    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining('/api/ai/chat'),
      expect.objectContaining({
        method: 'POST',
        body: expect.stringContaining('"credential_id":"cred_534988e132d5"'),
      })
    )
  })
})
