// Canvas logic tests (M10): node/edge CRUD, duplicate, validation.

import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useUiStore } from './uiStore'
import { resetInit, useWorkflowStore } from './workflowStore'

const mockApi = vi.hoisted(() => ({
  generateWorkflow: vi.fn(),
  createWorkflow: vi.fn(),
  getWorkflow: vi.fn(),
  saveWorkflow: vi.fn(),
  deleteWorkflow: vi.fn(),
  listNodes: vi.fn(),
  listWorkflows: vi.fn(),
}))

vi.mock('../api', () => ({ api: mockApi }))

beforeEach(() => {
  vi.clearAllMocks()
  resetInit()
  useWorkflowStore.setState({ nodes: [], edges: [], workflow: null })
  useUiStore.setState({ selectedNodeId: null })
})

function add(type = 'set_data', x = 0) {
  useWorkflowStore.getState().addNode(type, { x, y: 0 })
}

describe('node ids', () => {
  it('are unique per type and reused after deletion', () => {
    add('set_data')
    add('set_data')
    add('http_request')
    const ids = useWorkflowStore.getState().nodes.map((n) => n.id)
    expect(ids).toEqual(['set_data_1', 'set_data_2', 'http_request_1'])

    useWorkflowStore.getState().deleteNodes(['set_data_1'])
    add('set_data')
    expect(useWorkflowStore.getState().nodes.some((n) => n.id === 'set_data_1')).toBe(true)
  })
})

describe('connections', () => {
  it('rejects self-loops and exact duplicates', () => {
    add('set_data', 0)
    add('set_data', 100)
    const [a, b] = useWorkflowStore.getState().nodes.map((n) => n.id)

    const { canConnect, onConnect } = useWorkflowStore.getState()
    expect(canConnect({ source: a, target: a })).toBe(false)
    expect(canConnect({ source: a, target: b })).toBe(true)

    onConnect({ source: a, target: b })
    onConnect({ source: a, target: b })
    expect(useWorkflowStore.getState().edges).toHaveLength(1)
  })
})

describe('duplicateNodes', () => {
  it('copies nodes and internal edges with new ids, offset position', () => {
    add('set_data', 0)
    add('set_data', 100)
    const [a, b] = useWorkflowStore.getState().nodes.map((n) => n.id)
    useWorkflowStore.getState().onConnect({ source: a, target: b })

    useWorkflowStore.getState().duplicateNodes([a, b])
    const { nodes, edges } = useWorkflowStore.getState()
    expect(nodes).toHaveLength(4)
    expect(edges).toHaveLength(2)

    const copyA = nodes.find((n) => n.data.node.type === 'set_data' && n.position.x === 40)
    const copyB = nodes.find((n) => n.data.node.type === 'set_data' && n.position.x === 140)
    expect(copyA).toBeDefined()
    expect(copyB).toBeDefined()
    expect(copyA.id).not.toBe(a)
    expect(copyA.selected).toBe(true)

    const internal = edges.find((e) => e.source === copyA.id && e.target === copyB.id)
    expect(internal).toBeDefined()
    expect(useUiStore.getState().selectedNodeId).toBe(copyA.id)
  })
})

describe('deleteNodes', () => {
  it('removes nodes and any touching edge, clears selection', () => {
    add('set_data', 0)
    add('set_data', 100)
    add('set_data', 200)
    const [a, b, c] = useWorkflowStore.getState().nodes.map((n) => n.id)
    useWorkflowStore.getState().onConnect({ source: a, target: b })
    useWorkflowStore.getState().onConnect({ source: b, target: c })
    useUiStore.getState().selectNode(b)

    useWorkflowStore.getState().deleteNodes([b])
    const { nodes, edges } = useWorkflowStore.getState()
    expect(nodes.map((n) => n.id)).toEqual([a, c])
    expect(edges).toHaveLength(0)
    expect(useUiStore.getState().selectedNodeId).toBeNull()
  })
})

describe('generateWorkflow', () => {
  it('stores the candidate as a preview without creating anything', async () => {
    const candidate = { workflow: { id: 'wf_ai', name: 'Poller', status: 'draft', nodes: [], connections: [], settings: {} },
      validation: { ok: true, errors: [], warnings: [] }, attempts: 1, created: false }
    mockApi.generateWorkflow.mockResolvedValue(candidate)

    await useWorkflowStore.getState().generateWorkflow('poll the api')

    expect(mockApi.generateWorkflow).toHaveBeenCalledWith('poll the api')
    // Approval gate: nothing is created until approveGenerated.
    expect(mockApi.createWorkflow).not.toHaveBeenCalled()
    expect(useWorkflowStore.getState().generated).toEqual(candidate)
  })

  it('approveGenerated creates the draft, loads it and clears the preview', async () => {
    const candidate = { workflow: { id: 'wf_ai', name: 'Poller', status: 'draft', nodes: [], connections: [], settings: {} },
      validation: { ok: true, errors: [], warnings: [] }, attempts: 1 }
    const saved = { ...candidate.workflow, version: 1 }
    const loaded = { ...saved, nodes: [], connections: [] }
    mockApi.generateWorkflow.mockResolvedValue(candidate)
    mockApi.createWorkflow.mockResolvedValue(saved)
    mockApi.getWorkflow.mockResolvedValue(loaded)
    useUiStore.getState().selectNode('set_data_1')
    await useWorkflowStore.getState().generateWorkflow('poll the api')

    await useWorkflowStore.getState().approveGenerated()

    expect(mockApi.createWorkflow).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'wf_ai', status: 'draft' }),
    )
    expect(mockApi.getWorkflow).toHaveBeenCalledWith(saved.id)
    expect(useWorkflowStore.getState().workflow).toEqual(loaded)
    expect(useWorkflowStore.getState().generated).toBeNull()
    expect(useUiStore.getState().selectedNodeId).toBeNull()
  })

  it('discardGenerated clears the preview without side effects', async () => {
    const candidate = { workflow: { id: 'wf_ai', nodes: [] }, validation: { ok: false, errors: [{ code: 'X' }], warnings: [] } }
    mockApi.generateWorkflow.mockResolvedValue(candidate)
    await useWorkflowStore.getState().generateWorkflow('x')

    useWorkflowStore.getState().discardGenerated()

    expect(useWorkflowStore.getState().generated).toBeNull()
    expect(mockApi.createWorkflow).not.toHaveBeenCalled()
  })

  it('propagates API errors and leaves the canvas untouched', async () => {
    mockApi.generateWorkflow.mockRejectedValue(new Error('No usable llm credential'))
    const before = useWorkflowStore.getState().workflow

    await expect(useWorkflowStore.getState().generateWorkflow('x')).rejects.toThrow(
      'No usable llm credential',
    )
    expect(useWorkflowStore.getState().workflow).toBe(before)
    expect(mockApi.createWorkflow).not.toHaveBeenCalled()
  })
})
describe('save', () => {
  it('PUTs the mapped workflow and records savedAt', async () => {
    const wf = { id: 'wf_1', name: 'My Workflow', version: 1, active: false, nodes: [], connections: [] }
    const saved = { ...wf, name: 'My Workflow', version: 2, active: false }
    useWorkflowStore.setState({ workflow: wf, savedAt: null, saving: false })
    add('set_data', 0)
    add('set_data', 100)
    const [a, b] = useWorkflowStore.getState().nodes.map((n) => n.id)
    useWorkflowStore.getState().onConnect({ source: a, target: b })
    mockApi.saveWorkflow.mockResolvedValue(saved)

    const result = await useWorkflowStore.getState().save()

    expect(mockApi.saveWorkflow).toHaveBeenCalledTimes(1)
    const [savedId, payload] = mockApi.saveWorkflow.mock.calls[0]
    expect(savedId).toBe('wf_1')
    expect(payload.nodes).toHaveLength(2)
    expect(payload.nodes.map((n) => n.type)).toEqual(['set_data', 'set_data'])
    expect(payload.connections).toHaveLength(1)
    expect(result).toBe(saved)
    expect(useWorkflowStore.getState().workflow).toBe(saved)
    expect(useWorkflowStore.getState().savedAt).not.toBeNull()
    expect(useWorkflowStore.getState().saving).toBe(false)
  })

  it('reports save errors and clears the saving flag', async () => {
    const wf = { id: 'wf_1', name: 'My Workflow', version: 1, active: false, nodes: [], connections: [] }
    useWorkflowStore.setState({ workflow: wf, savedAt: null, saving: false })
    mockApi.saveWorkflow.mockRejectedValue(new Error('Invalid workflow'))

    await expect(useWorkflowStore.getState().save()).rejects.toThrow('Invalid workflow')
    expect(useWorkflowStore.getState().saving).toBe(false)
    expect(useWorkflowStore.getState().error).toBe('Invalid workflow')
  })
})

describe('deleteWorkflow', () => {
  it('deletes, resets the canvas, and loads the next workflow', async () => {
    const wf = { id: 'wf_1', name: 'Old', version: 1, active: false, nodes: [], connections: [], settings: {} }
    const next = { id: 'wf_2', name: 'Next', version: 1, active: false, nodes: [], connections: [], settings: {} }
    useWorkflowStore.setState({ workflow: wf })
    add('set_data', 0)
    mockApi.deleteWorkflow.mockResolvedValue(undefined)
    mockApi.listWorkflows.mockResolvedValue([next])
    mockApi.getWorkflow.mockResolvedValue(next)

    await useWorkflowStore.getState().deleteWorkflow('wf_1')

    expect(mockApi.deleteWorkflow).toHaveBeenCalledWith('wf_1')
    expect(mockApi.getWorkflow).toHaveBeenCalledWith('wf_2')
    expect(useWorkflowStore.getState().workflow).toBe(next)
    expect(useWorkflowStore.getState().nodes).toHaveLength(0)
  })

  it('creates a fresh workflow when the last one is deleted', async () => {
    const wf = { id: 'wf_1', name: 'Solo', version: 1, active: false, nodes: [], connections: [], settings: {} }
    const fresh = { id: 'fresh', name: 'My Workflow', version: 1, active: false, nodes: [], connections: [], settings: {} }
    useWorkflowStore.setState({ workflow: wf })
    mockApi.deleteWorkflow.mockResolvedValue(undefined)
    mockApi.listWorkflows.mockResolvedValue([])
    mockApi.createWorkflow.mockResolvedValue(fresh)

    await useWorkflowStore.getState().deleteWorkflow('wf_1')

    expect(mockApi.createWorkflow).toHaveBeenCalled()
    expect(useWorkflowStore.getState().workflow).toBe(fresh)
    expect(useWorkflowStore.getState().nodes.map((n) => n.data.node.type)).toEqual(['manual_trigger'])
  })

  it('propagates API errors and leaves the current workflow intact', async () => {
    const wf = { id: 'wf_1', name: 'Old', version: 1, active: false, nodes: [], connections: [], settings: {} }
    useWorkflowStore.setState({ workflow: wf })
    add('set_data', 0)
    const nodesBefore = useWorkflowStore.getState().nodes
    mockApi.deleteWorkflow.mockRejectedValue(new Error('Not found'))

    await expect(useWorkflowStore.getState().deleteWorkflow('wf_1')).rejects.toThrow('Not found')
    expect(useWorkflowStore.getState().workflow).toBe(wf)
    expect(useWorkflowStore.getState().nodes).toBe(nodesBefore)
  })
})

describe('load / refresh', () => {
  it('hydrates nodes/edges from the saved workflow and marks it saved', async () => {
    const saved = {
      id: 'wf_1',
      name: 'Saved Workflow',
      version: 2,
      active: true,
      nodes: [
        { id: 'trigger', type: 'manual_trigger', position: { x: 0, y: 0 }, parameters: {}, settings: {} },
        { id: 'transform', type: 'set_data', position: { x: 100, y: 0 }, parameters: { fields: {} }, settings: {} },
      ],
      connections: [{ source: 'trigger', sourceHandle: 'main', target: 'transform', targetHandle: 'main' }],
      settings: {},
    }
    mockApi.getWorkflow.mockResolvedValue(saved)

    await useWorkflowStore.getState().load('wf_1')

    const state = useWorkflowStore.getState()
    expect(state.workflow).toBe(saved)
    expect(state.nodes.map((n) => n.id)).toEqual(['trigger', 'transform'])
    expect(state.edges).toHaveLength(1)
    expect(state.savedAt).not.toBeNull()
    expect(state.loading).toBe(false)
  })

  it('init reloads the most recent workflow after a browser refresh', async () => {
    const wf = { id: 'wf_1', name: 'Refreshed', version: 3, active: false, nodes: [], connections: [], settings: {} }
    mockApi.listNodes.mockResolvedValue([])
    mockApi.listWorkflows.mockResolvedValue([wf])
    mockApi.getWorkflow.mockResolvedValue(wf)
    useWorkflowStore.setState({ loading: true, workflow: null })

    await useWorkflowStore.getState().init()

    const state = useWorkflowStore.getState()
    expect(state.loading).toBe(false)
    expect(mockApi.getWorkflow).toHaveBeenCalledWith('wf_1')
    expect(state.workflow.id).toBe('wf_1')
    expect(state.savedAt).not.toBeNull()
  })

  it('init is idempotent under double invocation (StrictMode)', async () => {
    const wf = { id: 'wf_1', name: 'Only One', version: 1, active: false, nodes: [], connections: [], settings: {} }
    mockApi.listNodes.mockResolvedValue([])
    mockApi.listWorkflows.mockResolvedValue([])
    mockApi.createWorkflow.mockResolvedValue(wf)
    useWorkflowStore.setState({ loading: true, workflow: null })

    await Promise.all([useWorkflowStore.getState().init(), useWorkflowStore.getState().init()])

    expect(mockApi.createWorkflow).toHaveBeenCalledTimes(1)
    expect(useWorkflowStore.getState().workflow.id).toBe('wf_1')
  })

  it('keeps loading=true until the workflow is hydrated (no early-canvas race)', async () => {
    let resolveCreate
    mockApi.listNodes.mockResolvedValue([])
    mockApi.listWorkflows.mockResolvedValue([])
    mockApi.createWorkflow.mockImplementation(
      () => new Promise((res) => { resolveCreate = res }),
    )
    useWorkflowStore.setState({ loading: true, workflow: null })

    const p = useWorkflowStore.getState().init()
    await vi.waitFor(() => expect(resolveCreate).toBeDefined())
    // While createNew is in flight, the canvas must stay hidden so edits
    // cannot race the hydration and be clobbered.
    expect(useWorkflowStore.getState().loading).toBe(true)
    resolveCreate({ id: 'wf_1', name: 'My Workflow', version: 1, active: false, nodes: [], connections: [], settings: {} })
    await p
    expect(useWorkflowStore.getState().loading).toBe(false)
    expect(useWorkflowStore.getState().workflow.id).toBe('wf_1')
  })
})

describe('clearSelection', () => {
  it('unselects all nodes and the config panel selection', () => {
    add('set_data', 0)
    add('set_data', 100)
    useWorkflowStore.setState({
      nodes: useWorkflowStore.getState().nodes.map((n) => ({ ...n, selected: true })),
    })
    useUiStore.getState().selectNode('set_data_1')

    useWorkflowStore.getState().clearSelection()
    expect(useWorkflowStore.getState().nodes.every((n) => !n.selected)).toBe(true)
    expect(useUiStore.getState().selectedNodeId).toBeNull()
  })
})

describe('connector-only node types', () => {
  it('can be added with connector defaults from the catalog', () => {
    const salesforce = {
      type: 'salesforce',
      display_name: 'Salesforce',
      icon: '??',
      credential_types: ['salesforce'],
      parameters_schema: {
        type: 'object',
        properties: {
          operation: { type: 'string', enum: ['query', 'create'], default: 'query' },
          soql: { type: 'string', default: 'SELECT Id FROM Account' },
        },
      },
    }
    useWorkflowStore.setState({ catalog: [salesforce] })
    useWorkflowStore.getState().addNode('salesforce', { x: 10, y: 10 })
    const node = useWorkflowStore.getState().nodes.find((n) => n.id === 'salesforce_1')
    expect(node.data.node.parameters).toEqual({
      operation: 'query',
      soql: 'SELECT Id FROM Account',
      resource: 'Account',
    })
    expect(node.data.node.type).toBe('salesforce')
  })
})

describe('insertNodeOnEdge', () => {
  it('splits the edge and connects source -> new node -> target', () => {
    add('set_data', 0)
    add('set_data', 200)
    const [a, b] = useWorkflowStore.getState().nodes.map((n) => n.id)
    const edgeId = 'edge_ab'
    useWorkflowStore.setState({
      edges: [{ id: edgeId, source: a, target: b, type: 'exec' }],
    })

    const newId = useWorkflowStore.getState().insertNodeOnEdge(edgeId, 'http_request')
    const state = useWorkflowStore.getState()

    expect(state.nodes.some((n) => n.id === newId)).toBe(true)
    expect(state.edges.some((e) => e.id === edgeId)).toBe(false)
    expect(state.edges.some((e) => e.source === a && e.target === newId)).toBe(true)
    expect(state.edges.some((e) => e.source === newId && e.target === b)).toBe(true)
    expect(useUiStore.getState().selectedNodeId).toBe(newId)
  })
})

describe('group frames', () => {
  it('creates, updates, syncs bounds on move, and ungroups correctly', () => {
    add('set_data', 100)
    const node = useWorkflowStore.getState().nodes[0]
    const groupId = useWorkflowStore.getState().groupSelected([node.id], 'Stage 1', 'emerald')
    const state = useWorkflowStore.getState()
    expect(state.groups).toHaveLength(1)
    expect(state.groups[0].label).toBe('Stage 1')
    expect(state.groups[0].color).toBe('emerald')

    // Updating group properties
    useWorkflowStore.getState().updateGroup(groupId, { label: 'New Label', color: 'purple' })
    expect(useWorkflowStore.getState().groups[0].label).toBe('New Label')
    expect(useWorkflowStore.getState().groups[0].color).toBe('purple')

    // Moving member node triggers syncGroupBounds without throwing ReferenceError
    useWorkflowStore.getState().onNodesChange([
      { id: node.id, type: 'position', position: { x: 120, y: 10 } },
    ])
    expect(useWorkflowStore.getState().groups).toHaveLength(1)

    // Ungroup removes the frame while keeping the node
    useWorkflowStore.getState().ungroup(groupId)
    expect(useWorkflowStore.getState().groups).toHaveLength(0)
    expect(useWorkflowStore.getState().nodes).toHaveLength(1)
  })
})

