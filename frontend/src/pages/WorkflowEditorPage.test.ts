import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, onMounted } from 'vue'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  managementApi,
  type MainAgent,
  type Workflow,
  type WorkflowGraphDocument,
  type WorkflowNodeCatalogItem,
} from '@/api'
import { en } from '@/locales/en'

import WorkflowEditorPage from './WorkflowEditorPage.vue'

const workflow: Workflow = {
  id: 'workflow-1',
  name: 'Research Workflow',
  workflow_role: 'parent',
  description: 'Runs the research agent.',
  checkpointer_id: null,
  workflow_event_output_id: null,
  recursion_limit: 1_000_000,
  execution_timeout_seconds: 1_200,
  max_concurrency: 100,
  enabled: true,
}

const childWorkflow: Workflow = {
  ...workflow,
  id: 'workflow-child-1',
  name: 'Research Child',
  workflow_role: 'child',
}

const agent: MainAgent = {
  id: 'agent-config-1',
  name: 'Research Agent',
} as MainAgent

const graph: WorkflowGraphDocument = {
  definition: {
    schema_version: 1,
    state_contract: 'agent-shell.workflow.agent-invocations.v1',
    nodes: [
      { id: 'start', type: 'start', type_version: 1, config: {} },
      {
        id: 'agent-1',
        type: 'agent',
        type_version: 1,
        config: { main_agent_id: agent.id },
      },
      { id: 'end', type: 'end', type_version: 1, config: {} },
    ],
    edges: [
      {
        id: 'edge-start-agent',
        source: 'start',
        source_handle: 'next',
        target: 'agent-1',
        target_handle: 'in',
      },
      {
        id: 'edge-agent-end',
        source: 'agent-1',
        source_handle: 'next',
        target: 'end',
        target_handle: 'in',
      },
    ],
  },
  layout: {
    nodes: {
      start: { x: 40, y: 180 },
      'agent-1': { x: 320, y: 180 },
      end: { x: 620, y: 180 },
    },
    viewport: { x: 10, y: 20, zoom: 1.25 },
  },
}

const graphWithBranchProblem: WorkflowGraphDocument = {
  definition: {
    schema_version: 1,
    state_contract: 'agent-shell.workflow.agent-invocations.v1',
    nodes: [
      { id: 'start', type: 'start', type_version: 1, config: {} },
      {
        id: 'router-1',
        type: 'command',
        type_version: 1,
        config: { command_id: 'router-config-1' },
      },
      { id: 'end', type: 'end', type_version: 1, config: {} },
    ],
    edges: [{
      id: 'edge-branch',
      source: 'router-1',
      source_handle: 'branch',
      target: 'end',
      target_handle: 'in',
    }],
  },
  layout: {
    nodes: {
      start: { x: 40, y: 180 },
      'router-1': { x: 320, y: 180 },
      end: { x: 620, y: 180 },
    },
    viewport: { x: 10, y: 20, zoom: 1.25 },
  },
}

const nodeCatalog: WorkflowNodeCatalogItem[] = [
  {
    type: 'start',
    type_version: 1,
    runtime_kind: 'graph_entry',
    title_key: '',
    description_key: '',
    config_schema: {},
    workflow_roles: ['parent', 'child'],
    input_handles: [],
    output_handles: [{ id: 'next', kind: 'control', edge_type: 'normal', max_connections: null }],
  },
  {
    type: 'agent',
    type_version: 1,
    runtime_kind: 'agent_wrapper',
    title_key: '',
    description_key: '',
    config_schema: {},
    workflow_roles: ['parent', 'child'],
    input_handles: [{ id: 'in', kind: 'control', edge_type: 'normal', max_connections: null }],
    output_handles: [{ id: 'next', kind: 'control', edge_type: 'normal', max_connections: null }],
  },
  {
    type: 'command',
    type_version: 1,
    runtime_kind: 'command_node',
    title_key: '',
    description_key: '',
    config_schema: {},
    workflow_roles: ['parent', 'child'],
    input_handles: [{ id: 'in', kind: 'control', edge_type: 'normal', max_connections: null }],
    output_handles: [{ id: 'branch', kind: 'control', edge_type: 'branch', max_connections: null }],
  },
  {
    type: 'task-dispatcher',
    type_version: 1,
    runtime_kind: 'send_dispatcher',
    title_key: '',
    description_key: '',
    config_schema: {},
    workflow_roles: ['parent', 'child'],
    input_handles: [{ id: 'in', kind: 'control', edge_type: 'normal', max_connections: null }],
    output_handles: [{ id: 'dispatch', kind: 'control', edge_type: 'dispatch', max_connections: null }],
  },
  {
    type: 'end',
    type_version: 1,
    runtime_kind: 'graph_exit',
    title_key: '',
    description_key: '',
    config_schema: {},
    workflow_roles: ['parent', 'child'],
    input_handles: [{
      id: 'in',
      kind: 'control',
      edge_type: 'normal',
      accepted_edge_types: ['normal', 'branch'],
      max_connections: null,
    }],
    output_handles: [],
  },
]

const flow = {
  findNode: vi.fn((nodeId: string) => (
    nodeId === 'agent-1'
      ? {
          id: nodeId,
          computedPosition: { x: 320, y: 180, z: 0 },
          dimensions: { width: 160, height: 80 },
        }
      : undefined
  )),
  getViewport: vi.fn(() => ({ x: 10, y: 20, zoom: 1.25 })),
  screenToFlowCoordinate: vi.fn(),
  setCenter: vi.fn().mockResolvedValue(undefined),
  setViewport: vi.fn().mockResolvedValue(undefined),
}

const VueFlowStub = defineComponent({
  name: 'VueFlow',
  emits: ['connect', 'edgeClick', 'init', 'nodeClick', 'paneClick', 'update:edges', 'update:nodes'],
  setup(_, { emit }) {
    onMounted(() => emit('init', flow))
    return () => h('div', { class: 'vue-flow-stub' }, [
      h('button', {
        'data-testid': 'pane',
        type: 'button',
        onClick: () => emit('paneClick'),
      }),
    ])
  },
})

function i18n() {
  return createI18n({ legacy: false, locale: 'en', messages: { en } })
}

async function mountEditor() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/workflows', component: { template: '<div />' } },
      { path: '/workflows/:id/editor', component: WorkflowEditorPage },
    ],
  })
  await router.push('/workflows/workflow-1/editor')
  await router.isReady()
  const wrapper = mount(WorkflowEditorPage, {
    global: {
      plugins: [i18n(), router],
      stubs: { VueFlow: VueFlowStub },
    },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(managementApi, 'getWorkflow').mockResolvedValue(workflow)
  vi.spyOn(managementApi, 'getWorkflowGraph').mockResolvedValue(graph)
  vi.spyOn(managementApi, 'listMainAgents').mockResolvedValue([agent])
  vi.spyOn(managementApi, 'listBlocks').mockResolvedValue([])
  vi.spyOn(managementApi, 'listWorkflows').mockResolvedValue([childWorkflow])
  vi.spyOn(managementApi, 'listWorkflowNodeCatalog').mockResolvedValue(nodeCatalog)
  vi.spyOn(managementApi, 'validateWorkflow').mockResolvedValue({
    valid: true,
    stage: 'workflow_publish',
    issues: [],
  })
  vi.spyOn(managementApi, 'saveWorkflowDraft').mockResolvedValue(graph)
  vi.spyOn(managementApi, 'publishWorkflow').mockResolvedValue(graph)
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    callback(0)
    return 1
  })
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('WorkflowEditorPage', () => {
  it('keeps both icon rails visible while panels switch or close', async () => {
    const wrapper = await mountEditor()
    const leftDock = wrapper.get('.workflow-tool-dock--left')
    const rightDock = wrapper.get('.workflow-tool-dock--right')

    expect(leftDock.find('.workflow-tool-rail').exists()).toBe(true)
    expect(rightDock.find('.workflow-tool-rail').exists()).toBe(true)
    expect(leftDock.findAll('.workflow-tool-button')).toHaveLength(3)
    expect(leftDock.find('.workflow-tool-badge').exists()).toBe(false)
    expect(leftDock.find('.workflow-node-library-list').exists()).toBe(true)
    expect(rightDock.find('.workflow-inspector-row').exists()).toBe(true)
    expect(document.documentElement.classList.contains('workflow-editor-active')).toBe(true)

    await leftDock.findAll('.workflow-tool-button')[1]!.trigger('click')
    expect(leftDock.find('.workflow-node-tracker-list').exists()).toBe(true)
    expect(leftDock.find('.workflow-tool-rail').exists()).toBe(true)

    await rightDock.get('.workflow-tool-button').trigger('click')
    expect(rightDock.find('.workflow-tool-panel').exists()).toBe(false)
    expect(rightDock.find('.workflow-tool-rail').exists()).toBe(true)
    wrapper.unmount()
    expect(document.documentElement.classList.contains('workflow-editor-active')).toBe(false)
  })

  it('centers a tracked node and pane click closes a cleared Inspector', async () => {
    const wrapper = await mountEditor()
    const leftDock = wrapper.get('.workflow-tool-dock--left')
    const rightDock = wrapper.get('.workflow-tool-dock--right')
    await leftDock.findAll('.workflow-tool-button')[1]!.trigger('click')

    const agentItem = leftDock.findAll('.workflow-node-tracker-item')
      .find((item) => item.text().includes('agent-1'))
    if (!agentItem) throw new Error('Agent tracker item not found')
    await agentItem.trigger('click')
    await flushPromises()

    expect(flow.findNode).toHaveBeenCalledWith('agent-1')
    expect(flow.setCenter).toHaveBeenCalledWith(400, 220, {
      duration: 220,
      interpolate: 'smooth',
      zoom: 1.25,
    })
    expect(agentItem.attributes('data-active')).toBe('true')
    expect(rightDock.text()).toContain('Research Agent')

    await wrapper.get('[data-testid="pane"]').trigger('click')
    expect(rightDock.find('.workflow-tool-panel').exists()).toBe(false)
    expect(agentItem.attributes('data-active')).toBe('false')

    await rightDock.get('.workflow-tool-button').trigger('click')
    expect(rightDock.text()).toContain(workflow.name)
    expect(rightDock.text()).toContain(graph.definition.state_contract)
    wrapper.unmount()
  })

  it('uses the blocking problem to select its Edge and open the Inspector', async () => {
    vi.mocked(managementApi.getWorkflowGraph).mockResolvedValueOnce(graphWithBranchProblem)
    const wrapper = await mountEditor()

    expect(wrapper.get('.workflow-editor-toolbar button:last-child').attributes('disabled'))
      .toBeDefined()
    const leftDock = wrapper.get('.workflow-tool-dock--left')
    expect(leftDock.get('.workflow-tool-badge').text()).toBe('1')
    expect(wrapper.find('.workflow-editor-canvas .workflow-problems-list').exists()).toBe(false)

    await leftDock.findAll('.workflow-tool-button')[2]!.trigger('click')
    expect(leftDock.findAll('.workflow-problems-item')).toHaveLength(1)

    await leftDock.get('.workflow-problems-item').trigger('click')

    const rightDock = wrapper.get('.workflow-tool-dock--right')
    expect(rightDock.text()).toContain('Branch Edge')
    expect(rightDock.find('#workflow-edge-branch-key').exists()).toBe(true)
    expect(leftDock.get('.workflow-problems-item').text()).toContain('Enter a branch key.')
    wrapper.unmount()
  })

  it('shows every publish issue while draft saving remains available', async () => {
    vi.useFakeTimers()
    vi.mocked(managementApi.validateWorkflow).mockResolvedValueOnce({
      valid: false,
      stage: 'workflow_publish',
      issues: [
        {
          code: 'workflow.node_unreachable_from_start',
          scope: 'workflow',
          owner_id: 'agent-1',
          owner_name: 'agent-1',
          owner_type: 'agent',
          path: 'definition.nodes[1]',
          message: 'The Workflow node is not reachable from Start.',
          message_key: 'validation.issue.workflow.nodeUnreachableFromStart',
          message_args: {},
          severity: 'error',
        },
        {
          code: 'assembly.model_not_found',
          scope: 'workflow',
          owner_id: 'agent-1',
          owner_name: 'agent-1',
          owner_type: 'agent',
          path: 'definition.nodes[1].config.main_agent_id',
          message: 'The selected model does not exist.',
          message_key: 'validation.issue.assembly.modelNotFound',
          message_args: {},
          severity: 'error',
        },
      ],
    })
    const wrapper = await mountEditor()
    await vi.advanceTimersByTimeAsync(350)
    await flushPromises()

    const toolbar = wrapper.get('.workflow-editor-toolbar')
    const saveDraft = toolbar.get('button[aria-label="Save draft"]')
    const publish = toolbar.get('button[aria-label="Publish Workflow"]')
    expect(saveDraft.attributes('disabled')).toBeUndefined()
    expect(publish.attributes('disabled')).toBeDefined()
    expect(wrapper.get('.workflow-tool-badge').text()).toBe('2')

    await wrapper.get('.workflow-tool-dock--left .workflow-tool-button:nth-child(3)').trigger('click')
    expect(wrapper.findAll('.workflow-problems-item')).toHaveLength(2)

    await saveDraft.trigger('click')
    await flushPromises()
    expect(managementApi.saveWorkflowDraft).toHaveBeenCalledOnce()
    expect(toolbar.text()).toContain('Draft')
    wrapper.unmount()
  })

  it('publishes only after the current graph passes validation', async () => {
    vi.useFakeTimers()
    const wrapper = await mountEditor()
    await vi.advanceTimersByTimeAsync(350)
    await flushPromises()

    const publish = wrapper.get('.workflow-editor-toolbar button[aria-label="Publish Workflow"]')
    expect(publish.attributes('disabled')).toBeUndefined()
    await publish.trigger('click')
    await flushPromises()

    expect(managementApi.publishWorkflow).toHaveBeenCalledOnce()
    expect(wrapper.get('.workflow-editor-toolbar').text()).toContain('Published')
    wrapper.unmount()
  })

  it('keeps publish disabled when validation fails and retries explicitly', async () => {
    vi.useFakeTimers()
    vi.mocked(managementApi.validateWorkflow).mockRejectedValueOnce(
      new Error('validation service offline'),
    )
    const wrapper = await mountEditor()
    await vi.advanceTimersByTimeAsync(350)
    await flushPromises()

    const publish = wrapper.get('.workflow-editor-toolbar button[aria-label="Publish Workflow"]')
    expect(publish.attributes('disabled')).toBeDefined()
    expect(wrapper.get('.workflow-validation-error').text()).toContain('Formal validation failed.')

    await wrapper.get('.workflow-validation-error button').trigger('click')
    await vi.advanceTimersByTimeAsync(0)
    await flushPromises()

    expect(managementApi.validateWorkflow).toHaveBeenCalledTimes(2)
    expect(wrapper.find('.workflow-validation-error').exists()).toBe(false)
    expect(publish.attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })
})
