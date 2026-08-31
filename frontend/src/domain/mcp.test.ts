import { describe, expect, it } from 'vitest'

import { mcpConnectionAdapter } from '@/domain/blocks'
import { blankMcpReference, mcpReferencePayload, normalizeMcpReference } from '@/domain/mcp'

describe('MCP authoring adapters', () => {
  it('preserves masked secret slots while keeping literal values visible', () => {
    const draft = mcpConnectionAdapter.fromApi({
      id: '11111111-1111-4111-8111-111111111111',
      name: 'Remote MCP',
      transport: 'http',
      url: 'https://example.test/mcp',
      headers: {
        Authorization: { source: 'secret', status: 'masked' },
        'X-Tenant': { source: 'literal', value: 'alpha' },
      },
    })

    expect(mcpConnectionAdapter.toPayload(draft)).toEqual({
      name: 'Remote MCP',
      transport: 'http',
      url: 'https://example.test/mcp',
      headers: {
        Authorization: { source: 'secret', status: 'masked' },
        'X-Tenant': { source: 'literal', value: 'alpha' },
      },
    })
  })

  it('normalizes and emits the official raw Tool selection shape', () => {
    expect(blankMcpReference()).toEqual({
      requirement_id: '',
      tool_selection: { mode: 'all', tools: [] },
    })
    const normalized = normalizeMcpReference({
      requirement_id: '22222222-2222-4222-8222-222222222222',
      tool_selection: { mode: 'include', tools: [' search ', 'open'] },
      ignored: true,
    })
    expect(mcpReferencePayload(normalized)).toEqual({
      requirement_id: '22222222-2222-4222-8222-222222222222',
      tool_selection: { mode: 'include', tools: ['search', 'open'] },
    })
  })
})
