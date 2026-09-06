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
    enter: 'Open',
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
      enter: 'Open {entry}',
    },
    endpoints: {
      langgraphDevTitle: 'LangGraph Dev API',
      openaiTitle: 'OpenAI-compatible API',
      agentShellBase: 'Agent Shell API Base URL',
      openaiBase: 'OpenAI-compatible Base URL',
      models: 'Models endpoint (GET)',
      chatCompletions: 'Chat completions endpoint (POST)',
      langgraphRoute: 'LangGraph Agent Server route',
      assistantsApi: 'Assistants API',
      threadsApi: 'Threads API',
      runsApi: 'Runs API',
      storeApi: 'Store API',
      mcp: 'MCP',
      a2a: 'A2A',
      agentShellHealth: 'Agent Shell Health (GET)',
      agentShellReadiness: 'Agent Shell Readiness (GET)',
      langgraphHealth: 'LangGraph Health (GET)',
      langgraphInfo: 'LangGraph Info (GET)',
      langgraphMetrics: 'LangGraph Metrics (GET)',
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
    expect(serviceEntryCard.findAll('.col-lg-6')).toHaveLength(5)
    expect(serviceEntryCard.findAll('input[readonly]')).toHaveLength(5)
    expect(serviceEntryCard.get('[data-testid="service-entry-management-console-link"]').attributes('href'))
      .toBe('http://localhost/admin#/')
    expect(serviceEntryCard.get('[data-testid="service-entry-api-docs-link"]').attributes('href'))
      .toBe('http://localhost/docs')
    expect(serviceEntryCard.get('[data-testid="service-entry-openapi-schema-link"]').attributes('href'))
      .toBe('http://localhost/openapi.json')
    expect(serviceEntryCard.get('[data-testid="service-entry-langgraph-studio-link"]').attributes('href'))
      .toBe('https://smith.langchain.com/studio/?baseUrl=http%3A%2F%2Flocalhost')
    expect(serviceEntryCard.findAll('a')).toHaveLength(4)
    expect(serviceEntryCard.findAll('a').every((link) => link.text() === 'Open')).toBe(true)

    const langgraphDevApiCard = wrapper.get('[data-testid="langgraph-dev-api-card"]')
    expect(langgraphDevApiCard.text()).toContain('LangGraph Dev API')
    expect(langgraphDevApiCard.findAll('.col-lg-6')).toHaveLength(12)
    expect(langgraphDevApiCard.findAll('input[readonly]')).toHaveLength(12)
    expect(langgraphDevApiCard.findAll('.small')).toHaveLength(0)
    expect(langgraphDevApiCard.findAll('.input-group-sm')).toHaveLength(0)
    expect(langgraphDevApiCard.findAll('code')).toHaveLength(0)
    expect(langgraphDevApiCard.get<HTMLInputElement>('#agent-shell-base-url').element.value)
      .toBe('http://localhost/agent-shell/api')
    expect(langgraphDevApiCard.get('label[for="langgraph-route-0"]').text())
      .toBe('Assistants API')
    expect(langgraphDevApiCard.get('label[for="langgraph-route-1"]').text())
      .toBe('Threads API')
    expect(langgraphDevApiCard.get('label[for="langgraph-route-2"]').text())
      .toBe('Runs API')
    expect(langgraphDevApiCard.get('label[for="langgraph-route-3"]').text())
      .toBe('Store API')
    expect(langgraphDevApiCard.get('label[for="langgraph-route-4"]').text())
      .toBe('MCP')
    expect(langgraphDevApiCard.get('label[for="langgraph-route-5"]').text())
      .toBe('A2A')
    expect(langgraphDevApiCard.get<HTMLInputElement>('#langgraph-route-0').element.value)
      .toBe('/assistants/*')
    expect(langgraphDevApiCard.get<HTMLInputElement>('#diagnostic-langgraph-metrics').element.value)
      .toBe('http://localhost/metrics')
    expect(langgraphDevApiCard.find('#management-authentication').exists()).toBe(false)

    const openaiApiCard = wrapper.get('[data-testid="openai-api-card"]')
    expect(openaiApiCard.text()).toContain('OpenAI-compatible API')
    expect(openaiApiCard.findAll('.col-lg-6')).toHaveLength(3)
    expect(openaiApiCard.findAll('input[readonly]')).toHaveLength(3)
    expect(openaiApiCard.get<HTMLInputElement>('#openai-base-url').element.value)
      .toBe('http://localhost/compat/openai/v1')
    expect(openaiApiCard.get<HTMLInputElement>('#models-endpoint').element.value)
      .toBe('http://localhost/compat/openai/v1/models')
    expect(openaiApiCard.get<HTMLInputElement>('#chat-completions-endpoint').element.value)
      .toBe('http://localhost/compat/openai/v1/chat/completions')
    expect(openaiApiCard.find('#api-key-authentication').exists()).toBe(false)
    expect(wrapper.find('[data-testid="endpoint-card"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="configuration-card"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="key-form"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="request-settings-form"]').exists()).toBe(false)
    expect(wrapper.find('.info-box').exists()).toBe(false)
    expect(wrapper.find('[data-testid="service-state"]').exists()).toBe(false)
    wrapper.unmount()
  })

})
