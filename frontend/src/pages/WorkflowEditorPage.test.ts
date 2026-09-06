import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, onMounted } from 'vue'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { managementApi, type Workflow, type WorkflowGraphDocument, type WorkflowNodeCatalogItem } from '@/api'
import { en } from '@/locales/en'
import WorkflowEditorPage from './WorkflowEditorPage.vue'

const workflow: Workflow = {
  id: 'workflow-1',
  name: 'Control Workflow',
  description: 'Runs deterministic control steps.',
  is_model_entry: true,
  workflow_event_output_id: null,
  durability: 'async',
  on_disconnect: 'cancel',
  enabled: true,
}
const command = { id: '11111111-1111-4111-8111-111111111111', name: 'Route' }
const graph: WorkflowGraphDocument = {
  definition: {
    schema_version: 1,
    state_contract: 'agent-shell.workflow.control.v1',
    nodes: [
      { id: 'start', type: 'start', type_version: 1, config: {} },
      { id: 'router', type: 'command', type_version: 1, config: { command_id: command.id } },
      { id: 'end', type: 'end', type_version: 1, config: {} },
    ],
    edges: [
      { id: 'start-router', source: 'start', source_handle: 'next', target: 'router', target_handle: 'in' },
      { id: 'router-end', source: 'router', source_handle: 'next', target: 'end', target_handle: 'in' },
    ],
  },
  layout: { nodes: {}, viewport: { x: 10, y: 20, zoom: 1.25 } },
}
const handleIn = { id: 'in', kind: 'control' as const, edge_type: 'normal', accepted_edge_types: ['normal'], max_connections: null }
const handleOut = { id: 'next', kind: 'control' as const, edge_type: 'normal', accepted_edge_types: ['normal'], max_connections: null }
const catalog: WorkflowNodeCatalogItem[] = [
  { type: 'start', type_version: 1, runtime_kind: 'graph_entry', title_key: '', description_key: '', config_schema: {}, input_handles: [], output_handles: [handleOut] },
  { type: 'command', type_version: 1, runtime_kind: 'command_node', title_key: '', description_key: '', config_schema: {}, input_handles: [handleIn], output_handles: [handleOut] },
  { type: 'end', type_version: 1, runtime_kind: 'graph_exit', title_key: '', description_key: '', config_schema: {}, input_handles: [handleIn], output_handles: [] },
]
const flow = {
  findNode: vi.fn(() => ({ computedPosition: { x: 320, y: 180 }, dimensions: { width: 160, height: 80 } })),
  getViewport: vi.fn(() => ({ x: 10, y: 20, zoom: 1.25 })),
  screenToFlowCoordinate: vi.fn(() => ({ x: 200, y: 200 })),
  setCenter: vi.fn().mockResolvedValue(undefined),
  setViewport: vi.fn().mockResolvedValue(undefined),
}
const VueFlowStub = defineComponent({
  name: 'VueFlow',
  emits: ['connect', 'edgeClick', 'init', 'nodeClick', 'paneClick', 'update:edges', 'update:nodes'],
  setup(_, { emit }) {
    onMounted(() => emit('init', flow))
    return () => h('div', { class: 'vue-flow-stub' }, [
      h('button', { 'data-testid': 'pane', onClick: () => emit('paneClick') }),
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
  const wrapper = mount({ template: '<RouterView />' }, {
    global: { plugins: [i18n(), router], stubs: { VueFlow: VueFlowStub } },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(managementApi, 'getWorkflow').mockResolvedValue(workflow)
  vi.spyOn(managementApi, 'getWorkflowGraph').mockResolvedValue(graph)
  vi.spyOn(managementApi, 'getConfigurationOptions').mockResolvedValue({
    repository_id: '00000000-0000-4000-8000-000000000099',
    repository_revision: 1,
    components: { command: [command] },
    main_agents: [],
    subagents: [],
    async_subagents: [],
    workflows: [],
  })
  vi.spyOn(managementApi, 'listWorkflowNodeCatalog').mockResolvedValue(catalog)
  vi.spyOn(managementApi, 'validateWorkflow').mockResolvedValue({ valid: true, stage: 'workflow_publish', issues: [] })
  vi.spyOn(managementApi, 'saveWorkflowDraft').mockResolvedValue(graph)
  vi.spyOn(managementApi, 'publishWorkflow').mockResolvedValue(graph)
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { callback(0); return 1 })
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('WorkflowEditorPage', () => {
  it('loads a Start/Command/End control graph', async () => {
    const wrapper = await mountEditor()
    expect(wrapper.get('.workflow-editor-toolbar').text()).toContain(workflow.name)
    expect(wrapper.get('.workflow-node-library-list').text()).toContain('Command Node')
    expect(wrapper.text()).not.toContain('Compiled Agent')
    wrapper.unmount()
  })

  it('adds a Command and saves the current control document', async () => {
    const wrapper = await mountEditor()
    await wrapper.get('.workflow-node-library-item').trigger('click')
    await wrapper.get('.workflow-editor-toolbar button[aria-label="Save draft"]').trigger('click')
    await flushPromises()
    expect(managementApi.saveWorkflowDraft).toHaveBeenCalledWith(
      workflow.id,
      expect.objectContaining({
        definition: expect.objectContaining({ state_contract: 'agent-shell.workflow.control.v1' }),
      }),
    )
    wrapper.unmount()
  })

  it('keeps the tool rails and shows all control nodes in the tracker', async () => {
    const wrapper = await mountEditor()
    const left = wrapper.get('.workflow-tool-dock--left')
    const right = wrapper.get('.workflow-tool-dock--right')
    expect(left.findAll('.workflow-tool-button')).toHaveLength(3)
    expect(right.find('.workflow-tool-rail').exists()).toBe(true)
    await left.findAll('.workflow-tool-button')[1]!.trigger('click')
    expect(left.findAll('.workflow-node-tracker-item')).toHaveLength(3)
    expect(left.text()).toContain('router')
    wrapper.unmount()
  })

  it('publishes after current validation succeeds', async () => {
    vi.useFakeTimers()
    const wrapper = await mountEditor()
    await vi.advanceTimersByTimeAsync(350)
    await flushPromises()
    const publish = wrapper.get('.workflow-editor-toolbar button[aria-label="Publish Workflow"]')
    expect(publish.attributes('disabled')).toBeUndefined()
    await publish.trigger('click')
    await flushPromises()
    expect(managementApi.publishWorkflow).toHaveBeenCalledOnce()
    wrapper.unmount()
  })
})
