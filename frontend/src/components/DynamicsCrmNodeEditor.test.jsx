import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import DynamicsCrmNodeEditor from './DynamicsCrmNodeEditor'

describe('DynamicsCrmNodeEditor Suite', () => {
  it('renders resource and operation selection with Dataverse CRM defaults', () => {
    const node = {
      id: 'dynamics_1',
      type: 'dynamics_crm',
      parameters: {
        resource: 'Contact',
        entity: 'contacts',
        operation: 'create',
      },
    }
    const html = renderToStaticMarkup(
      React.createElement(DynamicsCrmNodeEditor, {
        node,
        onParamsChange: () => {},
      })
    )
    expect(html).toContain('Resource')
    expect(html).toContain('Table / Entity Set Name')
    expect(html).toContain('Operation')
    expect(html).toContain('Record Fields')
    expect(html).toContain('Advanced Options')
  })

  it('renders record ID field for update and get operations', () => {
    const node = {
      id: 'dynamics_2',
      type: 'dynamics_crm',
      parameters: {
        resource: 'Account',
        entity: 'accounts',
        operation: 'update',
        record_id: '11111111-2222-3333-4444-555555555555',
        data: { name: 'Contoso Ltd' },
      },
    }
    const html = renderToStaticMarkup(
      React.createElement(DynamicsCrmNodeEditor, {
        node,
        onParamsChange: () => {},
      })
    )
    expect(html).toContain('Record ID (GUID)')
    expect(html).toContain('11111111-2222-3333-4444-555555555555')
    expect(html).toContain('Account Name')
  })

  it('renders alternate key inputs for upsert operation', () => {
    const node = {
      id: 'dynamics_3',
      type: 'dynamics_crm',
      parameters: {
        resource: 'Contact',
        entity: 'contacts',
        operation: 'upsert',
        key_field: 'emailaddress1',
        key_value: 'alex@contoso.com',
      },
    }
    const html = renderToStaticMarkup(
      React.createElement(DynamicsCrmNodeEditor, {
        node,
        onParamsChange: () => {},
      })
    )
    expect(html).toContain('Alternate Key Field')
    expect(html).toContain('Alternate Key Value')
    expect(html).toContain('alex@contoso.com')
  })

  it('renders query parameters when operation is query', () => {
    const node = {
      id: 'dynamics_4',
      type: 'dynamics_crm',
      parameters: {
        resource: 'Opportunity',
        entity: 'opportunities',
        operation: 'query',
        filter: "statecode eq 0",
        top: 25,
      },
    }
    const html = renderToStaticMarkup(
      React.createElement(DynamicsCrmNodeEditor, {
        node,
        onParamsChange: () => {},
      })
    )
    expect(html).toContain('Query Mode')
    expect(html).toContain('OData Filters')
    expect(html).toContain('FetchXML')
    expect(html).toContain('Filter Query ($filter)')
    expect(html).toContain('statecode eq 0')
  })

  it('renders action inputs when operation is execute_action', () => {
    const node = {
      id: 'dynamics_5',
      type: 'dynamics_crm',
      parameters: {
        resource: 'Action',
        operation: 'execute_action',
        action_name: 'WhoAmI',
      },
    }
    const html = renderToStaticMarkup(
      React.createElement(DynamicsCrmNodeEditor, {
        node,
        onParamsChange: () => {},
      })
    )
    expect(html).toContain('Action Name')
    expect(html).toContain('WhoAmI')
    expect(html).toContain('Action Parameters (JSON)')
  })
})
