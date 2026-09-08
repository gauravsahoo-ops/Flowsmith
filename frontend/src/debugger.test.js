// Phase 13 debugger util tests: masking, timeline math, branch
// derivation, API-status extraction, retry safety, execution diff.

import { describe, expect, it } from 'vitest'

import {
  computeSpans,
  connectorIdFromNote,
  deriveBranches,
  diffExecutions,
  extractApiStatus,
  maskJson,
  retrySafety,
  sensitiveKey,
  totalSpanMs,
} from './utils/debugger'

function step(node_id, started_at, duration_ms, extra = {}) {
  return { node_id, node_type: node_id, status: 'success', started_at, duration_ms, ...extra }
}

describe('secret masking', () => {
  it('masks sensitive-looking keys at any depth, nothing else', () => {
    const out = maskJson({
      api_key: 'sk-123',
      Authorization: 'Bearer xyz',
      note: 'fine',
      nested: { password: 'hunter2', keep: 42 },
      list: [{ client_secret: 'zzz', ok: true }],
    })
    expect(out.api_key).toBe('\u2022'.repeat(8))
    expect(out.Authorization).toBe('\u2022'.repeat(8))
    expect(out.note).toBe('fine')
    expect(out.nested.password).toBe('\u2022'.repeat(8))
    expect(out.nested.keep).toBe(42)
    expect(out.list[0].client_secret).toBe('\u2022'.repeat(8))
    expect(out.list[0].ok).toBe(true)
  })

  it('sensitiveKey matches substrings case-insensitively (separators normalised)', () => {
    expect(sensitiveKey('X-API-Key')).toBe(true)
    expect(sensitiveKey('Set-Cookie')).toBe(true)
    expect(sensitiveKey('access-token')).toBe(true) // "token" marker
    expect(sensitiveKey('monkey')).toBe(false) // bare "key" is not a marker
  })

  it('does not treat ordinary fields as sensitive', () => {
    const out = maskJson({ email: 'a@b.com', total: 5, nickname: 'abc' })
    expect(out.email).toBe('a@b.com')
    expect(out.total).toBe(5)
    expect(out.nickname).toBe('abc')
  })
})

describe('timeline spans', () => {
  it('positions steps relative to the earliest start', () => {
    const spans = computeSpans([
      step('a', '2024-01-01T00:00:00.000Z', 100),
      step('b', '2024-01-01T00:00:00.100Z', 100),
    ])
    expect(spans[0].leftPct).toBeCloseTo(0, 5)
    expect(spans[0].widthPct).toBeCloseTo(50, 1)
    expect(spans[1].leftPct).toBeCloseTo(50, 1)
    expect(totalSpanMs(spans)).toBe(200)
  })

  it('gives instant steps a visible minimum width and handles empty input', () => {
    const spans = computeSpans([step('a', '2024-01-01T00:00:00.000Z', 0)])
    expect(spans[0].widthPct).toBeGreaterThan(0)
    expect(computeSpans([])).toEqual([])
    expect(computeSpans([{ node_id: 'x' }])).toEqual([]) // no started_at
  })
})

describe('deriveBranches', () => {
  it('reads true/false routing from persisted handle outputs', () => {
    const branches = deriveBranches(
      { node_id: 'gate' },
      { gate: { true: [{ a: 1 }, { b: 2 }], false: [] } },
    )
    expect(branches).toEqual([
      { handle: 'true', items: 2, taken: true },
      { handle: 'false', items: 0, taken: false },
    ])
  })

  it('supports switch route handles and ignores non-routing nodes', () => {
    const sw = deriveBranches(
      { node_id: 'sw' },
      { sw: { route_0: [{}], default: [], main: [{}] } },
    )
    expect(sw.map((b) => b.handle)).toEqual(['route_0', 'default'])
    expect(deriveBranches({ node_id: 'http' }, { http: { main: [{}] } })).toEqual([])
    expect(deriveBranches({ node_id: 'x' }, undefined)).toEqual([])
  })
})

describe('extractApiStatus', () => {
  it('finds the HTTP status in well-known output shapes', () => {
    expect(extractApiStatus({ main: [{ status: 201, body: {} }] })).toBe(201)
    expect(extractApiStatus({ main: [{ status: 200, items: [] }] })).toBe(200)
    expect(extractApiStatus({ main: [{ value: 3 }] })).toBeNull()
    expect(extractApiStatus(null)).toBeNull()
  })
})

describe('connectorIdFromNote', () => {
  it('parses the engine note format', () => {
    expect(connectorIdFromNote("Via connector 'stripe'.")).toBe('stripe')
    expect(connectorIdFromNote("Via connector 'stripe'; succeeded after 1 retries.")).toBe('stripe')
    expect(connectorIdFromNote('plain failure')).toBeNull()
    expect(connectorIdFromNote(null)).toBeNull()
  })
})

describe('retrySafety', () => {
  it('classifies from catalog metadata; unknown is caution', () => {
    expect(retrySafety({ idempotency: 'idempotent' })).toBe('safe')
    expect(retrySafety({ idempotency: 'conditionally_idempotent' })).toBe('safe')
    expect(retrySafety({ idempotency: 'non_idempotent' })).toBe('caution')
    expect(retrySafety(null)).toBe('caution')
    // Connector nodes with mixed op safety are caution.
    expect(
      retrySafety({
        operations: {
          get: { idempotency: 'idempotent' },
          create: { idempotency: 'non_idempotent' },
        },
      }),
    ).toBe('caution')
    expect(
      retrySafety({
        operations: {
          get: { idempotency: 'idempotent' },
          list: { idempotency: 'conditionally_idempotent' },
        },
      }),
    ).toBe('safe')
  })
})

describe('diffExecutions', () => {
  const base = {
    id: 'e1',
    trace: [
      step('trigger', '2024-01-01T00:00:00Z', 10),
      step('api', '2024-01-01T00:00:00Z', 500, { retries: 1 }),
    ],
    node_statuses: { trigger: 'success', api: 'success' },
    results: { outputs: { api: { main: [{ status: 200 }] } } },
  }
  const cmp = {
    id: 'e2',
    trace: [
      step('trigger', '2024-01-02T00:00:00Z', 12),
      step('api', '2024-01-02T00:00:00Z', 250),
    ],
    node_statuses: { trigger: 'success', api: 'success' },
    results: { outputs: { api: { main: [{ status: 500 }] } } },
  }

  it('produces aligned rows with deltas and output-change flags', () => {
    const rows = diffExecutions(base, cmp)
    const api = rows.find((r) => r.nodeId === 'api')
    expect(api.inBoth).toBe(true)
    expect(api.durationDelta).toBe(-250)
    expect(api.baseRetries).toBe(1)
    expect(api.cmpRetries).toBe(0)
    expect(api.outputsChanged).toBe(true)

    const trigger = rows.find((r) => r.nodeId === 'trigger')
    expect(trigger.outputsChanged).toBe(false)
  })

  it('handles nodes missing on one side', () => {
    const rows = diffExecutions(base, { id: 'e3', trace: [], node_statuses: {}, results: {} })
    expect(rows.every((r) => !r.inBoth)).toBe(true)
  })
})
