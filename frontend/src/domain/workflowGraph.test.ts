import { describe, expect, it } from 'vitest'

import type { WorkflowGraphDocument, WorkflowNodeCatalogItem } from '@/api'
import {
  workflowCanvasEdgeVisual,
  workflowCanvasToDocument,
  workflowDocumentToCanvas,
  type WorkflowCanvasEdge,
  type WorkflowCanvasNode,
} from './workflowGraph'

describe('Workflow control graph projection', () => {
  it('renders one normal Edge with terminal color precedence', () => {
    const startEnd = workflowCanvasEdgeVisual('normal', 'start', 'end')
    expect(startEnd.class).toBe('workflow-edge--start workflow-edge--end')
    expect(startEnd.markerEnd).toMatchObject({ color: 'var(--bs-danger)' })
    expect(startEnd.animated).toBe(false)
  })

  it('loads and saves only the control graph wire fields', () => {
    const document: WorkflowGraphDocument = {
      definition: {
        schema_version: 1,
        state_contract: 'agent-shell.workflow.control.v1',
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
    }
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

    const canvas = workflowDocumentToCanvas(document, catalog)
    expect(canvas.edges[0]).toMatchObject({ data: { edgeType: 'normal' } })
    const saved = workflowCanvasToDocument(canvas.nodes, canvas.edges, canvas.viewport)
    expect(saved.definition).toEqual(document.definition)
    expect(saved.layout.viewport).toEqual(document.layout.viewport)
    expect(Object.keys(saved.layout.nodes)).toEqual(['start', 'end'])
  })

  it('adds editor terminals only for an empty editable document', () => {
    const emptyDocument = {
      definition: {
        schema_version: 1,
        state_contract: 'agent-shell.workflow.control.v1',
        nodes: [],
        edges: [],
      },
      layout: { nodes: {}, viewport: { x: 0, y: 0, zoom: 1 } },
    } as WorkflowGraphDocument
    expect(workflowDocumentToCanvas(emptyDocument, []).nodes.map((node) => node.id))
      .toEqual(['start', 'end'])
    expect(workflowDocumentToCanvas(emptyDocument, [], { addDefaultTerminals: false }).nodes)
      .toEqual([])
  })

  it('does not serialize Vue Flow presentation fields', () => {
    const nodes = [
      { id: 'start', data: { nodeType: 'start' }, position: { x: 0, y: 0 } },
      { id: 'end', data: { nodeType: 'end' }, position: { x: 100, y: 0 } },
    ] as WorkflowCanvasNode[]
    const edges = [{
      id: 'edge-1',
      source: 'start',
      sourceHandle: 'next',
      target: 'end',
      targetHandle: 'in',
      class: 'workflow-edge--start workflow-edge--end',
      markerEnd: { type: 'arrowclosed', color: 'var(--bs-danger)' },
      data: { edgeType: 'normal' },
    }] as WorkflowCanvasEdge[]
    expect(workflowCanvasToDocument(nodes, edges, { x: 0, y: 0, zoom: 1 }).definition.edges)
      .toEqual([{ id: 'edge-1', source: 'start', source_handle: 'next', target: 'end', target_handle: 'in' }])
  })
})
