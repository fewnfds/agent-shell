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
  WorkflowGraphEdge,
  WorkflowGraphNode,
  WorkflowNodeHandleSpec,
  WorkflowNodeCatalogItem,
  WorkflowNodeType,
} from '@/api'

export interface WorkflowCanvasNodeData {
  nodeType: WorkflowNodeType
  mainAgentId: string
  commandId?: string
  taskDispatcherId?: string
  defer?: boolean
}

export type WorkflowCanvasNode = Node<WorkflowCanvasNodeData>

export interface WorkflowCanvasEdgeData {
  edgeType: string
  branchKey?: string
  dispatchKey?: string
}

export type WorkflowCanvasEdge = Edge<WorkflowCanvasEdgeData>

export const WORKFLOW_NODE_DRAG_MIME = 'application/x-agent-shell-workflow-node'
export const WORKFLOW_CANVAS_EDGE_TYPES = ['normal', 'branch', 'dispatch'] as const
export type WorkflowCanvasEdgeType = (typeof WORKFLOW_CANVAS_EDGE_TYPES)[number]
export type WorkflowEndpointDirection = 'input' | 'output'

export interface WorkflowCanvasState {
  nodes: WorkflowCanvasNode[]
  edges: WorkflowCanvasEdge[]
  viewport: ViewportTransform
}

const defaultPositions = {
  start: { x: 80, y: 180 },
  agent: { x: 360, y: 180 },
  'command': { x: 620, y: 180 },
  'task-dispatcher': { x: 620, y: 340 },
  end: { x: 900, y: 180 },
} satisfies Record<WorkflowNodeType, { x: number; y: number }>

function canvasNode(node: WorkflowGraphNode, document: WorkflowGraphDocument): WorkflowCanvasNode {
  return {
    id: node.id,
    type: node.type,
    position: document.layout.nodes[node.id] ?? defaultPositions[node.type],
    deletable: !['start', 'end'].includes(node.type),
    data: {
      nodeType: node.type,
      mainAgentId: node.config.main_agent_id ?? '',
      commandId: node.config.command_id ?? '',
      taskDispatcherId: node.config.task_dispatcher_id ?? '',
      defer: node.config.defer ?? false,
    },
  }
}

function isWorkflowCanvasEdgeType(value: string): value is WorkflowCanvasEdgeType {
  return WORKFLOW_CANVAS_EDGE_TYPES.some((edgeType) => edgeType === value)
}

export function workflowCanvasNodeEndpoints(
  catalog: WorkflowNodeCatalogItem[],
  nodeType: WorkflowNodeType,
  direction: WorkflowEndpointDirection,
): WorkflowNodeHandleSpec[] {
  const nodeTypeSpec = catalog.find((item) => item.type === nodeType)
  if (!nodeTypeSpec) return []
  const endpoints = direction === 'output'
    ? nodeTypeSpec.output_handles
    : nodeTypeSpec.input_handles
  return endpoints.filter((endpoint) => isWorkflowCanvasEdgeType(endpoint.edge_type))
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

function documentEdgeType(
  edge: WorkflowGraphEdge,
  document: WorkflowGraphDocument,
  catalog: WorkflowNodeCatalogItem[],
): string {
  const source = document.definition.nodes.find((node) => node.id === edge.source)
  const target = document.definition.nodes.find((node) => node.id === edge.target)
  if (!source || !target) return ''
  const sourceHandle = catalogHandle(catalog, source.type, edge.source_handle, 'output')
  const targetHandle = catalogHandle(catalog, target.type, edge.target_handle, 'input')
  if (!sourceHandle || !targetHandle) return ''
  const accepted = targetHandle.accepted_edge_types ?? [targetHandle.edge_type]
  return accepted.includes(sourceHandle.edge_type) ? sourceHandle.edge_type : ''
}

export function workflowDocumentToCanvas(
  document: WorkflowGraphDocument,
  catalog: WorkflowNodeCatalogItem[],
): WorkflowCanvasState {
  const sourceNodes = document.definition.nodes.length > 0
    ? document.definition.nodes
    : [
        { id: 'start', type: 'start', type_version: 1, config: {} },
        { id: 'end', type: 'end', type_version: 1, config: {} },
      ] satisfies WorkflowGraphNode[]
  const nodeTypesById = new Map(sourceNodes.map((node) => [node.id, node.type]))

  return {
    nodes: sourceNodes.map((node) => canvasNode(node, document)),
    edges: document.definition.edges.map((edge) => {
      const edgeType = documentEdgeType(edge, document, catalog)
      return {
        id: edge.id,
        source: edge.source,
        sourceHandle: edge.source_handle,
        target: edge.target,
        targetHandle: edge.target_handle,
        type: 'default',
        ...workflowCanvasEdgeVisual(
          edgeType,
          nodeTypesById.get(edge.source),
          nodeTypesById.get(edge.target),
        ),
        data: {
          edgeType,
          branchKey: edge.branch_key ?? undefined,
          dispatchKey: edge.dispatch_key ?? undefined,
        },
      }
    }),
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
      state_contract: 'agent-shell.workflow.agent-invocations.v1',
      nodes: nodes.map((node) => {
        const config = node.data.nodeType === 'agent'
          ? {
              main_agent_id: node.data.mainAgentId,
              ...(node.data.defer ? { defer: true } : {}),
            }
          : node.data.nodeType === 'command'
            ? { command_id: node.data.commandId }
          : node.data.nodeType === 'task-dispatcher'
            ? { task_dispatcher_id: node.data.taskDispatcherId }
          : {}
        return {
          id: node.id,
          type: node.data.nodeType,
          type_version: 1,
          config,
        }
      }),
      edges: edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        source_handle: edge.sourceHandle ?? '',
        target: edge.target,
        target_handle: edge.targetHandle ?? '',
        ...(edge.data.edgeType === 'branch' && edge.data.branchKey
          ? { branch_key: edge.data.branchKey }
          : {}),
        ...(edge.data.edgeType === 'dispatch' && edge.data.dispatchKey
          ? { dispatch_key: edge.data.dispatchKey }
          : {}),
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

export function newAgentCanvasNode(
  id: string,
  mainAgentId: string,
  position: XYPosition = defaultPositions.agent,
): WorkflowCanvasNode {
  return {
    id,
    type: 'agent',
    position: { ...position },
    deletable: true,
    data: {
      nodeType: 'agent',
      mainAgentId,
      commandId: '',
      taskDispatcherId: '',
      defer: false,
    },
  }
}

export function newCommandCanvasNode(
  id: string,
  commandId: string,
  position: XYPosition = defaultPositions['command'],
): WorkflowCanvasNode {
  return {
    id,
    type: 'command',
    position: { ...position },
    deletable: true,
    data: { nodeType: 'command', mainAgentId: '', commandId },
  }
}

export function newTaskDispatcherCanvasNode(
  id: string,
  taskDispatcherId: string,
  position: XYPosition = defaultPositions['task-dispatcher'],
): WorkflowCanvasNode {
  return {
    id,
    type: 'task-dispatcher',
    position: { ...position },
    deletable: true,
    data: { nodeType: 'task-dispatcher', mainAgentId: '', taskDispatcherId },
  }
}

export function workflowCanvasEdgeVisual(
  edgeType: string,
  sourceNodeType?: WorkflowNodeType,
  targetNodeType?: WorkflowNodeType,
): { markerEnd: EdgeMarkerType; animated: boolean; class?: string } {
  const classes: string[] = []
  if (edgeType === 'branch') classes.push('workflow-edge--branch')
  if (edgeType === 'dispatch') classes.push('workflow-edge--dispatch')
  if (sourceNodeType === 'start') classes.push('workflow-edge--start')
  if (targetNodeType === 'end') classes.push('workflow-edge--end')

  const color = targetNodeType === 'end'
    ? 'var(--bs-danger)'
    : sourceNodeType === 'start'
      ? 'var(--bs-success)'
      : edgeType === 'branch'
        ? 'var(--bs-warning)'
        : edgeType === 'dispatch'
          ? 'var(--bs-info)'
          : 'var(--bs-primary)'
  return {
    markerEnd: { type: MarkerType.ArrowClosed, color },
    animated: edgeType === 'branch' || edgeType === 'dispatch',
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
    || !isWorkflowCanvasEdgeType(sourceHandle.edge_type)
    || !(targetHandle.accepted_edge_types ?? [targetHandle.edge_type]).includes(sourceHandle.edge_type)
  ) return null

  const duplicate = edges.some((edge) => (
    edge.id !== connection.id
    && edge.source === connection.source
    && edge.sourceHandle === connection.sourceHandle
    && edge.target === connection.target
    && edge.targetHandle === connection.targetHandle
  ))
  if (duplicate && !['branch', 'dispatch'].includes(sourceHandle.edge_type)) return null
  return sourceHandle.edge_type
}

export function workflowCanvasEdgeTypesBetween(
  source: WorkflowCanvasNode | null,
  target: WorkflowCanvasNode | null,
  catalog: WorkflowNodeCatalogItem[],
): WorkflowCanvasEdgeType[] {
  if (!source || !target) return []
  const sourceTypes = new Set(
    workflowCanvasNodeEndpoints(catalog, source.data.nodeType, 'output')
      .map((endpoint) => endpoint.edge_type),
  )
  return WORKFLOW_CANVAS_EDGE_TYPES.filter((edgeType) => (
    sourceTypes.has(edgeType)
    && workflowCanvasNodeEndpoints(catalog, target.data.nodeType, 'input')
      .some((endpoint) => (endpoint.accepted_edge_types ?? [endpoint.edge_type]).includes(edgeType))
  ))
}
