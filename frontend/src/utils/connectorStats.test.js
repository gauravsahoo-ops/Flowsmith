import { describe, expect, it } from 'vitest'
import { connectorSummaryText, summarizeConnectors } from './connectorStats'

describe('connectorStats', () => {
  it('separates native, generated, and catalog-only connectors', () => {
    const summary = summarizeConnectors([
      { connector_key: 'salesforce', metadata: {} },
      { connector_key: 'httpbin', metadata: { source: 'openapi-import' } },
      {
        connector_key: 'active_campaign',
        metadata: { implementation: 'catalog_only', requires_endpoint: true },
      },
    ])

    expect(summary).toEqual({ total: 3, native: 1, generated: 1, catalogOnly: 1 })
    expect(connectorSummaryText(summary)).toContain('3 registered names')
    expect(connectorSummaryText(summary)).toContain('1 catalog-only')
  })

  it('does not count missing connectors', () => {
    expect(summarizeConnectors([null, undefined])).toEqual({
      total: 0,
      native: 0,
      generated: 0,
      catalogOnly: 0,
    })
    expect(connectorSummaryText({ total: 0 })).toMatch(/loading/i)
  })
})
