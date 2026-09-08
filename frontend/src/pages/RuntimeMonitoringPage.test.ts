import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { managementApi, type LangGraphLifecycleSnapshot } from '@/api'
import { en } from '@/locales/en'

import RuntimeMonitoringPage from './RuntimeMonitoringPage.vue'

const snapshot: LangGraphLifecycleSnapshot = {
  lifecycle_id: 'lifecycle-1',
  request_id: 'request-1',
  created_at: '2026-09-06T00:00:00Z',
  updated_at: '2026-09-06T00:01:00Z',
  status: 'running',
  subjects: [
    { graph_kind: 'agent', id: 'agent-1', name: 'Research Agent' },
    { graph_kind: 'workflow', id: 'workflow-1', name: 'Review Workflow' },
  ],
  run_count: 3,
  active_run_count: 1,
  error_run_count: 0,
  threads: [
    {
      thread_id: 'thread-agent',
      thread: {
        thread_id: 'thread-agent',
        created_at: '2026-09-06T00:00:00Z',
        updated_at: '2026-09-06T00:00:30Z',
        metadata: { lifecycle_id: 'lifecycle-1' },
        status: 'busy',
        values: {},
        interrupts: {},
      },
      error: null,
      runs: [
        {
          run_id: 'run-agent',
          run: {
            run_id: 'run-agent',
            thread_id: 'thread-agent',
            assistant_id: 'assistant-agent',
            created_at: '2026-09-06T00:00:00Z',
            updated_at: '2026-09-06T00:00:30Z',
            status: 'running',
            metadata: {
              graph_kind: 'agent',
              main_agent_id: 'agent-1',
              main_agent_name: 'Research Agent',
            },
            multitask_strategy: 'enqueue',
          },
          relation: {
            lifecycle_id: 'lifecycle-1',
            graph_kind: 'agent',
            operation_id: 'entry',
            caller_run_id: '',
            resource_id: 'agent-1',
            resource_name: 'Research Agent',
            on_disconnect: 'continue',
            assistant_id: 'assistant-agent',
            thread_id: 'thread-agent',
            run_id: 'run-agent',
          },
          error: null,
        },
        {
          run_id: 'run-agent-2',
          run: {
            run_id: 'run-agent-2',
            thread_id: 'thread-agent',
            assistant_id: 'assistant-agent',
            created_at: '2026-09-06T00:00:20Z',
            updated_at: '2026-09-06T00:00:25Z',
            status: 'success',
            metadata: {
              graph_kind: 'agent',
              main_agent_id: 'agent-1',
              main_agent_name: 'Research Agent',
            },
            multitask_strategy: 'enqueue',
          },
          relation: {
            lifecycle_id: 'lifecycle-1',
            graph_kind: 'agent',
            operation_id: 'follow-up',
            caller_run_id: '',
            resource_id: 'agent-1',
            resource_name: 'Research Agent',
            on_disconnect: 'continue',
            assistant_id: 'assistant-agent',
            thread_id: 'thread-agent',
            run_id: 'run-agent-2',
          },
          error: null,
        },
      ],
    },
    {
      thread_id: 'thread-workflow',
      thread: {
        thread_id: 'thread-workflow',
        created_at: '2026-09-06T00:00:31Z',
        updated_at: '2026-09-06T00:01:00Z',
        metadata: { lifecycle_id: 'lifecycle-1' },
        status: 'idle',
        values: {},
        interrupts: {},
      },
      error: null,
      runs: [
        {
          run_id: 'run-workflow',
          run: {
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
          relation: {
            lifecycle_id: 'lifecycle-1',
            graph_kind: 'workflow',
            operation_id: 'review',
            caller_run_id: 'run-agent',
            resource_id: 'workflow-1',
            resource_name: 'Review Workflow',
            on_disconnect: 'continue',
            assistant_id: 'assistant-workflow',
            thread_id: 'thread-workflow',
            run_id: 'run-workflow',
          },
          error: null,
        },
      ],
    },
  ],
}

const AgentThreadViewStub = defineComponent({
  name: 'AgentThreadView',
  props: ['assistantId', 'threadId'],
  template: '<div data-testid="agent-thread">{{ assistantId }}:{{ threadId }}</div>',
})

const WorkflowRuntimeViewStub = defineComponent({
  name: 'WorkflowRuntimeView',
  props: ['graph', 'state'],
  template: '<div data-testid="workflow-runtime">{{ state?.next?.join(",") }}</div>',
})

const browserStorage = new Map<string, string>()
const browserStorageMock = {
  clear: () => browserStorage.clear(),
  getItem: (key: string) => browserStorage.get(key) ?? null,
  key: (index: number) => [...browserStorage.keys()][index] ?? null,
  get length() {
    return browserStorage.size
  },
  removeItem: (key: string) => browserStorage.delete(key),
  setItem: (key: string, value: string) => browserStorage.set(key, String(value)),
}

beforeEach(() => {
  browserStorage.clear()
  vi.stubGlobal('localStorage', browserStorageMock)
})

afterEach(() => {
  vi.restoreAllMocks()
  browserStorage.clear()
  vi.unstubAllGlobals()
})

describe('RuntimeMonitoringPage', () => {
  it('selects active Thread, switches Graph view, and displays Lifecycle Store', async () => {
    vi.spyOn(managementApi, 'getLangGraphLifecycleSnapshot').mockResolvedValue(snapshot)
    vi.spyOn(managementApi, 'getLangGraphLifecycleStore').mockResolvedValue({
      lifecycle_id: 'lifecycle-1',
      namespaces: [
        {
          namespace: ['workflow-lifecycle', 'lifecycle-1', 'filesystem'],
          items: [
            {
              namespace: ['workflow-lifecycle', 'lifecycle-1', 'filesystem'],
              key: 'workspace',
              value: { path: 'H:/workspace' },
              created_at: '2026-09-06T00:00:00Z',
              updated_at: '2026-09-06T00:00:01Z',
            },
          ],
        },
      ],
    })
    vi.spyOn(managementApi, 'getLangGraphRunState').mockImplementation(async (_lifecycleId, runId) => ({
      run_id: runId,
      thread_id: runId.startsWith('run-agent') ? 'thread-agent' : 'thread-workflow',
      state: { values: { answer: 42 }, next: runId === 'run-workflow' ? ['review'] : [] },
      error: null,
    }))
    const graphSpy = vi.spyOn(managementApi, 'getLangGraphRunGraph').mockResolvedValue({
      run_id: 'run-workflow',
      assistant_id: 'assistant-workflow',
      graph: {
        nodes: [{ id: '__start__' }, { id: 'review' }, { id: '__end__' }],
        edges: [
          { source: '__start__', target: 'review' },
          { source: 'review', target: '__end__' },
        ],
      },
      error: null,
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
        stubs: {
          AgentThreadView: AgentThreadViewStub,
          WorkflowRuntimeView: WorkflowRuntimeViewStub,
        },
      },
    })
    await flushPromises()

    expect(wrapper.findAll('.runtime-thread-row')).toHaveLength(2)
    expect(wrapper.get('[data-testid="agent-thread"]').text()).toContain('thread-agent')
    const agentRuns = wrapper.findAll('.runtime-run-item')
    expect(agentRuns).toHaveLength(2)
    expect(agentRuns[0]?.attributes('aria-current')).toBe('true')
    await agentRuns[1]?.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.runtime-run-item')[1]?.attributes('aria-current')).toBe('true')

    const workflowThread = wrapper.findAll('.runtime-thread-row')
      .find((row) => row.text().includes('Review Workflow'))
    expect(workflowThread).toBeDefined()
    await workflowThread?.trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="workflow-runtime"]').text()).toBe('review')
    expect(graphSpy).toHaveBeenCalledWith('lifecycle-1', 'run-workflow')

    const storeTab = wrapper.findAll('.runtime-inspector-tab')
      .find((button) => button.text() === 'Store')
    await storeTab?.trigger('click')
    expect(wrapper.text()).toContain('filesystem')
    expect(wrapper.text()).toContain('workspace')
    expect(wrapper.find('pre').exists()).toBe(false)
    wrapper.unmount()
  })

  it('resizes the three columns and restores their widths from browser storage', async () => {
    vi.spyOn(managementApi, 'getLangGraphLifecycleSnapshot').mockResolvedValue(snapshot)
    vi.spyOn(managementApi, 'getLangGraphLifecycleStore').mockResolvedValue({
      lifecycle_id: 'lifecycle-1',
      namespaces: [],
    })
    vi.spyOn(managementApi, 'getLangGraphRunState').mockResolvedValue({
      run_id: 'run-agent',
      thread_id: 'thread-agent',
      state: { values: {}, next: [] },
      error: null,
    })
    window.localStorage.setItem(
      'agent-shell.runtime-monitoring.columns.v1',
      JSON.stringify({ threads: 320, inspector: 360 }),
    )

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        {
          path: '/system/workflow-lifecycles/:lifecycleId/monitoring',
          component: RuntimeMonitoringPage,
        },
      ],
    })
    await router.push('/system/workflow-lifecycles/lifecycle-1/monitoring')
    await router.isReady()

    const mountPage = () => mount(RuntimeMonitoringPage, {
      global: {
        plugins: [createI18n({ legacy: false, locale: 'en', messages: { en } }), router],
        stubs: { AgentThreadView: AgentThreadViewStub },
      },
    })
    const wrapper = mountPage()
    await flushPromises()

    const workbench = wrapper.get('.runtime-monitoring-workbench')
    expect((workbench.element as HTMLElement).style.getPropertyValue('--runtime-threads-width'))
      .toBe('320px')
    expect((workbench.element as HTMLElement).style.getPropertyValue('--runtime-inspector-width'))
      .toBe('360px')
    expect(wrapper.findAll('[role="separator"]')).toHaveLength(2)
    expect(wrapper.find('.page-action-dock').exists()).toBe(false)

    await wrapper.findAll('[role="separator"]')[0]?.trigger('keydown', { key: 'ArrowRight' })
    expect(JSON.parse(window.localStorage.getItem(
      'agent-shell.runtime-monitoring.columns.v1',
    ) ?? '{}')).toEqual({ threads: 336, inspector: 360 })
    wrapper.unmount()

    const restoredWrapper = mountPage()
    await flushPromises()
    expect((restoredWrapper.get('.runtime-monitoring-workbench').element as HTMLElement)
      .style.getPropertyValue('--runtime-threads-width')).toBe('336px')
    restoredWrapper.unmount()
  })
})
