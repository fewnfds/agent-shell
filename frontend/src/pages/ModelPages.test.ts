import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ModelConnection, ModelRequirementBinding } from '@/api'

import ModelMappingPage from './ModelMappingPage.vue'

const api = vi.hoisted(() => ({
  listModelConnections: vi.fn(),
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
function requirement(id: string, binding: string | null): ModelRequirementBinding {
  return { id, name: 'Reasoning requirement', description: 'Use a reasoning-capable local model.', binding, connection: binding ? connection : null }
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
