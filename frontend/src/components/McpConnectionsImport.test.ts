import { enableAutoUnmount, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { McpImportPreview } from '@/api'
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

enableAutoUnmount(afterEach)

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: Error) => void
  const promise = new Promise<T>((accept, fail) => {
    resolve = accept
    reject = fail
  })
  return { promise, resolve, reject }
}

async function mountImporter() {
  const wrapper = mount(McpConnectionsImport, {
    attachTo: document.body,
    global: { plugins: [i18n()] },
  })
  await wrapper.get('button').trigger('click')
  await flushPromises()
  return wrapper
}

async function selectFile(wrapper: VueWrapper, text: () => Promise<string>) {
  const file = new File([], 'mcp.json', { type: 'application/json' })
  Object.defineProperty(file, 'text', { value: text })
  const input = wrapper.get<HTMLInputElement>('input[type="file"]')
  Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })
  await input.trigger('change')
}

beforeEach(() => {
  vi.resetAllMocks()
  api.previewMcpConnectionsImport.mockResolvedValue({
    connections: [{
      name: 'browser',
      transport: 'stdio',
      package_source: 'npm',
      values: [{ target: 'env', name: 'TOKEN', source: 'secret' }],
    }],
  })
  api.importMcpConnections.mockResolvedValue([{
    id: '11111111-1111-4111-8111-111111111111',
    name: 'browser',
    transport: 'stdio',
    package_source: 'npm',
    package: '@playwright/mcp',
    version: '0.0.1',
    args: [],
    env: { TOKEN: { source: 'literal', value: 'demo' } },
    installation: {
      status: 'not_installed',
      package_source: 'npm',
      package: '@playwright/mcp',
      version: '0.0.1',
    },
  }])
})

afterEach(() => {
  document.body.replaceChildren()
})

describe('MCP connection JSON import', () => {
  it('previews canonical mcpServers JSON and commits explicit value storage choices', async () => {
    const wrapper = await mountImporter()
    const json = '{"mcpServers":{"browser":{"command":"npx","args":["-y","@playwright/mcp@0.0.1"],"env":{"TOKEN":"demo"}}}}'

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
  })

  it('keeps the input fixed during preview and requires a new preview after editing it', async () => {
    const pending = deferred<McpImportPreview>()
    api.previewMcpConnectionsImport.mockReturnValueOnce(pending.promise)
    const wrapper = await mountImporter()
    const alphaJson = '{"mcpServers":{"alpha":{"url":"https://alpha.example/mcp"}}}'
    const betaJson = '{"mcpServers":{"beta":{"url":"https://beta.example/mcp"}}}'
    const input = wrapper.get<HTMLTextAreaElement>('#mcp-import-json')

    await input.setValue(alphaJson)
    await wrapper.get('[data-action="mcp-import-preview"]').trigger('click')

    expect(input.element.disabled).toBe(true)
    expect(wrapper.get<HTMLInputElement>('input[type="file"]').element.disabled).toBe(true)
    expect(wrapper.get<HTMLButtonElement>('[data-action="mcp-import-commit"]').element.disabled).toBe(true)
    pending.resolve({ connections: [{ name: 'alpha', transport: 'http', values: [] }] })
    await flushPromises()
    expect(wrapper.get('tbody').text()).toContain('alpha')

    await input.setValue(betaJson)
    expect(wrapper.find('tbody').exists()).toBe(false)
    expect(wrapper.get<HTMLButtonElement>('[data-action="mcp-import-commit"]').element.disabled).toBe(true)
    api.previewMcpConnectionsImport.mockResolvedValueOnce({
      connections: [{ name: 'beta', transport: 'http', values: [] }],
    })
    await wrapper.get('[data-action="mcp-import-preview"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-action="mcp-import-commit"]').trigger('click')
    await flushPromises()

    expect(api.importMcpConnections).toHaveBeenCalledExactlyOnceWith(betaJson, {
      beta: { env: {}, headers: {} },
    })
  })

  it('keeps file reads busy and allows another file after a read failure', async () => {
    const pending = deferred<string>()
    const wrapper = await mountImporter()
    await selectFile(wrapper, () => pending.promise)

    expect(wrapper.get<HTMLTextAreaElement>('#mcp-import-json').element.disabled).toBe(true)
    expect(wrapper.get<HTMLInputElement>('input[type="file"]').element.disabled).toBe(true)
    expect(api.previewMcpConnectionsImport).not.toHaveBeenCalled()
    pending.reject(new Error('The selected file could not be read.'))
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain('The selected file could not be read.')
    expect(wrapper.get<HTMLInputElement>('input[type="file"]').element.disabled).toBe(false)
    const json = '{"mcpServers":{"browser":{"command":"npx","args":["@playwright/mcp"]}}}'
    await selectFile(wrapper, async () => json)
    await flushPromises()

    expect(api.previewMcpConnectionsImport).toHaveBeenCalledExactlyOnceWith(json)
    expect(wrapper.get<HTMLTextAreaElement>('#mcp-import-json').element.value).toBe(json)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.get<HTMLButtonElement>('[data-action="mcp-import-commit"]').element.disabled).toBe(false)
  })

  it('does not start a preview when a file read finishes after unmount', async () => {
    const pending = deferred<string>()
    const wrapper = await mountImporter()
    await selectFile(wrapper, () => pending.promise)
    wrapper.unmount()
    pending.resolve('{"mcpServers":{"alpha":{"url":"https://alpha.example/mcp"}}}')
    await flushPromises()

    expect(api.previewMcpConnectionsImport).not.toHaveBeenCalled()
  })
})
