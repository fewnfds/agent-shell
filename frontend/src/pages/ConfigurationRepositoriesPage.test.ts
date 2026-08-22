import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useConfirmation } from '@/composables/useConfirmation'
import { useToasts } from '@/composables/useToasts'
import { en } from '@/locales/en'

import ConfigurationRepositoriesPage from './ConfigurationRepositoriesPage.vue'

const api = vi.hoisted(() => ({
  listConfigurationRepositories: vi.fn(),
  activateConfigurationRepository: vi.fn(),
  copyConfigurationRepository: vi.fn(),
  downloadConfigurationRepository: vi.fn(),
  deleteConfigurationRepository: vi.fn(),
  validateRepository: vi.fn(),
}))
const triggerBrowserDownload = vi.hoisted(() => vi.fn())

vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return { ...actual, managementApi: { ...actual.managementApi, ...api } }
})
vi.mock('@/utils/download', () => ({ triggerBrowserDownload }))

const active = {
  id: '11111111-1111-4111-8111-111111111111',
  name: 'Default',
  schema_version: 1 as const,
  active: true,
}
const inactive = {
  id: '22222222-2222-4222-8222-222222222222',
  name: 'Experiment',
  schema_version: 1 as const,
  active: false,
}

function rowByName(wrapper: ReturnType<typeof mount>, name: string) {
  const row = wrapper.findAll('[data-testid="data-table-row"]')
    .find((candidate) => candidate.text().includes(name))
  if (!row) throw new Error(`Repository row not found: ${name}`)
  return row
}

beforeEach(() => {
  vi.clearAllMocks()
  api.listConfigurationRepositories.mockResolvedValue({
    active_id: active.id,
    repositories: [active, inactive],
  })
  api.activateConfigurationRepository.mockResolvedValue({
    ...inactive,
    active: true,
    restart_required: false,
    validation: { valid: true, stage: 'repository', issues: [] },
  })
  api.copyConfigurationRepository.mockResolvedValue({
    ...inactive,
    id: '33333333-3333-4333-8333-333333333333',
    name: 'Experiment copy',
  })
  api.downloadConfigurationRepository.mockResolvedValue({
    blob: new Blob(['repository']),
    filename: 'Experiment.agent-shell-repository.zip',
  })
  api.deleteConfigurationRepository.mockResolvedValue({ ok: true })
  api.validateRepository.mockResolvedValue({ valid: true, stage: 'repository', issues: [] })
})

afterEach(() => {
  useConfirmation().cancel()
  const toasts = useToasts()
  for (const item of toasts.items.value) toasts.dismiss(item.id)
})

describe('ConfigurationRepositoriesPage', () => {
  it('uses the common table actions and prevents deleting the active repository', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/library/configuration-repositories', component: ConfigurationRepositoriesPage }],
    })
    await router.push('/library/configuration-repositories')
    await router.isReady()
    const wrapper = mount(ConfigurationRepositoriesPage, {
      global: {
        plugins: [createI18n({ legacy: false, locale: 'en', messages: { en } }), router],
      },
    })
    await flushPromises()

    const activeRow = rowByName(wrapper, 'Default')
    const inactiveRow = rowByName(wrapper, 'Experiment')
    expect(activeRow.text()).toContain('Active')
    expect(activeRow.get('[data-action="delete"]').attributes('disabled')).toBeDefined()
    expect(activeRow.find('[data-action="activate"]').exists()).toBe(false)

    await inactiveRow.get('[data-action="activate"]').trigger('click')
    await flushPromises()
    expect(api.activateConfigurationRepository).toHaveBeenCalledWith(inactive.id)

    await rowByName(wrapper, 'Experiment').get('[data-action="copy"]').trigger('click')
    await flushPromises()
    await wrapper.get('#configuration-repository-copy-form input').setValue('Experiment copy')
    await wrapper.get('#configuration-repository-copy-form').trigger('submit')
    await flushPromises()
    expect(api.copyConfigurationRepository).toHaveBeenCalledWith(inactive.id, 'Experiment copy')

    await rowByName(wrapper, 'Experiment').get('[data-action="download"]').trigger('click')
    await flushPromises()
    expect(api.downloadConfigurationRepository).toHaveBeenCalledWith(inactive.id)
    expect(triggerBrowserDownload).toHaveBeenCalledWith(
      expect.any(Blob),
      'Experiment.agent-shell-repository.zip',
    )

    await rowByName(wrapper, 'Experiment').get('[data-action="delete"]').trigger('click')
    expect(useConfirmation().current.value?.description).toContain('Experiment')
    useConfirmation().accept()
    await flushPromises()
    expect(api.deleteConfigurationRepository).toHaveBeenCalledWith(inactive.id)

    wrapper.unmount()
  })
})
