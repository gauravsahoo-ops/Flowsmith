import { describe, it, expect, vi } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import SalesforceOAuthModal from './SalesforceOAuthModal'

describe('SalesforceOAuthModal Component', () => {
  it('renders nothing when isOpen is false', () => {
    const html = renderToStaticMarkup(
      React.createElement(SalesforceOAuthModal, { isOpen: false, onClose: vi.fn() })
    )
    expect(html).toBe('')
  })

  it('renders Obsidian Glass modal with Flowsmith branding and tabs when isOpen is true', () => {
    const html = renderToStaticMarkup(
      React.createElement(SalesforceOAuthModal, {
        isOpen: true,
        onClose: vi.fn(),
        initialData: {
          id: 'cred_123',
          name: 'My Production Salesforce',
          data: {
            client_id: '3MVG9_TEST_CLIENT_ID',
            login_url: 'https://login.salesforce.com',
          },
        },
      })
    )

    // Flowsmith header & badges
    expect(html).toContain('Edit Salesforce Credential')
    expect(html).toContain('OAuth 2.0 PKCE')
    expect(html).toContain('Configure custom Connected App')

    // Tabs
    expect(html).toContain('App Credentials')
    expect(html).toContain('Environment &amp; Scope')
    expect(html).toContain('Security &amp; Details')

    // Initial data
    expect(html).toContain('My Production Salesforce')
    expect(html).toContain('3MVG9_TEST_CLIENT_ID')

    // Action buttons
    expect(html).toContain('Save Credential')
    expect(html).toContain('Cancel')
  })
})
