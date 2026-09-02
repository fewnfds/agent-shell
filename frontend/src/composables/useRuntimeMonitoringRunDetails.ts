import { ref, type Ref } from 'vue'

import {
  managementApi,
  type RuntimeMonitoringModelRequestPage,
  type RuntimeMonitoringProtocolEvent,
  type RuntimeMonitoringProtocolEventSequence,
  type RuntimeMonitoringStateResponse,
} from '@/api'
import { useManagementError } from '@/composables/useManagementError'

export type RuntimeMonitoringRunDetailKind = 'protocol' | 'models' | 'state'

export function useRuntimeMonitoringRunDetails(
  lifecycleId: Readonly<Ref<string>>,
  runId: Readonly<Ref<string>>,
) {
  const managementError = useManagementError()
  const activeKind = ref<RuntimeMonitoringRunDetailKind | null>(null)
  const protocol = ref<RuntimeMonitoringProtocolEventSequence | null>(null)
  const protocolLoading = ref(false)
  const protocolError = ref('')
  const models = ref<RuntimeMonitoringModelRequestPage | null>(null)
  const modelsLoading = ref(false)
  const modelsError = ref('')
  const modelPageSize = ref(20)
  const state = ref<RuntimeMonitoringStateResponse | null>(null)
  const stateLoading = ref(false)
  const stateError = ref('')

  let protocolGeneration = 0
  let modelsGeneration = 0
  let stateGeneration = 0
  let protocolController: AbortController | null = null
  let modelsController: AbortController | null = null
  let stateController: AbortController | null = null

  function reset(): void {
    protocolController?.abort()
    modelsController?.abort()
    stateController?.abort()
    protocolGeneration += 1
    modelsGeneration += 1
    stateGeneration += 1
    activeKind.value = null
    protocol.value = null
    protocolLoading.value = false
    protocolError.value = ''
    models.value = null
    modelsLoading.value = false
    modelsError.value = ''
    state.value = null
    stateLoading.value = false
    stateError.value = ''
  }

  function isCurrent(targetRunId: string, kind: RuntimeMonitoringRunDetailKind): boolean {
    return runId.value === targetRunId && activeKind.value === kind
  }

  async function collectProtocolEvents(
    targetLifecycleId: string,
    targetRunId: string,
    afterSequence: number,
    signal: AbortSignal,
  ): Promise<{
    availability: RuntimeMonitoringProtocolEventSequence['availability']
    readAt: string
    items: RuntimeMonitoringProtocolEvent[]
    nextSequence: number
    limit: number
  }> {
    const items: RuntimeMonitoringProtocolEvent[] = []
    let cursor = afterSequence
    let availability: RuntimeMonitoringProtocolEventSequence['availability']
    let readAt: string
    let limit: number
    do {
      const response = await managementApi.listRuntimeMonitoringProtocolEvents(
        targetLifecycleId,
        targetRunId,
        { after_sequence: cursor },
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

  async function loadProtocol(background = false): Promise<void> {
    if (background && protocolLoading.value) return
    protocolController?.abort()
    const controller = new AbortController()
    protocolController = controller
    const generation = ++protocolGeneration
    const targetLifecycleId = lifecycleId.value
    const targetRunId = runId.value
    const afterSequence = background ? protocol.value?.next_after_sequence ?? 0 : 0
    if (!background) {
      protocol.value = null
      protocolLoading.value = true
    }
    protocolError.value = ''
    try {
      const result = await collectProtocolEvents(
        targetLifecycleId,
        targetRunId,
        afterSequence,
        controller.signal,
      )
      if (generation === protocolGeneration && isCurrent(targetRunId, 'protocol')) {
        const existing = background ? protocol.value?.items ?? [] : []
        protocol.value = {
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
        && isCurrent(targetRunId, 'protocol')
      ) {
        protocolError.value = managementError.describe(
          error,
          'runtimeMonitoring.protocol.loadFailed',
        ).display
      }
    } finally {
      if (generation === protocolGeneration) protocolLoading.value = false
    }
  }

  async function loadModels(
    page = models.value?.page ?? 1,
    pageSize = modelPageSize.value,
    background = false,
  ): Promise<void> {
    if (background && modelsLoading.value) return
    modelsController?.abort()
    const controller = new AbortController()
    modelsController = controller
    const generation = ++modelsGeneration
    const targetLifecycleId = lifecycleId.value
    const targetRunId = runId.value
    modelPageSize.value = pageSize
    if (!background) {
      models.value = null
      modelsLoading.value = true
    }
    modelsError.value = ''
    try {
      const response = await managementApi.listRuntimeMonitoringModelRequests(
        targetLifecycleId,
        targetRunId,
        { page, page_size: pageSize },
        controller.signal,
      )
      if (generation === modelsGeneration && isCurrent(targetRunId, 'models')) {
        models.value = response
      }
    } catch (error) {
      if (
        !controller.signal.aborted
        && generation === modelsGeneration
        && isCurrent(targetRunId, 'models')
      ) {
        modelsError.value = managementError.describe(
          error,
          'runtimeMonitoring.models.loadFailed',
        ).display
      }
    } finally {
      if (generation === modelsGeneration) modelsLoading.value = false
    }
  }

  async function loadState(background = false): Promise<void> {
    if (background && stateLoading.value) return
    stateController?.abort()
    const controller = new AbortController()
    stateController = controller
    const generation = ++stateGeneration
    const targetLifecycleId = lifecycleId.value
    const targetRunId = runId.value
    if (!background) {
      state.value = null
      stateLoading.value = true
    }
    stateError.value = ''
    try {
      const response = await managementApi.getRuntimeMonitoringState(
        targetLifecycleId,
        targetRunId,
        controller.signal,
      )
      if (generation === stateGeneration && isCurrent(targetRunId, 'state')) {
        state.value = response
      }
    } catch (error) {
      if (
        !controller.signal.aborted
        && generation === stateGeneration
        && isCurrent(targetRunId, 'state')
      ) {
        stateError.value = managementError.describe(
          error,
          'runtimeMonitoring.state.loadFailed',
        ).display
      }
    } finally {
      if (generation === stateGeneration) stateLoading.value = false
    }
  }

  function open(kind: RuntimeMonitoringRunDetailKind): void {
    if (!runId.value) return
    activeKind.value = kind
    if (kind === 'protocol' && !protocol.value && !protocolLoading.value) void loadProtocol()
    if (kind === 'models' && !models.value && !modelsLoading.value) void loadModels(1)
    if (kind === 'state' && !state.value && !stateLoading.value) void loadState()
  }

  function changeModelPage(page: number): void {
    void loadModels(page, modelPageSize.value)
  }

  function changeModelPageSize(pageSize: number): void {
    void loadModels(1, pageSize)
  }

  async function refresh(): Promise<void> {
    if (activeKind.value === 'protocol') await loadProtocol(true)
    if (activeKind.value === 'models') await loadModels(undefined, undefined, true)
  }

  return {
    activeKind,
    protocol,
    protocolLoading,
    protocolError,
    models,
    modelsLoading,
    modelsError,
    state,
    stateLoading,
    stateError,
    reset,
    open,
    close: reset,
    changeModelPage,
    changeModelPageSize,
    retryProtocol: () => { void loadProtocol(Boolean(protocol.value)) },
    retryModels: () => {
      void loadModels(models.value?.page, modelPageSize.value, Boolean(models.value))
    },
    retryState: () => { void loadState(Boolean(state.value)) },
    refresh,
  }
}
