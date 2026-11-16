import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

vi.mock('../../api', () => ({
  api: {
    listWorkspaces: vi.fn().mockResolvedValue([]),
    listMCPServers: vi.fn().mockResolvedValue([]),
    createMCPServer: vi.fn(),
    updateMCPServer: vi.fn(),
    deleteMCPServer: vi.fn(),
    discoverMCPServerTools: vi.fn(),
    updateMCPTool: vi.fn(),
  },
}))

import MCPServersPanel from './MCPServersPanel'
import { EMPTY_MCP_SERVER_FORM } from './mcpServerForm'

describe('MCPServersPanel', () => {
  it('renders the workspace selector and empty-state guidance', () => {
    const html = renderToStaticMarkup(<MCPServersPanel />)
    expect(html).toContain('Add MCP server')
    expect(html).toContain('No workspaces')
    expect(html).toContain('Create a workspace before registering MCP servers.')
  })

  it('defaults new servers to the subprocess sandbox', () => {
    expect(EMPTY_MCP_SERVER_FORM.sandbox_backend).toBe('subprocess')
    expect(EMPTY_MCP_SERVER_FORM.sandbox_workspace_mode).toBe('none')
    expect(EMPTY_MCP_SERVER_FORM.sandbox_network).toBe('none')
    expect(EMPTY_MCP_SERVER_FORM.sandbox_read_only).toBe(true)
  })
})
