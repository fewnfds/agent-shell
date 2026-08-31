import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { McpConnection, McpRequirementBinding, ModelConnection, ModelRequirementBinding } from '@/api'

import McpMappingPage from './McpMappingPage.vue'
import ModelMappingPage from './ModelMappingPage.vue'

const api = vi.hoisted(() => ({
  listModelConnections: vi.fn(),
  listModelRequirements: vi.fn(),
  bindModelRequirement: vi.fn(),
  listMcpConnections: vi.fn(),
  listMcpRequirements: vi.fn(),
  bindMcpRequirement: vi.fn(),
}))

vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return { ...actual, managementApi: api }
})

const messages = {
  navigation: {
    system: 'System', models: 'Models', mcp: 'MCP',
    sectionAriaLabel: 'Current section',
    sections: { modelConnections: 'Model connections', modelMapping: 'Model mapping' },
  },
  mcp: {
    mapping: {
      warningTitle: 'MCP mapping needed', warning: '{count} MCP unbound', description: 'Description',
      connection: 'Connection', unbound: 'Unbound', empty: 'No MCP requirements', loadFailed: 'Load failed',
      stdioSummary: '{name} · stdio · {command}', httpSummary: '{name} · HTTP · {url}',
    },
  },
  models: {
    mapping: {
      warningTitle: 'Requirements need mapping', warning: '{count} unbound', description: 'Description',
      connection: 'Connection', connectionSummary: '{model} ({configuration} / {provider} provider)',
      unbound: 'Unbound', empty: 'No requirements', loadFailed: 'Load failed',
    },
  },
}

const connection: ModelConnection = {
  id: '11111111-1111-4111-8111-111111111111', name: 'Local GPT', provider: 'openai', base_url: 'https://example.test/v1',
  credential: { status: 'masked' }, model: 'gpt-local', provider_settings: {}, tool_choice: null, response_format: null, model_settings: {},
}
const mcpConnection: McpConnection = {
  id: '22222222-2222-4222-8222-222222222222',
  name: 'Browser MCP',
  transport: 'stdio',
  command: 'npx',
  args: ['playwright-mcp'],
  env: {},
}
function requirement(id: string, binding: string | null): ModelRequirementBinding {
  return { id, name: 'Reasoning requirement', description: 'Use a reasoning-capable local model.', binding, connection: binding ? connection : null }
}
function mcpRequirement(id: string, binding: string | null): McpRequirementBinding {
  return {
    id,
    name: 'Browser access',
    description: 'Navigate and inspect web pages.',
    namespace: 'browser',
    binding,
    connection: binding ? mcpConnection : null,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((accept) => {
    resolve = accept
  })
  return { promise, resolve }
}

function i18n() {
  return createI18n({ legacy: false, locale: 'en', messages: { en: messages } })
}

async function mountPage(component: typeof ModelMappingPage, path: string) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/models/:page', component }] })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(component, {
    attachTo: document.body,
    global: {
      plugins: [router, i18n()],
    },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
  api.listModelConnections.mockResolvedValue([connection])
  api.listModelRequirements.mockResolvedValue([requirement('33333333-3333-4333-8333-333333333333', null)])
  api.bindModelRequirement.mockImplementation(async (_id: string, connectionId: string | null) => requirement('33333333-3333-4333-8333-333333333333', connectionId))
  api.listMcpConnections.mockResolvedValue([mcpConnection])
  api.listMcpRequirements.mockResolvedValue([mcpRequirement('44444444-4444-4444-8444-444444444444', null)])
  api.bindMcpRequirement.mockImplementation(async (_id: string, connectionId: string | null) => mcpRequirement('44444444-4444-4444-8444-444444444444', connectionId))
})

describe('model management pages', () => {
  it('shows requirement description and binds or clears a local connection', async () => {
    const wrapper = await mountPage(ModelMappingPage, '/models/mapping')
    expect(wrapper.get('[data-testid="model-mapping-cards"]').text()).toContain('Use a reasoning-capable local model.')
    expect(wrapper.get('option[value="11111111-1111-4111-8111-111111111111"]').text()).toBe('gpt-local (Local GPT / openai provider)')
    expect(wrapper.find('[role="alert"]').text()).toContain('1 unbound')

    await wrapper.get('select').setValue(connection.id)
    await flushPromises()
    expect(api.bindModelRequirement).toHaveBeenCalledWith('33333333-3333-4333-8333-333333333333', connection.id)

    await wrapper.get('select').setValue('')
    await flushPromises()
    expect(api.bindModelRequirement).toHaveBeenLastCalledWith('33333333-3333-4333-8333-333333333333', null)
    wrapper.unmount()
  })

  it('serializes changes for each Model Requirement while its binding is saved', async () => {
    const pending = deferred<ModelRequirementBinding>()
    api.bindModelRequirement.mockReturnValueOnce(pending.promise)
    const wrapper = await mountPage(ModelMappingPage, '/models/mapping')
    const select = wrapper.get('select')

    await select.setValue(connection.id)
    expect(select.attributes('disabled')).toBeDefined()
    expect(wrapper.get('.action-button').attributes('disabled')).toBeDefined()
    await select.setValue('')
    expect(api.bindModelRequirement).toHaveBeenCalledTimes(1)

    pending.resolve(requirement('33333333-3333-4333-8333-333333333333', connection.id))
    await flushPromises()
    expect(select.attributes('disabled')).toBeUndefined()
    expect((select.element as HTMLSelectElement).value).toBe(connection.id)
    wrapper.unmount()
  })

  it('renders the explicit empty state when the active repository has no requirements', async () => {
    api.listModelRequirements.mockResolvedValueOnce([])
    const wrapper = await mountPage(ModelMappingPage, '/models/mapping')
    expect(wrapper.text()).toContain('No requirements')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('keeps warning visible when a stored binding points to a deleted connection', async () => {
    api.listModelRequirements.mockResolvedValueOnce([{
      ...requirement('33333333-3333-4333-8333-333333333333', 'missing-connection'),
      connection: null,
    }])
    const wrapper = await mountPage(ModelMappingPage, '/models/mapping')
    expect(wrapper.find('[role="alert"]').text()).toContain('1 unbound')
    wrapper.unmount()
  })
})

describe('MCP mapping page', () => {
  it('shows namespace and binds a requirement to one instance connection', async () => {
    const wrapper = await mountPage(McpMappingPage, '/models/mapping')
    expect(wrapper.get('[data-testid="mcp-mapping-cards"]').text()).toContain('browser')
    expect(wrapper.text()).toContain('Navigate and inspect web pages.')
    expect(wrapper.get(`option[value="${mcpConnection.id}"]`).text()).toContain('npx')

    await wrapper.get('select').setValue(mcpConnection.id)
    await flushPromises()
    expect(api.bindMcpRequirement).toHaveBeenCalledWith('44444444-4444-4444-8444-444444444444', mcpConnection.id)
    wrapper.unmount()
  })
})
