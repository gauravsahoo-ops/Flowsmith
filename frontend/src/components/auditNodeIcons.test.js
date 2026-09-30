import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { NodeIcon } from './NodeIcons'
import catalogData from '../all_catalog_items.json'

const FALLBACK_PATH = 'M19.4 15a1.65'

describe('Comprehensive Node & Connector Logo/Icon Realness Audit', () => {
  const allConnectors = Array.from(new Set([...catalogData.connectors, ...catalogData.connector_nodes]))
  const allBuiltins = catalogData.builtins
  const allCredentials = catalogData.credentials

  const results = {
    connectorsWithRealLogos: [],
    connectorsWithFallback: [],
    builtinsWithRealIcons: [],
    builtinsWithFallback: [],
    credentialsWithRealLogos: [],
    credentialsWithFallback: [],
  }

  it('audits all connectors and connector node types', () => {
    const details = []
    for (const key of allConnectors) {
      const el = React.createElement(NodeIcon, { type: key, size: 32 })
      const html = renderToStaticMarkup(el)
      const isFallback = html.includes(FALLBACK_PATH) || html.includes('<span')

      if (isFallback) {
        results.connectorsWithFallback.push(key)
      } else {
        results.connectorsWithRealLogos.push(key)
      }
      details.push({ key, isFallback, preview: html.slice(0, 70) })
    }

    console.log(`\n=== CONNECTOR LOGOS AUDIT (${allConnectors.length} total) ===`)
    console.log(`Real dedicated SVG brand logos: ${results.connectorsWithRealLogos.length}`)
    console.log(`Fallback / generic icon:        ${results.connectorsWithFallback.length}`)
    expect(results.connectorsWithFallback).toEqual([])
  })

  it('audits all built-in flow node types', () => {
    for (const key of allBuiltins) {
      const el = React.createElement(NodeIcon, { type: key, size: 32 })
      const html = renderToStaticMarkup(el)
      const isFallback = html.includes(FALLBACK_PATH) || html.includes('<span')

      if (isFallback) {
        results.builtinsWithFallback.push(key)
      } else {
        results.builtinsWithRealIcons.push(key)
      }
    }

    expect(results.builtinsWithFallback).toEqual([])
  })

  it('audits all credential types', () => {
    for (const key of allCredentials) {
      const el = React.createElement(NodeIcon, { type: key, size: 32 })
      const html = renderToStaticMarkup(el)
      const isFallback = html.includes(FALLBACK_PATH) || html.includes('<span')

      if (isFallback) {
        results.credentialsWithFallback.push(key)
      } else {
        results.credentialsWithRealLogos.push(key)
      }
    }

    expect(results.credentialsWithFallback).toEqual([])
  })
})
