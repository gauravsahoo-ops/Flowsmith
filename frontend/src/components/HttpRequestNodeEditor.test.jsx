import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import HttpRequestNodeEditor from './HttpRequestNodeEditor'

describe('HttpRequestNodeEditor Suite', () => {
  it('renders direct authorization and authentication options', () => {
    const node = {
      id: 'http_1',
      type: 'http_request',
      parameters: {
        method: 'GET',
        url: 'https://api.example.com/test',
        authentication: 'none',
      },
    }
    const html = renderToStaticMarkup(
      React.createElement(HttpRequestNodeEditor, {
        node,
        onParamsChange: () => {},
      })
    )
    expect(html).toContain('Bearer Token (Direct Authorization Header)')
    expect(html).toContain('Custom Header / API Key (Authorization)')
    expect(html).toContain('Basic Auth (Direct)')
    expect(html).toContain('Predefined Credential Type (Saved)')
    expect(html).toContain('Generic Credential Type (Saved)')
  })

  it('renders direct Bearer Token card when auth_type is bearer', () => {
    const node = {
      id: 'http_2',
      type: 'http_request',
      parameters: {
        method: 'POST',
        url: 'https://api.example.com/data',
        authentication: 'generic',
        auth_type: 'bearer',
        auth_token: 'secret_jwt_token',
      },
    }
    const html = renderToStaticMarkup(
      React.createElement(HttpRequestNodeEditor, {
        node,
        onParamsChange: () => {},
      })
    )
    expect(html).toContain('Sends direct header:')
    expect(html).toContain('Authorization: Bearer &lt;token&gt;')
    expect(html).toContain('Bearer Token')
    expect(html).toContain('secret_jwt_token')
  })

  it('renders Quick Add header presets and header datalist', () => {
    const node = {
      id: 'http_3',
      type: 'http_request',
      parameters: {
        method: 'GET',
        url: 'https://api.example.com/data',
        sendHeaders: true,
        headerParameters: [
          { name: 'Authorization', value: 'Bearer token_123' },
        ],
      },
    }
    const html = renderToStaticMarkup(
      React.createElement(HttpRequestNodeEditor, {
        node,
        onParamsChange: () => {},
      })
    )
    expect(html).toContain('🔑 + Authorization Header')
    expect(html).toContain('+ Content-Type: JSON')
    expect(html).toContain('+ Accept: JSON')
    expect(html).toContain('id="fs-header-datalist"')
    expect(html).toContain('value="Authorization"')
    expect(html).toContain('🔑 Auth')
    expect(html).toContain('Key-Value Headers')
  })

  it('renders segmented control for query parameters and headers', () => {
    const node = {
      id: 'http_4',
      type: 'http_request',
      parameters: {
        method: 'GET',
        url: 'https://api.example.com/data',
        sendQuery: true,
        sendHeaders: true,
      },
    }
    const html = renderToStaticMarkup(
      React.createElement(HttpRequestNodeEditor, {
        node,
        onParamsChange: () => {},
      })
    )
    expect(html).toContain('Key-Value Parameters')
    expect(html).toContain('Query JSON / Expression')
    expect(html).toContain('Key-Value Headers')
    expect(html).toContain('Headers JSON / Expression')
  })
})
