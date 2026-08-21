import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ModelConnection, ModelProviderCatalog, ModelRequirementBinding } from '@/api'
import { useConfirmation } from '@/composables/useConfirmation'

import ModelConnectionsPage from './ModelConnectionsPage.vue'
import ModelMappingPage from './ModelMappingPage.vue'

const api = vi.hoisted(() => ({
  listModelConnections: vi.fn(),
  listModelProviders: vi.fn(),
  saveModelConnection: vi.fn(),
  copyModelConnection: vi.fn(),
  deleteModelConnection: vi.fn(),
  fetchModels: vi.fn(),
  listModelRequirements: vi.fn(),
  bindModelRequirement: vi.fn(),
}))

vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return { ...actual, managementApi: api }
})

const messages = {
  navigation: {
    system: 'System', models: 'Models',
    sectionAriaLabel: 'Current section',
    sections: { modelConnections: 'Model connections', modelMapping: 'Model mapping' },
  },
  models: {
    connections: {
      deleteTitle: 'Delete connection', deleteDescription: 'Delete {name}?', empty: 'No connections', loadFailed: 'Load failed',
      saveFailed: 'Save failed', copyFailed: 'Copy failed', deleteFailed: 'Delete failed', modelsFailed: 'Models failed',
      credentialReplacementRequired: 'Enter a new credential.',
    },
    mapping: {
      warningTitle: 'Requirements need mapping', warning: '{count} unbound', description: 'Description',
      connection: 'Connection', unbound: 'Unbound', empty: 'No requirements', loadFailed: 'Load failed',
    },
  },
  editors: { common: { refresh: 'Refresh' } },
  common: { new: 'New', copy: 'Copy', delete: 'Delete', save: 'Save', cancel: 'Cancel', configuredSecretPlaceholder: 'Configured', apiKeyPlaceholder: 'API key' },
  errors: {
    requestFailed: 'Request failed', modelConnectionInvalid: 'Invalid model', modelBindingInvalid: 'Invalid binding',
    modelConnectionNotFound: 'Connection not found', modelRequirementNotFound: 'Requirement not found',
    modelConnectionNameConflict: 'Name conflict', copyRequestInvalid: 'Invalid copy',
  },
}

const connection: ModelConnection = {
  id: '11111111-1111-4111-8111-111111111111', name: 'Local GPT', provider: 'openai', base_url: 'https://example.test/v1',
  credential: { status: 'masked' }, model: 'gpt-local', provider_settings: {}, tool_choice: null, response_format: null, model_settings: {},
}
const providerCatalog: ModelProviderCatalog = { langchain_version: '1.3.14', providers: [] }

function requirement(id: string, binding: string | null): ModelRequirementBinding {
  return { id, name: 'Reasoning requirement', description: 'Use a reasoning-capable local model.', binding, connection: binding ? connection : null }
}

function i18n() {
  return createI18n({ legacy: false, locale: 'en', messages: { en: messages } })
}

async function mountPage(component: typeof ModelConnectionsPage | typeof ModelMappingPage, path: string, stubs = {}) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/models/:page', component }] })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(component, {
    attachTo: document.body,
    global: {
      plugins: [router, i18n()],
      stubs: {
        ModelEditor: { template: '<div data-testid="model-editor-stub" />' },
        ...stubs,
      },
    },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
  api.listModelConnections.mockResolvedValue([connection])
  api.listModelProviders.mockResolvedValue(providerCatalog)
  api.saveModelConnection.mockImplementation(async (payload: { id?: string, name: string }) => ({
    ...connection,
    id: payload.id ?? '44444444-4444-4444-8444-444444444444',
    name: payload.name,
  }))
  api.copyModelConnection.mockResolvedValue({ ...connection, id: '22222222-2222-4222-8222-222222222222', name: 'Local GPT (copy)' })
  api.deleteModelConnection.mockResolvedValue({ ok: true })
  api.listModelRequirements.mockResolvedValue([requirement('33333333-3333-4333-8333-333333333333', null)])
  api.bindModelRequirement.mockImplementation(async (_id: string, connectionId: string | null) => requirement('33333333-3333-4333-8333-333333333333', connectionId))
})

afterEach(() => useConfirmation().cancel())

describe('model management pages', () => {
  it('creates and renames private model connections through the connection API', async () => {
    const wrapper = await mountPage(ModelConnectionsPage, '/models/connections')
    expect(wrapper.text()).toContain('Local GPT')
    expect(api.listModelConnections).toHaveBeenCalledOnce()
    expect(api.listModelProviders).toHaveBeenCalledOnce()

    await wrapper.get('[data-field="model-connection-name"]').setValue('Renamed connection')
    const actions = () => Array.from(document.body.querySelectorAll<HTMLButtonElement>('.page-action-dock button'))
    const saveButton = () => actions().find((button) => button.textContent?.trim() === 'Save')
    saveButton()?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(api.saveModelConnection).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({ id: connection.id, name: 'Renamed connection' }),
    )

    actions().find((button) => button.textContent?.trim() === 'New')
      ?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(saveButton()?.disabled).toBe(true)
    await wrapper.get('[data-field="model-connection-name"]').setValue('New connection')
    expect(saveButton()?.disabled).toBe(false)
    saveButton()?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(api.saveModelConnection).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ name: 'New connection' }),
    )
    expect(api.saveModelConnection.mock.calls[1]?.[0]).not.toHaveProperty('id')
    wrapper.unmount()
  })

  it('clears a previous save error after a successful retry', async () => {
    api.saveModelConnection
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(connection)
    const wrapper = await mountPage(ModelConnectionsPage, '/models/connections')
    const save = Array.from(document.body.querySelectorAll<HTMLButtonElement>('.page-action-dock button'))
      .find((button) => button.textContent?.trim() === 'Save')

    save?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)

    save?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('shows requirement description and binds or clears a local connection', async () => {
    const wrapper = await mountPage(ModelMappingPage, '/models/mapping')
    expect(wrapper.get('[data-testid="model-mapping-cards"]').text()).toContain('Use a reasoning-capable local model.')
    expect(wrapper.find('[role="alert"]').text()).toContain('1 unbound')

    await wrapper.get('select').setValue(connection.id)
    await flushPromises()
    expect(api.bindModelRequirement).toHaveBeenCalledWith('33333333-3333-4333-8333-333333333333', connection.id)

    await wrapper.get('select').setValue('')
    await flushPromises()
    expect(api.bindModelRequirement).toHaveBeenLastCalledWith('33333333-3333-4333-8333-333333333333', null)
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
