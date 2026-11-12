import { describe, expect, it } from 'vitest'
import { fuzzyScore } from './utils/fuzzy'
import { nodeSearchText } from './utils/nodeSearch'

describe('node search text', () => {
  const hubspot = {
    display_name: 'HubSpot',
    type: 'hubspot',
    category: 'Connectors',
    description: 'Search and manage CRM records.',
    is_connector: true,
    credential_types: ['hubspot'],
    operations: {
      search: { display_name: 'Search Record', description: 'Find records by property value.' },
      list_object_types: { display_name: 'List Object Types', description: 'Discover custom objects.' },
    },
  }

  it('matches "HubSpot methods" in the sidebar and command palette', () => {
    expect(fuzzyScore('hubspot methods', nodeSearchText(hubspot))).toBeGreaterThanOrEqual(0)
    expect(fuzzyScore('hubspot methods', nodeSearchText(hubspot, 'Add HubSpot'))).toBeGreaterThanOrEqual(0)
  })

  it('includes operation labels so a method name is searchable', () => {
    const text = nodeSearchText(hubspot).toLowerCase()
    expect(text).toContain('search record')
    expect(text).toContain('list object types')
    expect(text).toContain('methods')
  })

  it('handles nodes without operations or credentials', () => {
    const text = nodeSearchText({ display_name: 'Set Data', type: 'set_data' })
    expect(text).toContain('Set Data')
    expect(text).not.toContain('methods')
  })
})
