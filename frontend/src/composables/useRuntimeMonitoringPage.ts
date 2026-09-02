import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import {
  managementApi,
  type RuntimeMonitoringAvailability,
  type RuntimeMonitoringGraphResponse,
  type RuntimeMonitoringNodeSummaryPage,
  type RuntimeMonitoringSnapshot,
  type WorkflowNodeCatalogItem,
} from '@/api'
import { useManagementError } from '@/composables/useManagementError'
import { useRuntimeMonitoringNodeDetails } from '@/composables/useRuntimeMonitoringNodeDetails'
import {
  runtimeMonitoringScopeRequest,
  runtimeMonitoringSelectorKey,
  useRuntimeMonitoringScope,
} from '@/composables/useRuntimeMonitoringScope'
import {
  useRuntimeMonitoringRunDetails,
  type RuntimeMonitoringRunDetailKind,
} from '@/composables/useRuntimeMonitoringRunDetails'
import {
  runtimeMonitoringRunForest,
  selectRuntimeMonitoringRunId,
} from '@/domain/runtimeMonitoring'

const POLL_INTERVAL_MS = 2000

export function useRuntimeMonitoringPage() {
  const { t } = useI18n()
  const route = useRoute()
  const router = useRouter()
  const managementError = useManagementError()
  const lifecycleId = computed(() => String(route.params.lifecycleId ?? ''))

  const lifecycleSnapshot = ref<RuntimeMonitoringSnapshot | null>(null)
  const snapshot = ref<RuntimeMonitoringSnapshot | null>(null)
  const nodeCatalog = ref<WorkflowNodeCatalogItem[]>([])
  const selectedRunId = ref('')
  const graphResponse = ref<RuntimeMonitoringGraphResponse | null>(null)
  const nodeSummaryPage = ref<RuntimeMonitoringNodeSummaryPage | null>(null)
  const nodeSummaryError = ref('')
  const nodeSummaryRetrying = ref(false)
  const lifecycleLoading = ref(false)
  const runLoading = ref(false)
  const lifecycleError = ref('')
  const catalogError = ref('')
  const runError = ref('')
  const pollRefreshing = ref(false)
  const pollError = ref('')
  let lifecycleGeneration = 0
  let scopeGeneration = 0
  let runGeneration = 0
  let pollGeneration = 0
  let lifecycleController: AbortController | null = null
  let scopeController: AbortController | null = null
  let runController: AbortController | null = null
  let nodeSummaryController: AbortController | null = null
  let pollController: AbortController | null = null
  let pollTimer: number | null = null
  let resourceRunId = ''

  const nodeDetails = useRuntimeMonitoringNodeDetails(lifecycleId, selectedRunId)
  const runDetails = useRuntimeMonitoringRunDetails(lifecycleId, selectedRunId)
  const scopeRoute = useRuntimeMonitoringScope(lifecycleSnapshot, snapshot, selectedRunId)
  const {
    selectedNodeId,
    selectedInvocationId,
    attemptPage: nodeAttemptPage,
    attemptLoading: nodeAttemptLoading,
    attemptError: nodeAttemptError,
    agentArtifact,
    agentArtifactLoading,
    agentArtifactError,
    agentProtocol,
    agentProtocolLoading,
    agentProtocolError,
    commandObservations,
    commandLoading,
    commandError,
  } = nodeDetails
  const {
    activeKind: runDetailKind,
    protocol: runProtocol,
    protocolLoading: runProtocolLoading,
    protocolError: runProtocolError,
    models: runModels,
    modelsLoading: runModelsLoading,
    modelsError: runModelsError,
    state: runState,
    stateLoading: runStateLoading,
    stateError: runStateError,
  } = runDetails
  const {
    requestedRunId,
    requestedScope,
    requestedScopeRouteKey,
    displayedScope,
    scopeSelectorId,
    scopeWorkflows,
    baseRunQuery,
    replaceCanonicalScopeQuery,
    selectScope,
    selectScopeTarget,
  } = scopeRoute
  const requestedNodeId = computed(() => (
    typeof route.query.node_id === 'string' ? route.query.node_id : ''
  ))
  const requestedRunDetailKind = computed<RuntimeMonitoringRunDetailKind | null>(() => {
    const value = typeof route.query.view === 'string' ? route.query.view : ''
    return value === 'protocol' || value === 'models' || value === 'state' ? value : null
  })
  const runRoots = computed(() => snapshot.value ? runtimeMonitoringRunForest(snapshot.value) : [])
  const selectedRun = computed(() => snapshot.value?.runs.find((run) => (
    run.run_id === selectedRunId.value
  )) ?? null)
  const graphDocument = computed(() => graphResponse.value?.graph?.document ?? null)
  const selectedNode = computed(() => graphDocument.value?.definition.nodes.find((node) => (
    node.id === selectedNodeId.value
  )) ?? null)
  const selectedNodeSummary = computed(() => nodeSummaryPage.value?.items.find((summary) => (
    summary.workflow_node_id === selectedNodeId.value
  )) ?? null)
  const lifecycleIsActive = computed(() => (
    Boolean(lifecycleSnapshot.value)
    && lifecycleSnapshot.value!.lifecycle.fully_terminal_at === null
  ))

  function localTime(value: string | null): string {
    if (!value) return t('common.none')
    const parsed = new Date(value)
    return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
  }

  function availabilityLabel(value: RuntimeMonitoringAvailability): string {
    return t(`runtimeMonitoring.availability.${value}`)
  }

  function graphEmptyMessage(): string {
    const availability = graphResponse.value?.availability
    return availability
      ? t(`runtimeMonitoring.graph.emptyByAvailability.${availability}`)
      : t('runtimeMonitoring.graph.empty')
  }

  function isCurrentRunRequest(generation: number, runId: string): boolean {
    return generation === runGeneration
      && selectedRunId.value === runId
      && resourceRunId === runId
  }

  function clearPollTimer(): void {
    if (pollTimer === null) return
    window.clearTimeout(pollTimer)
    pollTimer = null
  }

  function stopPolling(): void {
    clearPollTimer()
    pollController?.abort()
    pollGeneration += 1
    pollRefreshing.value = false
  }

  function schedulePoll(): void {
    clearPollTimer()
    if (!snapshot.value || !lifecycleIsActive.value || document.hidden) return
    pollTimer = window.setTimeout(() => { void pollOnce() }, POLL_INTERVAL_MS)
  }

  async function refreshSelectedRunNodes(
    targetLifecycleId: string,
    targetRunId: string,
    signal: AbortSignal,
  ): Promise<void> {
    const document = graphDocument.value
    if (!document || selectedRunId.value !== targetRunId) return
    const pageSize = Math.max(1, document.definition.nodes.length)
    const response = await managementApi.listRuntimeMonitoringNodes(
      targetLifecycleId,
      targetRunId,
      { page: 1, page_size: pageSize },
      signal,
    )
    if (
      selectedRunId.value === targetRunId
      && resourceRunId === targetRunId
      && lifecycleId.value === targetLifecycleId
      && !signal.aborted
    ) {
      nodeSummaryPage.value = response
      nodeSummaryError.value = ''
    }
  }

  async function retryNodeSummaries(): Promise<void> {
    const targetLifecycleId = lifecycleId.value
    const targetRunId = selectedRunId.value
    if (!graphDocument.value || !targetRunId) return
    nodeSummaryController?.abort()
    const controller = new AbortController()
    nodeSummaryController = controller
    nodeSummaryRetrying.value = true
    nodeSummaryError.value = ''
    try {
      await refreshSelectedRunNodes(targetLifecycleId, targetRunId, controller.signal)
    } catch (error) {
      if (
        !controller.signal.aborted
        && lifecycleId.value === targetLifecycleId
        && selectedRunId.value === targetRunId
      ) {
        nodeSummaryError.value = managementError.describe(
          error,
          'runtimeMonitoring.graph.nodeSummaryLoadFailed',
        ).display
      }
    } finally {
      if (nodeSummaryController === controller) nodeSummaryRetrying.value = false
    }
  }

  async function pollOnce(manual = false): Promise<void> {
    if (
      !snapshot.value
      || pollRefreshing.value
      || (!manual && (!lifecycleIsActive.value || document.hidden))
    ) return
    clearPollTimer()
    pollController?.abort()
    const controller = new AbortController()
    pollController = controller
    const generation = ++pollGeneration
    const targetLifecycleId = lifecycleId.value
    const targetRunId = selectedRunId.value
    const targetSelector = snapshot.value.selector
    pollRefreshing.value = true
    pollError.value = ''
    try {
      const fullRequest = managementApi.getRuntimeMonitoringSnapshot(
        targetLifecycleId,
        undefined,
        controller.signal,
      )
      const [nextLifecycleSnapshot, nextSnapshot] = targetSelector.scope === 'lifecycle'
        ? await fullRequest.then((value) => [value, value] as const)
        : await Promise.all([
            fullRequest,
            managementApi.getRuntimeMonitoringSnapshot(
              targetLifecycleId,
              runtimeMonitoringScopeRequest(targetSelector),
              controller.signal,
            ),
          ])
      if (
        controller.signal.aborted
        || generation !== pollGeneration
        || lifecycleId.value !== targetLifecycleId
        || runtimeMonitoringSelectorKey(
          snapshot.value?.selector ?? { scope: 'lifecycle', id: null },
        ) !== runtimeMonitoringSelectorKey(targetSelector)
      ) return
      lifecycleSnapshot.value = nextLifecycleSnapshot
      snapshot.value = nextSnapshot
      if (!nextSnapshot.runs.some((run) => run.run_id === targetRunId)) {
        applyRouteSelection()
        return
      }
      await Promise.all([
        refreshSelectedRunNodes(targetLifecycleId, targetRunId, controller.signal),
        nodeDetails.refresh(),
        runDetails.refresh(),
      ])
    } catch (error) {
      if (!controller.signal.aborted && generation === pollGeneration) {
        pollError.value = managementError.describe(
          error,
          'runtimeMonitoring.polling.failed',
        ).display
      }
    } finally {
      if (generation === pollGeneration) {
        pollRefreshing.value = false
        schedulePoll()
      }
    }
  }

  function handleVisibilityChange(): void {
    if (document.hidden) {
      stopPolling()
      return
    }
    if (lifecycleIsActive.value) void pollOnce()
  }

  function applyRouteDetailSelection(): void {
    if (!selectedRun.value) return
    const nodeId = requestedNodeId.value
    if (!nodeId) {
      if (route.query.view !== undefined && !requestedRunDetailKind.value) {
        void router.replace({ query: baseRunQuery() })
        return
      }
      if (selectedNodeId.value) nodeDetails.reset()
      if (requestedRunDetailKind.value) runDetails.open(requestedRunDetailKind.value)
      else if (runDetailKind.value) runDetails.reset()
      return
    }
    runDetails.reset()
    if (!graphDocument.value) return
    const node = graphDocument.value.definition.nodes.find((item) => item.id === nodeId)
    if (!node) {
      nodeDetails.reset()
      void router.replace({ query: baseRunQuery() })
      return
    }
    nodeDetails.selectNode(node.id, node.type)
    if (route.query.view !== undefined) {
      void router.replace({ query: { ...baseRunQuery(), node_id: node.id } })
    }
  }

  async function loadRunResources(
    runId: string,
    force = false,
    restoreNodeFromRoute = true,
  ): Promise<void> {
    if (!snapshot.value?.runs.some((run) => run.run_id === runId)) return
    if (!force && selectedRunId.value === runId && resourceRunId === runId) return

    runController?.abort()
    nodeSummaryController?.abort()
    const controller = new AbortController()
    runController = controller
    const generation = ++runGeneration
    const targetLifecycleId = lifecycleId.value
    selectedRunId.value = runId
    resourceRunId = runId
    nodeDetails.reset()
    runDetails.reset()
    graphResponse.value = null
    nodeSummaryPage.value = null
    nodeSummaryError.value = ''
    nodeSummaryRetrying.value = false
    runError.value = ''
    runLoading.value = true

    try {
      const graph = await managementApi.getRuntimeMonitoringGraph(
        targetLifecycleId,
        runId,
        controller.signal,
      )
      if (!isCurrentRunRequest(generation, runId)) return
      graphResponse.value = graph
      if (!graph.graph) {
        if (restoreNodeFromRoute) {
          if (requestedNodeId.value) void router.replace({ query: baseRunQuery() })
          else applyRouteDetailSelection()
        }
        return
      }

      try {
        await refreshSelectedRunNodes(targetLifecycleId, runId, controller.signal)
      } catch (error) {
        if (!controller.signal.aborted && isCurrentRunRequest(generation, runId)) {
          nodeSummaryError.value = managementError.describe(
            error,
            'runtimeMonitoring.graph.nodeSummaryLoadFailed',
          ).display
        }
      }
      if (isCurrentRunRequest(generation, runId) && restoreNodeFromRoute) {
        applyRouteDetailSelection()
      }
    } catch (error) {
      if (!controller.signal.aborted && isCurrentRunRequest(generation, runId)) {
        runError.value = managementError.describe(
          error,
          'runtimeMonitoring.graph.loadFailed',
        ).display
        if (restoreNodeFromRoute && requestedRunDetailKind.value && !requestedNodeId.value) {
          applyRouteDetailSelection()
        }
      }
    } finally {
      if (isCurrentRunRequest(generation, runId)) runLoading.value = false
    }
  }

  function replaceInvalidRunQuery(runId: string): void {
    if (requestedRunId.value === runId) return
    void router.replace({
      query: { ...route.query, run_id: runId },
    })
  }

  function applyRouteSelection(): void {
    if (!snapshot.value) return
    const runId = selectRuntimeMonitoringRunId(snapshot.value, requestedRunId.value)
    if (!runId) {
      selectedRunId.value = ''
      return
    }
    void loadRunResources(runId)
    replaceInvalidRunQuery(runId)
  }

  async function loadRequestedScope(force = false): Promise<void> {
    const full = lifecycleSnapshot.value
    if (!full) return
    const selection = displayedScope.value
    replaceCanonicalScopeQuery(selection)
    if (
      !force
      && snapshot.value
      && runtimeMonitoringSelectorKey(snapshot.value.selector)
        === runtimeMonitoringSelectorKey(selection)
    ) {
      applyRouteSelection()
      return
    }

    stopPolling()
    scopeController?.abort()
    const controller = new AbortController()
    scopeController = controller
    const generation = ++scopeGeneration
    const targetLifecycleId = lifecycleId.value
    lifecycleLoading.value = true
    lifecycleError.value = ''
    try {
      const response = selection.scope === 'lifecycle'
        ? full
        : await managementApi.getRuntimeMonitoringSnapshot(
            targetLifecycleId,
            runtimeMonitoringScopeRequest(selection),
            controller.signal,
          )
      if (
        controller.signal.aborted
        || generation !== scopeGeneration
        || targetLifecycleId !== lifecycleId.value
      ) return
      snapshot.value = response
      pollError.value = ''
      applyRouteSelection()
    } catch (error) {
      if (!controller.signal.aborted && generation === scopeGeneration) {
        snapshot.value = null
        lifecycleError.value = managementError.describe(
          error,
          'runtimeMonitoring.snapshot.loadFailed',
        ).display
      }
    } finally {
      if (generation === scopeGeneration) {
        lifecycleLoading.value = false
        schedulePoll()
      }
    }
  }

  async function loadLifecycle(): Promise<void> {
    stopPolling()
    lifecycleController?.abort()
    scopeController?.abort()
    runController?.abort()
    nodeSummaryController?.abort()
    const controller = new AbortController()
    lifecycleController = controller
    const generation = ++lifecycleGeneration
    scopeGeneration += 1
    runGeneration += 1
    resourceRunId = ''
    lifecycleSnapshot.value = null
    snapshot.value = null
    nodeCatalog.value = []
    selectedRunId.value = ''
    graphResponse.value = null
    nodeSummaryPage.value = null
    nodeSummaryError.value = ''
    nodeSummaryRetrying.value = false
    nodeDetails.reset()
    runDetails.reset()
    lifecycleError.value = ''
    catalogError.value = ''
    runError.value = ''
    pollError.value = ''
    lifecycleLoading.value = true
    runLoading.value = false
    const targetLifecycleId = lifecycleId.value

    const [snapshotResult, catalogResult] = await Promise.allSettled([
      managementApi.getRuntimeMonitoringSnapshot(targetLifecycleId, undefined, controller.signal),
      managementApi.listWorkflowNodeCatalog(),
    ])
    if (controller.signal.aborted || generation !== lifecycleGeneration) return

    if (snapshotResult.status === 'rejected') {
      lifecycleError.value = managementError.describe(
        snapshotResult.reason,
        'runtimeMonitoring.snapshot.loadFailed',
      ).display
    } else {
      lifecycleSnapshot.value = snapshotResult.value
    }
    if (catalogResult.status === 'rejected') {
      catalogError.value = managementError.describe(
        catalogResult.reason,
        'runtimeMonitoring.graph.catalogLoadFailed',
      ).display
    } else {
      nodeCatalog.value = catalogResult.value
    }
    if (!lifecycleSnapshot.value) {
      lifecycleLoading.value = false
      return
    }
    await loadRequestedScope(true)
  }

  function selectRun(runId: string): void {
    if (!snapshot.value?.runs.some((run) => run.run_id === runId)) return
    if (runId === selectedRunId.value) return
    void loadRunResources(runId, false, false)
    if (requestedRunId.value !== runId) {
      void router.push({ query: baseRunQuery(runId) })
    }
  }

  function selectNode(nodeId: string): void {
    const node = graphDocument.value?.definition.nodes.find((item) => item.id === nodeId)
    if (!node) return
    runDetails.reset()
    nodeDetails.selectNode(node.id, node.type)
    if (requestedNodeId.value !== nodeId) {
      void router.push({ query: { ...baseRunQuery(), node_id: nodeId } })
    }
  }

  function closeNodeAttempts(): void {
    nodeDetails.reset()
    if (requestedNodeId.value) void router.push({ query: baseRunQuery() })
  }

  function openRunDetails(kind: RuntimeMonitoringRunDetailKind): void {
    if (!selectedRun.value) return
    nodeDetails.reset()
    runDetails.open(kind)
    if (requestedRunDetailKind.value !== kind || requestedNodeId.value) {
      void router.push({ query: { ...baseRunQuery(), view: kind } })
    }
  }

  function closeRunDetails(): void {
    runDetails.reset()
    if (requestedRunDetailKind.value) void router.push({ query: baseRunQuery() })
  }

  function retryRun(): void {
    if (selectedRunId.value) void loadRunResources(selectedRunId.value, true)
  }

  watch(lifecycleId, () => { void loadLifecycle() }, { immediate: true })
  watch(requestedScopeRouteKey, () => {
    if (lifecycleSnapshot.value && !lifecycleLoading.value) void loadRequestedScope()
  })
  watch(requestedRunId, () => {
    if (requestedScope.value !== 'run' && !lifecycleLoading.value) applyRouteSelection()
  })
  watch([requestedNodeId, requestedRunDetailKind], applyRouteDetailSelection)

  onMounted(() => {
    document.addEventListener('visibilitychange', handleVisibilityChange)
  })

  onUnmounted(() => {
    lifecycleGeneration += 1
    scopeGeneration += 1
    runGeneration += 1
    lifecycleController?.abort()
    scopeController?.abort()
    runController?.abort()
    nodeSummaryController?.abort()
    stopPolling()
    document.removeEventListener('visibilitychange', handleVisibilityChange)
    nodeDetails.reset()
    runDetails.reset()
  })

  return {
    lifecycleId,
    lifecycleSnapshot,
    snapshot,
    nodeCatalog,
    selectedRunId,
    graphResponse,
    nodeSummaryPage,
    nodeSummaryError,
    nodeSummaryRetrying,
    lifecycleLoading,
    runLoading,
    lifecycleError,
    catalogError,
    runError,
    pollRefreshing,
    pollError,
    nodeDetails,
    runDetails,
    selectedNodeId,
    selectedInvocationId,
    nodeAttemptPage,
    nodeAttemptLoading,
    nodeAttemptError,
    agentArtifact,
    agentArtifactLoading,
    agentArtifactError,
    agentProtocol,
    agentProtocolLoading,
    agentProtocolError,
    commandObservations,
    commandLoading,
    commandError,
    runDetailKind,
    runProtocol,
    runProtocolLoading,
    runProtocolError,
    runModels,
    runModelsLoading,
    runModelsError,
    runState,
    runStateLoading,
    runStateError,
    runRoots,
    selectedRun,
    graphDocument,
    selectedNode,
    selectedNodeSummary,
    lifecycleIsActive,
    displayedScope,
    scopeSelectorId,
    scopeWorkflows,
    localTime,
    availabilityLabel,
    graphEmptyMessage,
    selectScope,
    selectScopeTarget,
    pollOnce,
    loadLifecycle,
    selectRun,
    selectNode,
    closeNodeAttempts,
    openRunDetails,
    closeRunDetails,
    retryRun,
    retryNodeSummaries,
  }
}
