import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { NodeIcon } from './NodeIcons'

describe('NodeIcon Real Logos Suite', () => {
  const connectors = [
    'salesforce', 'hubspot', 'slack', 'github', 'gitlab', 'bitbucket',
    'jira', 'notion', 'airtable', 'trello', 'asana', 'linear',
    'clickup', 'monday', 'todoist', 'msteams', 'outlook', 'discord',
    'twilio', 'whatsapp', 'zoom', 'zendesk', 'freshdesk', 'pagerduty',
    'stripe', 'shopify', 'quickbooks', 'dropbox', 'calendly', 'openai',
    'mailchimp', 'brevo', 'pipedrive', 'google_drive', 'google_sheets',
    'google_calendar', 'google_docs', 'gmail', 'postgres', 'mysql',
    'mongodb', 'redis'
  ]

  const flowNodes = [
    'http_request', 'code', 'if_condition', 'switch', 'loop',
    'loop_over_items', 'split', 'merge', 'wait', 'filter',
    'set_data', 'aggregate', 'compare_datasets', 'data_table',
    'database_query', 'manual_trigger', 'schedule', 'webhook',
    'form_trigger', 'chat_trigger', 'salesforce_trigger',
    'stop_and_error', 'human_approval', 'noop', 'ai', 'ai_agent',
    'embeddings', 'rag_pipeline', 'memory', 'text_splitter',
    'output_parser', 'token_manager', 'token_fetch', 'token_store',
    'crypto_tools', 'csv_json_transform', 'date_time', 'email_read',
    'send_email', 'file_io', 'ftp', 'git', 'graphql', 'html_extract',
    'item_lists', 'markdown_text', 'pagination', 'respond_to_webhook',
    'rss_feed', 'ssh', 'telegram', 'websocket', 'xml_ops'
  ]

  connectors.forEach((type) => {
    it(`renders real SVG logo for connector: ${type}`, () => {
      const el = React.createElement(NodeIcon, { type, size: 32 })
      const html = renderToStaticMarkup(el)
      expect(html).toContain('<svg')
      expect(html).toContain('width="32"')
      expect(html).toContain('height="32"')
      expect(html).not.toContain('<span')
    })
  })

  flowNodes.forEach((type) => {
    it(`renders clean vector SVG for flow node: ${type}`, () => {
      const el = React.createElement(NodeIcon, { type, size: 32 })
      const html = renderToStaticMarkup(el)
      expect(html).toContain('<svg')
      expect(html).toContain('width="32"')
      expect(html).toContain('height="32"')
      expect(html).not.toContain('<span')
    })
  })
})
