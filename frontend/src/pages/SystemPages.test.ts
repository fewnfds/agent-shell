import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import type {
  ApiServerSettings,
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
  n_jobs_per_worker: 20,
  recursion_limit: 100000,
  max_concurrency: 20,
  debug_port: null,
  allow_remote: false,
  langsmith_tracing_enabled: false,
  langsmith_endpoint: 'https://api.smith.langchain.com',
  langsmith_project: 'agent-shell',
  langsmith_workspace_id: null,
  langsmith_api_key: { configured: true },
  management_token: { configured: true },
  cors_origins: [],
  trusted_proxy_cidrs: [],
  response_stream_scheduling: {
    idle_timeout_seconds: 10,
    max_batch_kb: 64,
    send_interval_seconds: 0.05,
  },
  restart_required: false,
  active_management_url: 'http://127.0.0.1:19100/admin#/',
  active_api_docs_url: 'http://127.0.0.1:19100/docs',
  active_studio_url: 'https://smith.langchain.com/studio/?baseUrl=http%3A%2F%2F127.0.0.1%3A19100',
}

const currentApiServerSettings: ApiServerSettings = {
  enabled: false,
  status: 'stopped',
  api_key: { configured: true },
  message_interception_enabled: false,
  service_entries: {
    management_console_url: 'http://127.0.0.1:19100/admin#/',
    agent_server_base_url: 'http://127.0.0.1:19100',
    api_docs_url: 'http://127.0.0.1:19100/docs',
    openapi_schema_url: 'http://127.0.0.1:19100/openapi.json',
    langgraph_studio_url: 'https://smith.langchain.com/studio/?baseUrl=http%3A%2F%2F127.0.0.1%3A19100',
  },
  api_endpoints: {
    agent_shell_base_url: 'http://127.0.0.1:19100/agent-shell/api',
    openai_base_url: 'http://127.0.0.1:19100/compat/openai/v1',
    models_endpoint: 'http://127.0.0.1:19100/compat/openai/v1/models',
    chat_completions_endpoint: 'http://127.0.0.1:19100/compat/openai/v1/chat/completions',
    langgraph_route_families: ['/assistants/*', '/threads/*', '/runs/*', '/store/*', '/mcp/', '/a2a/{assistant_id}'],
    agent_shell_health_endpoint: 'http://127.0.0.1:19100/agent-shell/api/health',
    agent_shell_readiness_endpoint: 'http://127.0.0.1:19100/agent-shell/api/readiness',
    langgraph_health_endpoint: 'http://127.0.0.1:19100/ok',
    langgraph_info_endpoint: 'http://127.0.0.1:19100/info',
    langgraph_metrics_endpoint: 'http://127.0.0.1:19100/metrics',
  },
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

describe('SystemSettingsPage', () => {
  it('saves each settings owner independently without filling secret values', async () => {
    const api = {
      ...validationSettingsApi(),
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
    expect(cards).toHaveLength(7)
    expect(cards.every((card) => !card.classes().includes('card-primary'))).toBe(true)
    expect(cards.every((card) => card.get('.card-title').element.tagName === 'H2')).toBe(true)
    expect(cards.map((card) => card.attributes('data-testid'))).toEqual([
      'system-card-api-server',
      'system-card-proxy',
      'system-card-runtime-policy',
      'system-card-response-scheduling',
      'system-card-langgraph-dev',
      'system-card-langsmith',
      'system-card-validation',
    ])
    const fieldColumns = wrapper.findAll(
      '[data-testid^="system-card-"] > .card-body > .row.g-3 > div',
    )
    expect(fieldColumns.length).toBeGreaterThan(0)
    expect(fieldColumns.every((column) => column.classes().includes('col-lg-3'))).toBe(true)

    const saveButtons = wrapper.findAll('button').filter((button) => button.text() === 'common.save')
    expect(saveButtons).toHaveLength(7)
    expect(cards.map((card) => card.get('.card-header i').classes().find((name) => name.startsWith('bi-'))))
      .toEqual(['bi-key', 'bi-hdd-network', 'bi-sliders', 'bi-shuffle', 'bi-diagram-3', 'bi-cloud-arrow-up', 'bi-check2-square'])
    await wrapper.get('[data-testid="system-card-proxy"]').trigger('submit')
    await flushPromises()

    expect(api.updateSystemSettings).toHaveBeenCalledWith({
      host: '127.0.0.1',
      port: 19100,
      n_jobs_per_worker: 20,
      recursion_limit: 100000,
      max_concurrency: 20,
      debug_port: null,
      allow_remote: false,
      langsmith_tracing_enabled: false,
      langsmith_endpoint: 'https://api.smith.langchain.com',
      langsmith_project: 'agent-shell',
      langsmith_workspace_id: null,
      langsmith_api_key: { operation: 'keep' },
      management_token: { operation: 'preserve' },
      cors_origins: [],
      trusted_proxy_cidrs: [],
      response_stream_scheduling: {
        idle_timeout_seconds: 10,
        max_batch_kb: 64,
        send_interval_seconds: 0.05,
      },
    })
    expect(api.saveApiServer).not.toHaveBeenCalled()
    expect(api.updateValidationSettings).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('systemSettings.restartRequired')

    await wrapper.get('[data-testid="system-card-api-server"]').trigger('submit')
    await flushPromises()
    expect(api.saveApiServer).toHaveBeenCalledWith({
      api_key: { operation: 'keep' },
    })
    expect(api.updateSystemSettings).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).not.toContain('test-management-token')
  })

  it('converts edited number, boolean select, secret and multiline fields into the backend payload', async () => {
    const api = {
      ...validationSettingsApi(),
      getSystemSettings: vi.fn().mockResolvedValue(currentSettings),
      getApiServer: vi.fn().mockResolvedValue(currentApiServerSettings),
      updateSystemSettings: vi.fn().mockImplementation(async (payload: SystemSettingsUpdate) => ({
        ...currentSettings,
        host: payload.host,
        port: payload.port,
        n_jobs_per_worker: payload.n_jobs_per_worker,
        recursion_limit: payload.recursion_limit,
        max_concurrency: payload.max_concurrency,
        debug_port: payload.debug_port,
        allow_remote: payload.allow_remote,
        cors_origins: payload.cors_origins,
        trusted_proxy_cidrs: payload.trusted_proxy_cidrs,
        response_stream_scheduling: payload.response_stream_scheduling,
      })),
      saveApiServer: vi.fn().mockImplementation(async () => currentApiServerSettings),
    }
    const wrapper = mount(SystemSettingsPage, { props: { api } })
    await flushPromises()

    expect(wrapper.get('#allow-remote').element.tagName).toBe('SELECT')
    expect(wrapper.get('#langsmith-tracing').element.tagName).toBe('SELECT')
    await wrapper.get('#system-host').setValue('0.0.0.0')
    await wrapper.get('#system-port').setValue('21000')
    await wrapper.get('#limit-jobs-per-worker').setValue('14')
    await wrapper.get('#limit-recursion').setValue('321')
    await wrapper.get('#limit-concurrency').setValue('7')
    await wrapper.get('#langgraph-debug-port').setValue('21001')
    await wrapper.get('#response-idle-timeout').setValue('1.5')
    await wrapper.get('#response-max-batch').setValue('32')
    await wrapper.get('#response-send-interval').setValue('0.1')
    await wrapper.get('#allow-remote').setValue(true)
    await wrapper.get('#management-password').setValue('new-management-password')
    await wrapper.get('#api-server-key').setValue('new-api-key')
    await wrapper.get('#langsmith-tracing').setValue(true)
    await wrapper.get('#langsmith-api-key').setValue('new-langsmith-key')
    const textareas = wrapper.findAll('textarea')
    await textareas[0]!.setValue('http://localhost:3000\nhttp://127.0.0.1:3000')
    await textareas[1]!.setValue('127.0.0.1/32')
    await wrapper.get('[data-testid="system-card-proxy"]').trigger('submit')
    await flushPromises()

    expect(api.updateSystemSettings).toHaveBeenNthCalledWith(1, expect.objectContaining({
      host: '0.0.0.0',
      port: 21000,
      n_jobs_per_worker: 20,
      recursion_limit: 100000,
      max_concurrency: 20,
      debug_port: null,
      allow_remote: true,
      langsmith_tracing_enabled: false,
      langsmith_api_key: { operation: 'keep' },
      management_token: { operation: 'replace', value: 'new-management-password' },
      cors_origins: ['http://localhost:3000', 'http://127.0.0.1:3000'],
      trusted_proxy_cidrs: ['127.0.0.1/32'],
    }))

    await wrapper.get('[data-testid="system-card-langgraph-dev"]').trigger('submit')
    await flushPromises()
    expect(api.updateSystemSettings).toHaveBeenNthCalledWith(2, expect.objectContaining({
      host: '0.0.0.0',
      port: 21000,
      n_jobs_per_worker: 20,
      debug_port: 21001,
      allow_remote: true,
      langsmith_tracing_enabled: false,
      langsmith_api_key: { operation: 'keep' },
      management_token: { operation: 'preserve' },
    }))

    await wrapper.get('[data-testid="system-card-runtime-policy"]').trigger('submit')
    await flushPromises()
    expect(api.updateSystemSettings).toHaveBeenNthCalledWith(3, expect.objectContaining({
      n_jobs_per_worker: 14,
      recursion_limit: 321,
      max_concurrency: 7,
      debug_port: 21001,
    }))

    await wrapper.get('[data-testid="system-card-response-scheduling"]').trigger('submit')
    await flushPromises()
    expect(api.updateSystemSettings).toHaveBeenNthCalledWith(4, expect.objectContaining({
      response_stream_scheduling: {
        idle_timeout_seconds: 1.5,
        max_batch_kb: 32,
        send_interval_seconds: 0.1,
      },
    }))

    await wrapper.get('[data-testid="system-card-langsmith"]').trigger('submit')
    await flushPromises()
    expect(api.updateSystemSettings).toHaveBeenNthCalledWith(5, expect.objectContaining({
      n_jobs_per_worker: 14,
      langsmith_tracing_enabled: true,
      langsmith_api_key: { operation: 'replace', value: 'new-langsmith-key' },
      management_token: { operation: 'preserve' },
    }))
    expect(api.saveApiServer).not.toHaveBeenCalled()

    await wrapper.get('[data-testid="system-card-api-server"]').trigger('submit')
    await flushPromises()
    expect(api.saveApiServer).toHaveBeenCalledWith({
      api_key: { operation: 'replace', value: 'new-api-key' },
    })
  })

  it('reveals only newly entered credentials and clears secrets through their owning save', async () => {
    const api = {
      ...validationSettingsApi(),
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
    await wrapper.get('[data-testid="system-card-api-server"]').trigger('submit')
    await flushPromises()

    expect(api.saveApiServer).toHaveBeenCalledWith({
      api_key: { operation: 'clear' },
    })
    expect(api.updateSystemSettings).not.toHaveBeenCalled()

    await wrapper.get('[data-testid="system-card-langsmith"]').trigger('submit')
    await flushPromises()
    expect(api.updateSystemSettings).toHaveBeenCalledWith(expect.objectContaining({
      langsmith_api_key: { operation: 'clear' },
    }))
    await wrapper.get('[data-testid="system-card-proxy"]').trigger('submit')
    await flushPromises()
    expect(api.updateSystemSettings).toHaveBeenCalledWith(expect.objectContaining({
      management_token: { operation: 'replace', value: 'visible-management-password' },
    }))
  })

})
