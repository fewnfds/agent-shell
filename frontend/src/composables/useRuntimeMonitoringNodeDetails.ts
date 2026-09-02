import { ref, type Ref } from 'vue'

import {
  managementApi,
  type RuntimeMonitoringAgentInvocationResponse,
  type RuntimeMonitoringCommandObservation,
  type RuntimeMonitoringCommandObservationSequence,
  type RuntimeMonitoringNodeAttemptPage,
  type RuntimeMonitoringProtocolEvent,
  type RuntimeMonitoringProtocolEventSequence,
  type WorkflowNodeType,
} from '@/api'
import { useManagementError } from '@/composables/useManagementError'

interface SequenceResult<T> {
  availability: RuntimeMonitoringProtocolEventSequence['availability']
  readAt: string
  items: T[]
  nextSequence: number
  limit: number
}

export function useRuntimeMonitoringNodeDetails(
  lifecycleId: Readonly<Ref<string>>,
  runId: Readonly<Ref<string>>,
) {
  const managementError = useManagementError()
  const selectedNodeId = ref('')
  const selectedNodeType = ref<WorkflowNodeType | null>(null)
  const selectedInvocationId = ref('')
  const attemptPage = ref<RuntimeMonitoringNodeAttemptPage | null>(null)
  const attemptPageSize = ref(20)
  const attemptLoading = ref(false)
  const attemptError = ref('')
  const agentArtifact = ref<RuntimeMonitoringAgentInvocationResponse | null>(null)
  const agentArtifactLoading = ref(false)
  const agentArtifactError = ref('')
  const agentProtocol = ref<RuntimeMonitoringProtocolEventSequence | null>(null)
  const agentProtocolLoading = ref(false)
  const agentProtocolError = ref('')
  const commandObservations = ref<RuntimeMonitoringCommandObservationSequence | null>(null)
  const commandLoading = ref(false)
  const commandError = ref('')

  let attemptGeneration = 0
  let artifactGeneration = 0
  let protocolGeneration = 0
  let commandGeneration = 0
  let attemptController: AbortController | null = null
  let artifactController: AbortController | null = null
  let protocolController: AbortController | null = null
  let commandController: AbortController | null = null
  let attemptRequestKey = ''

  function currentIdentity(nodeId: string, targetRunId: string): boolean {
    return selectedNodeId.value === nodeId && runId.value === targetRunId
  }

  function clearSpecializedDetails(): void {
    artifactController?.abort()
    protocolController?.abort()
    commandController?.abort()
    artifactGeneration += 1
    protocolGeneration += 1
    commandGeneration += 1
    selectedInvocationId.value = ''
    agentArtifact.value = null
    agentArtifactLoading.value = false
    agentArtifactError.value = ''
    agentProtocol.value = null
    agentProtocolLoading.value = false
    agentProtocolError.value = ''
    commandObservations.value = null
    commandLoading.value = false
    commandError.value = ''
  }

  function reset(): void {
    attemptController?.abort()
    attemptGeneration += 1
    attemptRequestKey = ''
    selectedNodeId.value = ''
    selectedNodeType.value = null
    attemptPage.value = null
    attemptLoading.value = false
    attemptError.value = ''
    clearSpecializedDetails()
  }

  async function collectProtocolEvents(
    targetLifecycleId: string,
    targetRunId: string,
    nodeId: string,
    invocationId: string,
    afterSequence: number,
    signal: AbortSignal,
  ): Promise<SequenceResult<RuntimeMonitoringProtocolEvent>> {
    const items: RuntimeMonitoringProtocolEvent[] = []
    let cursor = afterSequence
    let availability: RuntimeMonitoringProtocolEventSequence['availability']
    let readAt: string
    let limit: number
    do {
      const response = await managementApi.listRuntimeMonitoringProtocolEvents(
        targetLifecycleId,
        targetRunId,
        {
          after_sequence: cursor,
          node_id: nodeId,
          invocation_id: invocationId,
        },
        signal,
      )
      availability = response.availability
      readAt = response.read_at
      limit = response.limit
      items.push(...response.items)
      if (response.remaining <= 0) {
        return {
          availability,
          readAt,
          items,
          nextSequence: response.next_after_sequence,
          limit,
        }
      }
      if (response.next_after_sequence <= cursor) {
        throw new Error('Protocol event cursor did not advance.')
      }
      cursor = response.next_after_sequence
    } while (!signal.aborted)
    throw new DOMException('Request aborted', 'AbortError')
  }

  async function collectCommandObservations(
    targetLifecycleId: string,
    targetRunId: string,
    nodeId: string,
    afterSequence: number,
    signal: AbortSignal,
  ): Promise<SequenceResult<RuntimeMonitoringCommandObservation>> {
    const items: RuntimeMonitoringCommandObservation[] = []
    let cursor = afterSequence
    let availability: RuntimeMonitoringCommandObservationSequence['availability']
    let readAt: string
    let limit: number
    do {
      const response = await managementApi.listRuntimeMonitoringCommandObservations(
        targetLifecycleId,
        targetRunId,
        { after_sequence: cursor, node_id: nodeId },
        signal,
      )
      availability = response.availability
      readAt = response.read_at
      limit = response.limit
      items.push(...response.items)
      if (response.remaining <= 0) {
        return {
          availability,
          readAt,
          items,
          nextSequence: response.next_after_sequence,
          limit,
        }
      }
      if (response.next_after_sequence <= cursor) {
        throw new Error('Command observation cursor did not advance.')
      }
      cursor = response.next_after_sequence
    } while (!signal.aborted)
    throw new DOMException('Request aborted', 'AbortError')
  }

  async function loadAgentArtifact(background = false): Promise<void> {
    const nodeId = selectedNodeId.value
    const invocationId = selectedInvocationId.value
    if (selectedNodeType.value !== 'agent' || !nodeId || !invocationId) return
    if (background && agentArtifactLoading.value) return
    artifactController?.abort()
    const controller = new AbortController()
    artifactController = controller
    const generation = ++artifactGeneration
    const targetLifecycleId = lifecycleId.value
    const targetRunId = runId.value
    if (!background) {
      agentArtifact.value = null
      agentArtifactLoading.value = true
    }
    agentArtifactError.value = ''
    try {
      const response = await managementApi.getRuntimeMonitoringAgentInvocation(
        targetLifecycleId,
        targetRunId,
        invocationId,
        controller.signal,
      )
      if (
        generation === artifactGeneration
        && currentIdentity(nodeId, targetRunId)
        && selectedInvocationId.value === invocationId
      ) {
        agentArtifact.value = response
      }
    } catch (error) {
      if (
        !controller.signal.aborted
        && generation === artifactGeneration
        && currentIdentity(nodeId, targetRunId)
        && selectedInvocationId.value === invocationId
      ) {
        agentArtifactError.value = managementError.describe(
          error,
          'runtimeMonitoring.agent.loadArtifactFailed',
        ).display
      }
    } finally {
      if (generation === artifactGeneration) agentArtifactLoading.value = false
    }
  }

  async function loadAgentProtocol(background = false): Promise<void> {
    const nodeId = selectedNodeId.value
    const invocationId = selectedInvocationId.value
    if (selectedNodeType.value !== 'agent' || !nodeId || !invocationId) return
    if (background && agentProtocolLoading.value) return
    protocolController?.abort()
    const controller = new AbortController()
    protocolController = controller
    const generation = ++protocolGeneration
    const targetLifecycleId = lifecycleId.value
    const targetRunId = runId.value
    const afterSequence = background ? agentProtocol.value?.next_after_sequence ?? 0 : 0
    if (!background) {
      agentProtocol.value = null
      agentProtocolLoading.value = true
    }
    agentProtocolError.value = ''
    try {
      const result = await collectProtocolEvents(
        targetLifecycleId,
        targetRunId,
        nodeId,
        invocationId,
        afterSequence,
        controller.signal,
      )
      if (
        generation === protocolGeneration
        && currentIdentity(nodeId, targetRunId)
        && selectedInvocationId.value === invocationId
      ) {
        const existing = background ? agentProtocol.value?.items ?? [] : []
        agentProtocol.value = {
          availability: result.availability,
          read_at: result.readAt,
          items: [...existing, ...result.items],
          after_sequence: 0,
          next_after_sequence: result.nextSequence,
          limit: result.limit,
          remaining: 0,
        }
      }
    } catch (error) {
      if (
        !controller.signal.aborted
        && generation === protocolGeneration
        && currentIdentity(nodeId, targetRunId)
        && selectedInvocationId.value === invocationId
      ) {
        agentProtocolError.value = managementError.describe(
          error,
          'runtimeMonitoring.agent.loadProtocolFailed',
        ).display
      }
    } finally {
      if (generation === protocolGeneration) agentProtocolLoading.value = false
    }
  }

  async function loadCommandObservations(background = false): Promise<void> {
    const nodeId = selectedNodeId.value
    if (selectedNodeType.value !== 'command' || !nodeId) return
    if (background && commandLoading.value) return
    commandController?.abort()
    const controller = new AbortController()
    commandController = controller
    const generation = ++commandGeneration
    const targetLifecycleId = lifecycleId.value
    const targetRunId = runId.value
    const afterSequence = background ? commandObservations.value?.next_after_sequence ?? 0 : 0
    if (!background) {
      commandObservations.value = null
      commandLoading.value = true
    }
    commandError.value = ''
    try {
      const result = await collectCommandObservations(
        targetLifecycleId,
        targetRunId,
        nodeId,
        afterSequence,
        controller.signal,
      )
      if (generation === commandGeneration && currentIdentity(nodeId, targetRunId)) {
        const existing = background ? commandObservations.value?.items ?? [] : []
        commandObservations.value = {
          availability: result.availability,
          read_at: result.readAt,
          items: [...existing, ...result.items],
          after_sequence: 0,
          next_after_sequence: result.nextSequence,
          limit: result.limit,
          remaining: 0,
        }
      }
    } catch (error) {
      if (
        !controller.signal.aborted
        && generation === commandGeneration
        && currentIdentity(nodeId, targetRunId)
      ) {
        commandError.value = managementError.describe(
          error,
          'runtimeMonitoring.command.loadFailed',
        ).display
      }
    } finally {
      if (generation === commandGeneration) commandLoading.value = false
    }
  }

  function loadSelectedInvocation(): void {
    if (selectedNodeType.value !== 'agent' || !selectedInvocationId.value) return
    void loadAgentArtifact()
    void loadAgentProtocol()
  }

  function applyAttemptPage(
    response: RuntimeMonitoringNodeAttemptPage,
    preserveInvocation: boolean,
  ): void {
    attemptPage.value = response
    const stillVisible = preserveInvocation && response.items.some((item) => (
      item.invocation_id === selectedInvocationId.value
    ))
    if (!stillVisible) {
      selectedInvocationId.value = response.items.at(-1)?.invocation_id ?? ''
    }
  }

  async function loadAttempts(
    nodeId: string,
    nodeType: WorkflowNodeType,
    page = 1,
    pageSize = attemptPageSize.value,
    options: {
      force?: boolean
      preferLatest?: boolean
      preserveInvocation?: boolean
      background?: boolean
      refreshSpecialized?: boolean
    } = {},
  ): Promise<void> {
    const {
      force = false,
      preferLatest = false,
      preserveInvocation = false,
      background = false,
      refreshSpecialized = true,
    } = options
    if (background && attemptLoading.value) return
    const targetLifecycleId = lifecycleId.value
    const targetRunId = runId.value
    const requestKey = `${targetRunId}:${nodeId}:${page}:${pageSize}`
    if (!force && attemptRequestKey === requestKey) return

    const nodeChanged = selectedNodeId.value !== nodeId || selectedNodeType.value !== nodeType
    if (nodeChanged) clearSpecializedDetails()
    attemptController?.abort()
    const controller = new AbortController()
    attemptController = controller
    const generation = ++attemptGeneration
    attemptRequestKey = requestKey
    selectedNodeId.value = nodeId
    selectedNodeType.value = nodeType
    attemptPageSize.value = pageSize
    if (!background) {
      attemptPage.value = null
      attemptLoading.value = true
    }
    attemptError.value = ''

    try {
      let response = await managementApi.listRuntimeMonitoringNodeAttempts(
        targetLifecycleId,
        targetRunId,
        nodeId,
        { page, page_size: pageSize },
        controller.signal,
      )
      if (preferLatest && response.total_pages > response.page) {
        response = await managementApi.listRuntimeMonitoringNodeAttempts(
          targetLifecycleId,
          targetRunId,
          nodeId,
          { page: response.total_pages, page_size: pageSize },
          controller.signal,
        )
      }
      if (generation !== attemptGeneration || !currentIdentity(nodeId, targetRunId)) return
      attemptRequestKey = `${targetRunId}:${nodeId}:${response.page}:${pageSize}`
      applyAttemptPage(response, preserveInvocation)
      if (refreshSpecialized) {
        if (nodeType === 'agent') loadSelectedInvocation()
        if (nodeType === 'command' && !commandObservations.value && !commandLoading.value) {
          void loadCommandObservations()
        }
      }
    } catch (error) {
      if (
        !controller.signal.aborted
        && generation === attemptGeneration
        && currentIdentity(nodeId, targetRunId)
      ) {
        attemptError.value = managementError.describe(
          error,
          'runtimeMonitoring.nodeAttempts.loadFailed',
        ).display
      }
    } finally {
      if (generation === attemptGeneration) attemptLoading.value = false
    }
  }

  function selectNode(nodeId: string, nodeType: WorkflowNodeType): void {
    if (
      selectedNodeId.value === nodeId
      && selectedNodeType.value === nodeType
      && (attemptLoading.value || attemptPage.value !== null || Boolean(attemptError.value))
    ) return
    void loadAttempts(nodeId, nodeType, 1, attemptPageSize.value, {
      force: true,
      preferLatest: true,
    })
    if (nodeType === 'command') void loadCommandObservations()
  }

  function selectInvocation(invocationId: string): void {
    if (
      selectedNodeType.value !== 'agent'
      || !attemptPage.value?.items.some((item) => item.invocation_id === invocationId)
      || selectedInvocationId.value === invocationId
    ) return
    selectedInvocationId.value = invocationId
    loadSelectedInvocation()
  }

  function changePage(page: number): void {
    if (!selectedNodeId.value || !selectedNodeType.value) return
    void loadAttempts(
      selectedNodeId.value,
      selectedNodeType.value,
      page,
      attemptPageSize.value,
      { force: true, preserveInvocation: true },
    )
  }

  function changePageSize(pageSize: number): void {
    if (!selectedNodeId.value || !selectedNodeType.value) return
    void loadAttempts(selectedNodeId.value, selectedNodeType.value, 1, pageSize, {
      force: true,
      preferLatest: true,
    })
  }

  function viewLatest(): void {
    if (!selectedNodeId.value || !selectedNodeType.value) return
    void loadAttempts(
      selectedNodeId.value,
      selectedNodeType.value,
      1,
      attemptPageSize.value,
      { force: true, preferLatest: true },
    )
  }

  function retryAttempts(): void {
    if (!selectedNodeId.value || !selectedNodeType.value) return
    void loadAttempts(
      selectedNodeId.value,
      selectedNodeType.value,
      attemptPage.value?.page ?? 1,
      attemptPageSize.value,
      {
        force: true,
        preserveInvocation: true,
        background: Boolean(attemptPage.value),
      },
    )
  }

  async function refresh(): Promise<void> {
    if (!selectedNodeId.value || !selectedNodeType.value) return
    const jobs: Promise<void>[] = [loadAttempts(
      selectedNodeId.value,
      selectedNodeType.value,
      attemptPage.value?.page ?? 1,
      attemptPageSize.value,
      {
        force: true,
        preserveInvocation: true,
        background: true,
        refreshSpecialized: false,
      },
    )]
    if (selectedNodeType.value === 'agent' && selectedInvocationId.value) {
      jobs.push(loadAgentProtocol(true))
      if (agentArtifact.value?.availability !== 'available') jobs.push(loadAgentArtifact(true))
    }
    if (selectedNodeType.value === 'command') jobs.push(loadCommandObservations(true))
    await Promise.all(jobs)
  }

  return {
    selectedNodeId,
    selectedNodeType,
    selectedInvocationId,
    attemptPage,
    attemptPageSize,
    attemptLoading,
    attemptError,
    agentArtifact,
    agentArtifactLoading,
    agentArtifactError,
    agentProtocol,
    agentProtocolLoading,
    agentProtocolError,
    commandObservations,
    commandLoading,
    commandError,
    reset,
    selectNode,
    selectInvocation,
    changePage,
    changePageSize,
    viewLatest,
    retryAttempts,
    retryAgentArtifact: () => { void loadAgentArtifact(Boolean(agentArtifact.value)) },
    retryAgentProtocol: () => { void loadAgentProtocol(Boolean(agentProtocol.value)) },
    retryCommand: () => { void loadCommandObservations(Boolean(commandObservations.value)) },
    refresh,
  }
}
