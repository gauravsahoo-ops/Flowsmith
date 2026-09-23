import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import SmithDrawer from './SmithDrawer'
import TopBar from './TopBar'

describe('SmithDrawer Logo Suite', () => {
  it('renders default Flowsmith brand mark in the drawer header and not the lightning bolt', () => {
    const html = renderToStaticMarkup(
      React.createElement(SmithDrawer, {
        isOpen: true,
        onClose: () => {},
        nodes: [],
        edges: [],
      })
    )

    // Verify FlowsmithBrandMark is rendered in the header
    expect(html).toContain('smith-header-logo')
    expect(html).toContain('fs-brand-bg')
    expect(html).toContain('fs-brand-glow')

    // Verify header does not contain lightning bolt inside smith-header-logo
    const headerLogoHtml = html.match(/<div class="[^"]*smith-header-logo[^"]*">([\s\S]*?)<\/div>/)?.[1]
    expect(headerLogoHtml).toBeDefined()
    expect(headerLogoHtml).not.toContain('M13 2L3 14h9l-1 8 10-12h-9l1-8z')
    expect(headerLogoHtml).toContain('fs-brand-bg')

    // Verify welcome avatar and message avatar render Flowsmith brand mark instead of raw "S"
    expect(html).toContain('smith-avatar-circle')
    expect(html).not.toContain('<div class="smith-avatar-circle">S</div>')
  })

  it('renders default Flowsmith brand mark in the TopBar Smith button and removes ⚡', () => {
    const html = renderToStaticMarkup(
      React.createElement(TopBar, {
        workflow: { id: 'wf_1', name: 'Test Flow' },
        onOpenSmith: () => {},
      })
    )

    // Verify TopBar has topbar-smith-btn with FlowsmithBrandMark
    expect(html).toContain('topbar-smith-btn')
    expect(html).not.toContain('⚡ Smith')
    expect(html).toContain('<span>Smith</span>')
    expect(html).toContain('fs-brand-bg')
  })
})
