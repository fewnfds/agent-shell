import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  managementApi,
  type LangGraphLifecyclePage,
  type LangGraphLifecycleSummary,
} from '@/api'
import { useConfirmation } from '@/composables/useConfirmation'
import { useToasts } from '@/composables/useToasts'
import { en } from '@/locales/en'

import WorkflowLifecyclesPage from './WorkflowLifecyclesPage.vue'

const lifecycle: LangGraphLifecycleSummary = {
  lifecycle_id: 'lifecycle-1',
  request_id: 'request-1',
  created_at: '2026-08-17T00:00:00.000+00:00',
  updated_at: '2026-08-17T00:01:00.000+00:00',
  status: 'running',
  workflow_names: ['Research Workflow'],
  run_count: 4,
  active_run_count: 1,
  error_run_count: 1,
}

afterEach(() => {
  vi.restoreAllMocks()
  useConfirmation().cancel()
  const toasts = useToasts()
  for (const toast of toasts.items.value) toasts.dismiss(toast.id)
})

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/system/workflow-lifecycles', component: WorkflowLifecyclesPage },
      {
        path: '/system/workflow-lifecycles/:lifecycleId/monitoring',
        component: { template: '<div />' },
      },
    ],
  })
  await router.push('/system/workflow-lifecycles')
  await router.isReady()
  const wrapper = mount(WorkflowLifecyclesPage, {
    global: {
      plugins: [createI18n({ legacy: false, locale: 'en', messages: { en } }), router],
    },
  })
  return { router, wrapper }
}

describe('WorkflowLifecyclesPage', () => {
  it('shows official Run summaries and allows every Lifecycle to be monitored', async () => {
    const terminal = {
      ...lifecycle,
      lifecycle_id: 'lifecycle-2',
      status: 'success' as const,
      active_run_count: 0,
    }
    const page: LangGraphLifecyclePage = {
      items: [lifecycle, terminal],
      page: 1,
      page_size: 10,
      total: 2,
      total_pages: 1,
    }
    const list = vi.spyOn(managementApi, 'listWorkflowLifecycles').mockResolvedValue(page)
    const remove = vi.spyOn(managementApi, 'deleteWorkflowLifecycle').mockResolvedValue({ ok: true })
    const { router, wrapper } = await mountPage()
    await flushPromises()

    expect(list).toHaveBeenCalledWith({ page: 1, page_size: 10, query: '' })
    expect(wrapper.text()).toContain('Research Workflow')
    expect(wrapper.text()).toContain('Running')
    expect(wrapper.text()).toContain('Success')
    expect(wrapper.text()).toContain('1 / 4')
    const monitorButtons = wrapper.findAll('button[data-action="monitor"]')
    expect(monitorButtons).toHaveLength(2)

    await monitorButtons[0]!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe(
      '/system/workflow-lifecycles/lifecycle-1/monitoring',
    )

    const deleteButtons = wrapper.findAll('button[data-action="delete"]')
    expect(deleteButtons[0]?.attributes('disabled')).toBeDefined()
    expect(deleteButtons[1]?.attributes('disabled')).toBeUndefined()
    await deleteButtons[1]!.trigger('click')
    useConfirmation().accept()
    await flushPromises()

    expect(remove).toHaveBeenCalledWith(terminal.lifecycle_id)
    wrapper.unmount()
  })

  it('bulk deletes the complete applied query and reports retained active Lifecycles', async () => {
    vi.spyOn(managementApi, 'listWorkflowLifecycles').mockResolvedValue({
      items: [lifecycle],
      page: 1,
      page_size: 10,
      total: 12,
      total_pages: 2,
    })
    const removeMatching = vi.spyOn(managementApi, 'deleteWorkflowLifecyclesMatching')
      .mockResolvedValue({ matched: 12, deleted: 11, skipped_active: 1 })
    const { wrapper } = await mountPage()
    await flushPromises()

    const search = wrapper.get<HTMLInputElement>('input[type="search"]')
    await search.setValue('research')
    await wrapper.get('form[role="search"]').trigger('submit')
    await flushPromises()

    const bulkDelete = wrapper.findAll('button').find(
      (button) => button.text() === 'Bulk delete',
    )
    expect(bulkDelete).toBeDefined()
    await bulkDelete!.trigger('click')
    expect(useConfirmation().current.value?.description).toContain('12')
    useConfirmation().accept()
    await flushPromises()

    expect(removeMatching).toHaveBeenCalledWith('research')
    expect(useToasts().items.value.some(
      (toast) => toast.title
        === 'Deleted runtime data for 11 Lifecycles and retained 1 active Lifecycles.',
    )).toBe(true)
    wrapper.unmount()
  })
})
