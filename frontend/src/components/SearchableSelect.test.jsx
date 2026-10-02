import { describe, it, expect } from 'vitest'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import SearchableSelect from './SearchableSelect'

describe('SearchableSelect Suite', () => {
  const mockOptions = [
    { value: 'openai', label: 'OpenAI', category: 'Major Providers', meta: 'Supported' },
    { value: 'anthropic', label: 'Anthropic', category: 'Major Providers', meta: 'Supported' },
    { value: 'groq', label: 'Groq', category: 'Inference Providers', meta: 'Supported' },
    { value: 'deepseek', label: 'DeepSeek', category: 'Major Providers', tags: ['Reasoning', 'Vision'] },
    { value: 'custom', label: 'Other Custom provider', category: 'Custom', meta: 'Custom' },
  ]

  it('renders with placeholder when no value selected', () => {
    const html = renderToStaticMarkup(
      React.createElement(SearchableSelect, {
        value: '',
        onChange: () => {},
        options: mockOptions,
        placeholder: 'Search 180+ providers…',
      })
    )
    expect(html).toContain('Search 180+ providers…')
    expect(html).toContain('searchable-select')
  })

  it('renders selected option label and meta badge', () => {
    const html = renderToStaticMarkup(
      React.createElement(SearchableSelect, {
        value: 'openai',
        onChange: () => {},
        options: mockOptions,
      })
    )
    expect(html).toContain('OpenAI')
    expect(html).toContain('Supported')
  })

  it('renders loading spinner when loading prop is true', () => {
    const html = renderToStaticMarkup(
      React.createElement(SearchableSelect, {
        value: '',
        onChange: () => {},
        options: mockOptions,
        loading: true,
      })
    )
    expect(html).toContain('spinner-sm')
  })

  it('renders disabled state properly', () => {
    const html = renderToStaticMarkup(
      React.createElement(SearchableSelect, {
        value: 'openai',
        onChange: () => {},
        options: mockOptions,
        disabled: true,
      })
    )
    expect(html).toContain('disabled=""')
  })

  it('renders clearable button when value is present and clearable is true', () => {
    const html = renderToStaticMarkup(
      React.createElement(SearchableSelect, {
        value: 'groq',
        onChange: () => {},
        options: mockOptions,
        clearable: true,
      })
    )
    expect(html).toContain('Clear selection')
    expect(html).toContain('Groq')
  })

  it('renders model tags and context meta properly', () => {
    const modelOptions = [
      {
        value: 'gpt-4o',
        label: 'GPT-4o',
        tags: ['Vision', 'Tools'],
        meta: '128K context',
        hint: 'Flagship omni model',
      },
      {
        value: 'o3-mini',
        label: 'o3-mini',
        tags: ['Reasoning'],
        meta: '200K context',
        hint: 'Reasoning model',
      }
    ]
    const html = renderToStaticMarkup(
      React.createElement(SearchableSelect, {
        value: 'gpt-4o',
        onChange: () => {},
        options: modelOptions,
      })
    )
    expect(html).toContain('GPT-4o')
    expect(html).toContain('128K context')
  })
})
