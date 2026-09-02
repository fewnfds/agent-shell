import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, type PropType } from 'vue'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  managementApi,
  type RuntimeMonitoringGraphResponse,
  type RuntimeMonitoringNodeAttemptPage,
  type RuntimeMonitoringNodeSummaryPage,
  type RuntimeMonitoringSnapshot,
  type WorkflowGraphDocument,
} from '@/api'
import { en } from '@/locales/en'

import RuntimeMonitoringPage from './RuntimeMonitoringPage.vue'

function run(
  runId: string,
  workflowName: string,
  parentRunId: string | null,
  runDepth: number,
) {
  return {
    run_id: runId,
    lifecycle_id: 'lifecycle-1',
    request_id: 'request-1',
    checkpoint_thread_id: null,
    workflow_id: `workflow-${runId}`,
    workflow_name: workflowName,
    parent_run_id: parentRunId,
    background_task_id: null,
    run_depth: runDepth,
    status: runId === 'run-root' ? 'running' as const : 'completed' as const,
    created_at: '2026-09-03T00:00:00Z',
    started_at: '2026-09-03T00:00:00Z',
    finished_at: null,
    finish_reason: '',
    error_code: '',
    usage: { input_tokens: 1, output_tokens: 2, total_tokens: 3 },
    monitoring: {
      graph: 'available' as const,
      node: 'available' as const,
      protocol: 'available' as const,
      model: 'available' as const,
      command: 'available' as const,
      created_at: '2026-09-03T00:00:00Z',
      updated_at: '2026-09-03T00:00:00Z',
    },
  }
}

const snapshot: RuntimeMonitoringSnapshot = {
  selector: { scope: 'lifecycle', id: null },
  read_at: '2026-09-03T00:00:10Z',
  lifecycle: {
    lifecycle_id: 'lifecycle-1',
    request_id: 'request-1',
    root_run_id: 'run-root',
    workflow_id: 'workflow-root',
    workflow_name: 'Parent Workflow',
    created_at: '2026-09-03T00:00:00Z',
    lifecycle_status: 'active',
    root_status: 'running',
    monitoring_capture_enabled: true,
    fully_terminal_at: null,
    message_count: 1,
  },
  summary: {
    run_count: 2,
    active_run_count: 1,
    failed_run_count: 0,
    run_status_counts: { running: 1, completed: 1 },
    node_attempt_status_counts: { running: 1, completed: 1 },
    usage: { input_tokens: 2, output_tokens: 4, total_tokens: 6 },
    partition_availability: {
      graph: 'available',
      node: 'available',
      protocol: 'available',
      model: 'available',
      command: 'available',
    },
  },
  runs: [
    run('run-root', 'Parent Workflow', null, 0),
    run('run-child', 'Child Workflow', 'run-root', 1),
  ],
  forest: {
    root_run_ids: ['run-root'],
    relationships: [{ parent_run_id: 'run-root', child_run_id: 'run-child' }],
    orphan_run_ids: [],
    relationship_availability: 'available',
  },
}

function document(nodeIds: string | string[]): WorkflowGraphDocument {
  const ids = Array.isArray(nodeIds) ? nodeIds : [nodeIds]
  return {
    definition: {
      schema_version: 1,
      state_contract: 'agent-shell.workflow.agent-invocations.v1',
      nodes: ids.map((nodeId) => ({
        id: nodeId,
        type: 'agent',
        type_version: 1,
        config: { main_agent_id: `config-${nodeId}` },
      })),
      edges: [],
    },
    layout: {
      nodes: Object.fromEntries(ids.map((nodeId, index) => (
        [nodeId, { x: index * 200, y: 0 }]
      ))),
      viewport: { x: 0, y: 0, zoom: 1 },
    },
  }
}

function graphResponse(
  runId: string,
  nodeIds: string | string[],
): RuntimeMonitoringGraphResponse {
  return {
    availability: 'available',
    read_at: '2026-09-03T00:00:10Z',
    graph: {
      run_id: runId,
      lifecycle_id: 'lifecycle-1',
      workflow_id: `workflow-${runId}`,
      workflow_name: runId === 'run-root' ? 'Parent Workflow' : 'Child Workflow',
      document_sha: `sha-${runId}`,
      document: document(nodeIds),
      created_at: '2026-09-03T00:00:00Z',
    },
  }
}

const nodePage: RuntimeMonitoringNodeSummaryPage = {
  availability: 'available',
  read_at: '2026-09-03T00:00:10Z',
  items: [],
  page: 1,
  page_size: 1,
  total: 0,
  total_pages: 1,
}

function nodeAttemptPage(
  runId: string,
  nodeId: string,
  invocationId = `invocation-${nodeId}`,
): RuntimeMonitoringNodeAttemptPage {
  return {
    availability: 'available',
    read_at: '2026-09-03T00:00:10Z',
    items: [{
      sequence: 1,
      lifecycle_id: 'lifecycle-1',
      run_id: runId,
      workflow_node_id: nodeId,
      invocation_id: invocationId,
      attempt: 1,
      node_first_attempt_time: null,
      started_at: '2026-09-03T00:00:00Z',
      finished_at: '2026-09-03T00:00:01Z',
      status: 'completed',
      error_code: '',
    }],
    page: 1,
    page_size: 20,
    total: 1,
    total_pages: 1,
  }
}

const RuntimeWorkflowCanvasStub = defineComponent({
  name: 'RuntimeWorkflowCanvas',
  props: {
    document: { type: Object as PropType<WorkflowGraphDocument>, required: true },
    selectedNodeId: { type: String, required: true },
  },
  emits: ['selectNode'],
  setup(props, { emit }) {
    return () => h('div', { 'data-testid': 'runtime-workflow-canvas' }, [
      props.document.definition.nodes.map((node) => h('button', {
        'data-testid': `select-node-${node.id}`,
        'data-selected': node.id === props.selectedNodeId,
        onClick: () => emit('selectNode', node.id),
      }, node.id)),
    ])
  },
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((accept) => { resolve = accept })
  return { promise, resolve }
}

async function mountPage(initialPath = '/system/workflow-lifecycles/lifecycle-1/monitoring') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/system/workflow-lifecycles', component: { template: '<div />' } },
      {
        path: '/system/workflow-lifecycles/:lifecycleId/monitoring',
        component: RuntimeMonitoringPage,
      },
    ],
  })
  await router.push(initialPath)
  await router.isReady()
  const wrapper = mount({ template: '<RouterView />' }, {
    global: {
      plugins: [
        router,
        createI18n({ legacy: false, locale: 'en', messages: { en } }),
      ],
      stubs: { RuntimeWorkflowCanvas: RuntimeWorkflowCanvasStub },
    },
  })
  await flushPromises()
  return { router, wrapper }
}

beforeEach(() => {
  vi.spyOn(managementApi, 'getRuntimeMonitoringSnapshot').mockResolvedValue(snapshot)
  vi.spyOn(managementApi, 'listWorkflowNodeCatalog').mockResolvedValue([])
  vi.spyOn(managementApi, 'getRuntimeMonitoringGraph').mockImplementation((_, runId) => (
    Promise.resolve(graphResponse(runId, runId === 'run-root' ? 'root-agent' : 'child-agent'))
  ))
  vi.spyOn(managementApi, 'listRuntimeMonitoringNodes').mockResolvedValue(nodePage)
  vi.spyOn(managementApi, 'listRuntimeMonitoringNodeAttempts').mockImplementation((
    _, runId, nodeId,
  ) => Promise.resolve(nodeAttemptPage(runId, nodeId)))
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('RuntimeMonitoringPage', () => {
  it('selects the Lifecycle root by default and stores later Run selection in the URL', async () => {
    const { router, wrapper } = await mountPage()

    expect(managementApi.getRuntimeMonitoringGraph).toHaveBeenCalledWith(
      'lifecycle-1',
      'run-root',
      expect.any(AbortSignal),
    )
    expect(wrapper.get('[data-testid="runtime-workflow-canvas"]').text()).toBe('root-agent')
    expect(router.currentRoute.value.query.run_id).toBe('run-root')

    const childButton = wrapper.findAll('.runtime-run-index-button').find((button) => (
      button.text().includes('Child Workflow')
    ))
    await childButton!.trigger('click')
    await flushPromises()

    expect(managementApi.getRuntimeMonitoringGraph).toHaveBeenCalledWith(
      'lifecycle-1',
      'run-child',
      expect.any(AbortSignal),
    )
    expect(wrapper.get('[data-testid="runtime-workflow-canvas"]').text()).toBe('child-agent')
    expect(router.currentRoute.value.query.run_id).toBe('run-child')
  })

  it('does not let an earlier Run response replace the newly selected Run', async () => {
    const rootGraph = deferred<RuntimeMonitoringGraphResponse>()
    vi.mocked(managementApi.getRuntimeMonitoringGraph).mockImplementation((_, runId) => (
      runId === 'run-root'
        ? rootGraph.promise
        : Promise.resolve(graphResponse('run-child', 'child-agent'))
    ))
    const { wrapper } = await mountPage()

    const childButton = wrapper.findAll('.runtime-run-index-button').find((button) => (
      button.text().includes('Child Workflow')
    ))
    await childButton!.trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-testid="runtime-workflow-canvas"]').text()).toBe('child-agent')

    rootGraph.resolve(graphResponse('run-root', 'stale-root-agent'))
    await flushPromises()

    expect(wrapper.get('[data-testid="runtime-workflow-canvas"]').text()).toBe('child-agent')
    expect(wrapper.text()).not.toContain('stale-root-agent')
  })

  it('keeps the Run index usable when one Run has no available frozen Graph', async () => {
    vi.mocked(managementApi.getRuntimeMonitoringGraph).mockImplementation((_, runId) => (
      Promise.resolve(runId === 'run-root'
        ? { availability: 'unavailable', read_at: '2026-09-03T00:00:10Z', graph: null }
        : graphResponse('run-child', 'child-agent'))
    ))
    const { wrapper } = await mountPage()

    expect(wrapper.text()).toContain('The frozen Workflow Graph is currently unavailable.')
    expect(wrapper.findAll('.runtime-run-index-button')).toHaveLength(2)

    const childButton = wrapper.findAll('.runtime-run-index-button').find((button) => (
      button.text().includes('Child Workflow')
    ))
    await childButton!.trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="runtime-workflow-canvas"]').text()).toBe('child-agent')
  })

  it('loads the selected Node attempts for the exact Lifecycle and Run and stores it in the URL', async () => {
    const { router, wrapper } = await mountPage()

    await wrapper.get('[data-testid="select-node-root-agent"]').trigger('click')
    await flushPromises()

    expect(managementApi.listRuntimeMonitoringNodeAttempts).toHaveBeenCalledWith(
      'lifecycle-1',
      'run-root',
      'root-agent',
      { page: 1, page_size: 20 },
      expect.any(AbortSignal),
    )
    expect(router.currentRoute.value.query.node_id).toBe('root-agent')
    expect(wrapper.get('.runtime-monitoring-node-panel').text())
      .toContain('invocation-root-agent')
  })

  it('does not let an earlier Node response replace the newly selected Node', async () => {
    vi.mocked(managementApi.getRuntimeMonitoringGraph).mockImplementation((_, runId) => (
      Promise.resolve(graphResponse(
        runId,
        runId === 'run-root'
          ? ['root-agent', 'second-agent']
          : ['child-agent'],
      ))
    ))
    const firstNode = deferred<RuntimeMonitoringNodeAttemptPage>()
    vi.mocked(managementApi.listRuntimeMonitoringNodeAttempts).mockImplementation((
      _, runId, nodeId,
    ) => (
      nodeId === 'root-agent'
        ? firstNode.promise
        : Promise.resolve(nodeAttemptPage(runId, nodeId, 'current-invocation'))
    ))
    const { wrapper } = await mountPage()

    await wrapper.get('[data-testid="select-node-root-agent"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="select-node-second-agent"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('.runtime-monitoring-node-panel').text()).toContain('current-invocation')

    firstNode.resolve(nodeAttemptPage('run-root', 'root-agent', 'stale-invocation'))
    await flushPromises()

    expect(wrapper.get('.runtime-monitoring-node-panel').text()).toContain('current-invocation')
    expect(wrapper.text()).not.toContain('stale-invocation')
  })

  it('closes Node details and removes node_id when selecting another Run', async () => {
    const { router, wrapper } = await mountPage()

    await wrapper.get('[data-testid="select-node-root-agent"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('.runtime-monitoring-node-panel').exists()).toBe(true)

    const childButton = wrapper.findAll('.runtime-run-index-button').find((button) => (
      button.text().includes('Child Workflow')
    ))
    await childButton!.trigger('click')
    await flushPromises()

    expect(wrapper.find('.runtime-monitoring-node-panel').exists()).toBe(false)
    expect(router.currentRoute.value.query.run_id).toBe('run-child')
    expect(router.currentRoute.value.query.node_id).toBeUndefined()
  })

  it('restores a valid Node deep link after its frozen Graph loads', async () => {
    const { router, wrapper } = await mountPage(
      '/system/workflow-lifecycles/lifecycle-1/monitoring?run_id=run-root&node_id=root-agent',
    )

    expect(router.currentRoute.value.query.node_id).toBe('root-agent')
    expect(managementApi.listRuntimeMonitoringNodeAttempts).toHaveBeenCalledWith(
      'lifecycle-1',
      'run-root',
      'root-agent',
      { page: 1, page_size: 20 },
      expect.any(AbortSignal),
    )
    expect(wrapper.get('[data-testid="select-node-root-agent"]')
      .attributes('data-selected')).toBe('true')
  })

  it('removes an invalid Node deep link without requesting attempt data', async () => {
    const { router, wrapper } = await mountPage(
      '/system/workflow-lifecycles/lifecycle-1/monitoring?run_id=run-root&node_id=missing-node',
    )

    expect(router.currentRoute.value.query.node_id).toBeUndefined()
    expect(managementApi.listRuntimeMonitoringNodeAttempts).not.toHaveBeenCalled()
    expect(wrapper.get('[data-testid="runtime-workflow-canvas"]').text()).toBe('root-agent')
  })

  it('keeps the Run index and Graph usable when Node attempt data is unavailable', async () => {
    vi.mocked(managementApi.listRuntimeMonitoringNodeAttempts).mockResolvedValue({
      ...nodeAttemptPage('run-root', 'root-agent'),
      availability: 'unavailable',
      items: [],
      total: 0,
    })
    const { wrapper } = await mountPage()

    await wrapper.get('[data-testid="select-node-root-agent"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Node attempt data is unavailable.')
    expect(wrapper.get('[data-testid="runtime-workflow-canvas"]').text()).toBe('root-agent')
    expect(wrapper.findAll('.runtime-run-index-button')).toHaveLength(2)
  })

  it('keeps the Run index and Graph usable when a Node attempt request fails', async () => {
    vi.mocked(managementApi.listRuntimeMonitoringNodeAttempts)
      .mockRejectedValue(new Error('attempt endpoint failed'))
    const { wrapper } = await mountPage()

    await wrapper.get('[data-testid="select-node-root-agent"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('.runtime-monitoring-node-panel .alert-danger').exists()).toBe(true)
    expect(wrapper.get('[data-testid="runtime-workflow-canvas"]').text()).toBe('root-agent')
    expect(wrapper.findAll('.runtime-run-index-button')).toHaveLength(2)
  })
})
