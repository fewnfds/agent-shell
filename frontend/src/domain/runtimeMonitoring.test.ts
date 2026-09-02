import { describe, expect, it } from 'vitest'

import type { RuntimeMonitoringSnapshot, WorkflowGraphDocument, WorkflowNodeCatalogItem } from '@/api'

import {
  resolveRuntimeMonitoringScope,
  runtimeMonitoringRunForest,
  runtimeWorkflowCanvasState,
  selectRuntimeMonitoringRunId,
} from './runtimeMonitoring'

const snapshot = {
  lifecycle: { root_run_id: 'run-root' },
  runs: [
    { run_id: 'run-child', workflow_id: 'workflow-child', workflow_name: 'Child' },
    { run_id: 'run-root', workflow_id: 'workflow-root', workflow_name: 'Parent' },
  ],
  forest: {
    root_run_ids: ['run-root'],
    relationships: [{ parent_run_id: 'run-root', child_run_id: 'run-child' }],
    orphan_run_ids: [],
  },
} as RuntimeMonitoringSnapshot

describe('runtime monitoring projection', () => {
  it('uses only the server forest and defaults invalid selections to the Lifecycle root Run', () => {
    const roots = runtimeMonitoringRunForest(snapshot)

    expect(roots.map((item) => item.run.run_id)).toEqual(['run-root'])
    expect(roots[0]?.children.map((item) => item.run.run_id)).toEqual(['run-child'])
    expect(selectRuntimeMonitoringRunId(snapshot, 'run-child')).toBe('run-child')
    expect(selectRuntimeMonitoringRunId(snapshot, 'missing-run')).toBe('run-root')
  })

  it('accepts only Workflow and Run scope identities present in the Lifecycle snapshot', () => {
    expect(resolveRuntimeMonitoringScope(snapshot, 'workflow', 'workflow-child', ''))
      .toEqual({ scope: 'workflow', id: 'workflow-child' })
    expect(resolveRuntimeMonitoringScope(snapshot, 'run', '', 'run-child'))
      .toEqual({ scope: 'run', id: 'run-child' })
    expect(resolveRuntimeMonitoringScope(snapshot, 'workflow', 'missing', ''))
      .toEqual({ scope: 'lifecycle', id: null })
    expect(resolveRuntimeMonitoringScope(snapshot, 'unknown', '', 'run-child'))
      .toEqual({ scope: 'lifecycle', id: null })
  })

  it('turns the frozen document into a non-editable canvas without animated edges', () => {
    const document = {
      definition: {
        schema_version: 1,
        state_contract: 'agent-shell.workflow.agent-invocations.v1',
        nodes: [
          { id: 'command-1', type: 'command', type_version: 1, config: { command_id: 'cmd-1' } },
          { id: 'end', type: 'end', type_version: 1, config: {} },
        ],
        edges: [{
          id: 'branch-1',
          source: 'command-1',
          source_handle: 'branch',
          target: 'end',
          target_handle: 'in',
        }],
      },
      layout: {
        nodes: {},
        viewport: { x: 0, y: 0, zoom: 1 },
      },
    } satisfies WorkflowGraphDocument
    const catalog = [
      {
        type: 'command',
        type_version: 1,
        runtime_kind: 'command_node',
        title_key: '',
        description_key: '',
        config_schema: {},
        input_handles: [],
        output_handles: [{
          id: 'branch',
          kind: 'control',
          edge_type: 'branch',
          max_connections: null,
        }],
        workflow_roles: ['parent'],
      },
      {
        type: 'end',
        type_version: 1,
        runtime_kind: 'graph_exit',
        title_key: '',
        description_key: '',
        config_schema: {},
        input_handles: [{
          id: 'in',
          kind: 'control',
          edge_type: 'normal',
          accepted_edge_types: ['branch'],
          max_connections: null,
        }],
        output_handles: [],
        workflow_roles: ['parent'],
      },
    ] satisfies WorkflowNodeCatalogItem[]

    const canvas = runtimeWorkflowCanvasState(document, catalog)

    expect(canvas.nodes.every((node) => node.draggable === false && node.deletable === false))
      .toBe(true)
    expect(canvas.edges[0]).toMatchObject({
      animated: false,
      selectable: false,
      deletable: false,
      updatable: false,
    })

    expect(runtimeWorkflowCanvasState({
      ...document,
      definition: { ...document.definition, nodes: [], edges: [] },
    }, catalog).nodes).toEqual([])
  })
})
