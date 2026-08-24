import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  managementApi,
  type WorkflowLifecycleDetail,
  type WorkflowLifecyclePage,
  type WorkflowLifecycleSummary,
  type WorkflowRunDetail,
} from '@/api'
import { useConfirmation } from '@/composables/useConfirmation'
import { useToasts } from '@/composables/useToasts'
import { en } from '@/locales/en'

import WorkflowLifecyclesPage from './WorkflowLifecyclesPage.vue'

const lifecycle: WorkflowLifecycleSummary = {
  lifecycle_id: 'lifecycle-1',
  lifecycle_status: 'active',
  request_id: 'request-1',
  parent_run_id: 'run-1',
  parent_status: 'running',
  workflow_id: 'workflow-1',
  workflow_name: 'Research Workflow',
  created_at: '2026-08-17T00:00:00.000+00:00',
  messages_sha: 'sha',
  message_count: 2,
  task_count: 3,
  active_task_count: 1,
  task_status_counts: { running: 1, succeeded: 2 },
  checkpoint_count: 7,
  store_item_count: 6,
  filesystem_count: 1,
  route_count: 2,
  dynamic_directory_count: 1,
  run_count: 4,
  active_run_count: 1,
  failed_run_count: 1,
  run_status_counts: { running: 1, completed: 2, failed: 1 },
  usage: { input_tokens: 100, output_tokens: 50, total_tokens: 150 },
  observation_status: 'available',
}

afterEach(() => {
  vi.restoreAllMocks()
  useConfirmation().cancel()
  const toasts = useToasts()
  for (const toast of toasts.items.value) toasts.dismiss(toast.id)
})

describe('WorkflowLifecyclesPage', () => {
  it('shows lifecycle summaries and performs explicit cleanup', async () => {
    const page: WorkflowLifecyclePage = {
      items: [
        lifecycle,
        { ...lifecycle, lifecycle_id: 'lifecycle-2', lifecycle_status: 'deleting' },
      ],
      page: 1,
      page_size: 10,
      total: 2,
      total_pages: 1,
    }
    const list = vi.spyOn(managementApi, 'listWorkflowLifecycles').mockResolvedValue(page)
    const remove = vi.spyOn(managementApi, 'deleteWorkflowLifecycle').mockResolvedValue({ ok: true })
    const wrapper = mount(WorkflowLifecyclesPage, {
      global: {
        plugins: [createI18n({ legacy: false, locale: 'en', messages: { en } })],
      },
    })
    await flushPromises()

    expect(list).toHaveBeenCalledWith({ page: 1, page_size: 10, query: '' })

    expect(wrapper.text()).toContain(lifecycle.workflow_name)
    expect(wrapper.text()).toContain('Running')
    expect(wrapper.text()).toContain('Deleting')
    expect(wrapper.text()).toContain('1 / 4')
    expect(wrapper.text()).toContain('150')
    await wrapper.findAll('button').find((button) => button.text() === 'Delete')!.trigger('click')
    useConfirmation().accept()
    await flushPromises()

    expect(remove).toHaveBeenCalledWith(lifecycle.lifecycle_id)
    wrapper.unmount()
  })

  it('opens structured Run history and downloads lifecycle and Run diagnostics', async () => {
    const detail: WorkflowLifecycleDetail = {
      ...lifecycle,
      runs: [{
        run_id: 'run-1',
        lifecycle_id: lifecycle.lifecycle_id,
        request_id: lifecycle.request_id,
        checkpoint_thread_id: 'thread-1',
        run_kind: 'workflow',
        target_id: lifecycle.workflow_id,
        target_name: lifecycle.workflow_name,
        parent_run_id: null,
        launcher_id: null,
        background_task_id: null,
        run_depth: 0,
        status: 'completed',
        created_at: lifecycle.created_at,
        started_at: lifecycle.created_at,
        finished_at: lifecycle.created_at,
        finish_reason: 'stop',
        error_code: '',
        usage: lifecycle.usage,
        observation_status: 'available',
      }, {
        run_id: 'run-2',
        lifecycle_id: lifecycle.lifecycle_id,
        request_id: lifecycle.request_id,
        checkpoint_thread_id: null,
        run_kind: 'agent',
        target_id: 'agent-1',
        target_name: 'Background Agent',
        parent_run_id: 'run-1',
        launcher_id: 'launcher-1',
        background_task_id: 'task-1',
        run_depth: 1,
        status: 'completed',
        created_at: lifecycle.created_at,
        started_at: lifecycle.created_at,
        finished_at: lifecycle.created_at,
        finish_reason: 'stop',
        error_code: '',
        usage: { input_tokens: 10, output_tokens: 5, total_tokens: 15 },
        observation_status: 'available',
      }],
      events: [{
        sequence: 1,
        lifecycle_id: lifecycle.lifecycle_id,
        run_id: 'run-1',
        occurred_at: lifecycle.created_at,
        event_type: 'workflow_node',
        phase: 'started',
        span_id: 'span-1',
        parent_span_id: 'run-1',
        subject_kind: 'workflow_node',
        subject_id: 'span-1',
        subject_name: 'agent',
        workflow_node_id: 'agent',
        node_invocation_id: 'span-1',
        status: 'running',
        error_code: '',
        usage: { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
        metadata: {},
      }],
      checkpoints: { 'run-1': [{ checkpoint_id: 'checkpoint-1' }] },
      artifacts: { item_count: 2 },
      diagnostics: [],
      next_event_sequence: 1,
      event_has_more: true,
    }
    vi.spyOn(managementApi, 'listWorkflowLifecycles').mockResolvedValue({
      items: [lifecycle],
      page: 1,
      page_size: 10,
      total: 1,
      total_pages: 1,
    })
    const getDetail = vi.spyOn(managementApi, 'getWorkflowLifecycle').mockResolvedValue(detail)
    const getRun = vi.spyOn(managementApi, 'getWorkflowRun').mockImplementation(
      async (_lifecycleId, runId): Promise<WorkflowRunDetail> => ({
        ...detail.runs.find((run) => run.run_id === runId)!,
        event_count: 1,
        checkpoint_count: runId === 'run-1' ? 7 : 0,
        diagnostic_count: 0,
      }),
    )
    const downloadLifecycle = vi.spyOn(managementApi, 'downloadWorkflowLifecycle')
      .mockResolvedValue(new Blob(['lifecycle']))
    const downloadRun = vi.spyOn(managementApi, 'downloadWorkflowRun')
      .mockResolvedValue(new Blob(['run']))
    const listEvents = vi.spyOn(managementApi, 'listWorkflowLifecycleEvents')
      .mockRejectedValue(new Error('event page unavailable'))
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(() => 'blob:test'),
      revokeObjectURL: vi.fn(),
    })

    const wrapper = mount(WorkflowLifecyclesPage, {
      global: {
        plugins: [createI18n({ legacy: false, locale: 'en', messages: { en } })],
      },
    })
    await flushPromises()

    await wrapper.get('[data-testid="data-table-row"]').trigger('click')
    await flushPromises()
    expect(getDetail).toHaveBeenCalledWith(lifecycle.lifecycle_id)
    expect(wrapper.text()).toContain('Structural events')
    expect(wrapper.text()).toContain('Workflow Node')
    expect(wrapper.text()).toContain('run-1')

    await wrapper.get('[title="View Run details"]').trigger('click')
    await flushPromises()
    expect(getRun).toHaveBeenCalledWith(lifecycle.lifecycle_id, 'run-1')
    expect(wrapper.text()).toContain('Checkpoint Thread ID')
    expect(wrapper.text()).toContain('thread-1')
    expect(wrapper.text()).toContain('7')

    await wrapper.findAll('[title="View Run details"]')[1]!.trigger('click')
    await flushPromises()
    expect(getRun).toHaveBeenCalledWith(lifecycle.lifecycle_id, 'run-2')
    expect(wrapper.text()).toContain('Checkpointer not enabled')
    expect(wrapper.text()).toContain('0')

    await wrapper.get('button[data-action="download"]').trigger('click')
    await flushPromises()
    expect(downloadLifecycle).toHaveBeenCalledWith(lifecycle.lifecycle_id)

    await wrapper.findAll('[title="Download Run diagnostics"]')[0]!.trigger('click')
    await flushPromises()
    expect(downloadRun).toHaveBeenCalledWith(lifecycle.lifecycle_id, 'run-1')

    downloadRun.mockRejectedValueOnce(new Error('run diagnostics unavailable'))
    await wrapper.findAll('[title="Download Run diagnostics"]')[0]!.trigger('click')
    await flushPromises()
    expect(useToasts().items.value.some(
      (toast) => toast.title === 'Could not download run diagnostics',
    )).toBe(true)

    const loadMore = wrapper.findAll('button').find(
      (button) => button.text().includes('Load more events'),
    )
    expect(loadMore).toBeDefined()
    await loadMore!.trigger('click')
    await flushPromises()
    expect(listEvents).toHaveBeenCalledWith(lifecycle.lifecycle_id, 1)
    expect(useToasts().items.value.some(
      (toast) => toast.title === 'Could not load more events',
    )).toBe(true)
    wrapper.unmount()
    vi.unstubAllGlobals()
  })
})
