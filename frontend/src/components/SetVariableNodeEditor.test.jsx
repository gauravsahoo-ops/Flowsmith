import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import SetVariableNodeEditor from './SetVariableNodeEditor'

describe('SetVariableNodeEditor Suite', () => {
  it('renders scope options for workspace and workflow runtime', () => {
    const node = {
      id: 'set_var_1',
      type: 'set_variable',
      parameters: {
        scope: 'workspace',
        variables: [{ key: 'API_KEY', value: '12345', type: 'string' }],
      },
    }
    const html = renderToStaticMarkup(
      React.createElement(SetVariableNodeEditor, {
        node,
        onParamsChange: () => {},
      })
    )
    expect(html).toContain('Variable Storage Scope')
    expect(html).toContain('Workspace Persistent')
    expect(html).toContain('Workflow Runtime ($env)')
    expect(html).toContain('API_KEY')
    expect(html).toContain('12345')
    expect(html).toContain('{{ $env.VAR_NAME }}')
  })

  it('renders variables table with type options', () => {
    const node = {
      id: 'set_var_2',
      type: 'set_variable',
      parameters: {
        scope: 'workflow',
        variables: [
          { key: 'COUNT', value: '42', type: 'number' },
          { key: 'USER_OBJ', value: '{"id": 1}', type: 'json' },
        ],
      },
    }
    const html = renderToStaticMarkup(
      React.createElement(SetVariableNodeEditor, {
        node,
        onParamsChange: () => {},
      })
    )
    expect(html).toContain('COUNT')
    expect(html).toContain('42')
    expect(html).toContain('USER_OBJ')
    expect(html).toContain('+ Add Another Variable')
  })
})
