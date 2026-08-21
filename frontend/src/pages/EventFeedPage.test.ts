import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it, vi } from 'vitest'

import { en } from '@/locales/en'

import EventFeedPage from './EventFeedPage.vue'

function api() {
  return {
    listEventFeed: vi.fn(async () => ({
      items: [],
      page: 1,
      page_size: 50,
      total: 0,
      total_pages: 1,
    })),
    downloadEvent: vi.fn(async () => new Blob(['{}'])),
    getRuntimeDiagnostics: vi.fn(async () => ({
      retention_limit: 20,
    })),
    updateRuntimeDiagnosticRetention: vi.fn(async (retentionLimit: number) => ({
      retention_limit: retentionLimit,
    })),
    getSystemLogSettings: vi.fn(async () => ({
      max_size_mib: 5,
      min_size_mib: 1,
    })),
    updateSystemLogSettings: vi.fn(async (maxSizeMib: number) => ({
      max_size_mib: maxSizeMib,
      min_size_mib: 1,
    })),
    deleteMatchingEventFeed: vi.fn(async () => ({ deleted: 0 })),
    watchApiServerEvents: vi.fn(() => vi.fn()),
  }
}

async function mountPage(mockApi: ReturnType<typeof api>) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/system/events', component: EventFeedPage }],
  })
  await router.push('/system/events?source=runtime')
  await router.isReady()
  const wrapper = mount(EventFeedPage, {
    props: { api: mockApi },
    global: {
      plugins: [
        router,
        createI18n({ legacy: false, locale: 'en', messages: { en } }),
      ],
    },
  })
  await flushPromises()
  return wrapper
}

describe('EventFeedPage', () => {
  it('shows only log-owned retention controls', async () => {
    const mockApi = api()
    const wrapper = await mountPage(mockApi)

    expect(wrapper.find('[data-testid="retention-runtime"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="retention-workflow-debug"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="retention-api_call"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="runtime-detail"]').exists()).toBe(false)
    expect(mockApi.listEventFeed).toHaveBeenCalledWith(expect.objectContaining({
      source: ['runtime'],
    }))
  })
})
