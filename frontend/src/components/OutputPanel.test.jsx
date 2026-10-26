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
    expect(html).toContain('AI Auto-Repair')
    expect(html).toContain('Re-test')
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
    expect(html).toContain('Flowsmith AI Self-Healing Diagnostic')
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

  it('does not count the preview truncation marker as a record', () => {
    const records = Array.from({ length: 50 }, (_, index) => ({ id: index + 1 }))
    const data = {
      main: [{
        summary: { total_parsed: 282 },
        records: [
          ...records,
          {
            _truncated: true,
            _total_count: 282,
            _omitted: 232,
            _note: '... and 232 more items (282 total).',
          },
        ],
        rows: records,
      }],
    }

    const html = renderToStaticMarkup(
      React.createElement(OutputPanel, {
        status: 'success',
        executing: false,
        data,
        nodeId: 'node_preview',
        nodeLabel: 'CSV Parser',
        executionId: 'exec_preview',
        initialView: 'schema',
        onLoadFullOutput: async () => null,
      })
    )

    expect(html).toContain('Preview: showing 50 of 282 records.')
    expect(html).toContain('Load all 282')
    expect(html).toContain('array[50]')
    expect(html).not.toContain('array[51]')
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
