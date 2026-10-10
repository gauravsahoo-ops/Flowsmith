import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import OAuthCallbackPage from './OAuthCallbackPage'

describe('OAuthCallbackPage Component', () => {
  let originalWindow

  beforeEach(() => {
    originalWindow = globalThis.window
    globalThis.window = {
      location: {
        origin: 'http://localhost:5173',
        pathname: '/oauth/callback',
        search: '?provider=dynamics_crm&ok=1',
        hash: '',
      },
      history: {
        replaceState: vi.fn(),
      },
      close: vi.fn(),
      opener: {
        postMessage: vi.fn(),
      },
    }
  })

  afterEach(() => {
    if (originalWindow === undefined) {
      delete globalThis.window
    } else {
      globalThis.window = originalWindow
    }
  })

  it('renders connection successful for dynamics_crm with ok=1', () => {
    globalThis.window.location.search = '?provider=dynamics_crm&ok=1'
    const html = renderToStaticMarkup(React.createElement(OAuthCallbackPage))
    expect(html).toContain('Connection successful')
    expect(html).toContain('Microsoft Dynamics 365 connected')
  })

  it('renders connection successful for boolean ok=true', () => {
    globalThis.window.location.search = '?provider=dynamics_crm&ok=true'
    const html = renderToStaticMarkup(React.createElement(OAuthCallbackPage))
    expect(html).toContain('Connection successful')
    expect(html).toContain('Microsoft Dynamics 365 connected')
  })

  it('renders connection successful for google_calendar with ok=1', () => {
    globalThis.window.location.search = '?provider=google_calendar&ok=1'
    const html = renderToStaticMarkup(React.createElement(OAuthCallbackPage))
    expect(html).toContain('Connection successful')
    expect(html).toContain('Google Calendar connected')
  })

  it('renders connection failed when ok=0 with error message', () => {
    globalThis.window.location.search = '?provider=dynamics_crm&ok=0&error=Access%20denied'
    const html = renderToStaticMarkup(React.createElement(OAuthCallbackPage))
    expect(html).toContain('Connection failed')
    expect(html).toContain('Access denied')
  })
})
