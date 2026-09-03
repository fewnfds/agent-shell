import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  managementApi,
  type WorkflowLifecyclePage,
  type WorkflowLifecycleSummary,
} from '@/api'
import { useConfirmation } from '@/composables/useConfirmation'
import { useToasts } from '@/composables/useToasts'
import { en } from '@/locales/en'

import WorkflowLifecyclesPage from './WorkflowLifecyclesPage.vue'

const triggerBrowserDownload = vi.hoisted(() => vi.fn())

vi.mock('@/utils/download', () => ({ triggerBrowserDownload }))

const lifecycle: WorkflowLifecycleSummary = {
  lifecycle_id: 'lifecycle-1',
  lifecycle_status: 'active',
  request_id: 'request-1',
  root_run_id: 'run-1',
  root_status: 'running',
  workflow_id: 'workflow-1',
  workflow_name: 'Research Workflow',
  created_at: '2026-08-17T00:00:00.000+00:00',
  monitoring_capture_enabled: true,
  messages_sha: 'sha',
  message_count: 2,
  run_count: 4,
  active_run_count: 1,
  failed_run_count: 1,
  usage: { input_tokens: 100, output_tokens: 50, total_tokens: 150 },
}

afterEach(() => {
  vi.restoreAllMocks()
  triggerBrowserDownload.mockReset()
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
  it('shows the trustworthy catalog and explicit persistence-upgrade boundary', async () => {
    const page: WorkflowLifecyclePage = {
      items: [
        lifecycle,
        {
          ...lifecycle,
          lifecycle_id: 'lifecycle-2',
          lifecycle_status: 'purge_pending',
          monitoring_capture_enabled: false,
        },
      ],
      page: 1,
      page_size: 10,
      total: 2,
      total_pages: 1,
    }
    const list = vi.spyOn(managementApi, 'listWorkflowLifecycles').mockResolvedValue(page)
    const archive = {
      blob: new Blob(['runtime archive']),
      filename: 'runtime-monitoring-lifecycle-lifecycle-1.zip',
    }
    const download = vi.spyOn(managementApi, 'downloadWorkflowLifecycle')
      .mockResolvedValue(archive)
    const remove = vi.spyOn(managementApi, 'deleteWorkflowLifecycle').mockResolvedValue({ ok: true })
    const { router, wrapper } = await mountPage()
    await flushPromises()

    expect(list).toHaveBeenCalledWith({ page: 1, page_size: 10, query: '' })
    expect(wrapper.text()).toContain(lifecycle.workflow_name)
    expect(wrapper.text()).toContain('Running')
    expect(wrapper.text()).toContain('Pending automatic purge')
    expect(wrapper.text()).toContain('1 / 4')
    expect(wrapper.text()).toContain('150')
    expect(wrapper.text()).toContain('Enabled')
    expect(wrapper.text()).toContain('Disabled')
    const monitorButtons = wrapper.findAll('button[data-action="monitor"]')
    expect(monitorButtons).toHaveLength(2)
    expect(monitorButtons[0]?.attributes('title')).toBe('Monitor Lifecycle')
    expect(monitorButtons[1]?.attributes('disabled')).toBeDefined()
    expect(monitorButtons[1]?.attributes('title')).toBe(
      'Monitoring was disabled when this Lifecycle started',
    )
    const downloadButtons = wrapper.findAll('button[data-action="download"]')
    expect(downloadButtons).toHaveLength(2)
    expect(downloadButtons[0]?.attributes('title')).toBe('Download')
    expect(downloadButtons[1]?.attributes('disabled')).toBeDefined()
    expect(downloadButtons[1]?.attributes('title')).toBe(
      'No runtime monitoring data was captured for this Lifecycle',
    )

    await downloadButtons[0]!.trigger('click')
    await flushPromises()
    expect(download).toHaveBeenCalledWith(lifecycle.lifecycle_id)
    expect(triggerBrowserDownload).toHaveBeenCalledWith(archive.blob, archive.filename)

    await monitorButtons[0]!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe(
      '/system/workflow-lifecycles/lifecycle-1/monitoring',
    )

    await wrapper.findAll('button').find((button) => button.text() === 'Delete')!.trigger('click')
    useConfirmation().accept()
    await flushPromises()

    expect(remove).toHaveBeenCalledWith(lifecycle.lifecycle_id)
    wrapper.unmount()
  })

  it('bulk deletes the complete applied query and reports retained active lifecycles', async () => {
    vi.spyOn(managementApi, 'listWorkflowLifecycles').mockResolvedValue({
      items: [lifecycle],
      page: 1,
      page_size: 10,
      total: 12,
      total_pages: 2,
    })
    const removeMatching = vi.spyOn(managementApi, 'deleteWorkflowLifecyclesMatching')
      .mockResolvedValue({
        matched: 12,
        deleted: 11,
        skipped_active: 1,
        deleted_checkpoint_thread_count: 3,
      })
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
