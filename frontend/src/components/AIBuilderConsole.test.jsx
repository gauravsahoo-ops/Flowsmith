import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import AIBuilderConsole from './AIBuilderConsole'

describe('AIBuilderConsole (3-Column Production Architecture)', () => {
  const mockStatus = {
    configured: true,
    active: {
      id: 'cred_test_1',
      name: 'OpenRouter Production',
      provider: 'openrouter',
      model: 'z-ai/glm-5.3',
    },
    credentials: [
      {
        id: 'cred_test_1',
        name: 'OpenRouter Production',
        provider: 'openrouter',
        model: 'z-ai/glm-5.3',
      },
    ],
  }

  it('renders the 3-column layout headers and modes', () => {
    const html = renderToStaticMarkup(
      React.createElement(
        MemoryRouter,
        {},
        React.createElement(AIBuilderConsole, {
          statusInfo: mockStatus,
          selectedCredentialId: 'cred_test_1',
          onSelectCredential: () => {},
        })
      )
    )

    // Left Column: Intent & Conversation
    expect(html).toContain('Natural Language Requirements')
    expect(html).toContain('✨ Build')
    expect(html).toContain('🔧 Modify')
    expect(html).toContain('🩹 Repair')
    expect(html).toContain('Model Router:')
    expect(html).toContain('Auto (Task-Based Optimal Routing)')

    // Center Column: Plan & Structure
    expect(html).toContain('Plan &amp; Sequence')
    expect(html).toContain('Blueprint Nodes (0)')

    // Right Column: Context, Capabilities, Validation & Simulation
    expect(html).toContain('Grounded Connectors')
    expect(html).toContain('6-Stage Validation Pipeline')
    expect(html).toContain('Simulation Runner')
    expect(html).toContain('Synthesize &amp; Validate Workflow')
  })
})

