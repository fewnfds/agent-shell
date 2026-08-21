import { describe, expect, it } from 'vitest'

import {
  workflowCanvasEdgeVisual,
  workflowCanvasToDocument,
  workflowDocumentToCanvas,
  type WorkflowCanvasEdge,
  type WorkflowCanvasNode,
} from './workflowGraph'
import type { WorkflowGraphDocument, WorkflowNodeCatalogItem } from '@/api'

describe('workflow edge visual projection', () => {
  it('uses End red before Start green while preserving protocol styling', () => {
    const startBranch = workflowCanvasEdgeVisual('branch', 'start', 'agent')
    expect(startBranch.class).toBe('workflow-edge--branch workflow-edge--start')
    expect(startBranch.markerEnd).toMatchObject({ color: 'var(--bs-success)' })
    expect(startBranch.animated).toBe(true)

    const startEnd = workflowCanvasEdgeVisual('normal', 'start', 'end')
    expect(startEnd.class).toBe('workflow-edge--start workflow-edge--end')
    expect(startEnd.markerEnd).toMatchObject({ color: 'var(--bs-danger)' })

    const dispatchEnd = workflowCanvasEdgeVisual('dispatch', 'task-dispatcher', 'end')
    expect(dispatchEnd.class).toBe('workflow-edge--dispatch workflow-edge--end')
    expect(dispatchEnd.markerEnd).toMatchObject({ color: 'var(--bs-danger)' })
    expect(dispatchEnd.animated).toBe(true)
  })

  it('reprojects terminal precedence when loading a saved graph', () => {
    const document = {
      definition: {
        schema_version: 1,
        state_contract: 'agent-shell.workflow.agent-invocations.v1',
        nodes: [
          { id: 'start', type: 'start', type_version: 1, config: {} },
          { id: 'end', type: 'end', type_version: 1, config: {} },
        ],
        edges: [{
          id: 'edge-1',
          source: 'start',
          source_handle: 'next',
          target: 'end',
          target_handle: 'in',
        }],
      },
      layout: { nodes: {}, viewport: { x: 0, y: 0, zoom: 1 } },
    } as WorkflowGraphDocument
    const catalog = [
      {
        type: 'start',
        output_handles: [{ id: 'next', kind: 'control', edge_type: 'normal', accepted_edge_types: ['normal'], max_connections: null }],
        input_handles: [],
      },
      {
        type: 'end',
        output_handles: [],
        input_handles: [{ id: 'in', kind: 'control', edge_type: 'normal', accepted_edge_types: ['normal'], max_connections: null }],
      },
    ] as WorkflowNodeCatalogItem[]

    const [edge] = workflowDocumentToCanvas(document, catalog).edges
    expect(edge.class).toBe('workflow-edge--start workflow-edge--end')
    expect(edge.markerEnd).toMatchObject({ color: 'var(--bs-danger)' })
  })

  it('does not serialize renderer classes, animation, or markers', () => {
    const nodes = [
      { id: 'start', data: { nodeType: 'start', mainAgentId: '' }, position: { x: 0, y: 0 } },
      { id: 'end', data: { nodeType: 'end', mainAgentId: '' }, position: { x: 100, y: 0 } },
    ] as WorkflowCanvasNode[]
    const edges = [{
      id: 'edge-1',
      source: 'start',
      sourceHandle: 'next',
      target: 'end',
      targetHandle: 'in',
      class: 'workflow-edge--start workflow-edge--end',
      animated: true,
      markerEnd: { type: 'arrowclosed', color: 'var(--bs-danger)' },
      data: { edgeType: 'normal' },
    }] as WorkflowCanvasEdge[]

    const wire = workflowCanvasToDocument(nodes, edges, { x: 0, y: 0, zoom: 1 })
    expect(wire.definition.edges).toEqual([{
      id: 'edge-1',
      source: 'start',
      source_handle: 'next',
      target: 'end',
      target_handle: 'in',
    }])
  })
})
