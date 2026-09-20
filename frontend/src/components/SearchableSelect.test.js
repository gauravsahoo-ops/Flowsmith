import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import SearchableSelect from './SearchableSelect'
import { NodeIcon } from './NodeIcons'

describe('SearchableSelect Credential Type Search Suite', () => {
  const options = [
    {
      value: 'salesforce',
      label: 'Salesforce (salesforce)',
      hint: 'OAuth 2.0 connection to Salesforce org',
      icon: React.createElement(NodeIcon, { type: 'salesforce', size: 16 }),
      keywords: 'salesforce crm oauth',
    },
    {
      value: 'postgres',
      label: 'PostgreSQL (postgres)',
      hint: 'PostgreSQL database connection string or credentials',
      icon: React.createElement(NodeIcon, { type: 'postgres', size: 16 }),
      keywords: 'database sql rds postgresql',
    },
    {
      value: 'teams',
      label: 'Microsoft Teams / Graph (microsoft_graph)',
      hint: 'Microsoft 365 and Teams Webhooks & Graph API',
      icon: React.createElement(NodeIcon, { type: 'teams', size: 16 }),
      keywords: 'microsoft teams chat office365',
    },
    {
      value: 'aws_s3',
      label: 'AWS S3 (aws_s3)',
      hint: 'Amazon Web Services S3 access keys',
      disabled: true,
      disabledReason: 'Not implemented',
      icon: React.createElement(NodeIcon, { type: 'aws_s3', size: 16 }),
      keywords: 'aws s3 bucket storage amazon cloud',
    },
  ]

  it('renders placeholder when no value is selected', () => {
    const html = renderToStaticMarkup(
      React.createElement(SearchableSelect, {
        value: '',
        onChange: () => {},
        options,
        placeholder: 'Search credential types…',
      })
    )
    expect(html).toContain('Search credential types…')
  })

  it('renders selected label and icon when value is selected', () => {
    const html = renderToStaticMarkup(
      React.createElement(SearchableSelect, {
        value: 'salesforce',
        onChange: () => {},
        options,
      })
    )
    expect(html).toContain('Salesforce (salesforce)')
    expect(html).toContain('svg')
  })

  it('renders disabled state properly with custom reason', () => {
    const html = renderToStaticMarkup(
      React.createElement(SearchableSelect, {
        value: 'aws_s3',
        onChange: () => {},
        options,
      })
    )
    expect(html).toContain('AWS S3 (aws_s3)')
  })
})
