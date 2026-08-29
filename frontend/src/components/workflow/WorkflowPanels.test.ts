import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it, vi } from 'vitest'

import type { MainAgent, WorkflowGraphDocument, WorkflowNodeCatalogItem } from '@/api'
import {
  newAgentCanvasNode,
  newCommandCanvasNode,
  nextWorkflowCanvasEdgeId,
  WORKFLOW_NODE_DRAG_MIME,
  workflowCanvasEdgeTypesBetween,
  workflowCanvasToDocument,
  workflowCanvasNodeEndpoints,
  workflowConnectionEdgeType,
  workflowDocumentToCanvas,
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

const agentCatalog: WorkflowNodeCatalogItem = {
  type: 'agent',
  type_version: 1,
  runtime_kind: 'agent_wrapper',
  title_key: 'workflow.nodes.agent.title',
  description_key: 'workflow.nodes.agent.description',
  config_schema: {},
  workflow_roles: ['parent', 'child'],
  input_handles: [{ id: 'in', kind: 'control', edge_type: 'normal', max_connections: null }],
  output_handles: [{ id: 'next', kind: 'control', edge_type: 'normal', max_connections: null }],
}

const startCatalog: WorkflowNodeCatalogItem = {
  type: 'start',
  type_version: 1,
  runtime_kind: 'graph_entry',
  title_key: 'workflow.nodes.start.title',
  description_key: 'workflow.nodes.start.description',
  config_schema: {},
  workflow_roles: ['parent', 'child'],
  input_handles: [],
  output_handles: [{ id: 'next', kind: 'control', edge_type: 'normal', max_connections: null }],
}

const endCatalog: WorkflowNodeCatalogItem = {
  type: 'end',
  type_version: 1,
  runtime_kind: 'graph_exit',
  title_key: 'workflow.nodes.end.title',
  description_key: 'workflow.nodes.end.description',
  config_schema: {},
  workflow_roles: ['parent', 'child'],
  input_handles: [{ id: 'in', kind: 'control', edge_type: 'normal', max_connections: null }],
  output_handles: [],
}

const commandCatalog: WorkflowNodeCatalogItem = {
  type: 'command',
  type_version: 1,
  runtime_kind: 'command_node',
  title_key: 'workflow.nodes.command.title',
  description_key: 'workflow.nodes.command.description',
  config_schema: {},
  workflow_roles: ['parent', 'child'],
  input_handles: [{ id: 'in', kind: 'control', edge_type: 'normal', accepted_edge_types: ['normal', 'branch'], max_connections: null }],
  output_handles: [
    { id: 'branch', kind: 'control', edge_type: 'branch', accepted_edge_types: ['branch'], max_connections: null },
    { id: 'dispatch', kind: 'control', edge_type: 'dispatch', accepted_edge_types: ['dispatch'], max_connections: null },
  ],
}

const agents: MainAgent[] = [
  { id: 'agent-1', name: 'Research Agent', capability_refs: [], subagents: [] },
  { id: 'agent-2', name: 'Review Agent', capability_refs: [], subagents: [] },
]

describe('Workflow canvas panels', () => {
  it('exposes the backend Agent node as the only drag source', async () => {
    const wrapper = mount(WorkflowNodeLibrary, {
      props: {
        agent: agentCatalog,
        command: null,
        agentDisabled: false,
        commandDisabled: true,
      },
      global: { plugins: [i18n()] },
    })
    const item = wrapper.get('.workflow-node-library-item')
    const setData = vi.fn()
    const dataTransfer = { effectAllowed: '', setData }

    await item.trigger('dragstart', { dataTransfer })
    await item.trigger('click')

    expect(setData).toHaveBeenCalledWith(WORKFLOW_NODE_DRAG_MIME, 'agent')
    expect(dataTransfer.effectAllowed).toBe('copy')
    expect(wrapper.emitted('addAgent')).toHaveLength(1)
  })

  it('edits the selected Agent reference in the property panel', async () => {
    const node = newAgentCanvasNode('agent-1', agents[0]!.id)
    const wrapper = mount(WorkflowInspector, {
      props: {
        edge: null,
        edgeSourceEndpoints: [],
        edgeTargetEndpoints: [],
        edgeTypeOptions: [],
        inputEndpoints: agentCatalog.input_handles,
        mainAgents: agents,
        commands: [],
        node,
        nodeIds: [node.id],
        outputEndpoints: agentCatalog.output_handles,
        stateContract: 'agent-shell.workflow.agent-invocations.v1',
        workflowName: 'Research Workflow',
      },
      global: { plugins: [i18n()] },
    })

    await wrapper.get('select').setValue(agents[1]!.id)
    await wrapper.get('#workflow-node-id').setValue('research_agent')
    await wrapper.get('#workflow-node-id').trigger('blur')

    expect(wrapper.emitted('updateAgent')).toEqual([[node.id, agents[1]!.id]])
    expect(wrapper.emitted('updateNodeId')).toEqual([[node.id, 'research_agent']])
    expect(wrapper.text()).toContain('Main Agent')
    expect(wrapper.text()).toContain('Input endpoint')
    expect(wrapper.text()).toContain('Normal Edge · in')
  })

  it('keeps a missing node target UUID visible in the property panel', () => {
    const missingId = '00000000-0000-4000-8000-000000000074'
    const node = newAgentCanvasNode('agent-missing', missingId)
    const wrapper = mount(WorkflowInspector, {
      props: {
        edge: null,
        edgeSourceEndpoints: [],
        edgeTargetEndpoints: [],
        edgeTypeOptions: [],
        inputEndpoints: agentCatalog.input_handles,
        mainAgents: agents,
        commands: [],
        node,
        nodeIds: [node.id],
        outputEndpoints: agentCatalog.output_handles,
        stateContract: 'agent-shell.workflow.agent-invocations.v1',
        workflowName: 'Research Workflow',
      },
      global: { plugins: [i18n()] },
    })

    const selected = wrapper.get('#workflow-node-main-agent')
    expect((selected.element as HTMLSelectElement).value).toBe(missingId)
    expect(selected.text()).toContain(missingId)
  })

  it('selects the semantic Edge class and its declared endpoint identities', async () => {
    const edge: WorkflowCanvasEdge = {
      id: 'edge-agent-end',
      source: 'agent-1',
      sourceHandle: 'next',
      target: 'end',
      targetHandle: 'in',
      data: { edgeType: 'normal' },
    }
    const wrapper = mount(WorkflowInspector, {
      props: {
        edge,
        edgeSourceEndpoints: agentCatalog.output_handles,
        edgeTargetEndpoints: endCatalog.input_handles,
        edgeTypeOptions: ['normal'],
        inputEndpoints: [],
        mainAgents: agents,
        commands: [],
        node: null,
        nodeIds: ['agent-1', 'end'],
        outputEndpoints: [],
        stateContract: 'agent-shell.workflow.agent-invocations.v1',
        workflowName: 'Research Workflow',
      },
      global: { plugins: [i18n()] },
    })

    await wrapper.get('select[name="edge-type"]').setValue('normal')
    await wrapper.get('select[name="source-endpoint"]').setValue('next')
    await wrapper.get('select[name="target-endpoint"]').setValue('in')

    expect(wrapper.emitted('selectEdgeType')).toEqual([[edge.id, 'normal']])
    expect(wrapper.emitted('selectEdgeSourceEndpoint')).toEqual([[edge.id, 'next']])
    expect(wrapper.emitted('selectEdgeTargetEndpoint')).toEqual([[edge.id, 'in']])
  })

  it('allows repeated Agent nodes and multiple normal activation directions', () => {
    const start: WorkflowCanvasNode = {
      id: 'start',
      type: 'start',
      position: { x: 0, y: 0 },
      data: { nodeType: 'start', mainAgentId: '' },
    }
    const first = newAgentCanvasNode('agent-1', agents[0]!.id)
    const second = newAgentCanvasNode('agent-2', agents[0]!.id)
    const end: WorkflowCanvasNode = {
      id: 'end',
      type: 'end',
      position: { x: 720, y: 0 },
      data: { nodeType: 'end', mainAgentId: '' },
    }
    const existing: WorkflowCanvasEdge = {
      id: 'edge-agent-1-end',
      source: first.id,
      sourceHandle: 'next',
      target: end.id,
      targetHandle: 'in',
      data: { edgeType: 'normal' },
    }
    const catalog = [startCatalog, agentCatalog, endCatalog]
    const nodes = [start, first, second, end]

    expect(workflowCanvasNodeEndpoints(catalog, 'agent', 'output')).toEqual(
      agentCatalog.output_handles,
    )
    expect(workflowCanvasEdgeTypesBetween(first, end, catalog)).toEqual(['normal'])
    expect(nextWorkflowCanvasEdgeId([
      existing,
      { ...existing, id: 'edge-1' },
    ])).toBe('edge-2')

    expect(workflowConnectionEdgeType({
      source: first.id,
      sourceHandle: 'next',
      target: second.id,
      targetHandle: 'in',
    }, nodes, [existing], catalog)).toBe('normal')
    expect(workflowConnectionEdgeType({
      source: second.id,
      sourceHandle: 'next',
      target: end.id,
      targetHandle: 'in',
    }, nodes, [existing], catalog)).toBe('normal')
    expect(workflowConnectionEdgeType({
      source: first.id,
      sourceHandle: 'next',
      target: end.id,
      targetHandle: 'in',
    }, nodes, [existing], catalog)).toBeNull()
    expect(workflowConnectionEdgeType(existing, nodes, [existing], catalog)).toBe('normal')
  })

  it('uses the Command routing endpoints and stores the explicit key on a Branch Edge', async () => {
    const router = newCommandCanvasNode('router-1', 'router-config-1')
    const end: WorkflowCanvasNode = {
      id: 'end',
      type: 'end',
      position: { x: 720, y: 0 },
      data: { nodeType: 'end', mainAgentId: '' },
    }
    const branchEdge: WorkflowCanvasEdge = {
      id: 'edge-review',
      source: router.id,
      sourceHandle: 'branch',
      target: end.id,
      targetHandle: 'in',
      animated: true,
      data: { edgeType: 'branch', branchKey: 'review' },
    }
    const endWithBranchInput = {
      ...endCatalog,
      input_handles: [{ ...endCatalog.input_handles[0]!, accepted_edge_types: ['normal', 'branch'] }],
    }
    expect(commandCatalog.output_handles).toHaveLength(2)
    expect(workflowConnectionEdgeType({
      source: router.id,
      sourceHandle: 'branch',
      target: end.id,
      targetHandle: 'in',
    }, [router, end], [], [commandCatalog, endWithBranchInput])).toBe('branch')

    const wrapper = mount(WorkflowInspector, {
      props: {
        edge: branchEdge,
        edgeSourceEndpoints: commandCatalog.output_handles,
        edgeTargetEndpoints: endWithBranchInput.input_handles,
        edgeTypeOptions: ['branch'],
        inputEndpoints: [],
        mainAgents: agents,
        commands: [],
        node: null,
        nodeIds: [router.id, end.id],
        outputEndpoints: [],
        stateContract: 'agent-shell.workflow.agent-invocations.v1',
        workflowName: 'Routing Workflow',
      },
      global: { plugins: [i18n()] },
    })
    await wrapper.get('input[type="text"]').setValue('audit')
    expect(wrapper.emitted('updateBranchKey')).toEqual([[branchEdge.id, 'audit']])
  })

  it('lists every canvas node and emits the selected node identity', async () => {
    const start: WorkflowCanvasNode = {
      id: 'start',
      type: 'start',
      position: { x: 0, y: 0 },
      data: { nodeType: 'start', mainAgentId: '' },
    }
    const agent = { ...newAgentCanvasNode('agent-1', agents[0]!.id), selected: true }
    const router = newCommandCanvasNode('router-1', 'router-config-1')
    const wrapper = mount(WorkflowNodeTracker, {
      props: { nodes: [start, agent, router] },
      global: { plugins: [i18n()] },
    })

    const items = wrapper.findAll('.workflow-node-tracker-item')
    expect(items).toHaveLength(3)
    expect(items[1]!.attributes('data-active')).toBe('true')
    expect(items[2]!.text()).toContain('Command Node')
    await items[0]!.trigger('click')
    expect(wrapper.emitted('locateNode')).toEqual([[start.id]])
  })

  it('round-trips a State-driven Dispatch Edge and requires its dispatch key', async () => {
    const command = newCommandCanvasNode('command-1', 'command-config-1')
    const worker = newAgentCanvasNode('worker-1', agents[0]!.id)
    const workerCatalog = {
      ...agentCatalog,
      input_handles: [{
        ...agentCatalog.input_handles[0]!,
        accepted_edge_types: ['normal', 'branch', 'dispatch'],
      }],
    }
    const edge: WorkflowCanvasEdge = {
      id: 'edge-city',
      source: command.id,
      sourceHandle: 'dispatch',
      target: worker.id,
      targetHandle: 'in',
      data: { edgeType: 'dispatch', dispatchKey: 'city' },
    }

    expect(workflowConnectionEdgeType({
      source: command.id,
      sourceHandle: 'dispatch',
      target: worker.id,
      targetHandle: 'in',
    }, [command, worker], [], [commandCatalog, workerCatalog])).toBe('dispatch')

    const document = workflowCanvasToDocument(
      [command, worker],
      [edge],
      { x: 0, y: 0, zoom: 1 },
    )
    expect(document.definition.nodes[0]!.config.command_id)
      .toBe('command-config-1')
    expect(document.definition.edges[0]!.dispatch_key).toBe('city')
    expect(workflowCanvasProblems([command, worker], [{
      ...edge,
      data: { edgeType: 'dispatch' },
    }])[0]?.message_key).toBe('workflows.editor.canvasProblems.dispatchKeyRequired')

    const wrapper = mount(WorkflowInspector, {
      props: {
        edge,
        edgeSourceEndpoints: commandCatalog.output_handles,
        edgeTargetEndpoints: workerCatalog.input_handles,
        edgeTypeOptions: ['dispatch'],
        inputEndpoints: [],
        mainAgents: agents,
        commands: [],
        node: null,
        nodeIds: [command.id, worker.id],
        outputEndpoints: [],
        stateContract: 'agent-shell.workflow.agent-invocations.v1',
        workflowName: 'Rainfall Workflow',
      },
      global: { plugins: [i18n()] },
    })
    await wrapper.get('#workflow-edge-dispatch-key').setValue('town')
    expect(wrapper.emitted('updateDispatchKey')).toEqual([[edge.id, 'town']])
  })

  it('projects save blockers into the canvas problems panel', async () => {
    const agent = newAgentCanvasNode('agent-1', '')
    const branch: WorkflowCanvasEdge = {
      id: 'edge-review',
      source: 'router-1',
      sourceHandle: 'branch',
      target: agent.id,
      targetHandle: 'in',
      data: { edgeType: 'branch' },
    }
    const problems = workflowCanvasProblems([agent], [branch])
    expect(problems.map((problem) => problem.owner_id)).toEqual([agent.id, branch.id])

    const wrapper = mount(WorkflowProblemsPanel, {
      props: { problems },
      global: { plugins: [i18n()] },
    })
    expect(wrapper.findAll('.workflow-problems-item')).toHaveLength(2)
    await wrapper.findAll('.workflow-problems-item')[1]!.trigger('click')
    expect(wrapper.emitted('selectProblem')).toEqual([[problems[1]]])
  })

  it('uses Bezier presentation without exposing the Branch key as an Edge label', () => {
    const document: WorkflowGraphDocument = {
      definition: {
        schema_version: 1,
        state_contract: 'agent-shell.workflow.agent-invocations.v1',
        nodes: [
          {
            id: 'router-1',
            type: 'command',
            type_version: 1,
            config: { command_id: 'router-config-1' },
          },
          { id: 'end', type: 'end', type_version: 1, config: {} },
        ],
        edges: [{
          id: 'edge-review',
          source: 'router-1',
          source_handle: 'branch',
          target: 'end',
          target_handle: 'in',
          branch_key: 'review',
        }],
      },
      layout: {
        nodes: { 'router-1': { x: 0, y: 0 }, end: { x: 400, y: 0 } },
        viewport: { x: 0, y: 0, zoom: 1 },
      },
    }
    const endWithBranchInput = {
      ...endCatalog,
      input_handles: [{ ...endCatalog.input_handles[0]!, accepted_edge_types: ['normal', 'branch'] }],
    }

    const canvas = workflowDocumentToCanvas(
      document,
      [commandCatalog, endWithBranchInput],
    )
    expect(canvas.edges[0]).toMatchObject({
      type: 'default',
      data: { edgeType: 'branch', branchKey: 'review' },
    })
    expect(canvas.edges[0]!.label).toBeUndefined()
    expect(workflowCanvasToDocument(canvas.nodes, canvas.edges, canvas.viewport)
      .definition.edges[0]!.branch_key).toBe('review')
  })
})
