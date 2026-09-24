import { describe, it, expect, vi } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import GoogleOAuthModal from './GoogleOAuthModal'

describe('GoogleOAuthModal Component', () => {
  it('renders nothing when isOpen is false', () => {
    const html = renderToStaticMarkup(
      React.createElement(GoogleOAuthModal, { isOpen: false, onClose: vi.fn(), serviceType: 'google_calendar' })
    )
    expect(html).toBe('')
  })

  it('renders Google Cloud modal with service branding and tabs when isOpen is true', () => {
    const html = renderToStaticMarkup(
      React.createElement(GoogleOAuthModal, {
        isOpen: true,
        serviceType: 'google_sheets',
        onClose: vi.fn(),
        initialData: {
          id: 'cred_goog_123',
          name: 'My Google Sheets',
          data: {
            client_id: '123456789.apps.googleusercontent.com',
            user: 'analyst@company.com',
          },
        },
      })
    )

    // Header & badges
    expect(html).toContain('Edit Google Sheets')
    expect(html).toContain('OAuth 2.0')
    expect(html).toContain('Configure Google Cloud OAuth 2.0 credentials')

    // Tabs
    expect(html).toContain('OAuth Client Credentials')
    expect(html).toContain('Google Cloud Guide')

    // Active connection preview
    expect(html).toContain('analyst@company.com')

    // Action buttons
    expect(html).toContain('Save Configuration')
    expect(html).toContain('Connect Google Sheets')
    expect(html).toContain('Cancel')
  })
})
