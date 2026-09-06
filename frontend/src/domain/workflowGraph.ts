import {
  MarkerType,
  type Connection,
  type Edge,
  type EdgeMarkerType,
  type Node,
  type ViewportTransform,
  type XYPosition,
} from '@vue-flow/core'

import type {
  WorkflowGraphDocument,
  WorkflowGraphNode,
  WorkflowNodeHandleSpec,
  WorkflowNodeCatalogItem,
  WorkflowNodeType,
} from '@/api'

export interface WorkflowCanvasNodeData {
  nodeType: WorkflowNodeType
  commandId?: string
}

export type WorkflowCanvasNode = Node<WorkflowCanvasNodeData>

export interface WorkflowCanvasEdgeData {
  edgeType: 'normal'
}

export type WorkflowCanvasEdge = Edge<WorkflowCanvasEdgeData>

export const WORKFLOW_NODE_DRAG_MIME = 'application/x-agent-shell-workflow-node'
export const WORKFLOW_CANVAS_EDGE_TYPES = ['normal'] as const
export type WorkflowCanvasEdgeType = (typeof WORKFLOW_CANVAS_EDGE_TYPES)[number]
export type WorkflowEndpointDirection = 'input' | 'output'

export interface WorkflowCanvasState {
  nodes: WorkflowCanvasNode[]
  edges: WorkflowCanvasEdge[]
  viewport: ViewportTransform
}

const defaultPositions = {
  start: { x: 80, y: 180 },
  command: { x: 450, y: 180 },
  end: { x: 820, y: 180 },
} satisfies Record<WorkflowNodeType, XYPosition>

function canvasNode(
  node: WorkflowGraphNode,
  document: WorkflowGraphDocument,
): WorkflowCanvasNode {
  return {
    id: node.id,
    type: node.type,
    position: document.layout.nodes[node.id] ?? defaultPositions[node.type],
    deletable: !['start', 'end'].includes(node.type),
    data: {
      nodeType: node.type,
      commandId: node.config.command_id ?? '',
    },
  }
}

export function workflowCanvasNodeEndpoints(
  catalog: WorkflowNodeCatalogItem[],
  nodeType: WorkflowNodeType,
  direction: WorkflowEndpointDirection,
): WorkflowNodeHandleSpec[] {
  const spec = catalog.find((item) => item.type === nodeType)
  if (!spec) return []
  return direction === 'output' ? spec.output_handles : spec.input_handles
}

function catalogHandle(
  catalog: WorkflowNodeCatalogItem[],
  nodeType: WorkflowNodeType,
  handleId: string | null | undefined,
  direction: WorkflowEndpointDirection,
): WorkflowNodeHandleSpec | null {
  if (!handleId) return null
  return workflowCanvasNodeEndpoints(catalog, nodeType, direction)
    .find((endpoint) => endpoint.id === handleId) ?? null
}

function documentEdgeIsValid(
  edge: WorkflowGraphDocument['definition']['edges'][number],
  document: WorkflowGraphDocument,
  catalog: WorkflowNodeCatalogItem[],
): boolean {
  const source = document.definition.nodes.find((node) => node.id === edge.source)
  const target = document.definition.nodes.find((node) => node.id === edge.target)
  if (!source || !target) return false
  const sourceHandle = catalogHandle(catalog, source.type, edge.source_handle, 'output')
  const targetHandle = catalogHandle(catalog, target.type, edge.target_handle, 'input')
  if (!sourceHandle || !targetHandle) return false
  return (targetHandle.accepted_edge_types ?? [targetHandle.edge_type])
    .includes(sourceHandle.edge_type)
}

export function workflowDocumentToCanvas(
  document: WorkflowGraphDocument,
  catalog: WorkflowNodeCatalogItem[],
  options: { addDefaultTerminals?: boolean } = {},
): WorkflowCanvasState {
  const sourceNodes = document.definition.nodes.length > 0 || options.addDefaultTerminals === false
    ? document.definition.nodes
    : [
        { id: 'start', type: 'start', type_version: 1, config: {} },
        { id: 'end', type: 'end', type_version: 1, config: {} },
      ] satisfies WorkflowGraphNode[]
  const nodeTypesById = new Map(sourceNodes.map((node) => [node.id, node.type]))

  return {
    nodes: sourceNodes.map((node) => canvasNode(node, document)),
    edges: document.definition.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      sourceHandle: edge.source_handle,
      target: edge.target,
      targetHandle: edge.target_handle,
      type: 'default',
      ...workflowCanvasEdgeVisual(
        documentEdgeIsValid(edge, document, catalog) ? 'normal' : '',
        nodeTypesById.get(edge.source),
        nodeTypesById.get(edge.target),
      ),
      data: { edgeType: 'normal' },
    })),
    viewport: { ...document.layout.viewport },
  }
}

export function workflowCanvasToDocument(
  nodes: WorkflowCanvasNode[],
  edges: WorkflowCanvasEdge[],
  viewport: ViewportTransform,
): WorkflowGraphDocument {
  return {
    definition: {
      schema_version: 1,
      state_contract: 'agent-shell.workflow.control.v1',
      nodes: nodes.map((node) => ({
        id: node.id,
        type: node.data.nodeType,
        type_version: 1,
        config: node.data.nodeType === 'command'
          ? { command_id: node.data.commandId }
          : {},
      })),
      edges: edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        source_handle: edge.sourceHandle ?? '',
        target: edge.target,
        target_handle: edge.targetHandle ?? '',
      })),
    },
    layout: {
      nodes: Object.fromEntries(
        nodes.map((node) => [node.id, { x: node.position.x, y: node.position.y }]),
      ),
      viewport: { ...viewport },
    },
  }
}

export function newCommandCanvasNode(
  id: string,
  commandId: string,
  position: XYPosition = defaultPositions.command,
): WorkflowCanvasNode {
  return {
    id,
    type: 'command',
    position: { ...position },
    deletable: true,
    data: { nodeType: 'command', commandId },
  }
}

export function workflowCanvasEdgeVisual(
  _edgeType: string,
  sourceNodeType?: WorkflowNodeType,
  targetNodeType?: WorkflowNodeType,
): { markerEnd: EdgeMarkerType; animated: boolean; class?: string } {
  const classes: string[] = []
  if (sourceNodeType === 'start') classes.push('workflow-edge--start')
  if (targetNodeType === 'end') classes.push('workflow-edge--end')
  const color = targetNodeType === 'end'
    ? 'var(--bs-danger)'
    : sourceNodeType === 'start'
      ? 'var(--bs-success)'
      : 'var(--bs-primary)'
  return {
    markerEnd: { type: MarkerType.ArrowClosed, color },
    animated: false,
    class: classes.length > 0 ? classes.join(' ') : undefined,
  }
}

export function nextWorkflowCanvasEdgeId(edges: WorkflowCanvasEdge[]): string {
  let index = 1
  while (edges.some((edge) => edge.id === `edge-${index}`)) index += 1
  return `edge-${index}`
}

export function workflowConnectionEdgeType(
  connection: Connection & { id?: string },
  nodes: WorkflowCanvasNode[],
  edges: WorkflowCanvasEdge[],
  catalog: WorkflowNodeCatalogItem[],
): WorkflowCanvasEdgeType | null {
  const source = nodes.find((node) => node.id === connection.source)
  const target = nodes.find((node) => node.id === connection.target)
  if (!source || !target || source.id === target.id) return null
  const sourceHandle = catalogHandle(
    catalog,
    source.data.nodeType,
    connection.sourceHandle,
    'output',
  )
  const targetHandle = catalogHandle(
    catalog,
    target.data.nodeType,
    connection.targetHandle,
    'input',
  )
  if (
    !sourceHandle
    || !targetHandle
    || sourceHandle.edge_type !== 'normal'
    || !(targetHandle.accepted_edge_types ?? [targetHandle.edge_type]).includes('normal')
  ) return null
  if (edges.some((edge) => (
    edge.id !== connection.id
    && edge.source === connection.source
    && edge.target === connection.target
  ))) return null
  return 'normal'
}

export function workflowCanvasEdgeTypesBetween(
  source: WorkflowCanvasNode | null,
  target: WorkflowCanvasNode | null,
  catalog: WorkflowNodeCatalogItem[],
): WorkflowCanvasEdgeType[] {
  if (!source || !target) return []
  const sourceSupportsNormal = workflowCanvasNodeEndpoints(
    catalog,
    source.data.nodeType,
    'output',
  ).some((endpoint) => endpoint.edge_type === 'normal')
  const targetSupportsNormal = workflowCanvasNodeEndpoints(
    catalog,
    target.data.nodeType,
    'input',
  ).some((endpoint) => (
    endpoint.accepted_edge_types ?? [endpoint.edge_type]
  ).includes('normal'))
  return sourceSupportsNormal && targetSupportsNormal ? ['normal'] : []
}
