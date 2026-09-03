import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, type PropType } from 'vue'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  managementApi,
  type RuntimeMonitoringGraphResponse,
  type RuntimeMonitoringProtocolEventSequence,
  type RuntimeMonitoringNodeAttemptPage,
  type RuntimeMonitoringNodeSummaryPage,
  type RuntimeMonitoringSnapshot,
  type WorkflowGraphDocument,
} from '@/api'
import { useToasts } from '@/composables/useToasts'
import { en } from '@/locales/en'

import RuntimeMonitoringPage from './RuntimeMonitoringPage.vue'

const triggerBrowserDownload = vi.hoisted(() => vi.fn())

vi.mock('@/utils/download', () => ({ triggerBrowserDownload }))

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

function scopedSnapshot(
  selector: RuntimeMonitoringSnapshot['selector'],
  runs: RuntimeMonitoringSnapshot['runs'],
): RuntimeMonitoringSnapshot {
  const runIds = new Set(runs.map((item) => item.run_id))
  const relationships = snapshot.forest.relationships.filter((item) => (
    runIds.has(item.parent_run_id) && runIds.has(item.child_run_id)
  ))
  return {
    ...snapshot,
    selector,
    summary: {
      ...snapshot.summary,
      run_count: runs.length,
      active_run_count: runs.filter((item) => item.status === 'running').length,
      failed_run_count: runs.filter((item) => item.status === 'failed').length,
    },
    runs,
    forest: {
      root_run_ids: runs.filter((item) => (
        !item.parent_run_id || !runIds.has(item.parent_run_id)
      )).map((item) => item.run_id),
      relationships,
      orphan_run_ids: [],
      relationship_availability: 'available',
    },
  }
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

const emptyProtocol: RuntimeMonitoringProtocolEventSequence = {
  availability: 'available',
  read_at: '2026-09-03T00:00:10Z',
  items: [],
  after_sequence: 0,
  next_after_sequence: 0,
  limit: 100,
  remaining: 0,
}

const mountedWrappers: Array<{ unmount: () => void }> = []

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
  mountedWrappers.push(wrapper)
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
  vi.spyOn(managementApi, 'getRuntimeMonitoringAgentInvocation').mockResolvedValue({
    availability: 'not_applicable',
    read_at: '2026-09-03T00:00:10Z',
    workflow_node_id: 'root-agent',
    artifact: null,
  })
  vi.spyOn(managementApi, 'listRuntimeMonitoringProtocolEvents')
    .mockResolvedValue(emptyProtocol)
  vi.spyOn(managementApi, 'listRuntimeMonitoringCommandObservations').mockResolvedValue({
    availability: 'available',
    read_at: '2026-09-03T00:00:10Z',
    items: [],
    after_sequence: 0,
    next_after_sequence: 0,
    limit: 100,
    remaining: 0,
  })
  vi.spyOn(managementApi, 'listRuntimeMonitoringModelRequests').mockResolvedValue({
    availability: 'available',
    read_at: '2026-09-03T00:00:10Z',
    items: [],
    page: 1,
    page_size: 20,
    total: 0,
    total_pages: 1,
  })
  vi.spyOn(managementApi, 'getRuntimeMonitoringState').mockResolvedValue({
    availability: 'not_enabled',
    read_at: '2026-09-03T00:00:10Z',
    state: null,
  })
  vi.spyOn(managementApi, 'downloadWorkflowRun').mockResolvedValue({
    blob: new Blob(['runtime archive']),
    filename: 'runtime-monitoring-run-run-root.zip',
  })
})

afterEach(() => {
  for (const wrapper of mountedWrappers.splice(0)) wrapper.unmount()
  const toasts = useToasts()
  for (const toast of toasts.items.value) toasts.dismiss(toast.id)
  triggerBrowserDownload.mockReset()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('RuntimeMonitoringPage', () => {
  it('downloads the currently selected Run without changing the monitoring view', async () => {
    const { router, wrapper } = await mountPage()

    await wrapper.get('button[data-action="download-run"]').trigger('click')
    await flushPromises()

    expect(managementApi.downloadWorkflowRun).toHaveBeenCalledWith(
      'lifecycle-1',
      'run-root',
    )
    expect(triggerBrowserDownload).toHaveBeenCalledWith(
      expect.any(Blob),
      'runtime-monitoring-run-run-root.zip',
    )
    expect(router.currentRoute.value.query.run_id).toBe('run-root')
  })

  it('reports a Run archive download failure without disrupting monitoring', async () => {
    vi.mocked(managementApi.downloadWorkflowRun).mockRejectedValueOnce(
      new Error('download failed'),
    )
    const { wrapper } = await mountPage()

    await wrapper.get('button[data-action="download-run"]').trigger('click')
    await flushPromises()

    expect(triggerBrowserDownload).not.toHaveBeenCalled()
    expect(useToasts().items.value.some(
      (toast) => toast.title === 'Could not download Run runtime data',
    )).toBe(true)
    expect(wrapper.get('[data-testid="runtime-workflow-canvas"]').exists()).toBe(true)
  })

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

  it('uses the backend Workflow scope without rebuilding descendants in the browser', async () => {
    const child = snapshot.runs[1]!
    const workflowSnapshot = scopedSnapshot(
      { scope: 'workflow', id: child.workflow_id },
      [child],
    )
    vi.mocked(managementApi.getRuntimeMonitoringSnapshot).mockImplementation((_, request) => (
      Promise.resolve(request?.workflow_id ? workflowSnapshot : snapshot)
    ))

    const { router, wrapper } = await mountPage(
      `/system/workflow-lifecycles/lifecycle-1/monitoring?scope=workflow&workflow_id=${child.workflow_id}`,
    )

    expect(managementApi.getRuntimeMonitoringSnapshot).toHaveBeenCalledWith(
      'lifecycle-1',
      { workflow_id: child.workflow_id },
      expect.any(AbortSignal),
    )
    expect(wrapper.findAll('.runtime-run-index-button')).toHaveLength(1)
    expect(wrapper.get('.runtime-run-index-button').text()).toContain('Child Workflow')
    expect(router.currentRoute.value.query.run_id).toBe('run-child')
  })

  it('switches Workflow scope through URL state and the backend selector', async () => {
    const root = snapshot.runs[0]!
    const child = snapshot.runs[1]!
    const rootScope = scopedSnapshot(
      { scope: 'workflow', id: root.workflow_id },
      snapshot.runs,
    )
    const childScope = scopedSnapshot(
      { scope: 'workflow', id: child.workflow_id },
      [child],
    )
    vi.mocked(managementApi.getRuntimeMonitoringSnapshot).mockImplementation((_, request) => {
      if (request?.workflow_id === root.workflow_id) return Promise.resolve(rootScope)
      if (request?.workflow_id === child.workflow_id) return Promise.resolve(childScope)
      return Promise.resolve(snapshot)
    })
    const { router, wrapper } = await mountPage(
      `/system/workflow-lifecycles/lifecycle-1/monitoring?scope=workflow&workflow_id=${root.workflow_id}&run_id=run-root`,
    )

    await wrapper.get('#runtime-monitoring-workflow-scope').setValue(child.workflow_id)
    await flushPromises()

    expect(managementApi.getRuntimeMonitoringSnapshot).toHaveBeenCalledWith(
      'lifecycle-1',
      { workflow_id: child.workflow_id },
      expect.any(AbortSignal),
    )
    expect(router.currentRoute.value.query).toMatchObject({
      scope: 'workflow',
      workflow_id: child.workflow_id,
      run_id: child.run_id,
    })
    expect(wrapper.findAll('.runtime-run-index-button')).toHaveLength(1)
    expect(wrapper.get('.runtime-run-index-button').text()).toContain('Child Workflow')
  })

  it('uses the backend exact Run scope and keeps that identity in the deep link', async () => {
    const child = snapshot.runs[1]!
    const runSnapshot = scopedSnapshot({ scope: 'run', id: child.run_id }, [child])
    vi.mocked(managementApi.getRuntimeMonitoringSnapshot).mockImplementation((_, request) => (
      Promise.resolve(request?.run_id ? runSnapshot : snapshot)
    ))

    const { router, wrapper } = await mountPage(
      '/system/workflow-lifecycles/lifecycle-1/monitoring?scope=run&run_id=run-child',
    )

    expect(managementApi.getRuntimeMonitoringSnapshot).toHaveBeenCalledWith(
      'lifecycle-1',
      { run_id: 'run-child' },
      expect.any(AbortSignal),
    )
    expect(wrapper.findAll('.runtime-run-index-button')).toHaveLength(1)
    expect(wrapper.get('.runtime-run-index-button').text()).toContain('Child Workflow')
    expect(router.currentRoute.value.query).toMatchObject({ scope: 'run', run_id: 'run-child' })
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

  it('keeps a loaded Graph usable when Node activity summaries fail', async () => {
    vi.mocked(managementApi.listRuntimeMonitoringNodes)
      .mockRejectedValueOnce(new Error('node summary endpoint failed'))
      .mockResolvedValue(nodePage)
    const { wrapper } = await mountPage()

    expect(wrapper.text()).toContain('Could not refresh Node activity')
    expect(wrapper.get('[data-testid="runtime-workflow-canvas"]').text()).toBe('root-agent')
    expect(wrapper.findAll('.runtime-run-index-button')).toHaveLength(2)

    await wrapper.get('.runtime-monitoring-graph-panel .alert-warning button').trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('Could not refresh Node activity')
    expect(wrapper.get('[data-testid="runtime-workflow-canvas"]').text()).toBe('root-agent')
    expect(managementApi.getRuntimeMonitoringGraph).toHaveBeenCalledTimes(1)
  })

  it('restores a Run data deep link even when its Graph request fails', async () => {
    vi.mocked(managementApi.getRuntimeMonitoringGraph)
      .mockRejectedValue(new Error('graph endpoint failed'))
    vi.mocked(managementApi.getRuntimeMonitoringState).mockResolvedValue({
      availability: 'available',
      read_at: '2026-09-03T00:00:10Z',
      state: {
        checkpoint_id: 'checkpoint-without-graph',
        checkpoint_ns: '',
        created_at: '2026-09-03T00:00:09Z',
        source: 'loop',
        step: 1,
        pending_write_count: 0,
        state: { answer: 'still available' },
      },
    })

    const { wrapper } = await mountPage(
      '/system/workflow-lifecycles/lifecycle-1/monitoring?run_id=run-root&view=state',
    )

    expect(wrapper.text()).toContain('Could not load this Run’s Workflow Graph')
    expect(wrapper.text()).toContain('checkpoint-without-graph')
    expect(wrapper.text()).toContain('still available')
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

  it('loads exact Agent invocation data and its direct-origin event stream', async () => {
    vi.mocked(managementApi.getRuntimeMonitoringAgentInvocation).mockResolvedValue({
      availability: 'available',
      read_at: '2026-09-03T00:00:10Z',
      workflow_node_id: 'root-agent',
      artifact: {
        invocation_id: 'invocation-root-agent',
        messages: [{
          role: 'assistant',
          content: [
            { type: 'text', text: 'completed answer' },
            { type: 'tool-call', name: 'search', arguments: { query: 'facts' } },
          ],
        }],
      },
    })
    vi.mocked(managementApi.listRuntimeMonitoringProtocolEvents).mockResolvedValue({
      ...emptyProtocol,
      items: [{
        sequence: 7,
        method: 'messages',
        captured_at: '2026-09-03T00:00:05Z',
        envelope: {
          type: 'event',
          method: 'messages',
          seq: 7,
          params: {
            namespace: [],
            timestamp: 1,
            data: [{
              event: 'content-block-delta',
              index: 0,
              delta: { type: 'text-delta', text: 'streamed answer' },
            }, { run_id: 'model-1' }],
          },
        },
        origin: {
          source_type: 'agent',
          workflow_node_id: 'root-agent',
          node_invocation_id: 'invocation-root-agent',
          agent_profile_id: 'agent-1',
          subagent_profile_id: '',
        },
      }],
      next_after_sequence: 7,
    })
    const { wrapper } = await mountPage()

    await wrapper.get('[data-testid="select-node-root-agent"]').trigger('click')
    await flushPromises()

    expect(managementApi.getRuntimeMonitoringAgentInvocation).toHaveBeenCalledWith(
      'lifecycle-1',
      'run-root',
      'invocation-root-agent',
      expect.any(AbortSignal),
    )
    expect(managementApi.listRuntimeMonitoringProtocolEvents).toHaveBeenCalledWith(
      'lifecycle-1',
      'run-root',
      {
        after_sequence: 0,
        node_id: 'root-agent',
        invocation_id: 'invocation-root-agent',
      },
      expect.any(AbortSignal),
    )
    expect(wrapper.text()).toContain('streamed answer')
    expect(wrapper.text()).toContain('completed answer')
    expect(wrapper.text()).toContain('tool-call')
    expect(wrapper.text()).toContain('search')
  })

  it('shows only direct Command observations for the selected Command Node', async () => {
    vi.mocked(managementApi.getRuntimeMonitoringGraph).mockImplementation((_, runId) => {
      if (runId !== 'run-root') return Promise.resolve(graphResponse(runId, 'child-agent'))
      const response = graphResponse(runId, 'command-1')
      response.graph!.document.definition.nodes = [{
        id: 'command-1',
        type: 'command',
        type_version: 1,
        config: { command_id: 'command-config-1' },
      }]
      return Promise.resolve(response)
    })
    vi.mocked(managementApi.listRuntimeMonitoringCommandObservations)
      .mockResolvedValueOnce({
        availability: 'available',
        read_at: '2026-09-03T00:00:10Z',
        items: [{
          sequence: 8,
          invocation_id: 'command-invocation',
          workflow_node_id: 'command-1',
          attempt: 1,
          occurred_at: '2026-09-03T00:00:05Z',
          phase: 'completed',
          error_code: '',
          payload: { activate: ['approved'], update: { accepted: true } },
        }],
        after_sequence: 0,
        next_after_sequence: 8,
        limit: 1,
        remaining: 1,
      })
      .mockResolvedValue({
        availability: 'available',
        read_at: '2026-09-03T00:00:11Z',
        items: [{
          sequence: 9,
          invocation_id: 'command-invocation',
          workflow_node_id: 'command-1',
          attempt: 1,
          occurred_at: '2026-09-03T00:00:06Z',
          phase: 'completed',
          error_code: '',
          payload: { dispatch: [{ task_id: 'task-1' }] },
        }],
        after_sequence: 8,
        next_after_sequence: 9,
        limit: 1,
        remaining: 0,
      })
    const { wrapper } = await mountPage()

    await wrapper.get('[data-testid="select-node-command-1"]').trigger('click')
    await flushPromises()

    expect(managementApi.listRuntimeMonitoringCommandObservations).toHaveBeenCalledWith(
      'lifecycle-1',
      'run-root',
      { after_sequence: 0, node_id: 'command-1' },
      expect.any(AbortSignal),
    )
    expect(wrapper.text()).toContain('activate')
    expect(wrapper.text()).toContain('approved')
    expect(wrapper.text()).toContain('update')
    expect(wrapper.text()).toContain('dispatch')
    expect(wrapper.text()).toContain('task-1')
    expect(managementApi.getRuntimeMonitoringAgentInvocation).not.toHaveBeenCalled()
  })

  it('opens Run Protocol, Model, and persisted State in the same detail area', async () => {
    vi.mocked(managementApi.listRuntimeMonitoringProtocolEvents)
      .mockResolvedValueOnce({
        ...emptyProtocol,
        items: [{
          sequence: 1,
          method: 'messages',
          captured_at: '2026-09-03T00:00:04Z',
          envelope: { params: { data: ['first persisted event'] } },
          origin: {
            source_type: 'non_agent',
            workflow_node_id: '',
            node_invocation_id: '',
            agent_profile_id: '',
            subagent_profile_id: '',
          },
        }],
        next_after_sequence: 1,
        limit: 1,
        remaining: 1,
      })
      .mockResolvedValue({
        ...emptyProtocol,
        items: [{
          sequence: 2,
          method: 'messages',
          captured_at: '2026-09-03T00:00:05Z',
          envelope: { params: { data: ['second persisted event'] } },
          origin: {
            source_type: 'non_agent',
            workflow_node_id: '',
            node_invocation_id: '',
            agent_profile_id: '',
            subagent_profile_id: '',
          },
        }],
        after_sequence: 1,
        next_after_sequence: 2,
        limit: 1,
        remaining: 0,
      })
    vi.mocked(managementApi.getRuntimeMonitoringState).mockResolvedValue({
      availability: 'available',
      read_at: '2026-09-03T00:00:10Z',
      state: {
        checkpoint_id: 'checkpoint-1',
        checkpoint_ns: 'root',
        created_at: '2026-09-03T00:00:09Z',
        source: 'loop',
        step: 3,
        pending_write_count: 0,
        state: { answer: 42 },
      },
    })
    const { router, wrapper } = await mountPage()

    const eventsButton = wrapper.findAll('button').find((button) => button.text() === 'Events')
    await eventsButton!.trigger('click')
    await flushPromises()
    expect(managementApi.listRuntimeMonitoringProtocolEvents).toHaveBeenNthCalledWith(
      1,
      'lifecycle-1',
      'run-root',
      { after_sequence: 0 },
      expect.any(AbortSignal),
    )
    expect(managementApi.listRuntimeMonitoringProtocolEvents).toHaveBeenNthCalledWith(
      2,
      'lifecycle-1',
      'run-root',
      { after_sequence: 1 },
      expect.any(AbortSignal),
    )
    expect(wrapper.text()).toContain('first persisted event')
    expect(wrapper.text()).toContain('second persisted event')

    const stateButton = wrapper.findAll('button').find((button) => button.text() === 'State')
    await stateButton!.trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.query.view).toBe('state')
    expect(managementApi.getRuntimeMonitoringState).toHaveBeenCalledWith(
      'lifecycle-1',
      'run-root',
      expect.any(AbortSignal),
    )
    expect(wrapper.text()).toContain('checkpoint-1')
    expect(wrapper.text()).toContain('root')
    expect(wrapper.text()).toContain('answer')
    expect(wrapper.text()).toContain('42')

    const modelsTab = wrapper.findAll('button').find((button) => button.text() === 'Models')
    await modelsTab!.trigger('click')
    await flushPromises()
    expect(managementApi.listRuntimeMonitoringModelRequests).toHaveBeenCalledWith(
      'lifecycle-1',
      'run-root',
      { page: 1, page_size: 20 },
      expect.any(AbortSignal),
    )
    expect(router.currentRoute.value.query.view).toBe('models')
  })

  it('performs a final persisted refresh when an active Lifecycle becomes terminal', async () => {
    vi.useFakeTimers()
    const terminalSnapshot: RuntimeMonitoringSnapshot = {
      ...snapshot,
      lifecycle: {
        ...snapshot.lifecycle,
        root_status: 'completed',
        fully_terminal_at: '2026-09-03T00:00:20Z',
      },
      summary: { ...snapshot.summary, active_run_count: 0 },
      runs: snapshot.runs.map((item) => ({
        ...item,
        status: 'completed',
        finished_at: '2026-09-03T00:00:20Z',
      })),
    }
    vi.mocked(managementApi.getRuntimeMonitoringSnapshot)
      .mockResolvedValueOnce(snapshot)
      .mockResolvedValueOnce(terminalSnapshot)
    const { wrapper } = await mountPage()
    expect(wrapper.text()).toContain('Live monitoring')

    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()

    expect(managementApi.getRuntimeMonitoringSnapshot).toHaveBeenCalledTimes(2)
    expect(managementApi.listRuntimeMonitoringNodes).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('Static result')

    await vi.advanceTimersByTimeAsync(4000)
    await flushPromises()
    expect(managementApi.getRuntimeMonitoringSnapshot).toHaveBeenCalledTimes(2)
  })

  it('keeps the last good view and retries after one polling failure', async () => {
    vi.useFakeTimers()
    vi.mocked(managementApi.getRuntimeMonitoringSnapshot)
      .mockResolvedValueOnce(snapshot)
      .mockRejectedValueOnce(new Error('poll endpoint failed'))
      .mockResolvedValue(snapshot)
    const { wrapper } = await mountPage()

    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()
    expect(wrapper.text()).toContain('Could not refresh runtime monitoring data')
    expect(wrapper.get('[data-testid="runtime-workflow-canvas"]').text()).toBe('root-agent')

    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()
    expect(managementApi.getRuntimeMonitoringSnapshot).toHaveBeenCalledTimes(3)
    expect(wrapper.text()).not.toContain('Could not refresh runtime monitoring data')
  })

  it('pauses polling while hidden and refreshes immediately when visible again', async () => {
    vi.useFakeTimers()
    let hidden = false
    vi.spyOn(globalThis.document, 'hidden', 'get').mockImplementation(() => hidden)
    await mountPage()

    hidden = true
    globalThis.document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(6000)
    expect(managementApi.getRuntimeMonitoringSnapshot).toHaveBeenCalledTimes(1)

    hidden = false
    globalThis.document.dispatchEvent(new Event('visibilitychange'))
    await flushPromises()
    expect(managementApi.getRuntimeMonitoringSnapshot).toHaveBeenCalledTimes(2)
  })

  it('does not replace a historical Agent invocation selection during polling', async () => {
    vi.useFakeTimers()
    const oldAttempt = nodeAttemptPage('run-root', 'root-agent', 'invocation-old').items[0]!
    const recentAttempt = {
      ...oldAttempt,
      sequence: 2,
      invocation_id: 'invocation-recent',
      started_at: '2026-09-03T00:00:02Z',
    }
    const latestAttempt = {
      ...oldAttempt,
      sequence: 3,
      invocation_id: 'invocation-latest',
      started_at: '2026-09-03T00:00:03Z',
    }
    vi.mocked(managementApi.listRuntimeMonitoringNodeAttempts)
      .mockResolvedValueOnce({
        ...nodeAttemptPage('run-root', 'root-agent'),
        items: [oldAttempt, recentAttempt],
        total: 2,
      })
      .mockResolvedValue({
        ...nodeAttemptPage('run-root', 'root-agent'),
        items: [oldAttempt, recentAttempt, latestAttempt],
        total: 3,
      })
    const { wrapper } = await mountPage()

    await wrapper.get('[data-testid="select-node-root-agent"]').trigger('click')
    await flushPromises()
    const oldButton = wrapper.findAll('button.runtime-node-attempt-button').find((button) => (
      button.text().includes('invocation-old')
    ))!
    await oldButton.trigger('click')
    await flushPromises()
    expect(oldButton.attributes('data-selected')).toBe('true')

    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()
    const buttons = wrapper.findAll('button.runtime-node-attempt-button')
    expect(buttons.find((button) => button.text().includes('invocation-old'))
      ?.attributes('data-selected')).toBe('true')
    expect(buttons.find((button) => button.text().includes('invocation-latest'))
      ?.attributes('data-selected')).toBe('false')
  })
})
