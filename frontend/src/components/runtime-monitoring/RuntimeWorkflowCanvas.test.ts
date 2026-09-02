import { mount } from '@vue/test-utils'
import { defineComponent, h, type PropType, type Slots } from 'vue'
import { createI18n } from 'vue-i18n'
import { describe, expect, it, vi } from 'vitest'

import type {
  RuntimeMonitoringNodeSummary,
  WorkflowGraphDocument,
  WorkflowNodeCatalogItem,
} from '@/api'
import { en } from '@/locales/en'

import RuntimeWorkflowCanvas from './RuntimeWorkflowCanvas.vue'

const setViewport = vi.fn().mockResolvedValue(undefined)
const VueFlowStub = defineComponent({
  name: 'VueFlow',
  inheritAttrs: false,
  props: {
    nodes: { type: Array as PropType<Array<{ id: string; type: string; data: object }>>, required: true },
    edges: { type: Array as PropType<Array<Record<string, unknown>>>, required: true },
  },
  emits: ['init'],
  setup(props, { emit, slots }) {
    emit('init', { setViewport })
    return () => h('div', { class: 'vue-flow-stub' }, props.nodes.map((node) => (
      (slots as Slots)[`node-${node.type}`]?.({ id: node.id, data: node.data })
    )))
  },
})

const document: WorkflowGraphDocument = {
  definition: {
    schema_version: 1,
    state_contract: 'agent-shell.workflow.agent-invocations.v1',
    nodes: [
      { id: 'agent-1', type: 'agent', type_version: 1, config: { main_agent_id: 'agent-config-1' } },
      { id: 'end', type: 'end', type_version: 1, config: {} },
    ],
    edges: [{
      id: 'edge-1',
      source: 'agent-1',
      source_handle: 'next',
      target: 'end',
      target_handle: 'in',
    }],
  },
  layout: {
    nodes: { 'agent-1': { x: 20, y: 30 }, end: { x: 300, y: 30 } },
    viewport: { x: 10, y: 15, zoom: 1.2 },
  },
}

const nodeCatalog = [
  {
    type: 'agent',
    type_version: 1,
    runtime_kind: 'agent_wrapper',
    title_key: '',
    description_key: '',
    config_schema: {},
    input_handles: [],
    output_handles: [{ id: 'next', kind: 'control', edge_type: 'normal', max_connections: null }],
    workflow_roles: ['parent'],
  },
  {
    type: 'end',
    type_version: 1,
    runtime_kind: 'graph_exit',
    title_key: '',
    description_key: '',
    config_schema: {},
    input_handles: [{ id: 'in', kind: 'control', edge_type: 'normal', max_connections: null }],
    output_handles: [],
    workflow_roles: ['parent'],
  },
] satisfies WorkflowNodeCatalogItem[]

describe('RuntimeWorkflowCanvas', () => {
  it('marks running Nodes with both visual state and readable attempt counts', () => {
    const summaries: RuntimeMonitoringNodeSummary[] = [{
      workflow_node_id: 'agent-1',
      first_sequence: 1,
      latest_sequence: 2,
      first_started_at: '2026-09-03T00:00:00Z',
      latest_started_at: '2026-09-03T00:00:01Z',
      attempt_count: 2,
      status_counts: { running: 1, completed: 1 },
    }]
    const wrapper = mount(RuntimeWorkflowCanvas, {
      props: { document, nodeCatalog, nodeSummaries: summaries },
      global: {
        plugins: [createI18n({ legacy: false, locale: 'en', messages: { en } })],
        stubs: { VueFlow: VueFlowStub, WorkflowNodeEndpoints: true },
      },
    })

    const runningNode = wrapper.get('[data-running="true"]')
    expect(runningNode.text()).toContain('Attempts: 2')
    expect(runningNode.text()).toContain('running: 1')
    expect(runningNode.text()).toContain('completed: 1')
    expect(wrapper.get('[data-running="false"]').text()).toContain('No recorded attempts')
    expect(wrapper.getComponent(VueFlowStub).props('edges')[0]).toMatchObject({ animated: false })
  })
})
