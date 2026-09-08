import { describe, it, expect } from 'vitest'
import { toReactFlow, toWorkflowJson } from './mappers.js'

describe('toReactFlow', () => {
  it('maps workflow nodes to React Flow nodes', () => {
    const wf = {
      nodes: [
        { id: 'a', type: 'http', position: { x: 10, y: 20 }, parameters: { url: 'http://x' } },
        { id: 'b', type: 'if', position: { x: 30, y: 40 } },
      ],
      connections: [],
    }
    const { nodes, edges } = toReactFlow(wf)
    expect(nodes).toHaveLength(2)
    expect(nodes[0]).toEqual({ id: 'a', type: 'custom', position: { x: 10, y: 20 }, data: { node: wf.nodes[0] } })
    expect(nodes[1]).toEqual({ id: 'b', type: 'custom', position: { x: 30, y: 40 }, data: { node: wf.nodes[1] } })
    expect(edges).toEqual([])
  })

  it('defaults position to {0,0} when missing', () => {
    const wf = { nodes: [{ id: 'a', type: 'x' }], connections: [] }
    const { nodes } = toReactFlow(wf)
    expect(nodes[0].position).toEqual({ x: 0, y: 0 })
  })

  it('maps connections to edges with default handles', () => {
    const wf = {
      nodes: [],
      connections: [{ source: 'a', target: 'b' }],
    }
    const { edges } = toReactFlow(wf)
    expect(edges).toEqual([{
      id: 'a->b->main',
      source: 'a',
      sourceHandle: 'main',
      target: 'b',
      targetHandle: 'main',
    }])
  })

  it('uses explicit sourceHandle and targetHandle when provided', () => {
    const wf = {
      nodes: [],
      connections: [{ source: 'a', sourceHandle: 'out1', target: 'b', targetHandle: 'in2' }],
    }
    const { edges } = toReactFlow(wf)
    expect(edges[0].sourceHandle).toBe('out1')
    expect(edges[0].targetHandle).toBe('in2')
    expect(edges[0].id).toBe('a->b->out1')
  })

  it('deduplicates identical connections', () => {
    const wf = {
      nodes: [],
      connections: [
        { source: 'a', target: 'b' },
        { source: 'a', target: 'b' },
        { source: 'a', sourceHandle: 'x', target: 'b' },
      ],
    }
    const { edges } = toReactFlow(wf)
    // All connections are preserved (duplicates get unique ids with #N suffix)
    expect(edges).toHaveLength(3)
    expect(edges[0].id).toBe('a->b->main')
    expect(edges[1].id).toBe('a->b->main#1')
    expect(edges[2].id).toBe('a->b->x')
  })

  it('handles empty/missing nodes and connections', () => {
    expect(toReactFlow({})).toEqual({ nodes: [], edges: [] })
    expect(toReactFlow({ nodes: null, connections: null })).toEqual({ nodes: [], edges: [] })
  })
})

describe('toWorkflowJson', () => {
  it('maps React Flow nodes back to workflow nodes', () => {
    const wf = { id: 'wf1', name: 'test' }
    const nodes = [
      { id: 'a', type: 'custom', position: { x: 10.6, y: 20.2 }, data: { node: { type: 'http', parameters: { url: 'x' }, settings: {} } } },
    ]
    const edges = []
    const result = toWorkflowJson(wf, nodes, edges)
    expect(result.id).toBe('wf1')
    expect(result.nodes).toHaveLength(1)
    expect(result.nodes[0]).toEqual({
      id: 'a',
      type: 'http',
      position: { x: 11, y: 20 },
      parameters: { url: 'x' },
      settings: {},
    })
  })

  it('rounds position to integers', () => {
    const nodes = [{ id: 'a', position: { x: 1.9, y: 2.1 }, data: { node: { type: 'x' } } }]
    const result = toWorkflowJson({}, nodes, [])
    expect(result.nodes[0].position).toEqual({ x: 2, y: 2 })
  })

  it('maps edges to connections with default handles', () => {
    const nodes = []
    const edges = [{ id: '1', source: 'a', target: 'b', sourceHandle: 'main', targetHandle: 'main' }]
    const result = toWorkflowJson({}, nodes, edges)
    expect(result.connections).toEqual([{
      source: 'a',
      sourceHandle: 'main',
      target: 'b',
      targetHandle: 'main',
    }])
  })

  it('preserves explicit handles on edges', () => {
    const edges = [{ id: '1', source: 'a', sourceHandle: 'out1', target: 'b', targetHandle: 'in2' }]
    const result = toWorkflowJson({}, [], edges)
    expect(result.connections[0].sourceHandle).toBe('out1')
    expect(result.connections[0].targetHandle).toBe('in2')
  })

  it('includes credentials and version when present on node data', () => {
    const nodes = [{
      id: 'a',
      position: { x: 0, y: 0 },
      data: { node: { type: 'sf', credentials: { sf: 'cred1' }, version: 2 } },
    }]
    const result = toWorkflowJson({}, nodes, [])
    expect(result.nodes[0].credentials).toEqual({ sf: 'cred1' })
    expect(result.nodes[0].version).toBe(2)
  })

  it('omits credentials and version when not set', () => {
    const nodes = [{ id: 'a', position: { x: 0, y: 0 }, data: { node: { type: 'sf' } } }]
    const result = toWorkflowJson({}, nodes, [])
    expect(result.nodes[0]).not.toHaveProperty('credentials')
    expect(result.nodes[0]).not.toHaveProperty('version')
  })

  it('merges with original workflow object', () => {
    const wf = { id: 'wf1', name: 'test', custom: 42 }
    const result = toWorkflowJson(wf, [], [])
    expect(result.id).toBe('wf1')
    expect(result.name).toBe('test')
    expect(result.custom).toBe(42)
  })
})

describe('round-trip consistency', () => {
  it('toReactFlow then toWorkflowJson preserves nodes and connections', () => {
    const original = {
      nodes: [
        { id: 'a', type: 'http', position: { x: 10, y: 20 }, parameters: { url: 'x' }, settings: {} },
        { id: 'b', type: 'if', position: { x: 30, y: 40 }, parameters: { cond: true } },
      ],
      connections: [{ source: 'a', target: 'b' }],
    }
    const rf = toReactFlow(original)
    const back = toWorkflowJson(original, rf.nodes, rf.edges)
    expect(back.nodes).toHaveLength(2)
    expect(back.nodes[0].id).toBe('a')
    expect(back.nodes[0].type).toBe('http')
    expect(back.connections).toHaveLength(1)
    expect(back.connections[0].source).toBe('a')
  })
})

// ---- Approval stamp formatting (Phase 40) ----
import { formatApprovalStamp } from './mappers.js'

describe('formatApprovalStamp', () => {
  it('renders approved stamp with user and time', () => {
    const out = formatApprovalStamp({ approved: true, approved_by: 7, approved_at: '2026-01-02T03:04:05Z' })
    expect(out).toMatch(/^Approved by user #7 · /)
  })

  it('renders rejection', () => {
    const out = formatApprovalStamp({ approved: false, approved_by: 3 })
    expect(out).toBe('Rejected by user #3')
  })

  it('handles missing fields', () => {
    expect(formatApprovalStamp(null)).toBe('')
    expect(formatApprovalStamp({})).toBe('Decision by user #?')
  })
})

// ---- Mapping insertion helper (Phase 5) ----
import { insertMapping } from './utils/mappingUtils.js'

describe('insertMapping', () => {
  it('replaces empty value with snippet', () => {
    expect(insertMapping('', '{{ $node["a"].json.email }}')).toBe('{{ $node["a"].json.email }}')
    expect(insertMapping(undefined, '{{ $json.x }}')).toBe('{{ $json.x }}')
  })

  it('replaces when value is already a single expression', () => {
    expect(
      insertMapping('{{ $json.old }}', '{{ $json.new }}')
    ).toBe('{{ $json.new }}')
  })

  it('appends to literal text', () => {
    expect(insertMapping('Hello ', '{{ $json.name }}')).toBe('Hello {{ $json.name }}')
  })

  it('appends to mixed text+expression', () => {
    const out = insertMapping('Hi {{ $json.a }} bye', '{{ $json.b }}')
    expect(out).toContain('{{ $json.a }}')
    expect(out.trim().endsWith('{{ $json.b }}')).toBe(true)
  })
})
