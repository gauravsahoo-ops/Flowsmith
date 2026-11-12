import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import DynamicNodeConfigPanel from './DynamicNodeConfigPanel'
import { buildOperationSearchOptions } from '../../utils/operationOptions'

describe('DynamicNodeConfigPanel Suite', () => {
  const mockNode = {
    id: 'node-1',
    type: 'mssql',
    parameters: {
      operation: 'query',
      query: 'SELECT * FROM Users',
    },
    credentials: {
      mssql: 'cred-123',
    },
    settings: {
      timeout_seconds: 30,
    },
  }

  const mockMeta = {
    display_name: 'Microsoft SQL Server',
    credential_types: ['mssql'],
    operations: {
      query: {
        display_name: 'Execute Query',
        description: 'Run SQL Query against MSSQL',
        idempotency: 'idempotent',
        retryable: true,
        properties: ['query', 'parameters'],
      },
      insert: {
        display_name: 'Insert Row',
        description: 'Insert new row into table',
        idempotency: 'non_idempotent',
        retryable: false,
        properties: ['table', 'data'],
      },
    },
    parameters_schema: {
      type: 'object',
      properties: {
        operation: {
          type: 'string',
          enum: ['query', 'insert'],
        },
        query: {
          type: 'string',
          title: 'SQL Query',
        },
        parameters: {
          type: 'array',
          title: 'Parameters',
        },
        table: {
          type: 'string',
          title: 'Table Name',
        },
        data: {
          type: 'object',
          title: 'Row Data',
        },
      },
    },
  }

  const mockCredentials = [
    {
      id: 'cred-123',
      name: 'Production MSSQL DB',
      type: 'mssql',
    },
  ]

  it('renders operation selector with correct active value and badges', () => {
    const html = renderToStaticMarkup(
      React.createElement(DynamicNodeConfigPanel, {
        node: mockNode,
        meta: mockMeta,
        onParamsChange: () => {},
        credentials: mockCredentials,
      })
    )

    expect(html).toContain('Operation')
    expect(html).toContain('Execute Query')
    expect(html).toContain('Idempotent')
    expect(html).toContain('Auto-Retry')
  })

  it('shows query field for query op and filters unselected operation fields', () => {
    const html = renderToStaticMarkup(
      React.createElement(DynamicNodeConfigPanel, {
        node: mockNode,
        meta: mockMeta,
        onParamsChange: () => {},
        credentials: mockCredentials,
      })
    )

    expect(html).toContain('SQL Query')
    expect(html).toContain('SELECT * FROM Users')
    // Table Name should not be rendered for query operation
    expect(html).not.toContain('Table Name')
  })

  it('renders credential picker with connected status', () => {
    const html = renderToStaticMarkup(
      React.createElement(DynamicNodeConfigPanel, {
        node: mockNode,
        meta: mockMeta,
        onParamsChange: () => {},
        credentials: mockCredentials,
      })
    )

    expect(html).toContain('Credential')
    expect(html).toContain('Production MSSQL DB')
    expect(html).toContain('Connected')
  })

  it('renders advanced options accordion and step test button', () => {
    const html = renderToStaticMarkup(
      React.createElement(DynamicNodeConfigPanel, {
        node: mockNode,
        meta: mockMeta,
        onParamsChange: () => {},
        credentials: mockCredentials,
        onExecuteStep: async () => {},
      })
    )

    expect(html).toContain('Advanced Options')
    expect(html).toContain('Test Step')
  })

  it('renders output preview when last execution data exists', () => {
    const html = renderToStaticMarkup(
      React.createElement(DynamicNodeConfigPanel, {
        node: {
          ...mockNode,
          last_execution: {
            status: 'success',
            output: { count: 42, rows: [{ id: 1, name: 'Alice' }] },
          },
        },
        meta: mockMeta,
        onParamsChange: () => {},
        credentials: mockCredentials,
      })
    )

    expect(html).toContain('Last Output Preview')
    expect(html).toContain('&quot;count&quot;: 42')
    expect(html).toContain('&quot;Alice&quot;')
  })

  it('never fabricates a preview result when no execution endpoint is connected', () => {
    // P0-4: the panel previously invented
    // { status: 'success', simulated: true, output: [{ status: 'verified' }] }
    // on click. It must not do so in any code path.
    const html = renderToStaticMarkup(
      React.createElement(DynamicNodeConfigPanel, {
        node: mockNode,
        meta: mockMeta,
        onParamsChange: () => {},
        credentials: mockCredentials,
        // NOTE: no onExecuteStep prop on purpose
      })
    )

    expect(html).toContain('disabled')
    expect(html).not.toContain('simulated')
    expect(html).not.toContain('Step preview validated')
    expect(html).not.toContain('verified')
  })

  it('does not mutate node.settings during render', () => {
    // P0-1: the advanced section previously assigned node.settings.<key> in its
    // onChange, which bypasses the store. Render must never touch node.settings;
    // changes flow through onSettingsChange instead.
    const before = JSON.stringify(mockNode.settings)
    const html = renderToStaticMarkup(
      React.createElement(DynamicNodeConfigPanel, {
        node: mockNode,
        meta: mockMeta,
        onParamsChange: () => {},
        onSettingsChange: () => {},
        credentials: mockCredentials,
      })
    )

    expect(html).toContain('Advanced Options')
    expect(html).toContain('Test Step')
    expect(JSON.stringify(mockNode.settings)).toBe(before)
    expect(mockNode.settings).toEqual({ timeout_seconds: 30 })
  })

  it('builds operation search aliases that match "HubSpot methods"', () => {
    const options = buildOperationSearchOptions(
      ['search', 'list_object_types'],
      {
        search: { display_name: 'Search Record', description: 'Find records by property value.' },
        list_object_types: { display_name: 'List Object Types', description: 'Discover custom objects.' },
      },
      'HubSpot',
    )
    const haystack = options.map((opt) => [
      opt.label,
      opt.description,
      ...(opt.aliases || []),
    ].join(' ').toLowerCase())

    expect(haystack.some((text) => text.includes('hubspot') && text.includes('methods'))).toBe(true)
  })

  it('renders HubSpot operation and object controls as searchable selects', () => {
    const hubspotMeta = {
      display_name: 'HubSpot',
      credential_types: ['hubspot'],
      operations: {
        search: {
          display_name: 'Search Record',
          description: 'Find records by property value.',
          properties: ['object_type', 'search_field', 'search_value'],
        },
      },
      parameters_schema: { type: 'object', properties: {} },
      fields: [
        { name: 'operation', title: 'Operation', type: 'select', required: true },
        { name: 'object_type', title: 'Object type', type: 'string', required: true, default: 'contacts' },
        { name: 'search_field', title: 'Search property', type: 'string' },
        { name: 'search_value', title: 'Search value', type: 'string' },
      ],
    }
    const html = renderToStaticMarkup(
      React.createElement(DynamicNodeConfigPanel, {
        node: {
          id: 'hs-1',
          type: 'hubspot',
          parameters: { operation: 'search', object_type: 'contacts', search_field: 'email', search_value: 'a@b.com' },
          credentials: { hubspot: 'cred-hs' },
          settings: {},
        },
        meta: hubspotMeta,
        onParamsChange: () => {},
        credentials: [{ id: 'cred-hs', name: 'HubSpot account', type: 'hubspot' }],
      })
    )

    expect(html).toContain('searchable-select')
    expect(html).toContain('Search Record')
    expect(html).toContain('data-testid="dncp-select-object_type"')
    expect(html).not.toContain('id="dncp-op-select"')
  })
})
