import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import CsvNodeEditor from './CsvNodeEditor'

describe('CsvNodeEditor Suite', () => {
  it('renders Flowsmith DataLoad identity banner and supported format tags', () => {
    const node = {
      id: 'node_dataload_1',
      type: 'flowsmith.data_load',
      parameters: {
        source_mode: 'upload',
      },
    }
    const html = renderToStaticMarkup(
      React.createElement(CsvNodeEditor, {
        node,
        onParamsChange: () => {},
      })
    )
    expect(html).toContain('Flowsmith DataLoad')
    expect(html).toContain('flowsmith.data_load')
    expect(html).toContain('Production Ready')
    expect(html).toContain('CSV')
    expect(html).toContain('TSV')
    expect(html).toContain('ZIP (Single &amp; Multi-File)')
    expect(html).toContain('Nested Archives')
    expect(html).toContain('GZIP (.gz)')
  })

  it('renders 4 source modes: upload, url, file_path, and inline', () => {
    const node = {
      id: 'node_dataload_2',
      type: 'flowsmith.data_load',
      parameters: {
        source_mode: 'upload',
      },
    }
    const html = renderToStaticMarkup(
      React.createElement(CsvNodeEditor, {
        node,
        onParamsChange: () => {},
      })
    )
    expect(html).toContain('Option A: Upload File')
    expect(html).toContain('Option B: Download URL')
    expect(html).toContain('Local File Path')
    expect(html).toContain('Inline Content')
  })

  it('renders SSRF protection guard when in URL mode', () => {
    const node = {
      id: 'node_dataload_3',
      type: 'flowsmith.data_load',
      parameters: {
        source_mode: 'url',
        download_url: 'https://cdn.example.com/contacts.csv',
      },
    }
    const html = renderToStaticMarkup(
      React.createElement(CsvNodeEditor, {
        node,
        onParamsChange: () => {},
      })
    )
    expect(html).toContain('SSRF Guard Active')
    expect(html).toContain('Rejects loopback, private networks')
    expect(html).toContain('Download URL (Supports Expressions)')
  })

  it('renders standard Salesforce Contact target schema fields and auto-map button', () => {
    const node = {
      id: 'node_dataload_4',
      type: 'flowsmith.data_load',
      parameters: {
        source_mode: 'upload',
        target_object: 'Contact',
      },
    }
    const html = renderToStaticMarkup(
      React.createElement(CsvNodeEditor, {
        node,
        onParamsChange: () => {},
      })
    )
    expect(html).toContain('Field Mapping')
    expect(html).toContain('Salesforce Contact')
    expect(html).toContain('Auto-Map All')
    expect(html).toContain('Last Name (LastName)')
    expect(html).toContain('Email Address (Email)')
    expect(html).toContain('Phone (Phone)')
    expect(html).toContain('Mailing Street (MailingStreet)')
  })

  it('keeps node editor clean and decoupled without duplicate policy or DB persistence clutter', () => {
    const node = {
      id: 'node_dataload_5',
      type: 'flowsmith.data_load',
      parameters: {
        source_mode: 'upload',
      },
    }
    const html = renderToStaticMarkup(
      React.createElement(CsvNodeEditor, {
        node,
        onParamsChange: () => {},
      })
    )
    expect(html).not.toContain('Duplicate Policy &amp; Database Persistence')
    expect(html).not.toContain('Skip Duplicate Rows')
    expect(html).not.toContain('Persist staged records to PostgreSQL')
  })

  it('renders Add Target Field button, Custom Schema option, and configured custom target fields', () => {
    const node = {
      id: 'node_dataload_custom_fields',
      type: 'flowsmith.data_load',
      parameters: {
        source_mode: 'upload',
        target_object: 'Custom',
        custom_target_fields: [
          { field: 'AccountId', label: 'Account ID', type: 'String (18)', required: true, isCustom: true },
          { field: 'Custom_Score__c', label: 'Lead Score', type: 'Number', required: false, isCustom: true },
        ],
        field_mapping: {
          account_id_csv: 'AccountId',
          score_col: 'Custom_Score__c',
        },
      },
    }
    const html = renderToStaticMarkup(
      React.createElement(CsvNodeEditor, {
        node,
        onParamsChange: () => {},
      })
    )
    expect(html).toContain('Add Target Field')
    expect(html).toContain('Custom Schema / Table')
    expect(html).toContain('Account ID (AccountId)')
    expect(html).toContain('Lead Score (Custom_Score__c)')
    expect(html).toContain('Custom')
    expect(html).toContain('title="Remove custom target field"')
    expect(html).toContain('value="account_id_csv"')
    expect(html).toContain('value="score_col"')
  })
})
