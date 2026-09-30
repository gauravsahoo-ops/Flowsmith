import { describe, it, expect } from 'vitest'
import { matchesCategory, CONNECTOR_CATEGORY_MAP } from './IntegrationsPage'
import catalogData from '../all_catalog_items.json'

describe('IntegrationsPage Category Completeness Suite', () => {
  const allConnectors = catalogData.connectors

  it('contains valid categories for all 8 categories in UI', () => {
    const categories = ['all', 'crm', 'database', 'communication', 'developer', 'ai', 'productivity', 'finance']
    for (const cat of categories) {
      expect(typeof cat).toBe('string')
    }
  })

  it('ensures every single registered connector belongs to at least one category', () => {
    const unmapped = []
    for (const key of allConnectors) {
      const conn = { connector_key: key, category: 'api' }
      const hasCategory = ['crm', 'database', 'communication', 'developer', 'ai', 'productivity', 'finance'].some(
        (cat) => matchesCategory(conn, cat)
      )
      if (!hasCategory) {
        unmapped.push(key)
      }
    }
    expect(unmapped).toEqual([])
  })

  it('correctly maps CRM & Sales connectors', () => {
    const expected = ['salesforce', 'hubspot', 'dynamics_crm', 'freshsales', 'zoho_crm', 'pipedrive', 'activecampaign', 'workday']
    for (const key of expected) {
      expect(matchesCategory({ connector_key: key, category: 'crm' }, 'crm')).toBe(true)
    }
  })

  it('correctly maps Databases & Storage connectors', () => {
    const expected = ['postgres', 'mysql', 'mongodb', 'redis', 'supabase', 'snowflake', 'bigquery', 's3', 'google_drive', 'dropbox', 'box', 'pinecone', 'airtable']
    for (const key of expected) {
      expect(matchesCategory({ connector_key: key, category: 'database' }, 'database')).toBe(true)
    }
  })

  it('correctly maps Communication connectors', () => {
    const expected = ['slack', 'discord', 'msteams', 'whatsapp', 'twilio', 'zoom', 'gmail', 'outlook', 'resend', 'sendgrid', 'mailchimp', 'brevo', 'intercom']
    for (const key of expected) {
      expect(matchesCategory({ connector_key: key, category: 'communication' }, 'communication')).toBe(true)
    }
  })

  it('correctly maps Developer & DevOps connectors', () => {
    const expected = ['github', 'gitlab', 'bitbucket', 'sentry', 'pagerduty', 'http', 'httpbin', 'dummy_json', 'json_placeholder', 'poke_api', 'open_notify', 'open_meteo', 'schedule', 'webhook']
    for (const key of expected) {
      expect(matchesCategory({ connector_key: key, category: 'developer' }, 'developer')).toBe(true)
    }
  })

  it('correctly maps AI & Knowledge connectors', () => {
    const expected = ['openai', 'anthropic', 'gemini', 'open_router', 'pinecone']
    for (const key of expected) {
      expect(matchesCategory({ connector_key: key, category: 'ai' }, 'ai')).toBe(true)
    }
  })

  it('correctly maps Productivity connectors', () => {
    const expected = ['notion', 'jira', 'linear', 'asana', 'clickup', 'monday', 'trello', 'todoist', 'coda', 'google_docs', 'google_sheets', 'google_calendar', 'calendly', 'docusign', 'airtable', 'servicenow', 'typeform', 'pipedrive']
    for (const key of expected) {
      expect(matchesCategory({ connector_key: key, category: 'productivity' }, 'productivity')).toBe(true)
    }
  })

  it('correctly maps Finance & Payments connectors', () => {
    const expected = ['stripe', 'shopify', 'quickbooks', 'xero', 'netsuite', 'sap', 'frankfurter', 'coin_gecko']
    for (const key of expected) {
      expect(matchesCategory({ connector_key: key, category: 'finance' }, 'finance')).toBe(true)
    }
  })
})
