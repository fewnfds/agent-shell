<script setup lang="ts">
import {
  ConnectionLineType,
  ConnectionMode,
  VueFlow,
  type Connection,
  type VueFlowStore,
  type ViewportTransform,
  type XYPosition,
} from '@vue-flow/core'
import { computed, nextTick, onBeforeMount, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import {
  ManagementApiError,
  managementApi,
  type MainAgent,
  type SavedBlock,
  type Workflow,
  type WorkflowNodeCatalogItem,
  type WorkflowNodeType,
} from '@/api'
import WorkflowInspector from '@/components/workflow/WorkflowInspector.vue'
import WorkflowNodeLibrary from '@/components/workflow/WorkflowNodeLibrary.vue'
import WorkflowNodeEndpoints from '@/components/workflow/WorkflowNodeEndpoints.vue'
import WorkflowNodeTracker from '@/components/workflow/WorkflowNodeTracker.vue'
import WorkflowProblemsPanel from '@/components/workflow/WorkflowProblemsPanel.vue'
import { useManagementError } from '@/composables/useManagementError'
import { useToasts } from '@/composables/useToasts'
import {
  newAgentCanvasNode,
  newCommandCanvasNode,
  newTaskDispatcherCanvasNode,
  nextWorkflowCanvasEdgeId,
  WORKFLOW_NODE_DRAG_MIME,
  workflowCanvasEdgeVisual,
  workflowCanvasEdgeTypesBetween,
  workflowCanvasNodeEndpoints,
  workflowCanvasToDocument,
  workflowConnectionEdgeType,
  workflowDocumentToCanvas,
  type WorkflowCanvasEdge,
  type WorkflowCanvasEdgeType,
  type WorkflowCanvasNode,
  type WorkflowEndpointDirection,
} from '@/domain/workflowGraph'
import {
  workflowCanvasProblems,
  workflowServerProblems,
  type WorkflowCanvasProblem,
} from '@/domain/workflowCanvasProblems'

type WorkflowLeftPanel = 'library' | 'tracker' | 'problems'
type WorkflowRightPanel = 'inspector'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const managementError = useManagementError()
const { notify } = useToasts()
const workflow = ref<Workflow | null>(null)
const mainAgents = ref<MainAgent[]>([])
const commands = ref<SavedBlock[]>([])
const taskDispatchers = ref<SavedBlock[]>([])
const nodeCatalog = ref<WorkflowNodeCatalogItem[]>([])
const nodes = ref<WorkflowCanvasNode[]>([])
const edges = ref<WorkflowCanvasEdge[]>([])
const flow = ref<VueFlowStore | null>(null)
const stateContract = ref('agent-shell.workflow.agent-invocations.v1')
const savedViewport = ref<ViewportTransform>({ x: 0, y: 0, zoom: 1 })
const leftPanel = ref<WorkflowLeftPanel | null>('library')
const rightPanel = ref<WorkflowRightPanel | null>('inspector')
const serverProblems = ref<WorkflowCanvasProblem[]>([])
const loaded = ref(false)
const saving = ref(false)
const validating = ref(false)
const validationReady = ref(false)
const validationError = ref('')
const loadError = ref('')
let validationTimer: ReturnType<typeof setTimeout> | undefined
let validationGeneration = 0
const workflowId = computed(() => String(route.params.id ?? ''))
const workflowListPath = computed(() => (
  workflow.value?.workflow_role === 'child'
    ? '/workflows/children'
    : '/workflows/parents'
))
const workflowRoleLabel = computed(() => (
  workflow.value ? t(`workflows.roles.${workflow.value.workflow_role}`) : ''
))
const agentCatalogItem = computed(() => (
  nodeCatalog.value.find((item) => item.type === 'agent') ?? null
))
const canAddAgent = computed(() => (
  loaded.value
  && mainAgents.value.length > 0
  && agentCatalogItem.value !== null
))
const commandCatalogItem = computed(() => (
  nodeCatalog.value.find((item) => item.type === 'command') ?? null
))
const canAddCommand = computed(() => (
  loaded.value
  && commands.value.length > 0
  && commandCatalogItem.value !== null
))
const taskDispatcherCatalogItem = computed(() => (
  nodeCatalog.value.find((item) => item.type === 'task-dispatcher') ?? null
))
const canAddTaskDispatcher = computed(() => (
  loaded.value
  && taskDispatchers.value.length > 0
  && taskDispatcherCatalogItem.value !== null
))
const canvasProblems = computed(() => workflowCanvasProblems(nodes.value, edges.value))
const problems = computed(() => [
  ...canvasProblems.value,
  ...serverProblems.value.filter((serverProblem) => !canvasProblems.value.some((canvasProblem) => (
    canvasProblem.owner_id === serverProblem.owner_id
    && canvasProblem.path === serverProblem.path
  ))),
])
const canSaveDraft = computed(() => (
  loaded.value
  && !saving.value
))
const canPublish = computed(() => (
  loaded.value
  && !saving.value
  && !validating.value
  && validationReady.value
  && !problems.value.some((problem) => problem.blocking)
))
const graphRevision = computed(() => JSON.stringify({
  nodes: nodes.value.map((node) => ({
    id: node.id,
    position: node.position,
    type: node.data.nodeType,
    mainAgentId: node.data.mainAgentId,
    commandId: node.data.commandId,
    taskDispatcherId: node.data.taskDispatcherId,
    defer: node.data.defer,
  })),
  edges: edges.value.map((edge) => ({
    id: edge.id,
    source: edge.source,
    sourceHandle: edge.sourceHandle,
    target: edge.target,
    targetHandle: edge.targetHandle,
    edgeType: edge.data.edgeType,
    branchKey: edge.data.branchKey,
    dispatchKey: edge.data.dispatchKey,
  })),
}))
const selectedNode = computed(() => nodes.value.find((node) => node.selected) ?? null)
const selectedEdge = computed(() => (
  selectedNode.value ? null : edges.value.find((edge) => edge.selected) ?? null
))
const selectedNodeInputEndpoints = computed(() => nodeEndpoints(
  selectedNode.value?.data.nodeType,
  'input',
))
const selectedNodeOutputEndpoints = computed(() => nodeEndpoints(
  selectedNode.value?.data.nodeType,
  'output',
))
const selectedEdgeSourceNode = computed(() => (
  nodes.value.find((node) => node.id === selectedEdge.value?.source) ?? null
))
const selectedEdgeTargetNode = computed(() => (
  nodes.value.find((node) => node.id === selectedEdge.value?.target) ?? null
))
const selectedEdgeSourceEndpoints = computed(() => nodeEndpoints(
  selectedEdgeSourceNode.value?.data.nodeType,
  'output',
))
const selectedEdgeTargetEndpoints = computed(() => nodeEndpoints(
  selectedEdgeTargetNode.value?.data.nodeType,
  'input',
))
const selectedEdgeTypeOptions = computed(() => workflowCanvasEdgeTypesBetween(
  selectedEdgeSourceNode.value,
  selectedEdgeTargetNode.value,
  nodeCatalog.value,
))

watch(graphRevision, (current, previous) => {
  if (previous !== undefined && current !== previous) scheduleValidation()
})

function nodeEndpoints(
  nodeType: WorkflowNodeType | undefined,
  direction: WorkflowEndpointDirection,
) {
  return nodeType
    ? workflowCanvasNodeEndpoints(nodeCatalog.value, nodeType, direction)
    : []
}

function isValidConnection(connection: Connection): boolean {
  return workflowConnectionEdgeType(
    connection,
    nodes.value,
    edges.value,
    nodeCatalog.value,
  ) !== null
}

function connect(connection: Connection): void {
  const edgeType = workflowConnectionEdgeType(
    connection,
    nodes.value,
    edges.value,
    nodeCatalog.value,
  )
  if (!edgeType) return
  const source = nodes.value.find((node) => node.id === connection.source)
  const target = nodes.value.find((node) => node.id === connection.target)
  if (!source || !target) return
  nodes.value = nodes.value.map((node) => ({ ...node, selected: false }))
  edges.value = [
    ...edges.value.map((edge) => ({ ...edge, selected: false })),
    {
      id: nextWorkflowCanvasEdgeId(edges.value),
      source: connection.source,
      sourceHandle: connection.sourceHandle,
      target: connection.target,
      targetHandle: connection.targetHandle,
      type: 'default',
      ...workflowCanvasEdgeVisual(edgeType, source.data.nodeType, target.data.nodeType),
      selected: true,
      data: { edgeType },
    },
  ]
  rightPanel.value = 'inspector'
}

function addAgent(position?: XYPosition): void {
  const firstAgent = mainAgents.value[0]
  if (!canAddAgent.value || !firstAgent) return
  const nodeId = nextAgentNodeId()
  const node = newAgentCanvasNode(nodeId, firstAgent.id, position ?? nextAgentPosition())
  node.selected = true
  nodes.value = [
    ...nodes.value.map((item) => ({ ...item, selected: false })),
    node,
  ]
  edges.value = edges.value.map((edge) => ({ ...edge, selected: false }))
  rightPanel.value = 'inspector'
}

function addCommand(position?: XYPosition): void {
  const firstRouter = commands.value[0]
  if (!canAddCommand.value || !firstRouter) return
  const nodeId = nextCommandNodeId()
  const node = newCommandCanvasNode(
    nodeId,
    firstRouter.id,
    position ?? nextCommandPosition(),
  )
  node.selected = true
  nodes.value = [
    ...nodes.value.map((item) => ({ ...item, selected: false })),
    node,
  ]
  edges.value = edges.value.map((edge) => ({ ...edge, selected: false }))
  rightPanel.value = 'inspector'
}

function addTaskDispatcher(position?: XYPosition): void {
  const firstDispatcher = taskDispatchers.value[0]
  if (!canAddTaskDispatcher.value || !firstDispatcher) return
  const nodeId = nextTaskDispatcherNodeId()
  const node = newTaskDispatcherCanvasNode(
    nodeId,
    firstDispatcher.id,
    position ?? nextTaskDispatcherPosition(),
  )
  node.selected = true
  nodes.value = [
    ...nodes.value.map((item) => ({ ...item, selected: false })),
    node,
  ]
  edges.value = edges.value.map((edge) => ({ ...edge, selected: false }))
  rightPanel.value = 'inspector'
}

function nextAgentPosition(): XYPosition {
  const count = nodes.value.filter((node) => node.data.nodeType === 'agent').length
  return {
    x: 360 + (count % 4) * 260,
    y: 180 + Math.floor(count / 4) * 140,
  }
}

function nextAgentNodeId(): string {
  let index = 1
  while (nodes.value.some((node) => node.id === `agent-${index}`)) index += 1
  return `agent-${index}`
}

function nextCommandPosition(): XYPosition {
  const count = nodes.value.filter((node) => node.data.nodeType === 'command').length
  return { x: 620 + (count % 3) * 280, y: 180 + Math.floor(count / 3) * 160 }
}

function nextCommandNodeId(): string {
  let index = 1
  while (nodes.value.some((node) => node.id === `command-${index}`)) index += 1
  return `command-${index}`
}

function nextTaskDispatcherPosition(): XYPosition {
  const count = nodes.value.filter((node) => node.data.nodeType === 'task-dispatcher').length
  return { x: 620 + (count % 3) * 280, y: 340 + Math.floor(count / 3) * 160 }
}

function nextTaskDispatcherNodeId(): string {
  let index = 1
  while (nodes.value.some((node) => node.id === `task-dispatcher-${index}`)) index += 1
  return `task-dispatcher-${index}`
}

function dragOver(event: DragEvent): void {
  if (
    (!canAddAgent.value && !canAddCommand.value && !canAddTaskDispatcher.value)
    || !event.dataTransfer?.types.includes(WORKFLOW_NODE_DRAG_MIME)
  ) return
  event.preventDefault()
  event.dataTransfer.dropEffect = 'copy'
}

function dropNode(event: DragEvent): void {
  if (
    (!canAddAgent.value && !canAddCommand.value && !canAddTaskDispatcher.value)
    || !flow.value
    || !['agent', 'command', 'task-dispatcher'].includes(
      event.dataTransfer?.getData(WORKFLOW_NODE_DRAG_MIME) ?? '',
    )
  ) return
  event.preventDefault()
  const position = flow.value.screenToFlowCoordinate({ x: event.clientX, y: event.clientY })
  const nodeType = event.dataTransfer?.getData(WORKFLOW_NODE_DRAG_MIME)
  if (nodeType === 'agent') addAgent(position)
  else if (nodeType === 'command') addCommand(position)
  else addTaskDispatcher(position)
}

function removeNode(nodeId: string): void {
  nodes.value = nodes.value.filter((node) => node.id !== nodeId)
  edges.value = edges.value.filter((edge) => edge.source !== nodeId && edge.target !== nodeId)
}

function updateNodeId(nodeId: string, nextNodeId: string): void {
  if (
    !/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(nextNodeId)
    || nodes.value.some((node) => node.id === nextNodeId)
  ) return
  const source = nodes.value.find((node) => node.id === nodeId)
  if (!source || source.data.nodeType === 'start' || source.data.nodeType === 'end') return
  nodes.value = nodes.value.map((node) => (
    node.id === nodeId ? { ...node, id: nextNodeId } : node
  ))
  edges.value = edges.value.map((edge) => ({
    ...edge,
    source: edge.source === nodeId ? nextNodeId : edge.source,
    target: edge.target === nodeId ? nextNodeId : edge.target,
  }))
}

function removeEdge(edgeId: string): void {
  edges.value = edges.value.filter((edge) => edge.id !== edgeId)
}

function replaceEdgeEndpoints(
  edgeId: string,
  sourceHandle: string,
  targetHandle: string,
): void {
  const edge = edges.value.find((item) => item.id === edgeId)
  if (!edge) return
  const edgeType = workflowConnectionEdgeType(
    {
      source: edge.source,
      sourceHandle,
      target: edge.target,
      targetHandle,
    },
    nodes.value,
    edges.value.filter((item) => item.id !== edgeId),
    nodeCatalog.value,
  )
  if (!edgeType) return
  const source = nodes.value.find((node) => node.id === edge.source)
  const target = nodes.value.find((node) => node.id === edge.target)
  if (!source || !target) return
  edges.value = edges.value.map((item) => (
    item.id === edgeId
      ? {
          ...item,
          sourceHandle,
          targetHandle,
          data: {
            edgeType,
            branchKey: edgeType === 'branch' ? item.data.branchKey : undefined,
            dispatchKey: edgeType === 'dispatch' ? item.data.dispatchKey : undefined,
          },
          ...workflowCanvasEdgeVisual(edgeType, source.data.nodeType, target.data.nodeType),
        }
      : item
  ))
}

function selectEdgeType(edgeId: string, edgeType: WorkflowCanvasEdgeType): void {
  const edge = edges.value.find((item) => item.id === edgeId)
  if (!edge) return
  const source = nodes.value.find((node) => node.id === edge.source)
  const target = nodes.value.find((node) => node.id === edge.target)
  if (!source || !target) return
  const sourceEndpoint = nodeEndpoints(source.data.nodeType, 'output')
    .find((endpoint) => endpoint.edge_type === edgeType)
  const targetEndpoint = nodeEndpoints(target.data.nodeType, 'input')
    .find((endpoint) => (endpoint.accepted_edge_types ?? [endpoint.edge_type]).includes(edgeType))
  if (!sourceEndpoint || !targetEndpoint) return
  replaceEdgeEndpoints(edgeId, sourceEndpoint.id, targetEndpoint.id)
}

function selectEdgeSourceEndpoint(edgeId: string, sourceHandle: string): void {
  const edge = edges.value.find((item) => item.id === edgeId)
  if (!edge || !edge.targetHandle) return
  replaceEdgeEndpoints(edgeId, sourceHandle, edge.targetHandle)
}

function selectEdgeTargetEndpoint(edgeId: string, targetHandle: string): void {
  const edge = edges.value.find((item) => item.id === edgeId)
  if (!edge || !edge.sourceHandle) return
  replaceEdgeEndpoints(edgeId, edge.sourceHandle, targetHandle)
}

function selectAgent(nodeId: string, mainAgentId: string): void {
  nodes.value = nodes.value.map((node) => (
    node.id === nodeId
      ? { ...node, data: { ...node.data, mainAgentId } }
      : node
  ))
}

function selectCommand(nodeId: string, commandId: string): void {
  nodes.value = nodes.value.map((node) => (
    node.id === nodeId
      ? { ...node, data: { ...node.data, commandId } }
      : node
  ))
}

function selectTaskDispatcher(nodeId: string, taskDispatcherId: string): void {
  nodes.value = nodes.value.map((node) => (
    node.id === nodeId
      ? { ...node, data: { ...node.data, taskDispatcherId } }
      : node
  ))
}

function updateBranchKey(edgeId: string, branchKey: string): void {
  edges.value = edges.value.map((edge) => (
    edge.id === edgeId && edge.data.edgeType === 'branch'
      ? { ...edge, data: { ...edge.data, branchKey } }
      : edge
  ))
}

function updateDispatchKey(edgeId: string, dispatchKey: string): void {
  edges.value = edges.value.map((edge) => (
    edge.id === edgeId && edge.data.edgeType === 'dispatch'
      ? { ...edge, data: { ...edge.data, dispatchKey } }
      : edge
  ))
}

function selectDefer(nodeId: string, defer: boolean): void {
  nodes.value = nodes.value.map((node) => (
    node.id === nodeId
      ? { ...node, data: { ...node.data, defer } }
      : node
  ))
}

function clearSelection(): void {
  nodes.value = nodes.value.map((node) => ({ ...node, selected: false }))
  edges.value = edges.value.map((edge) => ({ ...edge, selected: false }))
}

function clearSelectionAndCloseInspector(): void {
  clearSelection()
  rightPanel.value = null
}

function showInspector(): void {
  rightPanel.value = 'inspector'
}

function toggleLeftPanel(panel: WorkflowLeftPanel): void {
  leftPanel.value = leftPanel.value === panel ? null : panel
}

function toggleRightPanel(panel: WorkflowRightPanel): void {
  rightPanel.value = rightPanel.value === panel ? null : panel
}

async function selectAndCenterNode(nodeId: string): Promise<void> {
  if (!flow.value) return
  nodes.value = nodes.value.map((node) => ({ ...node, selected: node.id === nodeId }))
  edges.value = edges.value.map((edge) => ({ ...edge, selected: false }))
  rightPanel.value = 'inspector'
  await nextTick()
  await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))

  const node = flow.value.findNode(nodeId)
  if (!node || node.dimensions.width <= 0 || node.dimensions.height <= 0) return
  const viewport = flow.value.getViewport()
  await flow.value.setCenter(
    node.computedPosition.x + node.dimensions.width / 2,
    node.computedPosition.y + node.dimensions.height / 2,
    { duration: 220, interpolate: 'smooth', zoom: viewport.zoom },
  )
}

function selectProblem(problem: WorkflowCanvasProblem): void {
  if (nodes.value.some((node) => node.id === problem.owner_id)) {
    void selectAndCenterNode(problem.owner_id)
    return
  }
  if (edges.value.some((edge) => edge.id === problem.owner_id)) {
    nodes.value = nodes.value.map((node) => ({ ...node, selected: false }))
    edges.value = edges.value.map((edge) => ({
      ...edge,
      selected: edge.id === problem.owner_id,
    }))
    rightPanel.value = 'inspector'
    return
  }
  clearSelection()
  rightPanel.value = 'inspector'
}

function mainAgentName(mainAgentId: string): string {
  return mainAgents.value.find((agent) => agent.id === mainAgentId)?.name
    ?? t('workflows.editor.noMainAgentSelected')
}

function commandName(commandId: string): string {
  return commands.value.find((router) => router.id === commandId)?.name
    ?? t('workflows.editor.noCommandSelected')
}

function taskDispatcherName(taskDispatcherId: string): string {
  return taskDispatchers.value.find((dispatcher) => dispatcher.id === taskDispatcherId)?.name
    ?? t('workflows.editor.noTaskDispatcherSelected')
}

async function initializeFlow(instance: VueFlowStore): Promise<void> {
  flow.value = instance
  if (loaded.value) {
    await nextTick()
    await instance.setViewport(savedViewport.value)
  }
}

function currentDocument(): ReturnType<typeof workflowCanvasToDocument> | null {
  if (!flow.value) return null
  return workflowCanvasToDocument(nodes.value, edges.value, flow.value.getViewport())
}

function scheduleValidation(delay = 350): void {
  if (!loaded.value) return
  validationGeneration += 1
  const generation = validationGeneration
  validating.value = true
  validationReady.value = false
  validationError.value = ''
  serverProblems.value = []
  if (validationTimer !== undefined) clearTimeout(validationTimer)
  validationTimer = setTimeout(async () => {
    const document = currentDocument()
    if (!document) {
      if (generation === validationGeneration) {
        validating.value = false
        validationError.value = t('workflows.editor.validationFailed')
      }
      return
    }
    try {
      const report = await managementApi.validateWorkflow(workflowId.value, document)
      if (generation === validationGeneration) {
        serverProblems.value = workflowServerProblems(report.issues)
        validationReady.value = true
      }
    } catch (error) {
      if (generation === validationGeneration) {
        validationError.value = managementError.describe(error).display
      }
    } finally {
      if (generation === validationGeneration) validating.value = false
    }
  }, delay)
}

function retryValidation(): void {
  scheduleValidation(0)
}

async function saveDraft(): Promise<void> {
  if (!canSaveDraft.value) return
  saving.value = true
  try {
    const document = currentDocument()
    if (!document) return
    await managementApi.saveWorkflowDraft(workflowId.value, document)
    if (workflow.value) workflow.value = { ...workflow.value, enabled: false }
    notify({ tone: 'success', title: t('workflows.editor.draftSaved') })
  } catch (error) {
    const presentation = managementError.describe(error)
    if (error instanceof ManagementApiError && error.validation) {
      serverProblems.value = workflowServerProblems(error.validation.issues)
    }
    notify({
      tone: 'danger',
      title: t('workflows.editor.saveFailed'),
      message: error instanceof ManagementApiError && error.validation
        ? presentation.message
        : presentation.display,
    })
  } finally {
    saving.value = false
  }
}

async function publish(): Promise<void> {
  if (!canPublish.value) return
  saving.value = true
  try {
    const document = currentDocument()
    if (!document) return
    await managementApi.publishWorkflow(workflowId.value, document)
    if (workflow.value) workflow.value = { ...workflow.value, enabled: true }
    serverProblems.value = []
    notify({ tone: 'success', title: t('workflows.editor.published') })
  } catch (error) {
    const presentation = managementError.describe(error)
    if (error instanceof ManagementApiError && error.validation) {
      serverProblems.value = workflowServerProblems(error.validation.issues)
    }
    notify({
      tone: 'danger',
      title: t('workflows.editor.publishFailed'),
      message: error instanceof ManagementApiError && error.validation
        ? presentation.message
        : presentation.display,
    })
  } finally {
    saving.value = false
  }
}

onBeforeMount(() => {
  document.documentElement.classList.add('workflow-editor-active')
})

onMounted(async () => {
  try {
    const [
      metadata,
      graph,
      agents,
      commandRecords,
      taskDispatcherRecords,
      catalog,
    ] = await Promise.all([
      managementApi.getWorkflow(workflowId.value),
      managementApi.getWorkflowGraph(workflowId.value),
      managementApi.listMainAgents(),
      managementApi.listBlocks('command'),
      managementApi.listBlocks('task-dispatcher'),
      managementApi.listWorkflowNodeCatalog(),
    ])
    workflow.value = metadata
    mainAgents.value = agents
    commands.value = commandRecords
    taskDispatchers.value = taskDispatcherRecords
    nodeCatalog.value = catalog.filter((item) => item.workflow_roles.includes(metadata.workflow_role))
    stateContract.value = graph.definition.state_contract
    const canvas = workflowDocumentToCanvas(graph, nodeCatalog.value)
    nodes.value = canvas.nodes
    edges.value = canvas.edges
    savedViewport.value = canvas.viewport
    loaded.value = true
    await nextTick()
    await flow.value?.setViewport(canvas.viewport)
    scheduleValidation()
  } catch (error) {
    loadError.value = managementError.describe(error).display
  }
})

onUnmounted(() => {
  if (validationTimer !== undefined) clearTimeout(validationTimer)
  document.documentElement.classList.remove('workflow-editor-active')
})
</script>

<template>
  <div class="workflow-editor-shell">
    <header class="workflow-editor-toolbar">
      <button :aria-label="t('workflows.editor.back')" :title="t('workflows.editor.back')" type="button" @click="router.push(workflowListPath)">
        <i class="bi bi-chevron-left" aria-hidden="true" />
      </button>
      <h1>{{ workflow ? `${workflowRoleLabel} - ${workflow.name}` : t('workflows.editor.title') }}</h1>
      <div class="d-flex align-items-center gap-1">
        <span class="badge text-bg-secondary">{{ workflow?.enabled ? t('workflows.status.published') : t('workflows.status.draft') }}</span>
        <button :aria-label="t('workflows.editor.saveDraft')" :disabled="!canSaveDraft" :title="t('workflows.editor.saveDraft')" type="button" @click="saveDraft">
          <i class="bi bi-file-earmark" aria-hidden="true" />
        </button>
        <button :aria-label="t('workflows.editor.publish')" :disabled="!canPublish" :title="t('workflows.editor.publish')" type="button" @click="publish">
          <i class="bi bi-upload" aria-hidden="true" />
        </button>
      </div>
    </header>

    <div class="workflow-editor-workspace">
      <aside
        class="workflow-tool-dock workflow-tool-dock--left"
        :data-panel-open="Boolean(leftPanel)"
      >
        <nav class="workflow-tool-rail" :aria-label="t('workflows.editor.leftTools')">
          <button
            class="workflow-tool-button"
            :aria-label="t('workflows.editor.showNodeLibrary')"
            :aria-pressed="leftPanel === 'library'"
            :data-active="leftPanel === 'library'"
            :title="t('workflows.editor.showNodeLibrary')"
            type="button"
            @click="toggleLeftPanel('library')"
          >
            <i class="bi bi-boxes" aria-hidden="true" />
          </button>
          <button
            class="workflow-tool-button"
            :aria-label="t('workflows.editor.showNodeTracker')"
            :aria-pressed="leftPanel === 'tracker'"
            :data-active="leftPanel === 'tracker'"
            :title="t('workflows.editor.showNodeTracker')"
            type="button"
            @click="toggleLeftPanel('tracker')"
          >
            <i class="bi bi-list" aria-hidden="true" />
          </button>
          <button
            class="workflow-tool-button"
            :aria-label="t('workflows.editor.showProblems', { count: problems.length })"
            :aria-pressed="leftPanel === 'problems'"
            :data-active="leftPanel === 'problems'"
            :title="t('workflows.editor.showProblems', { count: problems.length })"
            type="button"
            @click="toggleLeftPanel('problems')"
          >
            <i class="bi bi-exclamation-triangle" aria-hidden="true" />
            <span
              v-if="problems.length > 0"
              class="workflow-tool-badge"
              aria-hidden="true"
            >{{ problems.length > 99 ? '99+' : problems.length }}</span>
          </button>
        </nav>
        <WorkflowNodeLibrary
          v-if="leftPanel === 'library'"
          :agent="agentCatalogItem"
          :command="commandCatalogItem"
          :task-dispatcher="taskDispatcherCatalogItem"
          :agent-disabled="!canAddAgent"
          :command-disabled="!canAddCommand"
          :task-dispatcher-disabled="!canAddTaskDispatcher"
          @add-agent="addAgent()"
          @add-command="addCommand()"
          @add-task-dispatcher="addTaskDispatcher()"
        />
        <WorkflowNodeTracker
          v-else-if="leftPanel === 'tracker'"
          :nodes="nodes"
          @locate-node="selectAndCenterNode"
        />
        <WorkflowProblemsPanel
          v-else-if="leftPanel === 'problems'"
          :problems="problems"
          @select-problem="selectProblem"
        />
      </aside>

      <main
        class="workflow-editor-canvas"
        :aria-label="t('workflows.editor.canvas')"
        @dragover="dragOver"
        @drop="dropNode"
      >
        <p v-if="loadError" class="workflow-editor-error" role="alert">{{ loadError }}</p>
        <div
          v-else-if="validationError"
          class="workflow-validation-error"
          role="alert"
        >
          <span>{{ t('workflows.editor.validationFailed') }} {{ validationError }}</span>
          <button
            class="btn btn-sm btn-outline-danger"
            type="button"
            @click="retryValidation"
          >{{ t('workflows.editor.retryValidation') }}</button>
        </div>
        <VueFlow
          v-if="!loadError"
          v-model:nodes="nodes"
          v-model:edges="edges"
          class="workflow-editor-flow"
          :connection-line-type="ConnectionLineType.Bezier"
          :connection-mode="ConnectionMode.Strict"
          default-marker-color="var(--bs-primary)"
          :delete-key-code="['Backspace', 'Delete']"
          :is-valid-connection="isValidConnection"
          :max-zoom="2"
          :min-zoom="0.25"
          @connect="connect"
          @edge-click="showInspector"
          @init="initializeFlow"
          @node-click="showInspector"
          @pane-click="clearSelectionAndCloseInspector"
        >
          <template #node-start="{ id }">
            <div class="workflow-node workflow-node--terminal">
              <span class="workflow-node-icon" aria-hidden="true"><i class="bi bi-play-fill" /></span>
              <span class="workflow-node-title">{{ id }}</span>
              <WorkflowNodeEndpoints
                direction="output"
                :endpoints="nodeEndpoints('start', 'output')"
              />
            </div>
          </template>

          <template #node-agent="{ id, data }">
            <div class="workflow-node workflow-node--agent">
              <WorkflowNodeEndpoints
                direction="input"
                :endpoints="nodeEndpoints('agent', 'input')"
              />
              <div class="workflow-node-header">
                <span class="workflow-node-icon" aria-hidden="true"><i class="bi bi-robot" /></span>
                <span class="workflow-node-title">{{ id }}</span>
              </div>
              <span class="workflow-node-summary">{{ mainAgentName(data.mainAgentId) }}</span>
              <WorkflowNodeEndpoints
                direction="output"
                :endpoints="nodeEndpoints('agent', 'output')"
              />
            </div>
          </template>

          <template #node-command="{ id, data }">
            <div class="workflow-node workflow-node--command">
              <WorkflowNodeEndpoints direction="input" :endpoints="nodeEndpoints('command', 'input')" />
              <div class="workflow-node-header">
                <span class="workflow-node-icon" aria-hidden="true"><i class="bi bi-circle-half" /></span>
                <span class="workflow-node-title">{{ id }}</span>
              </div>
              <span class="workflow-node-summary">{{ commandName(data.commandId ?? '') }}</span>
              <WorkflowNodeEndpoints direction="output" :endpoints="nodeEndpoints('command', 'output')" />
            </div>
          </template>

          <template #node-task-dispatcher="{ id, data }">
            <div class="workflow-node workflow-node--task-dispatcher">
              <WorkflowNodeEndpoints direction="input" :endpoints="nodeEndpoints('task-dispatcher', 'input')" />
              <div class="workflow-node-header">
                <span class="workflow-node-icon" aria-hidden="true"><i class="bi bi-boxes" /></span>
                <span class="workflow-node-title">{{ id }}</span>
              </div>
              <span class="workflow-node-summary">{{ taskDispatcherName(data.taskDispatcherId ?? '') }}</span>
              <WorkflowNodeEndpoints direction="output" :endpoints="nodeEndpoints('task-dispatcher', 'output')" />
            </div>
          </template>

          <template #node-end="{ id }">
            <div class="workflow-node workflow-node--terminal">
              <WorkflowNodeEndpoints
                direction="input"
                :endpoints="nodeEndpoints('end', 'input')"
              />
              <span class="workflow-node-icon" aria-hidden="true"><i class="bi bi-stop-fill" /></span>
              <span class="workflow-node-title">{{ id }}</span>
            </div>
          </template>
        </VueFlow>
      </main>

      <aside
        class="workflow-tool-dock workflow-tool-dock--right"
        :data-panel-open="Boolean(rightPanel)"
      >
        <WorkflowInspector
          v-if="rightPanel === 'inspector'"
          :edge="selectedEdge"
          :edge-source-endpoints="selectedEdgeSourceEndpoints"
          :edge-target-endpoints="selectedEdgeTargetEndpoints"
          :edge-type-options="selectedEdgeTypeOptions"
          :input-endpoints="selectedNodeInputEndpoints"
          :main-agents="mainAgents"
          :commands="commands"
          :task-dispatchers="taskDispatchers"
          :node="selectedNode"
          :node-ids="nodes.map((node) => node.id)"
          :output-endpoints="selectedNodeOutputEndpoints"
          :state-contract="stateContract"
          :workflow-name="workflow?.name ?? ''"
          @remove-edge="removeEdge"
          @remove-node="removeNode"
          @select-edge-source-endpoint="selectEdgeSourceEndpoint"
          @select-edge-target-endpoint="selectEdgeTargetEndpoint"
          @select-edge-type="selectEdgeType"
          @update-agent="selectAgent"
          @update-command="selectCommand"
          @update-task-dispatcher="selectTaskDispatcher"
          @update-node-id="updateNodeId"
          @update-branch-key="updateBranchKey"
          @update-dispatch-key="updateDispatchKey"
          @update-defer="selectDefer"
        />
        <nav class="workflow-tool-rail" :aria-label="t('workflows.editor.rightTools')">
          <button
            class="workflow-tool-button"
            :aria-label="t('workflows.editor.showInspector')"
            :aria-pressed="rightPanel === 'inspector'"
            :data-active="rightPanel === 'inspector'"
            :title="t('workflows.editor.showInspector')"
            type="button"
            @click="toggleRightPanel('inspector')"
          >
            <i class="bi bi-sliders" aria-hidden="true" />
          </button>
        </nav>
      </aside>
    </div>
  </div>
</template>
