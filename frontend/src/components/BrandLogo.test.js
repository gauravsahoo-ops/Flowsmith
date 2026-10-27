import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { NodeIcon } from './NodeIcons'
import { getBrandLogo } from '../utils/brandLogoResolver'
import manifest from '../generated/brandLogos.json'

describe('Self-hosted brand mark system', () => {
  it('resolves every manifest connector to a local asset', () => {
    for (const key of Object.keys(manifest.logos)) {
      const entry = getBrandLogo({ type: key })
      expect(entry, key).toBeTruthy()
      expect(entry.entry.src).toMatch(/^\/brand-logos\//)
    }
  })

  it('renders a branded plate for a real connector', () => {
    const html = renderToStaticMarkup(React.createElement(NodeIcon, { type: 'salesforce', size: 32 }))
    expect(html).toContain('fs-brand-mark')
    expect(html).toContain('data-brand-key="salesforce"')
    expect(html).toContain('<img')
    expect(html).toContain('/brand-logos/')
  })

  it('keeps protocol and logic nodes on the semantic vector path', () => {
    const html = renderToStaticMarkup(React.createElement(NodeIcon, { type: 'http_request', size: 32 }))
    expect(html).toContain('<svg')
    expect(html).not.toContain('fs-brand-mark')
  })
})
