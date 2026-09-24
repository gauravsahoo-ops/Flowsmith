import { describe, it, expect, vi } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import HubSpotOAuthModal from './HubSpotOAuthModal'

describe('HubSpotOAuthModal Component', () => {
  it('renders nothing when isOpen is false', () => {
    const html = renderToStaticMarkup(
      React.createElement(HubSpotOAuthModal, { isOpen: false, onClose: vi.fn() })
    )
    expect(html).toBe('')
  })

  it('renders Obsidian Glass modal with HubSpot branding and tabs when isOpen is true', () => {
    const html = renderToStaticMarkup(
      React.createElement(HubSpotOAuthModal, {
        isOpen: true,
        onClose: vi.fn(),
        initialData: {
          id: 'cred_hs_123',
          name: 'My HubSpot CRM',
          data: {
            client_id: 'hs_client_id_test',
            user: 'user@example.com',
            hub_id: '12345678',
          },
        },
      })
    )

    // Header & badges
    expect(html).toContain('Edit HubSpot Credential')
    expect(html).toContain('OAuth 2.0')
    expect(html).toContain('Configure custom HubSpot Developer App')

    // Tabs
    expect(html).toContain('OAuth App Credentials')
    expect(html).toContain('Private App Token')
    expect(html).toContain('Setup Guide')

    // Active connection preview
    expect(html).toContain('user@example.com')
    expect(html).toContain('12345678')

    // Buttons
    expect(html).toContain('Save Configuration')
    expect(html).toContain('Connect with HubSpot')
    expect(html).toContain('Cancel')
  })
})
