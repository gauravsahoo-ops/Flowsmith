import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import OutputPanel from './OutputPanel'

describe('OutputPanel Error & Server Response Suite', () => {
  it('renders HTTP status code, URL, and server response body when error details are present', () => {
    const error = {
      message: 'HTTP request failed with status 401: Unauthorized',
      code: 'HTTP_ERROR',
      details: {
        statusCode: 401,
        url: 'https://api.example.com/v1/users',
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ error: 'invalid_token', error_description: 'Bearer token expired' }),
      },
    }

    const html = renderToStaticMarkup(
      React.createElement(OutputPanel, {
        status: 'failed',
        executing: false,
        error,
        nodeId: 'node_1',
        nodeLabel: 'HTTP Request',
        onAutoRepair: () => {},
        onExecuteStep: () => {},
      })
    )

    expect(html).toContain('HTTP 401')
    expect(html).toContain('HTTP request failed with status 401: Unauthorized')
    expect(html).toContain('https://api.example.com/v1/users')
    expect(html).toContain('GET')
    expect(html).toContain('Server Response Body')
    expect(html).toContain('invalid_token')
    expect(html).toContain('Bearer token expired')
    expect(html).toContain('⚡ AI Auto-Repair')
    expect(html).toContain('🔄 Re-test')
  })

  it('renders standard ErrorState when non-HTTP error is passed', () => {
    const error = {
      message: 'Division by zero in formula expression',
      code: 'EVAL_ERROR',
    }

    const html = renderToStaticMarkup(
      React.createElement(OutputPanel, {
        status: 'failed',
        executing: false,
        error,
        nodeId: 'node_2',
        nodeLabel: 'Code Node',
        onAutoRepair: () => {},
      })
    )

    expect(html).toContain('Execution Failed')
    expect(html).toContain('Division by zero in formula expression')
    expect(html).toContain('⚡ Flowsmith AI Self-Healing Diagnostic')
  })

  it('renders JSON error payload when view is json', () => {
    // Set sessionStorage view to json
    if (typeof sessionStorage !== 'undefined') {
      sessionStorage.setItem('op_view_node_json', 'json')
    }

    const error = {
      message: 'Salesforce authentication failed: [401] 401: Unauthorized',
      code: 'AUTH_FAILED',
      details: {
        statusCode: 401,
        url: 'https://login.salesforce.com/services/oauth2/token',
      },
    }

    const html = renderToStaticMarkup(
      React.createElement(OutputPanel, {
        status: 'failed',
        executing: false,
        error,
        nodeId: 'node_json',
        nodeLabel: 'Salesforce',
        initialView: 'json',
      })
    )

    expect(html).toContain('Error Output JSON')
    expect(html).toContain('AUTH_FAILED')
    expect(html).toContain('Salesforce authentication failed')
  })

  it('renders structured error table when view is table', () => {
    const error = {
      message: 'Salesforce connection timeout',
      code: 'TIMEOUT',
      details: {
        statusCode: 504,
        url: 'https://login.salesforce.com/services/data/v63.0',
        method: 'GET',
      },
    }

    const html = renderToStaticMarkup(
      React.createElement(OutputPanel, {
        status: 'failed',
        executing: false,
        error,
        nodeId: 'node_table',
        nodeLabel: 'Salesforce',
        initialView: 'table',
      })
    )

    expect(html).toContain('Structured Error Fields')
    expect(html).toContain('Error Message')
    expect(html).toContain('Salesforce connection timeout')
  })
})
