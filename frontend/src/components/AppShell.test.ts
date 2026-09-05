import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ManagementApiError,
  type ApiServerSettings,
} from '@/api'
import { useToasts } from '@/composables/useToasts'
import { i18n, setLocale } from '@/locales'

import AppShell from './AppShell.vue'

const storage = new Map<string, string>()
const storageMock = {
  clear: () => storage.clear(),
  getItem: (key: string) => storage.get(key) ?? null,
  key: (index: number) => [...storage.keys()][index] ?? null,
  get length() {
    return storage.size
  },
  removeItem: (key: string) => storage.delete(key),
  setItem: (key: string, value: string) => storage.set(key, String(value)),
}

let narrow = false
let wrapper: VueWrapper | null = null

const stoppedSettings: ApiServerSettings = {
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

function createShellApi(overrides: Record<string, unknown> = {}) {
  return {
    getApiServer: vi.fn(async () => stoppedSettings),
    getValidationSettings: vi.fn(async () => ({
      debounce_ms: 1000,
      min_debounce_ms: 100,
    })),
    startApiServer: vi.fn(async () => ({ ...stoppedSettings, enabled: true, status: 'running' as const })),
    stopApiServer: vi.fn(async () => stoppedSettings),
    watchApiServerEvents: vi.fn(() => vi.fn()),
    ...overrides,
  }
}

function mediaQuery(query: string) {
  return {
    matches: query.includes('max-width') ? narrow : false,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }
}

function titleKeyForPath(path: string): string {
  if (path === '/files') return 'navigation.files'
  if (path.startsWith('/system/')) return 'navigation.system'
  if (path.startsWith('/mcp')) return 'navigation.mcp'
  if (path.startsWith('/agents/')) return 'navigation.agents'
  if (path.startsWith('/workflows')) return 'navigation.workflows'
  if (path.startsWith('/agent-components')) return 'components.title'
  if (path.startsWith('/library/')) return 'library.title'
  if (path === '/terminology') return 'terminology.title'
  return 'apiServer.homeTitle'
}

async function mountShell(path = '/', api = createShellApi()) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      '/',
      '/workflows',
      '/system',
      '/system/config',
      '/files',
      '/system/events',
      '/models',
      '/mcp',
      '/agents',
      '/agent-components',
      '/workflow-components',
      '/library',
      '/agents/main',
      '/agents/subagents',
      '/agent-components/model',
      '/agent-components/skill',
      '/library/model',
      '/terminology',
    ].map((routePath) => ({
      path: routePath,
      component: { template: `<p>${routePath}</p>` },
      meta: { titleKey: titleKeyForPath(routePath) },
    })),
  })
  await router.push(path)
  await router.isReady()
  wrapper = mount(AppShell, {
    attachTo: document.body,
    props: { api },
    global: { plugins: [router, i18n] },
  })
  await nextTick()
  return { router, wrapper }
}

beforeEach(() => {
  narrow = false
  storage.clear()
  vi.stubGlobal('localStorage', storageMock)
  vi.stubGlobal('matchMedia', vi.fn(mediaQuery))
  setLocale('zh-CN')
})

afterEach(() => {
  const toasts = useToasts()
  for (const toast of toasts.items.value) toasts.dismiss(toast.id)
  wrapper?.unmount()
  wrapper = null
  document.body.className = ''
  document.body.innerHTML = ''
  document.documentElement.removeAttribute('data-bs-theme')
  storage.clear()
  vi.unstubAllGlobals()
})

describe('AppShell', () => {
  it('renders real hash-router navigation without AdminLTE demo content', async () => {
    const { wrapper: shell } = await mountShell('/files')

    expect(shell.get('a[href="/files"]').classes()).toContain('active')
    expect(shell.text()).not.toContain('Alexander Pierce')
    expect(shell.text()).not.toContain('Followers')
    expect(shell.find('[data-bs-toggle="dropdown"]').exists()).toBe(false)
    expect(shell.find('.app-footer').exists()).toBe(false)
    expect(shell.get('a[href="/"] .nav-icon').classes()).toContain('bi-house')
    expect(shell.find('.app-sidebar .nav-treeview').exists()).toBe(false)
    expect(shell.find('a[href="/system/files"]').exists()).toBe(false)
    expect(shell.find('a[href="/agents/main"]').exists()).toBe(false)
    expect(shell.find('a[href^="/agent-components/"]').exists()).toBe(false)
    expect(shell.findAll('.app-sidebar .nav-link')).toHaveLength(11)
  })

  it('renders the localized route title beside the navigation toggle', async () => {
    const { router, wrapper: shell } = await mountShell('/files')

    const title = shell.get('.app-header .app-page-title')
    expect(title.element.previousElementSibling?.classList).toContain('navbar-nav')
    expect(title.text()).toBe('文件管理')

    await router.push('/agent-components/model')
    await nextTick()
    expect(title.text()).toBe('代理组件')

    await shell.get('#app-language').trigger('click')
    await nextTick()
    expect(title.text()).toBe('Agent components')

    await router.push('/workflows')
    await nextTick()
    expect(title.text()).toBe('Workflows')
    expect(shell.get('a[href="/workflows"]').classes()).toContain('active')
  })

  it('uses the official color-mode state and persists user changes', async () => {
    storage.set('lte-theme', 'dark')
    const { wrapper: shell } = await mountShell()

    const themeButton = shell.get('#app-theme')
    expect(themeButton.get('i').classes()).toContain('bi-moon-fill')
    expect(document.documentElement.getAttribute('data-bs-theme')).toBe('dark')

    await themeButton.trigger('click')
    await nextTick()

    expect(storage.get('lte-theme')).toBe('auto')
    expect(themeButton.get('i').classes()).toContain('bi-circle-half')

    await themeButton.trigger('click')
    await nextTick()

    expect(storage.get('lte-theme')).toBe('light')
    expect(document.documentElement.getAttribute('data-bs-theme')).toBe('light')
    expect(themeButton.get('i').classes()).toContain('bi-sun-fill')
  })

  it('shows and controls the API Server lifecycle from the right side of the navbar', async () => {
    const api = createShellApi()
    const { wrapper: shell } = await mountShell('/', api)
    await flushPromises()

    let statusButton = shell.get('#app-api-server-status')
    expect(statusButton.classes()).toContain('api-status-indicator--stopped')
    expect(statusButton.get('i').classes()).toContain('bi-stop-fill')
    expect(statusButton.attributes('title')).toContain('点击启动')

    await statusButton.trigger('click')
    await flushPromises()

    expect(api.startApiServer).toHaveBeenCalledTimes(1)
    statusButton = shell.get('#app-api-server-status')
    expect(statusButton.classes()).toContain('api-status-indicator--running')
    expect(statusButton.get('i').classes()).toContain('bi-play-fill')
    expect(statusButton.attributes('title')).toContain('点击停止')

    await statusButton.trigger('click')
    await flushPromises()
    expect(api.stopApiServer).toHaveBeenCalledTimes(1)
    expect(shell.get('#app-api-server-status').get('i').classes()).toContain('bi-stop-fill')
  })

  it('shows a yellow running arrow while message interception is enabled', async () => {
    const api = createShellApi({
      getApiServer: vi.fn(async () => ({
        ...stoppedSettings,
        enabled: true,
        status: 'running' as const,
        message_interception_enabled: true,
      })),
    })
    const { wrapper: shell } = await mountShell('/', api)
    await flushPromises()

    expect(shell.get('#app-api-server-status').classes())
      .toContain('api-status-indicator--intercepting')
  })

  it('reports an API Server lifecycle failure once through the shared toast owner', async () => {
    const api = createShellApi({
      startApiServer: vi.fn().mockRejectedValue(new ManagementApiError({
        status: 422,
        code: 'configuration_validation_failed',
        message: 'raw backend detail',
        messageKey: 'validation.failure.configuration',
        requestId: 'request-navbar-start',
        validation: null,
      })),
    })
    const { wrapper: shell } = await mountShell('/', api)
    await flushPromises()

    await shell.get('#app-api-server-status').trigger('click')
    await flushPromises()

    expect(useToasts().items.value).toHaveLength(1)
    expect(useToasts().items.value[0]).toMatchObject({
      tone: 'danger',
      title: '启动 API Server 失败',
    })
    expect(useToasts().items.value[0]?.message).toContain('request-navbar-start')
  })

  it('switches language through the existing locale owner', async () => {
    const { wrapper: shell } = await mountShell()

    const languageButton = shell.get('#app-language')
    expect(languageButton.get('i').classes()).toContain('bi-translate')
    expect(languageButton.attributes('aria-label')).toBe('Switch to English')

    await languageButton.trigger('click')
    await nextTick()

    expect(document.documentElement.lang).toBe('en')
    expect(shell.text()).toContain('System')
    expect(languageButton.attributes('aria-label')).toBe('Switch to variable names')

    await languageButton.trigger('click')
    await nextTick()

    expect(document.documentElement.lang).toBe('en')
    expect(shell.text()).toContain('navigation.system')
    expect(languageButton.attributes('aria-label')).toBe('preferences.switchToChinese')

    await languageButton.trigger('click')
    await nextTick()

    expect(document.documentElement.lang).toBe('zh-CN')
    expect(shell.text()).toContain('系统')
    expect(languageButton.attributes('aria-label')).toBe('Switch to English')
  })

  it('collapses desktop navigation and closes the mobile sidebar after routing', async () => {
    const { router, wrapper: shell } = await mountShell()
    const toggle = shell.get('button[aria-label="展开或收起导航"]')

    await toggle.trigger('click')
    expect(document.body.classList.contains('sidebar-collapse')).toBe(true)

    document.body.classList.remove('sidebar-collapse')
    narrow = true
    await toggle.trigger('click')
    expect(document.body.classList.contains('sidebar-open')).toBe(true)

    await router.push('/terminology')
    await nextTick()

    expect(document.body.classList.contains('sidebar-open')).toBe(false)
    expect(document.activeElement?.id).toBe('main-content')
  })
})
