import { describe, it, expect, beforeEach } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import LLMCredentialModal from './LLMCredentialModal'
import AINodeEditor from './AINodeEditor'
import { useCredentialStore } from '../stores/credentialStore'

describe('LLM Multi-Provider Platform UI Suite', () => {
  beforeEach(() => {
    useCredentialStore.setState({
      credentials: [
        {
          id: 'cred-openai-1',
          name: 'Production OpenAI',
          type: 'llm',
          data: {
            provider: 'openai',
            selected_model: 'gpt-4o',
          },
        },
        {
          id: 'cred-anthropic-1',
          name: 'Anthropic Claude Key',
          type: 'llm',
          data: {
            provider: 'anthropic',
            selected_model: 'claude-3-5-sonnet-20241022',
          },
        },
      ],
      types: [
        { type: 'llm', name: 'LLM Multi-Provider', auth_method: 'API Key' },
      ],
    })
  })

  describe('LLMCredentialModal Component', () => {
    it('renders null when open is false', () => {
      const html = renderToStaticMarkup(
        React.createElement(LLMCredentialModal, {
          open: false,
          onClose: () => {},
        })
      )
      expect(html).toBe('')
    })

    it('renders modal dialog with 4 core configuration steps when open', () => {
      const html = renderToStaticMarkup(
        React.createElement(LLMCredentialModal, {
          open: true,
          onClose: () => {},
        })
      )
      expect(html).toContain('Create LLM Provider Credential')
      expect(html).toContain('1. LLM Provider')
      expect(html).toContain('2. Credentials &amp; Authentication')
      expect(html).toContain('Test Connection')
      expect(html).toContain('Fetch Models')
      expect(html).toContain('3. Preferred Model')
      expect(html).toContain('4. Credential Name')
      expect(html).toContain('Save Credential')
    })

    it('renders category filter buttons', () => {
      const html = renderToStaticMarkup(
        React.createElement(LLMCredentialModal, {
          open: true,
          onClose: () => {},
        })
      )
      expect(html).toContain('All')
      expect(html).toContain('Major Providers')
      expect(html).toContain('LLM Gateways')
      expect(html).toContain('Inference Providers')
    })

    it('renders pre-populated values when editing existing credential', () => {
      const existing = {
        id: 'cred-openai-1',
        name: 'Production OpenAI',
        type: 'llm',
        data: {
          provider: 'openai',
          api_key: 'sk-test-12345',
          selected_model: 'gpt-4o',
        },
      }
      const html = renderToStaticMarkup(
        React.createElement(LLMCredentialModal, {
          open: true,
          initialData: existing,
          onClose: () => {},
        })
      )
      expect(html).toContain('Configure LLM Provider Credential')
      expect(html).toContain('Production OpenAI')
    })
  })

  describe('AINodeEditor Component', () => {
    const mockNode = {
      id: 'ai_node_1',
      type: 'ai',
      parameters: {
        provider: 'openai',
        model: 'gpt-4o',
        prompt: 'Analyze sentiment: {{ $json.text }}',
        system_prompt: 'You are an enterprise AI assistant.',
        temperature: 0.7,
        max_tokens: 1024,
      },
      credentials: {
        llm: 'cred-openai-1',
      },
    }

    it('renders all AI node configuration fields', () => {
      const html = renderToStaticMarkup(
        React.createElement(AINodeEditor, {
          node: mockNode,
          onParamsChange: () => {},
          credentials: useCredentialStore.getState().credentials,
          onCredentialChange: () => {},
        })
      )
      expect(html).toContain('LLM Provider')
      expect(html).toContain('Credential')
      expect(html).toContain('Model')
      expect(html).toContain('System Instructions')
      expect(html).toContain('Prompt')
      expect(html).toContain('Temperature')
      expect(html).toContain('Max Output Tokens')
      expect(html).toContain('Advanced Settings')
    })

    it('renders prompt with template expression support hint', () => {
      const html = renderToStaticMarkup(
        React.createElement(AINodeEditor, {
          node: mockNode,
          onParamsChange: () => {},
          credentials: useCredentialStore.getState().credentials,
          onCredentialChange: () => {},
        })
      )
      expect(html).toContain('{{ $json.fieldName }}')
      expect(html).toContain('Analyze sentiment: {{ $json.text }}')
    })

    it('renders provider and credential matching current node selection', () => {
      const html = renderToStaticMarkup(
        React.createElement(AINodeEditor, {
          node: mockNode,
          onParamsChange: () => {},
          credentials: useCredentialStore.getState().credentials,
          onCredentialChange: () => {},
        })
      )
      expect(html).toContain('Production OpenAI')
      expect(html).toContain('+ Create New LLM Credential')
    })
  })
})
