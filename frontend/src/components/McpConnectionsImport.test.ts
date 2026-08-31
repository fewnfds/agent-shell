import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { en } from '@/locales/en'

import McpConnectionsImport from './McpConnectionsImport.vue'

const api = vi.hoisted(() => ({
  previewMcpConnectionsImport: vi.fn(),
  importMcpConnections: vi.fn(),
}))
const notify = vi.hoisted(() => vi.fn())

vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return { ...actual, managementApi: api }
})
vi.mock('@/composables/useToasts', () => ({ useToasts: () => ({ notify }) }))

const i18n = () => createI18n({ legacy: false, locale: 'en', messages: { en } })

beforeEach(() => {
  vi.clearAllMocks()
  api.previewMcpConnectionsImport.mockResolvedValue({
    connections: [{
      name: 'browser',
      transport: 'stdio',
      values: [{ target: 'env', name: 'TOKEN', source: 'secret' }],
    }],
  })
  api.importMcpConnections.mockResolvedValue([{
    id: '11111111-1111-4111-8111-111111111111',
    name: 'browser',
    transport: 'stdio',
    command: 'npx',
    args: [],
    env: { TOKEN: { source: 'literal', value: 'demo' } },
  }])
})

describe('MCP connection JSON import', () => {
  it('previews canonical mcpServers JSON and commits explicit value storage choices', async () => {
    const wrapper = mount(McpConnectionsImport, {
      attachTo: document.body,
      global: { plugins: [i18n()] },
    })
    const json = '{"mcpServers":{"browser":{"command":"npx","env":{"TOKEN":"demo"}}}}'

    await wrapper.get('button').trigger('click')
    await flushPromises()
    await wrapper.get('#mcp-import-json').setValue(json)
    await wrapper.get('[data-action="mcp-import-preview"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="mcp-import-value-source"]').setValue('literal')
    await wrapper.get('[data-action="mcp-import-commit"]').trigger('click')
    await flushPromises()

    expect(api.previewMcpConnectionsImport).toHaveBeenCalledWith(json)
    expect(api.importMcpConnections).toHaveBeenCalledWith(json, {
      browser: { env: { TOKEN: 'literal' }, headers: {} },
    })
    expect(wrapper.emitted('imported')?.[0]?.[0]).toHaveLength(1)
    wrapper.unmount()
  })
})
