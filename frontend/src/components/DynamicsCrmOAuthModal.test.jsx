import { describe, it, expect, vi } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import DynamicsCrmOAuthModal from './DynamicsCrmOAuthModal'

describe('DynamicsCrmOAuthModal Component', () => {
  it('renders nothing when isOpen is false', () => {
    const html = renderToStaticMarkup(
      React.createElement(DynamicsCrmOAuthModal, { isOpen: false, onClose: vi.fn() })
    )
    expect(html).toBe('')
  })

  it('renders Microsoft Dynamics 365 modal with tabs and inputs when isOpen is true', () => {
    const html = renderToStaticMarkup(
      React.createElement(DynamicsCrmOAuthModal, {
        isOpen: true,
        onClose: vi.fn(),
        initialData: {
          id: 'cred_dyn_1',
          name: 'Dynamics 365 Production',
          data: {
            instance_url: 'https://contoso.crm.dynamics.com',
            tenant_id: 'common',
            user: 'admin@contoso.onmicrosoft.com',
          },
        },
      })
    )

    // Header & branding
    expect(html).toContain('Connect Microsoft Dynamics 365')
    expect(html).toContain('Microsoft Dataverse Web API v9.2 Integration')

    // Tabs
    expect(html).toContain('OAuth2 (1-Click)')
    expect(html).toContain('Service Principal (S2S)')
    expect(html).toContain('Azure App Setup')

    // Content
    expect(html).toContain('Dynamics 365 Production')
    expect(html).toContain('https://contoso.crm.dynamics.com')
    expect(html).toContain('Interactive Authorization (PKCE)')
    expect(html).toContain('Connected')
    expect(html).toContain('admin@contoso.onmicrosoft.com')
  })
})
