// Phase 12 editor logic: history, graph validation/cycles, auto-layout,
// decoration (de)serialisation, fuzzy matching.

import { describe, expect, it } from 'vitest'

import { createHistory } from './utils/history'
import { edgeKey, validateGraph, wouldCreateCycle, ancestors } from './utils/graphUtils'
import { autoLayout } from './utils/autoLayout'
import { readDecorations, withDecorations } from './mappers.js'
import { fuzzyScore } from './utils/fuzzy'

function n(id, x = 0, y = 0) {
  return { id, type: 'custom', position: { x, y }, data: { node: { id, type: 'set_data' } } }
}
function e(source, target) {
  return { id: `${source}->${target}`, source, target, sourceHandle: 'main', targetHandle: 'main' }
}

describe('history', () => {
  it('undo restores the previous state and redo reapplies it', () => {
    const h = createHistory()
    const a = { nodes: [n('1')], edges: [] }
    h.push(a.nodes, a.edges)
    const b = { nodes: [n('1'), n('2')], edges: [e('1', '2')] }
    // (mutation happens in the store; here we just push/undo/redo)
    expect(h.canUndo()).toBe(true)
    const restored = h.undo(b)
    expect(restored.nodes).toHaveLength(1)

    expect(h.canRedo()).toBe(true)
    const redone = h.undo === null ? null : h.redo({ nodes: restored.nodes, edges: restored.edges })
    expect(redone.nodes).toHaveLength(2)
  })

  it('coalesces rapid same-key pushes into one step', () => {
    const h = createHistory()
    h.push([n('1')], [], 'node:x')
    h.push([n('1'), n('2')], [], 'node:x')
    h.push([n('1'), n('2'), n('3')], [], 'node:x')
    // Three keystrokes -> one undo entry.
    const state = { nodes: [], edges: [] }
    const first = h.undo(state)
    void first
    expect(h.canUndo()).toBe(false) // only the merged entry existed
  })

  it('different keys do not coalesce', () => {
    const h = createHistory()
    h.push([n('1')], [], 'node:a')
    h.push([n('1'), n('2')], [], 'node:b')
    let remaining = 0
    let cur = { nodes: [], edges: [] }
    for (;;) {
      const prev = h.undo(cur)
      if (!prev) break
      cur = prev
      remaining += 1
    }
    expect(remaining).toBeGreaterThanOrEqual(2)
  })

  it('a new push clears the redo branch', () => {
    const h = createHistory()
    h.push([n('1')], [])
    h.undo({ nodes: [n('1')], edges: [] })
    expect(h.canRedo()).toBe(true)
    h.push([n('9')], [])
    expect(h.canRedo()).toBe(false)
  })

  it('respects the size limit without unbounded growth', () => {
    const h = createHistory()
    for (let i = 0; i < 250; i += 1) h.push([n(String(i))], [])
    let steps = 0
    let cur = { nodes: [], edges: [] }
    for (;;) {
      const prev = h.undo(cur)
      if (!prev) break
      cur = prev
      steps += 1
      if (steps > 300) break
    }
    expect(steps).toBeLessThanOrEqual(100)
  })
})

describe('wouldCreateCycle', () => {
  it('rejects self loops and back-edges, allows forward edges', () => {
    const edges = [e('a', 'b'), e('b', 'c')]
    expect(wouldCreateCycle(edges, 'a', 'a')).toBe(true)
    expect(wouldCreateCycle(edges, 'c', 'a')).toBe(true) // c reaches a
    expect(wouldCreateCycle(edges, 'a', 'd')).toBe(false)
    expect(wouldCreateCycle([], 'x', 'y')).toBe(false)
  })
})

describe('edgeKey', () => {
  it('normalises missing handles to main (4-part key)', () => {
    expect(edgeKey({ source: 'a', target: 'b' })).toBe('a|main|b|main')
    expect(edgeKey({ source: 'a', sourceHandle: 'true', target: 'b' })).toBe('a|true|b|main')
  })
})

describe('validateGraph', () => {
  it('reports cycles and orphans but passes a clean chain', () => {
    const clean = validateGraph([n('a'), n('b')], [e('a', 'b')])
    expect(clean.ok).toBe(true)

    const cyc = validateGraph(
      [n('a'), n('b'), n('z')],
      [e('a', 'b'), e('b', 'a')],
    )
    expect(cyc.ok).toBe(false)
    expect(cyc.problems.some((p) => p.includes('cycle'))).toBe(true)
    expect(cyc.problems.some((p) => p.includes('(z)'))).toBe(true)
  })
})

describe('autoLayout', () => {
  it('places downstream nodes strictly right of their sources (LR)', () => {
    const nodes = [n('a'), n('b'), n('c')]
    const edges = [e('a', 'b'), e('a', 'c')]
    const pos = autoLayout(nodes, edges)
    expect(pos.get('a').x).toBeLessThan(pos.get('b').x)
    expect(pos.get('b').x).toBe(pos.get('c').x) // siblings share a layer
    expect(pos.get('b').y).not.toBe(pos.get('c').y)

    // Chains deepen the layer.
    const chainPos = autoLayout(nodes, [e('a', 'b'), e('b', 'c')])
    expect(chainPos.get('a').x).toBeLessThan(chainPos.get('b').x)
    expect(chainPos.get('b').x).toBeLessThan(chainPos.get('c').x)
  })

  it('keeps every node placed, including isolated ones', () => {
    const nodes = [n('a'), n('b'), n('lone')]
    const pos = autoLayout(nodes, [e('a', 'b')])
    expect(pos.size).toBe(3)
    expect(pos.has('lone')).toBe(true)
  })

  it('survives cycles without hanging or dropping nodes', () => {
    const nodes = [n('a'), n('b')]
    const pos = autoLayout(nodes, [e('a', 'b'), e('b', 'a')])
    expect(pos.size).toBe(2)
  })

  it('supports top-to-bottom direction', () => {
    const nodes = [n('a'), n('b')]
    const pos = autoLayout(nodes, [e('a', 'b')], 'TB')
    expect(pos.get('a').y).toBeLessThan(pos.get('b').y)
  })
})

describe('editor decorations', () => {
  it('round-trips comments/groups/labels through workflow.settings', () => {
    const wf = { id: 'w', settings: {} }
    const payload = withDecorations(wf, {
      comments: [{ id: 'c1', x: 1, y: 2, text: 'hi' }],
      groups: [{ id: 'g1', label: 'Stage', x: 0, y: 0, width: 10, height: 10 }],
      edgeLabels: { 'a|main|b': 'yes' },
    })
    expect(payload.settings.editor.comments).toHaveLength(1)
    const decor = readDecorations(payload)
    expect(decor.comments[0].text).toBe('hi')
    expect(decor.groups[0].label).toBe('Stage')
    expect(decor.edgeLabels['a|main|b']).toBe('yes')
  })

  it('drops the editor key entirely when there is nothing to store', () => {
    const payload = withDecorations({ id: 'w', settings: { other: 1 } }, {
      comments: [],
      groups: [],
      edgeLabels: {},
    })
    expect(payload.settings.editor).toBeUndefined()
    expect(payload.settings.other).toBe(1)
  })

  it('reads defensively from workflows without editor settings', () => {
    expect(readDecorations({ id: 'w' })).toEqual({
      comments: [],
      groups: [],
      edgeLabels: {},
    })
    expect(readDecorations(null)).toEqual({ comments: [], groups: [], edgeLabels: {} })
  })
})

describe('fuzzyScore', () => {
  it('matches subsequences, prefers consecutive hits, rejects misses', () => {
    expect(fuzzyScore('', 'anything')).toBe(0)
    expect(fuzzyScore('http', 'Add HTTP Request')).toBeGreaterThan(0)
    expect(fuzzyScore('httpreq', 'Add HTTP Request')).toBeGreaterThan(
      fuzzyScore('httpreq', 'Add Slack Message'),
    )
    expect(fuzzyScore('zzz', 'Add HTTP Request')).toBe(-1)
  })
})

describe('ancestors DAG traversal', () => {
  it('returns empty array when node has no incoming edges', () => {
    expect(ancestors([], 'root')).toEqual([])
  })

  it('traverses multi-step upstream ancestors in reverse topological order', () => {
    const edges = [
      { source: 'trigger', target: 'code' },
      { source: 'code', target: 'login_api' },
      { source: 'login_api', target: 'salesforce' },
    ]
    const list = ancestors(edges, 'salesforce')
    expect(list).toEqual(['login_api', 'code', 'trigger'])
  })

  it('handles branching multiple upstream parents cleanly without duplicates', () => {
    const edges = [
      { source: 'trigger', target: 'branchA' },
      { source: 'trigger', target: 'branchB' },
      { source: 'branchA', target: 'join' },
      { source: 'branchB', target: 'join' },
    ]
    const list = ancestors(edges, 'join')
    expect(list).toContain('branchA')
    expect(list).toContain('branchB')
    expect(list).toContain('trigger')
    expect(list.length).toBe(3)
  })
})
