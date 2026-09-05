import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it, vi } from 'vitest'

import type { ApiServerSettings } from '@/api'
import { navigationItems } from '@/navigation'
import { router } from '@/router'

import ApiServerSettingsPage from './ApiServerSettingsPage.vue'

const messages = {
  common: {
    all: 'All',
    apiKeyPlaceholder: 'Enter an API key',
    cancel: 'Cancel',
    close: 'Close',
    show: 'Show',
    hide: 'Hide',
    configuredSecretPlaceholder: '••••••••',
    copy: 'Copy',
    delete: 'Delete',
    deleting: 'Deleting',
    detailSeparator: ': ',
    itemSeparator: '; ',
    loading: 'Loading',
    next: 'Next',
    notAvailable: 'Not available',
    paginationSummary: 'Page {page} of {totalPages}',
    previous: 'Previous',
    reset: 'Reset',
    retry: 'Retry',
    save: 'Save',
    saving: 'Saving',
    search: 'Search',
    start: 'Start',
    starting: 'Starting',
    stop: 'Stop',
    stopping: 'Stopping',
    view: 'View',
  },
  apiServer: {
    homeTitle: 'Home',
    alerts: {
      title: 'Configuration alerts',
    },
    loadFailed: 'Settings failed to load',
    started: 'API Server started',
    stopped: 'API Server stopped',
    startFailed: 'Start failed',
    stopFailed: 'Stop failed',
    start: 'Start API Server',
    stop: 'Stop API Server',
    status: {
      running: 'Running',
      stopped: 'Stopped',
      unavailable: 'Unavailable',
    },
    key: {
      title: 'API key',
      save: 'Save key',
      saved: 'Key setting saved',
      saveFailed: 'Key setting failed',
    },
    configuration: {
      title: 'Configuration settings',
    },
    request: {
      maxInitialMessages: 'Initial message limit',
      invalid: 'Invalid request limit',
      save: 'Save request settings',
      saved: 'Request settings saved',
      saveFailed: 'Request settings failed',
    },
    serviceEntries: {
      title: 'Service entries',
      managementConsole: 'Agent Shell management console',
      agentServerBase: 'LangGraph Agent Server Base URL',
      apiDocs: 'API Docs',
      openapiSchema: 'OpenAPI Schema',
      langgraphStudio: 'LangGraph Studio',
    },
    endpoints: {
      title: 'API endpoints',
      agentShellBase: 'Agent Shell API Base URL',
      openaiBase: 'OpenAI-compatible Base URL',
      getMethod: 'GET',
      postMethod: 'POST',
      models: 'Models endpoint',
      chatCompletions: 'Chat completions endpoint',
      langgraphRoutes: 'LangGraph Agent Server route families',
      diagnostics: 'Diagnostic endpoints',
      agentShellHealth: 'Agent Shell Health',
      agentShellReadiness: 'Agent Shell Readiness',
      langgraphHealth: 'LangGraph Health',
      langgraphInfo: 'LangGraph Info',
      langgraphMetrics: 'LangGraph Metrics',
      managementAuth: 'Management Bearer routes',
      apiKeyAuth: 'API Key Bearer routes',
    },
  },
  fields: {
    id: 'UUID',
    name: 'Configuration name',
  },
  errors: {
    codeLabel: 'Error code',
    requestFailed: 'Request failed',
    requestIdLabel: 'Request ID',
  },
  validation: {
    validatingDetail: 'Checking.',
    unavailableDetail: 'Unavailable.',
    issueSummary: 'Configuration problems: {count}. Expand to view the full details',
    status: {
      unavailable: 'Unavailable',
      validating: 'Checking',
      valid: 'Valid',
      invalid: 'Needs attention',
    },
    failure: { configuration: 'The configuration needs attention.' },
    scope: { mainAgent: 'Main Agent configuration' },
    location: {
      namedOwner: '{scope} named {name}',
      currentOwner: 'Current {scope}',
      owner: 'Configuration',
      problemLocation: 'Problem location',
      technicalPath: 'Technical path',
      reason: 'Reason',
      resolution: 'How to fix',
      wholeConfiguration: 'Entire configuration',
      indexedItem: 'Item {index} in {collection}',
      unknownField: '{field} field',
      nested: '{child} under {parent}',
    },
    resolution: {
      configurationReferenceNotFound: 'Select a new {expected_type_label} configuration.',
    },
    issue: {
      configuration: {
        referenceNotFound: 'The selected {expected_type_label} configuration no longer exists.',
      },
    },
  },
  capabilities: { model: { label: 'Model' } },
}

const settings: ApiServerSettings = {
  enabled: false,
  status: 'stopped',
  api_key: { configured: true },
  message_interception_enabled: false,
  service_entries: {
    management_console_url: 'http://localhost/admin#/',
    agent_server_base_url: 'http://localhost',
    api_docs_url: 'http://localhost/docs',
    openapi_schema_url: 'http://localhost/openapi.json',
    langgraph_studio_url: 'https://smith.langchain.com/studio/?baseUrl=http%3A%2F%2Flocalhost',
  },
  api_endpoints: {
    agent_shell_base_url: 'http://localhost/agent-shell/api',
    openai_base_url: 'http://localhost/compat/openai/v1',
    models_endpoint: 'http://localhost/compat/openai/v1/models',
    chat_completions_endpoint: 'http://localhost/compat/openai/v1/chat/completions',
    langgraph_route_families: [
      '/assistants/*',
      '/threads/*',
      '/runs/*',
      '/store/*',
      '/mcp/',
      '/a2a/{assistant_id}',
    ],
    agent_shell_health_endpoint: 'http://localhost/agent-shell/api/health',
    agent_shell_readiness_endpoint: 'http://localhost/agent-shell/api/readiness',
    langgraph_health_endpoint: 'http://localhost/ok',
    langgraph_info_endpoint: 'http://localhost/info',
    langgraph_metrics_endpoint: 'http://localhost/metrics',
  },
  runtime: 'model_streaming',
}

const healthyRepository = {
  valid: true,
  stage: 'repository_load',
  issues: [],
}

function i18n() {
  return createI18n({
    legacy: false,
    locale: 'en',
    messages: { en: messages },
  })
}

describe('ApiServerSettingsPage', () => {
  it('uses the API Server surface as the only home route', () => {
    expect(navigationItems[0]).toMatchObject({ path: '/', labelKey: 'navigation.home' })
    expect(navigationItems.map((item) => item.path)).toEqual([
      '/',
      '/system',
      '/files',
      '/models',
      '/mcp',
      '/agents',
      '/agent-components',
      '/workflows',
      '/workflow-components',
      '/library',
      '/terminology',
    ])
    expect(navigationItems.find((item) => item.path === '/workflows')?.icon).toBe('bi-diagram-3')
    expect(router.resolve('/').matched.at(-1)?.components?.default).toBeDefined()
    expect(router.getRoutes().some((route) => route.path === '/api-server/settings')).toBe(false)
  })

  it('keeps loading failures inline without producing unrelated lifecycle feedback', async () => {
    const loadingApi = {
      getApiServer: vi.fn().mockRejectedValue(new Error('offline')),
      validateRepository: vi.fn(async () => healthyRepository),
    }
    const loadingFailure = mount(ApiServerSettingsPage, {
      props: { api: loadingApi },
      global: { plugins: [i18n()] },
    })
    await flushPromises()

    expect(loadingFailure.get('[data-testid="load-error"]').attributes('role')).toBe('alert')
    loadingFailure.unmount()
  })

  it('shows repository alarms on the home page without unrelated navigation actions', async () => {
    const api = {
      getApiServer: vi.fn(async () => settings),
      validateRepository: vi.fn(async () => ({
        valid: false,
        stage: 'repository_load',
        issues: [{
          code: 'configuration.reference_not_found',
          scope: 'main_agent',
          owner_id: 'main-agent-id',
          owner_name: 'Broken MainAgent',
          path: 'capability_refs.model',
          message: 'raw issue detail',
          message_key: 'validation.issue.configuration.referenceNotFound',
          message_args: { expected_type: 'model', reference_id: 'missing-model-id' },
        }],
      })),
    }
    const wrapper = mount(ApiServerSettingsPage, {
      props: { api },
      global: { plugins: [i18n()] },
    })
    await flushPromises()

    expect(wrapper.find('.app-content-header').exists()).toBe(false)
    const alerts = wrapper.get('[data-testid="configuration-alerts"]')
    expect(alerts.find('details').exists()).toBe(false)
    expect(alerts.get('header').text())
      .toContain('Configuration problems: 1. Expand to view the full details')
    expect(alerts.get('.accordion-button').attributes('aria-expanded')).toBe('false')
    expect(alerts.text()).toContain('Configuration alerts')
    expect(alerts.text()).toContain('Broken MainAgent')
    expect(alerts.find('a').exists()).toBe(false)
    const serviceEntryCard = wrapper.get('[data-testid="service-entry-card"]')
    expect(serviceEntryCard.text()).toContain('Service entries')
    expect(serviceEntryCard.get('[data-testid="management-console-link"]').attributes('href'))
      .toBe('http://localhost/admin#/')
    expect(serviceEntryCard.get('[data-testid="api-docs-link"]').attributes('href'))
      .toBe('http://localhost/docs')
    expect(serviceEntryCard.get('[data-testid="openapi-schema-link"]').attributes('href'))
      .toBe('http://localhost/openapi.json')
    expect(serviceEntryCard.get('[data-testid="langgraph-studio-link"]').attributes('href'))
      .toBe('https://smith.langchain.com/studio/?baseUrl=http%3A%2F%2Flocalhost')
    const endpointCard = wrapper.get('[data-testid="endpoint-card"]')
    expect(endpointCard.text()).toContain('API endpoints')
    expect(endpointCard.text()).toContain('/assistants/*')
    expect(endpointCard.get<HTMLInputElement>('#agent-shell-base-url').element.value)
      .toBe('http://localhost/agent-shell/api')
    expect(endpointCard.get<HTMLInputElement>('#openai-base-url').element.value)
      .toBe('http://localhost/compat/openai/v1')
    expect(endpointCard.get<HTMLInputElement>('#models-endpoint').element.value)
      .toBe('http://localhost/compat/openai/v1/models')
    expect(endpointCard.findAll('button')).toHaveLength(0)
    expect(endpointCard.findAll('a')).toHaveLength(0)
    expect(wrapper.find('[data-testid="configuration-card"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="key-form"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="request-settings-form"]').exists()).toBe(false)
    expect(wrapper.find('.info-box').exists()).toBe(false)
    expect(wrapper.find('[data-testid="service-state"]').exists()).toBe(false)
    wrapper.unmount()
  })

})
