import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import type {
  ApiServerSettings,
  ConfigurationValidationSettings,
  RuntimePolicySettings,
  RuntimePolicyUpdate,
  SystemSettings,
} from '@/api'
import { i18n } from '@/locales'

import SystemSettingsPage from './SystemSettingsPage.vue'

const systemSettings: SystemSettings = {
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
  active_management_url: 'http://127.0.0.1:19100/admin#/',
  active_api_docs_url: 'http://127.0.0.1:19100/docs',
  active_studio_url: 'https://smith.langchain.com/studio/?baseUrl=http%3A%2F%2F127.0.0.1%3A19100',
}

const apiServerSettings: ApiServerSettings = {
  enabled: true,
  status: 'running',
  api_key: { configured: true },
  max_initial_messages: 1000,
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

const runtimePolicyValues: RuntimePolicySettings['defaults'] = {
  chat_completion_body_bytes: 64 * 1024 * 1024,
  content_blocks: 4096,
  decoded_block_bytes: 24 * 1024 * 1024,
  decoded_total_bytes: 48 * 1024 * 1024,
}
const runtimePolicySettings: RuntimePolicySettings = {
  ...runtimePolicyValues,
  defaults: { ...runtimePolicyValues },
  minimums: Object.fromEntries(
    Object.keys(runtimePolicyValues).map((key) => [key, 1]),
  ) as RuntimePolicySettings['minimums'],
  configurable: true,
}

function validationSettings(debounceMs: number): ConfigurationValidationSettings {
  return {
    debounce_ms: debounceMs,
    min_debounce_ms: 100,
  }
}

describe('SystemSettingsPage', () => {
  it('loads and saves the shared configuration alert interval', async () => {
    i18n.global.locale.value = 'zh-CN'
    const api = {
      getSystemSettings: vi.fn(async () => systemSettings),
      updateSystemSettings: vi.fn(async () => systemSettings),
      getApiServer: vi.fn(async () => apiServerSettings),
      saveApiServer: vi.fn(async () => apiServerSettings),
      getValidationSettings: vi.fn(async () => validationSettings(1000)),
      updateValidationSettings: vi.fn(async (value: number) => validationSettings(value)),
      getRuntimePolicy: vi.fn(async () => runtimePolicySettings),
      updateRuntimePolicy: vi.fn(async (payload: RuntimePolicyUpdate) => ({ ...runtimePolicySettings, ...payload })),
    }
    const wrapper = mount(SystemSettingsPage, {
      props: { api },
      global: { plugins: [i18n] },
    })
    await flushPromises()

    const interval = wrapper.get('#configuration-validation-debounce')
    expect((interval.element as HTMLInputElement).value).toBe('1000')
    expect(wrapper.get('label[for="configuration-validation-debounce"]').text()).toBe('配置报警间隔')
    expect(interval.attributes('aria-describedby')).toBe('configuration-validation-debounce-unit')
    expect(wrapper.get('#configuration-validation-debounce-unit').text()).toBe('ms')
    expect(wrapper.get('[data-testid="langgraph-api-docs-link"]').attributes('href'))
      .toBe(systemSettings.active_api_docs_url)
    expect(wrapper.get('[data-testid="langgraph-studio-link"]').attributes('href'))
      .toBe(systemSettings.active_studio_url)

    await interval.setValue('500')
    await wrapper.get('#runtime-policy-chat_completion_body_bytes').setValue('32')
    await wrapper.get('[data-testid="system-card-validation"]').trigger('submit')
    await flushPromises()

    expect(api.updateValidationSettings).toHaveBeenCalledWith(500)
    expect(api.updateRuntimePolicy).not.toHaveBeenCalled()

    await wrapper.get('[data-testid="system-card-runtime-policy"]').trigger('submit')
    await flushPromises()
    expect(api.updateRuntimePolicy).toHaveBeenCalledWith(expect.objectContaining({
      chat_completion_body_bytes: 32 * 1024 * 1024,
      content_blocks: 4096,
    }))
    wrapper.unmount()
  })

  it('shows backend wire fields instead of frontend refs in debug locale', async () => {
    i18n.global.locale.value = 'debug'
    const api = {
      getSystemSettings: vi.fn(async () => systemSettings),
      updateSystemSettings: vi.fn(async () => systemSettings),
      getApiServer: vi.fn(async () => apiServerSettings),
      saveApiServer: vi.fn(async () => apiServerSettings),
      getValidationSettings: vi.fn(async () => validationSettings(1000)),
      updateValidationSettings: vi.fn(async (value: number) => validationSettings(value)),
      getRuntimePolicy: vi.fn(async () => runtimePolicySettings),
      updateRuntimePolicy: vi.fn(async (payload: RuntimePolicyUpdate) => ({ ...runtimePolicySettings, ...payload })),
    }
    const wrapper = mount(SystemSettingsPage, {
      props: { api },
      global: { plugins: [i18n] },
    })
    await flushPromises()

    for (const wireField of [
      'host',
      'port',
      'allow_remote',
      'langsmith_tracing_enabled',
      'langsmith_endpoint',
      'langsmith_project',
      'langsmith_workspace_id',
      'langsmith_api_key',
      'management_token',
      'api_key',
      'max_initial_messages',
      'debounce_ms',
      'chat_completion_body_bytes',
      'cors_origins',
      'trusted_proxy_cidrs',
    ]) {
      expect(wrapper.text()).toContain(wireField)
    }
    expect(wrapper.text()).not.toContain('managementPassword')
    expect(wrapper.text()).not.toContain('trustedProxies')

    wrapper.unmount()
    i18n.global.locale.value = 'zh-CN'
  })
})
