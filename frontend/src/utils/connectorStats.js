/**
 * Connector registry counts, in one place.
 *
 * The API exposes all connector definitions in `/api/connectors`. A connector
 * is one of:
 *   - native: hand-written vendor-specific integration
 *   - generated: generated from an OpenAPI description
 *   - catalog-only: generic HTTP adapter from the reference inventory
 *
 * Catalog-only entries are not equivalent to native integrations.
 */
export function summarizeConnectors(connectors = []) {
  const summary = { total: 0, native: 0, generated: 0, catalogOnly: 0 }

  for (const connector of connectors) {
    if (!connector) continue
    summary.total += 1
    const metadata = connector.metadata || {}

    if (metadata.implementation === 'catalog_only') {
      summary.catalogOnly += 1
    } else if (metadata.source === 'openapi-import') {
      summary.generated += 1
    } else {
      summary.native += 1
    }
  }

  return summary
}

export function connectorSummaryText(summary) {
  if (!summary?.total) return 'Connector catalog is loading.'
  return `${summary.total} registered names: ${summary.native} native, ${summary.generated} generated, ${summary.catalogOnly} catalog-only.`
}
