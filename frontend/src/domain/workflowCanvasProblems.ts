import type { ValidationIssue } from '@/api'

import type { WorkflowCanvasEdge, WorkflowCanvasNode } from './workflowGraph'

export interface WorkflowCanvasProblem extends ValidationIssue {
  blocking: boolean
  source: 'canvas' | 'server'
}

function canvasProblem(
  code: string,
  messageKey: string,
  ownerId: string,
  ownerType: string,
  path: string,
): WorkflowCanvasProblem {
  return {
    blocking: true,
    code,
    message: '',
    message_args: {},
    message_key: messageKey,
    owner_id: ownerId,
    owner_name: ownerId,
    owner_type: ownerType,
    path,
    scope: 'workflow',
    severity: 'error',
    source: 'canvas',
  }
}

export function workflowCanvasProblems(
  nodes: WorkflowCanvasNode[],
  edges: WorkflowCanvasEdge[],
): WorkflowCanvasProblem[] {
  const problems: WorkflowCanvasProblem[] = []

  nodes.forEach((node, index) => {
    if (node.data.nodeType === 'agent' && !node.data.mainAgentId) {
      problems.push(canvasProblem(
        'workflow.canvas.main_agent_required',
        'workflows.editor.canvasProblems.mainAgentRequired',
        node.id,
        node.data.nodeType,
        `definition.nodes[${index}].config.main_agent_id`,
      ))
    }
    if (node.data.nodeType === 'command' && !node.data.commandId) {
      problems.push(canvasProblem(
        'workflow.canvas.command_required',
        'workflows.editor.canvasProblems.commandRequired',
        node.id,
        node.data.nodeType,
        `definition.nodes[${index}].config.command_id`,
      ))
    }
  })

  edges.forEach((edge, index) => {
    if (edge.data.edgeType === 'branch' && !edge.data.branchKey) {
      problems.push(canvasProblem(
        'workflow.canvas.branch_key_required',
        'workflows.editor.canvasProblems.branchKeyRequired',
        edge.id,
        'edge',
        `definition.edges[${index}].branch_key`,
      ))
    }
    if (edge.data.edgeType === 'dispatch' && !edge.data.dispatchKey) {
      problems.push(canvasProblem(
        'workflow.canvas.dispatch_key_required',
        'workflows.editor.canvasProblems.dispatchKeyRequired',
        edge.id,
        'edge',
        `definition.edges[${index}].dispatch_key`,
      ))
    }
  })

  return problems
}

export function workflowServerProblems(issues: ValidationIssue[]): WorkflowCanvasProblem[] {
  return issues.map((issue) => ({
    ...issue,
    blocking: issue.severity === 'error',
    source: 'server',
  }))
}
