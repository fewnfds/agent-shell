import type {
  RuntimeMonitoringRun,
  RuntimeMonitoringSnapshot,
  WorkflowGraphDocument,
  WorkflowNodeCatalogItem,
} from '@/api'
import { workflowDocumentToCanvas, type WorkflowCanvasState } from '@/domain/workflowGraph'

export interface RuntimeMonitoringRunTreeNode {
  run: RuntimeMonitoringRun
  children: RuntimeMonitoringRunTreeNode[]
}

export function runtimeMonitoringRunForest(
  snapshot: RuntimeMonitoringSnapshot,
): RuntimeMonitoringRunTreeNode[] {
  const nodes = new Map(snapshot.runs.map((run) => [
    run.run_id,
    { run, children: [] } satisfies RuntimeMonitoringRunTreeNode,
  ]))

  for (const relationship of snapshot.forest.relationships) {
    const parent = nodes.get(relationship.parent_run_id)
    const child = nodes.get(relationship.child_run_id)
    if (parent && child) parent.children.push(child)
  }

  return snapshot.forest.root_run_ids.flatMap((runId) => {
    const node = nodes.get(runId)
    return node ? [node] : []
  })
}

export function selectRuntimeMonitoringRunId(
  snapshot: RuntimeMonitoringSnapshot,
  requestedRunId: string,
): string | null {
  if (requestedRunId && snapshot.runs.some((run) => run.run_id === requestedRunId)) {
    return requestedRunId
  }
  if (snapshot.runs.some((run) => run.run_id === snapshot.lifecycle.root_run_id)) {
    return snapshot.lifecycle.root_run_id
  }
  return snapshot.forest.root_run_ids.find((runId) => (
    snapshot.runs.some((run) => run.run_id === runId)
  )) ?? snapshot.runs[0]?.run_id ?? null
}

export function runtimeWorkflowCanvasState(
  document: WorkflowGraphDocument,
  catalog: WorkflowNodeCatalogItem[],
): WorkflowCanvasState {
  const canvas = workflowDocumentToCanvas(document, catalog, { addDefaultTerminals: false })
  return {
    ...canvas,
    nodes: canvas.nodes.map((node) => ({
      ...node,
      deletable: false,
      draggable: false,
      selectable: false,
    })),
    edges: canvas.edges.map((edge) => ({
      ...edge,
      animated: false,
      deletable: false,
      selectable: false,
      updatable: false,
    })),
  }
}
