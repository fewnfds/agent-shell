import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it, vi } from 'vitest'

import type { ConfigurationSummary, WorkflowNodeCatalogItem } from '@/api'
import {
  newCommandCanvasNode,
  WORKFLOW_NODE_DRAG_MIME,
  workflowCanvasEdgeTypesBetween,
  workflowCanvasToDocument,
  workflowConnectionEdgeType,
  type WorkflowCanvasEdge,
  type WorkflowCanvasNode,
} from '@/domain/workflowGraph'
import { workflowCanvasProblems } from '@/domain/workflowCanvasProblems'
import { en } from '@/locales/en'
import WorkflowInspector from './WorkflowInspector.vue'
import WorkflowNodeLibrary from './WorkflowNodeLibrary.vue'
import WorkflowNodeTracker from './WorkflowNodeTracker.vue'
import WorkflowProblemsPanel from './WorkflowProblemsPanel.vue'

function i18n() {
  return createI18n({ legacy: false, locale: 'en', messages: { en } })
}

const normalOutput = { id: 'next', kind: 'control' as const, edge_type: 'normal', accepted_edge_types: ['normal'], max_connections: null }
const normalInput = { id: 'in', kind: 'control' as const, edge_type: 'normal', accepted_edge_types: ['normal'], max_connections: null }
const commandCatalog: WorkflowNodeCatalogItem = {
  type: 'command',
  type_version: 1,
  runtime_kind: 'command_node',
  title_key: '',
  description_key: '',
  config_schema: {},
  input_handles: [normalInput],
  output_handles: [normalOutput],
}
const endCatalog: WorkflowNodeCatalogItem = {
  type: 'end',
  type_version: 1,
  runtime_kind: 'graph_exit',
  title_key: '',
  description_key: '',
  config_schema: {},
  input_handles: [normalInput],
  output_handles: [],
}
const commands: ConfigurationSummary[] = [
  { id: 'command-1', name: 'Route request' },
  { id: 'command-2', name: 'Finish request' },
]

describe('Workflow control panels', () => {
  it('offers Command as the only draggable executable node', async () => {
    const wrapper = mount(WorkflowNodeLibrary, {
      props: { command: commandCatalog, commandDisabled: false },
      global: { plugins: [i18n()] },
    })
    const setData = vi.fn()
    const dataTransfer = { effectAllowed: '', setData }
    await wrapper.get('.workflow-node-library-item').trigger('dragstart', { dataTransfer })
    await wrapper.get('.workflow-node-library-item').trigger('click')
    expect(setData).toHaveBeenCalledWith(WORKFLOW_NODE_DRAG_MIME, 'command')
    expect(wrapper.emitted('addCommand')).toHaveLength(1)
  })

  it('edits a Command reference and stable Node ID', async () => {
    const node = newCommandCanvasNode('router', commands[0]!.id)
    const wrapper = mount(WorkflowInspector, {
      props: {
        edge: null,
        edgeSourceEndpoints: [],
        edgeTargetEndpoints: [],
        edgeTypeOptions: [],
        inputEndpoints: commandCatalog.input_handles,
        commands,
        node,
        nodeIds: [node.id],
        outputEndpoints: commandCatalog.output_handles,
        stateContract: 'agent-shell.workflow.control.v1',
        workflowName: 'Control Workflow',
      },
      global: { plugins: [i18n()] },
    })
    await wrapper.get('#workflow-node-command').setValue(commands[1]!.id)
    await wrapper.get('#workflow-node-id').setValue('review')
    await wrapper.get('#workflow-node-id').trigger('blur')
    expect(wrapper.emitted('updateCommand')).toEqual([[node.id, commands[1]!.id]])
    expect(wrapper.emitted('updateNodeId')).toEqual([[node.id, 'review']])
  })

  it('connects and serializes one normal Edge kind', () => {
    const command = newCommandCanvasNode('router', commands[0]!.id)
    const end = { id: 'end', type: 'end', position: { x: 400, y: 0 }, data: { nodeType: 'end' } } as WorkflowCanvasNode
    const nodes = [command, end]
    const catalog = [commandCatalog, endCatalog]
    const connection = { source: command.id, sourceHandle: 'next', target: end.id, targetHandle: 'in' }
    expect(workflowCanvasEdgeTypesBetween(command, end, catalog)).toEqual(['normal'])
    expect(workflowConnectionEdgeType(connection, nodes, [], catalog)).toBe('normal')
    const edge = { id: 'edge-1', ...connection, data: { edgeType: 'normal' } } as WorkflowCanvasEdge
    const document = workflowCanvasToDocument(nodes, [edge], { x: 0, y: 0, zoom: 1 })
    expect(document.definition.state_contract).toBe('agent-shell.workflow.control.v1')
    expect(document.definition.edges[0]).toEqual({
      id: 'edge-1', source: 'router', source_handle: 'next', target: 'end', target_handle: 'in',
    })
  })

  it('reports only missing Command configuration as a local blocker', async () => {
    const command = newCommandCanvasNode('router', '')
    const problems = workflowCanvasProblems([command], [])
    expect(problems).toHaveLength(1)
    expect(problems[0]!.path).toBe('definition.nodes[0].config.command_id')
    const wrapper = mount(WorkflowProblemsPanel, {
      props: { problems },
      global: { plugins: [i18n()] },
    })
    await wrapper.get('.workflow-problems-item').trigger('click')
    expect(wrapper.emitted('selectProblem')).toEqual([[problems[0]]])
  })

  it('tracks Start, Command, and End nodes', async () => {
    const nodes = [
      { id: 'start', type: 'start', position: { x: 0, y: 0 }, data: { nodeType: 'start' } },
      newCommandCanvasNode('router', commands[0]!.id),
      { id: 'end', type: 'end', position: { x: 400, y: 0 }, data: { nodeType: 'end' } },
    ] as WorkflowCanvasNode[]
    const wrapper = mount(WorkflowNodeTracker, {
      props: { nodes },
      global: { plugins: [i18n()] },
    })
    expect(wrapper.findAll('.workflow-node-tracker-item')).toHaveLength(3)
    await wrapper.findAll('.workflow-node-tracker-item')[1]!.trigger('click')
    expect(wrapper.emitted('locateNode')).toEqual([['router']])
  })
})
