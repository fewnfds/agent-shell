import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { createI18n } from 'vue-i18n'
import { describe, expect, it, vi } from 'vitest'

import { en } from '@/locales/en'

import WorkflowRuntimeView from './WorkflowRuntimeView.vue'

const VueFlowStub = defineComponent({
  name: 'VueFlow',
  props: [
    'nodes',
    'edges',
    'nodesDraggable',
    'nodesConnectable',
    'edgesUpdatable',
    'elementsSelectable',
    'deleteKeyCode',
  ],
  emits: ['init'],
  template: '<div data-testid="workflow-flow" />',
})

describe('WorkflowRuntimeView', () => {
  it('projects the frozen document without changing positions, handles, edges, or viewport', async () => {
    const wrapper = mount(WorkflowRuntimeView, {
      props: {
        graph: {
          definition: {
            schema_version: 1,
            state_contract: 'agent-shell.workflow.control.v1',
            nodes: [
              { id: 'start', type: 'start', type_version: 1, config: {} },
              { id: 'research', type: 'command', type_version: 1, config: { command_id: 'command-1' } },
              { id: 'end', type: 'end', type_version: 1, config: {} },
            ],
            edges: [
              {
                id: 'frozen-start-research',
                source: 'start',
                source_handle: 'next',
                target: 'research',
                target_handle: 'in',
              },
              {
                id: 'frozen-research-end',
                source: 'research',
                source_handle: 'next',
                target: 'end',
                target_handle: 'in',
              },
            ],
          },
          layout: {
            nodes: {
              start: { x: 17, y: 29 },
              research: { x: 411, y: 233 },
              end: { x: 907, y: 61 },
            },
            viewport: { x: 31, y: -47, zoom: 0.72 },
          },
        },
        nodeCatalog: [
          {
            type: 'start',
            type_version: 1,
            runtime_kind: 'graph_entry',
            title_key: 'workflow.nodes.start.title',
            description_key: 'workflow.nodes.start.description',
            config_schema: {},
            input_handles: [],
            output_handles: [{ id: 'next', kind: 'control', edge_type: 'normal', max_connections: null }],
          },
          {
            type: 'command',
            type_version: 1,
            runtime_kind: 'command_node',
            title_key: 'workflow.nodes.command.title',
            description_key: 'workflow.nodes.command.description',
            config_schema: {},
            input_handles: [{ id: 'in', kind: 'control', edge_type: 'normal', max_connections: null }],
            output_handles: [{ id: 'next', kind: 'control', edge_type: 'normal', max_connections: null }],
          },
          {
            type: 'end',
            type_version: 1,
            runtime_kind: 'graph_exit',
            title_key: 'workflow.nodes.end.title',
            description_key: 'workflow.nodes.end.description',
            config_schema: {},
            input_handles: [{ id: 'in', kind: 'control', edge_type: 'normal', max_connections: null }],
            output_handles: [],
          },
        ],
        commands: [{ id: 'command-1', name: 'Frozen Research Command' }],
        state: { values: { answer: 42 }, next: ['research'] },
        loading: false,
      },
      global: {
        plugins: [createI18n({ legacy: false, locale: 'en', messages: { en } })],
        stubs: { VueFlow: VueFlowStub },
      },
    })

    const flow = wrapper.getComponent(VueFlowStub)
    const nodes = flow.props('nodes') as Array<{
      id: string
      data: { active: boolean }
      position: { x: number, y: number }
      selectable: boolean
    }>
    const edges = flow.props('edges') as Array<{
      id: string
      sourceHandle: string
      targetHandle: string
      animated: boolean
    }>
    expect(nodes.filter((node) => node.data.active).map((node) => node.id))
      .toEqual(['research'])
    expect(nodes.map((node) => [node.id, node.position])).toEqual([
      ['start', { x: 17, y: 29 }],
      ['research', { x: 411, y: 233 }],
      ['end', { x: 907, y: 61 }],
    ])
    expect(edges.map((edge) => [edge.id, edge.sourceHandle, edge.targetHandle])).toEqual([
      ['frozen-start-research', 'next', 'in'],
      ['frozen-research-end', 'next', 'in'],
    ])
    expect(nodes.every((node) => node.selectable === false)).toBe(true)
    expect(edges.every((edge) => edge.animated === false)).toBe(true)
    expect(flow.props('nodesDraggable')).toBe(false)
    expect(flow.props('nodesConnectable')).toBe(false)
    expect(flow.props('edgesUpdatable')).toBe(false)
    expect(flow.props('elementsSelectable')).toBe(false)
    expect(flow.props('deleteKeyCode')).toBeNull()

    const setViewport = vi.fn().mockResolvedValue(undefined)
    flow.vm.$emit('init', { setViewport })
    await flushPromises()
    expect(setViewport).toHaveBeenCalledWith({ x: 31, y: -47, zoom: 0.72 })
  })
})
