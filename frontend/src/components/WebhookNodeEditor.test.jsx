import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import WebhookNodeEditor from './WebhookNodeEditor'

describe('WebhookNodeEditor Component', () => {
  it('renders endpoint configuration with path and method', () => {
    const node = {
      id: 'webhook_1',
      parameters: {
        path: 'stripe-event',
        method: 'POST',
        respond: false,
      },
    }
    const html = renderToStaticMarkup(
      React.createElement(WebhookNodeEditor, {
        node,
        onParamsChange: () => {},
        workflowId: 'wf-123',
      })
    )

    expect(html).toContain('stripe-event')
    expect(html).toContain('POST')
    expect(html).toContain('Public Webhook Endpoint')
    expect(html).toContain('Listen for Test Event')
    expect(html).toContain('Dispatch Test Webhook')
    expect(html).toContain('cURL &amp; Code Snippet Generator')
  })

  it('renders GitLab provider registration fields', () => {
    const node = {
      id: 'gitlab_1',
      type: 'gitlab_trigger',
      parameters: {
        path: 'gitlab-events',
        method: 'POST',
      },
    }
    const html = renderToStaticMarkup(
      React.createElement(WebhookNodeEditor, {
        node,
        onParamsChange: () => {},
        workflowId: 'wf-789',
      })
    )

    expect(html).toContain('GitLab Provider Webhook')
    expect(html).toContain('Project (group/project)')
    expect(html).toContain('Events (comma-separated)')
    expect(html).toContain('Webhook token (optional; generated if left blank)')
    expect(html).toContain('Register with GitLab')
  })

  it('renders synchronous response checkbox and snippet tabs', () => {
    const node = {
      id: 'webhook_2',
      parameters: {
        path: 'orders',
        method: 'GET',
        respond: true,
      },
    }
    const html = renderToStaticMarkup(
      React.createElement(WebhookNodeEditor, {
        node,
        onParamsChange: () => {},
        workflowId: 'wf-456',
      })
    )

    expect(html).toContain('orders')
    expect(html).toContain('Wait for execution and return synchronous response')
    expect(html).toContain('JavaScript (Fetch)')
    expect(html).toContain('Python (Requests)')
  })
})
