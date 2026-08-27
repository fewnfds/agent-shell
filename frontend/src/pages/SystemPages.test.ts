import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import type {
  ApiServerSettings,
  ApiServerSettingsUpdate,
  RuntimePolicySettings,
  RuntimePolicyUpdate,
  SystemSettings,
  SystemSettingsUpdate,
} from '@/api'

import SystemSettingsPage from './SystemSettingsPage.vue'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    locale: { value: 'en' },
    t: (key: string) => key,
    te: () => true,
  }),
}))

const currentSettings: SystemSettings = {
  host: '127.0.0.1',
  port: 19100,
  allow_remote: false,
  langsmith_tracing_enabled: false,
  langsmith_endpoint: 'https://api.smith.langchain.com',
  langsmith_project: 'agent-shell',
  langsmith_workspace_id: null,
  langsmith_api_key: { configured: true },
  management_token: { configured: true },
  cors_origins: [],
  trusted_proxy_cidrs: [],
  restart_required: false,
  active_management_url: 'http://127.0.0.1:19100/admin',
}

const currentApiServerSettings: ApiServerSettings = {
  enabled: false,
  status: 'stopped',
  api_key: { configured: true },
  max_initial_messages: 1000,
  message_interception_enabled: false,
  api_base_url: 'http://127.0.0.1:19100/v1',
  models_endpoint: 'http://127.0.0.1:19100/v1/models',
  chat_completions_endpoint: 'http://127.0.0.1:19100/v1/chat/completions',
  runtime: 'model_streaming',
}

function validationSettingsApi() {
  return {
    getValidationSettings: vi.fn().mockResolvedValue({
      debounce_ms: 1000,
      min_debounce_ms: 100,
    }),
    updateValidationSettings: vi.fn().mockResolvedValue({
      debounce_ms: 1000,
      min_debounce_ms: 100,
    }),
  }
}

const runtimePolicyValues: RuntimePolicySettings['defaults'] = {
  workflow_debug_capture_enabled: false,
  chat_completion_body_bytes: 64 * 1024 * 1024,
  content_blocks: 4096,
  decoded_block_bytes: 24 * 1024 * 1024,
  decoded_total_bytes: 48 * 1024 * 1024,
  media_output_bytes: 64 * 1024 * 1024,
  text_edit_bytes: 2 * 1024 * 1024,
  provider_timeout_seconds: 600,
  provider_connect_timeout_seconds: 5,
  provider_catalog_timeout_seconds: 15,
}

function runtimePolicyApi() {
  const settings: RuntimePolicySettings = {
    ...runtimePolicyValues,
    defaults: { ...runtimePolicyValues },
    minimums: Object.fromEntries(
      Object.keys(runtimePolicyValues).map((key) => [
        key,
        key === 'workflow_debug_capture_enabled' ? false : 1,
      ]),
    ) as RuntimePolicySettings['minimums'],
    configurable: true,
  }
  return {
    getRuntimePolicy: vi.fn().mockResolvedValue(settings),
    updateRuntimePolicy: vi.fn().mockImplementation(async (payload: RuntimePolicyUpdate) => ({
      ...settings,
      ...payload,
    })),
  }
}

describe('SystemSettingsPage', () => {
  it('loads and saves typed system settings without filling secret values', async () => {
    const api = {
      ...validationSettingsApi(),
      ...runtimePolicyApi(),
      getSystemSettings: vi.fn().mockResolvedValue(currentSettings),
      getApiServer: vi.fn().mockResolvedValue(currentApiServerSettings),
      updateSystemSettings: vi.fn().mockResolvedValue({
        ...currentSettings,
        restart_required: true,
      }),
      saveApiServer: vi.fn().mockResolvedValue(currentApiServerSettings),
    }
    const wrapper = mount(SystemSettingsPage, { props: { api } })
    await flushPromises()

    const cards = wrapper.findAll('[data-testid^="system-card-"]')
    expect(cards).toHaveLength(4)
    expect(cards.every((card) => !card.classes().includes('card-primary'))).toBe(true)
    expect(cards.map((card) => card.get('.card-header i').classes().find((name) => name.startsWith('bi-'))))
      .toEqual(['bi-hdd-network', 'bi-sliders', 'bi-gear', 'bi-shield-lock'])
    expect(cards.every((card) => card.get('.card-title').element.tagName === 'H2')).toBe(true)

    const saveButtons = wrapper.findAll('button').filter((button) => button.text() === 'common.save')
    expect(saveButtons).toHaveLength(1)
    await saveButtons[0]!.trigger('click')
    await flushPromises()

    expect(api.updateSystemSettings).toHaveBeenCalledWith({
      host: '127.0.0.1',
      port: 19100,
      allow_remote: false,
      langsmith_tracing_enabled: false,
      langsmith_endpoint: 'https://api.smith.langchain.com',
      langsmith_project: 'agent-shell',
      langsmith_workspace_id: null,
      langsmith_api_key: { operation: 'keep' },
      management_token: { operation: 'preserve' },
      cors_origins: [],
      trusted_proxy_cidrs: [],
    })
    expect(api.saveApiServer).toHaveBeenCalledWith({
      api_key: { operation: 'keep' },
      max_initial_messages: 1000,
    })
    expect(wrapper.text()).toContain('systemSettings.restartRequired')
    expect(wrapper.text()).not.toContain('test-management-token')
  })

  it('converts edited number, switch, secret and multiline fields into the backend payload', async () => {
    const api = {
      ...validationSettingsApi(),
      ...runtimePolicyApi(),
      getSystemSettings: vi.fn().mockResolvedValue(currentSettings),
      getApiServer: vi.fn().mockResolvedValue(currentApiServerSettings),
      updateSystemSettings: vi.fn().mockImplementation(async (payload: SystemSettingsUpdate) => ({
        ...currentSettings,
        host: payload.host,
        port: payload.port,
        allow_remote: payload.allow_remote,
        cors_origins: payload.cors_origins,
        trusted_proxy_cidrs: payload.trusted_proxy_cidrs,
      })),
      saveApiServer: vi.fn().mockImplementation(async (payload: ApiServerSettingsUpdate) => ({
        ...currentApiServerSettings,
        max_initial_messages: payload.max_initial_messages ?? 1000,
      })),
    }
    const wrapper = mount(SystemSettingsPage, { props: { api } })
    await flushPromises()

    await wrapper.get('input[type="text"]').setValue('0.0.0.0')
    await wrapper.get('#system-port').setValue('21000')
    await wrapper.get('#allow-remote').setValue(true)
    await wrapper.get('#management-password').setValue('new-management-password')
    await wrapper.get('#api-server-key').setValue('new-api-key')
    await wrapper.get('#max-initial-messages').setValue('2500')
    await wrapper.get('#langsmith-tracing').setValue(true)
    await wrapper.get('#langsmith-api-key').setValue('new-langsmith-key')
    const textareas = wrapper.findAll('textarea')
    await textareas[0]!.setValue('http://localhost:3000\nhttp://127.0.0.1:3000')
    await textareas[1]!.setValue('127.0.0.1/32')
    const save = wrapper.findAll('button').find((button) => button.text() === 'common.save')
    await save!.trigger('click')
    await flushPromises()

    expect(api.updateSystemSettings).toHaveBeenCalledWith({
      host: '0.0.0.0',
      port: 21000,
      allow_remote: true,
      langsmith_tracing_enabled: true,
      langsmith_endpoint: 'https://api.smith.langchain.com',
      langsmith_project: 'agent-shell',
      langsmith_workspace_id: null,
      langsmith_api_key: { operation: 'replace', value: 'new-langsmith-key' },
      management_token: { operation: 'replace', value: 'new-management-password' },
      cors_origins: ['http://localhost:3000', 'http://127.0.0.1:3000'],
      trusted_proxy_cidrs: ['127.0.0.1/32'],
    })
    expect(api.saveApiServer).toHaveBeenCalledWith({
      api_key: { operation: 'replace', value: 'new-api-key' },
      max_initial_messages: 2500,
    })
  })

  it('reveals only newly entered credentials and clears edited API keys through the unified save', async () => {
    const api = {
      ...validationSettingsApi(),
      ...runtimePolicyApi(),
      getSystemSettings: vi.fn().mockResolvedValue(currentSettings),
      getApiServer: vi.fn().mockResolvedValue(currentApiServerSettings),
      updateSystemSettings: vi.fn().mockResolvedValue(currentSettings),
      saveApiServer: vi.fn().mockResolvedValue({
        ...currentApiServerSettings,
        api_key: { configured: false },
      }),
    }
    const wrapper = mount(SystemSettingsPage, { props: { api } })
    await flushPromises()

    const managementPassword = wrapper.get('#management-password')
    const apiKey = wrapper.get('#api-server-key')
    const langsmithApiKey = wrapper.get('#langsmith-api-key')
    expect(managementPassword.attributes('type')).toBe('password')
    expect(apiKey.attributes('type')).toBe('password')
    expect(langsmithApiKey.attributes('type')).toBe('password')
    await managementPassword.setValue('visible-management-password')
    await managementPassword.element.parentElement!.querySelector('button')!.click()
    await apiKey.setValue('temporary-key')
    await apiKey.element.parentElement!.querySelector('button')!.click()
    await langsmithApiKey.setValue('temporary-langsmith-key')
    await langsmithApiKey.element.parentElement!.querySelector('button')!.click()
    expect(managementPassword.attributes('type')).toBe('text')
    expect(apiKey.attributes('type')).toBe('text')
    expect(langsmithApiKey.attributes('type')).toBe('text')

    await apiKey.setValue('')
    await langsmithApiKey.setValue('')
    await wrapper.get('[data-testid="system-settings-form"]').trigger('submit')
    await flushPromises()

    expect(api.saveApiServer).toHaveBeenCalledWith({
      api_key: { operation: 'clear' },
      max_initial_messages: 1000,
    })
    expect(api.updateSystemSettings).toHaveBeenCalledWith(expect.objectContaining({
      langsmith_api_key: { operation: 'clear' },
    }))
  })

})
