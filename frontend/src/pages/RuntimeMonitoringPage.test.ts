import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { managementApi, type LangGraphLifecycleSnapshot } from '@/api'
import { en } from '@/locales/en'

import RuntimeMonitoringPage from './RuntimeMonitoringPage.vue'

const snapshot: LangGraphLifecycleSnapshot = {
  lifecycle_id: 'lifecycle-1',
  request_id: 'request-1',
  created_at: '2026-09-06T00:00:00Z',
  updated_at: '2026-09-06T00:01:00Z',
  status: 'success',
  subjects: [
    { graph_kind: 'agent', id: 'agent-1', name: 'Research Agent' },
    { graph_kind: 'workflow', id: 'workflow-1', name: 'Review Workflow' },
  ],
  run_count: 2,
  active_run_count: 0,
  error_run_count: 0,
  threads: [],
  runs: [
    {
      run_id: 'run-agent',
      thread_id: 'thread-agent',
      assistant_id: 'assistant-agent',
      created_at: '2026-09-06T00:00:00Z',
      updated_at: '2026-09-06T00:00:30Z',
      status: 'success',
      metadata: {
        graph_kind: 'agent',
        main_agent_id: 'agent-1',
        main_agent_name: 'Research Agent',
      },
      multitask_strategy: 'enqueue',
    },
    {
      run_id: 'run-workflow',
      thread_id: 'thread-workflow',
      assistant_id: 'assistant-workflow',
      created_at: '2026-09-06T00:00:31Z',
      updated_at: '2026-09-06T00:01:00Z',
      status: 'success',
      metadata: {
        graph_kind: 'workflow',
        workflow_id: 'workflow-1',
        workflow_name: 'Review Workflow',
      },
      multitask_strategy: 'enqueue',
    },
  ],
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('RuntimeMonitoringPage', () => {
  it('labels Agent and Workflow Runs from their graph metadata', async () => {
    vi.spyOn(managementApi, 'getLangGraphLifecycleSnapshot').mockResolvedValue(snapshot)
    vi.spyOn(managementApi, 'getLangGraphRunGraph').mockResolvedValue({
      run_id: 'run-agent',
      assistant_id: 'assistant-agent',
      graph: {},
    })
    vi.spyOn(managementApi, 'getLangGraphRunState').mockResolvedValue({
      run_id: 'run-agent',
      thread_id: 'thread-agent',
      state: {},
    })
    vi.spyOn(managementApi, 'getLangGraphRunHistory').mockResolvedValue({
      run_id: 'run-agent',
      thread_id: 'thread-agent',
      history: [],
    })
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        {
          path: '/system/workflow-lifecycles/:lifecycleId/monitoring',
          component: RuntimeMonitoringPage,
        },
        { path: '/system/workflow-lifecycles', component: { template: '<div />' } },
      ],
    })
    await router.push('/system/workflow-lifecycles/lifecycle-1/monitoring')
    await router.isReady()

    const wrapper = mount(RuntimeMonitoringPage, {
      global: {
        plugins: [createI18n({ legacy: false, locale: 'en', messages: { en } }), router],
      },
    })
    await flushPromises()

    const runLabels = wrapper.findAll('[role="option"] .fw-semibold')
      .map((item) => item.text())
    expect(runLabels).toEqual(['Research Agent', 'Review Workflow'])
    expect(runLabels).not.toContain('run-agent')
    wrapper.unmount()
  })
})
