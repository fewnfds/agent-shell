<script setup lang="ts">
import { LteAlert } from '@adminlte/vue'
import type { CSSProperties } from 'vue'
import { computed, onMounted, onUnmounted, ref, watch, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import {
  managementApi,
  type LangGraphGraphResponse,
  type LangGraphLifecycleSnapshot,
  type LangGraphLifecycleStore,
  type LangGraphRunObservation,
  type LangGraphStateResponse,
  type LangGraphThreadObservation,
} from '@/api'
import PageShell from '@/components/PageShell.vue'
import AgentThreadView from '@/components/runtime-monitoring/AgentThreadView.vue'
import {
  monitoringPrimaryRun,
  monitoringThreadActive,
} from '@/components/runtime-monitoring/presentation'
import RuntimeDataInspector from '@/components/runtime-monitoring/RuntimeDataInspector.vue'
import RuntimeRunTrack from '@/components/runtime-monitoring/RuntimeRunTrack.vue'
import RuntimeThreadIndex from '@/components/runtime-monitoring/RuntimeThreadIndex.vue'
import WorkflowRuntimeView from '@/components/runtime-monitoring/WorkflowRuntimeView.vue'
import { useManagementError } from '@/composables/useManagementError'
import { readBrowserStorage, writeBrowserStorage } from '@/browserStorage'

const LIVE_REFRESH_MILLISECONDS = 3000
const COLUMN_STORAGE_KEY = 'agent-shell.runtime-monitoring.columns.v1'
const DEFAULT_THREADS_WIDTH = 288
const DEFAULT_INSPECTOR_WIDTH = 384
const MIN_THREADS_WIDTH = 176
const MIN_PRIMARY_WIDTH = 256
const MIN_INSPECTOR_WIDTH = 208
const RESIZER_WIDTH = 8
const KEYBOARD_RESIZE_STEP = 16
const UNMEASURED_MAX_WIDTH = 4096

interface ColumnPreferences {
  threads: number
  inspector: number
}

interface ActiveResize {
  target: 'threads' | 'inspector'
  pointerId: number
  startX: number
  startWidth: number
}

function finitePositive(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0
}

function readColumnPreferences(): ColumnPreferences {
  const stored = readBrowserStorage(COLUMN_STORAGE_KEY)
  if (!stored) {
    return { threads: DEFAULT_THREADS_WIDTH, inspector: DEFAULT_INSPECTOR_WIDTH }
  }
  try {
    const parsed = JSON.parse(stored) as Partial<ColumnPreferences>
    return {
      threads: finitePositive(parsed.threads) ? parsed.threads : DEFAULT_THREADS_WIDTH,
      inspector: finitePositive(parsed.inspector) ? parsed.inspector : DEFAULT_INSPECTOR_WIDTH,
    }
  }
  catch {
    return { threads: DEFAULT_THREADS_WIDTH, inspector: DEFAULT_INSPECTOR_WIDTH }
  }
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), Math.max(minimum, maximum))
}

const { t } = useI18n()
const managementError = useManagementError()
const route = useRoute()
const lifecycleId = computed(() => String(route.params.lifecycleId || ''))
// The snapshot carries recursive `JsonValue` payloads; letting Vue infer the
// unwrapped type here exceeds TypeScript's instantiation depth. Asserting the
// declared type keeps the deep reactivity `ref` already provides at runtime.
const snapshot = ref<LangGraphLifecycleSnapshot | null>(null) as Ref<LangGraphLifecycleSnapshot | null>
const store = ref<LangGraphLifecycleStore | null>(null)
const selectedThreadId = ref('')
const selectedRunId = ref('')
const graph = ref<LangGraphGraphResponse | null>(null)
const state = ref<LangGraphStateResponse | null>(null)
const loading = ref(false)
const detailLoading = ref(false)
const error = ref('')
const detailError = ref('')
const workbench = ref<HTMLElement | null>(null)
const workbenchWidth = ref(0)
const columnPreferences = ref<ColumnPreferences>(readColumnPreferences())
const activeResize = ref<ActiveResize | null>(null)
let refreshTimer: ReturnType<typeof setInterval> | undefined
let workbenchResizeObserver: ResizeObserver | undefined
let lifecycleGeneration = 0
let detailGeneration = 0
let refreshGeneration = 0
let refreshing = false

const selectedThread = computed<LangGraphThreadObservation | null>(() => (
  snapshot.value?.threads.find((thread) => thread.thread_id === selectedThreadId.value) ?? null
))
const selectedRunObservation = computed<LangGraphRunObservation | null>(() => (
  selectedThread.value?.runs.find((run) => run.run_id === selectedRunId.value) ?? null
))
const selectedRun = computed(() => selectedRunObservation.value?.run ?? null)
const selectedRelation = computed(() => selectedRunObservation.value?.relation ?? null)
const selectedGraphKind = computed<'agent' | 'workflow' | null>(() => {
  if (selectedRelation.value) return selectedRelation.value.graph_kind
  const kind = selectedRun.value?.metadata.graph_kind
  return kind === 'agent' || kind === 'workflow' ? kind : null
})
const selectedAssistantId = computed(() => (
  selectedRelation.value?.assistant_id ?? selectedRun.value?.assistant_id ?? ''
))
const selectedThreadAvailable = computed(() => selectedThread.value?.thread !== null)
const lifecycleActive = computed(() => (
  snapshot.value?.status === 'pending' || snapshot.value?.status === 'running'
))
const maximumThreadsWidth = computed(() => (
  workbenchWidth.value > 0
    ? Math.max(
        MIN_THREADS_WIDTH,
        workbenchWidth.value
          - RESIZER_WIDTH * 2
          - MIN_PRIMARY_WIDTH
          - MIN_INSPECTOR_WIDTH,
      )
    : UNMEASURED_MAX_WIDTH
))
const threadsWidth = computed(() => clamp(
  columnPreferences.value.threads,
  MIN_THREADS_WIDTH,
  maximumThreadsWidth.value,
))
const detailWidth = computed(() => (
  workbenchWidth.value > 0
    ? workbenchWidth.value - threadsWidth.value - RESIZER_WIDTH
    : 0
))
const maximumInspectorWidth = computed(() => (
  detailWidth.value > 0
    ? Math.max(
        MIN_INSPECTOR_WIDTH,
        detailWidth.value - RESIZER_WIDTH - MIN_PRIMARY_WIDTH,
      )
    : UNMEASURED_MAX_WIDTH
))
const inspectorWidth = computed(() => clamp(
  columnPreferences.value.inspector,
  MIN_INSPECTOR_WIDTH,
  maximumInspectorWidth.value,
))
const columnStyles = computed<CSSProperties>(() => ({
  '--runtime-threads-width': `${threadsWidth.value}px`,
  '--runtime-inspector-width': `${inspectorWidth.value}px`,
} as CSSProperties))

function persistColumnPreferences(): void {
  writeBrowserStorage(COLUMN_STORAGE_KEY, JSON.stringify(columnPreferences.value))
}

function syncWorkbenchWidth(): void {
  workbenchWidth.value = workbench.value?.clientWidth ?? 0
}

function updateColumnWidth(target: ActiveResize['target'], requestedWidth: number): void {
  if (target === 'threads') {
    columnPreferences.value = {
      ...columnPreferences.value,
      threads: clamp(requestedWidth, MIN_THREADS_WIDTH, maximumThreadsWidth.value),
    }
    return
  }
  columnPreferences.value = {
    ...columnPreferences.value,
    inspector: clamp(requestedWidth, MIN_INSPECTOR_WIDTH, maximumInspectorWidth.value),
  }
}

function resizeColumns(event: PointerEvent): void {
  const resize = activeResize.value
  if (!resize || resize.pointerId !== event.pointerId) return
  const delta = event.clientX - resize.startX
  updateColumnWidth(
    resize.target,
    resize.target === 'threads' ? resize.startWidth + delta : resize.startWidth - delta,
  )
}

function finishColumnResize(event?: PointerEvent): void {
  if (event && activeResize.value?.pointerId !== event.pointerId) return
  if (activeResize.value) persistColumnPreferences()
  activeResize.value = null
  window.removeEventListener('pointermove', resizeColumns)
  window.removeEventListener('pointerup', finishColumnResize)
  window.removeEventListener('pointercancel', finishColumnResize)
}

function startColumnResize(target: ActiveResize['target'], event: PointerEvent): void {
  syncWorkbenchWidth()
  activeResize.value = {
    target,
    pointerId: event.pointerId,
    startX: event.clientX,
    startWidth: target === 'threads' ? threadsWidth.value : inspectorWidth.value,
  }
  window.addEventListener('pointermove', resizeColumns)
  window.addEventListener('pointerup', finishColumnResize)
  window.addEventListener('pointercancel', finishColumnResize)
  event.preventDefault()
}

function resizeColumnWithKeyboard(target: ActiveResize['target'], event: KeyboardEvent): void {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
  syncWorkbenchWidth()
  const direction = event.key === 'ArrowRight' ? 1 : -1
  const currentWidth = target === 'threads' ? threadsWidth.value : inspectorWidth.value
  updateColumnWidth(
    target,
    currentWidth + KEYBOARD_RESIZE_STEP * (target === 'threads' ? direction : -direction),
  )
  persistColumnPreferences()
  event.preventDefault()
}

function selectThread(thread: LangGraphThreadObservation): void {
  selectedThreadId.value = thread.thread_id
  selectedRunId.value = monitoringPrimaryRun(thread)?.run_id ?? ''
}

function keepOrSelect(snapshotValue: LangGraphLifecycleSnapshot): void {
  const currentThread = snapshotValue.threads.find((thread) => (
    thread.thread_id === selectedThreadId.value
  ))
  if (currentThread) {
    if (!currentThread.runs.some((run) => run.run_id === selectedRunId.value)) {
      selectedRunId.value = monitoringPrimaryRun(currentThread)?.run_id ?? ''
    }
    return
  }

  const requestedRunId = typeof route.query.run_id === 'string' ? route.query.run_id : ''
  const requestedThread = snapshotValue.threads.find((thread) => (
    thread.runs.some((run) => run.run_id === requestedRunId)
  ))
  const defaultThread = requestedThread
    ?? snapshotValue.threads.find(monitoringThreadActive)
    ?? snapshotValue.threads.at(-1)
  if (!defaultThread) return
  selectedThreadId.value = defaultThread.thread_id
  selectedRunId.value = requestedRunId && requestedThread
    ? requestedRunId
    : monitoringPrimaryRun(defaultThread)?.run_id ?? ''
}

async function loadLifecycle(): Promise<void> {
  const targetLifecycleId = lifecycleId.value
  const generation = ++lifecycleGeneration
  loading.value = snapshot.value === null
  error.value = ''
  try {
    const [snapshotValue, storeValue] = await Promise.all([
      managementApi.getLangGraphLifecycleSnapshot(targetLifecycleId),
      managementApi.getLangGraphLifecycleStore(targetLifecycleId),
    ])
    if (generation !== lifecycleGeneration || targetLifecycleId !== lifecycleId.value) return
    snapshot.value = snapshotValue
    store.value = storeValue
    keepOrSelect(snapshotValue)
  }
  catch (cause) {
    if (generation === lifecycleGeneration && targetLifecycleId === lifecycleId.value) {
      error.value = managementError.describe(cause).display
    }
  }
  finally {
    if (generation === lifecycleGeneration) loading.value = false
  }
}

async function loadRunDetails(): Promise<void> {
  const runId = selectedRunId.value
  const kind = selectedGraphKind.value
  const generation = ++detailGeneration
  graph.value = null
  state.value = null
  detailError.value = ''
  if (!runId || !kind) return
  detailLoading.value = true
  try {
    const [stateValue, graphValue] = await Promise.all([
      managementApi.getLangGraphRunState(lifecycleId.value, runId),
      kind === 'workflow'
        ? managementApi.getLangGraphRunGraph(lifecycleId.value, runId)
        : Promise.resolve(null),
    ])
    if (generation !== detailGeneration) return
    state.value = stateValue
    graph.value = graphValue
    detailError.value = stateValue.error?.message ?? graphValue?.error?.message ?? ''
  }
  catch (cause) {
    if (generation === detailGeneration) {
      detailError.value = managementError.describe(cause).display
    }
  }
  finally {
    if (generation === detailGeneration) detailLoading.value = false
  }
}

async function refreshActiveFacts(): Promise<void> {
  if (!lifecycleActive.value || refreshing) return
  const targetLifecycleId = lifecycleId.value
  const generation = ++refreshGeneration
  refreshing = true
  try {
    const [snapshotValue, storeValue] = await Promise.all([
      managementApi.getLangGraphLifecycleSnapshot(targetLifecycleId),
      managementApi.getLangGraphLifecycleStore(targetLifecycleId),
    ])
    if (generation !== refreshGeneration || targetLifecycleId !== lifecycleId.value) return
    snapshot.value = snapshotValue
    store.value = storeValue
    keepOrSelect(snapshotValue)
    const runId = selectedRunId.value
    if (selectedGraphKind.value === 'workflow' && runId) {
      const stateValue = await managementApi.getLangGraphRunState(targetLifecycleId, runId)
      if (
        generation !== refreshGeneration
        || targetLifecycleId !== lifecycleId.value
        || runId !== selectedRunId.value
      ) return
      state.value = stateValue
      detailError.value = stateValue.error?.message ?? ''
    }
  }
  catch (cause) {
    if (generation === refreshGeneration && targetLifecycleId === lifecycleId.value) {
      detailError.value = managementError.describe(cause).display
    }
  }
  finally {
    if (generation === refreshGeneration) refreshing = false
  }
}

function updateAgentState(values: Record<string, unknown>): void {
  if (!selectedRunId.value || !selectedThreadId.value) return
  state.value = {
    run_id: selectedRunId.value,
    thread_id: selectedThreadId.value,
    state: { ...(state.value?.state ?? {}), values },
    error: state.value?.error ?? null,
  } as LangGraphStateResponse
}

watch(lifecycleId, () => {
  lifecycleGeneration += 1
  refreshGeneration += 1
  detailGeneration += 1
  refreshing = false
  snapshot.value = null
  store.value = null
  selectedThreadId.value = ''
  selectedRunId.value = ''
  graph.value = null
  state.value = null
  error.value = ''
  detailError.value = ''
  void loadLifecycle()
})

watch(
  () => `${selectedThreadId.value}:${selectedRunId.value}:${selectedGraphKind.value ?? ''}`,
  () => { void loadRunDetails() },
)

watch(workbench, (element) => {
  workbenchResizeObserver?.disconnect()
  workbenchResizeObserver = undefined
  if (!element) return
  syncWorkbenchWidth()
  if (typeof ResizeObserver !== 'undefined') {
    workbenchResizeObserver = new ResizeObserver(syncWorkbenchWidth)
    workbenchResizeObserver.observe(element)
  }
})

onMounted(() => {
  void loadLifecycle()
  refreshTimer = setInterval(() => { void refreshActiveFacts() }, LIVE_REFRESH_MILLISECONDS)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
  workbenchResizeObserver?.disconnect()
  finishColumnResize()
})
</script>

<template>
  <PageShell fill>
    <LteAlert v-if="error" theme="danger" :title="t('runtimeMonitoring.snapshot.loadFailed')">
      {{ error }}
    </LteAlert>

    <div v-if="loading && !snapshot" class="runtime-monitoring-loading" aria-busy="true">
      <span class="spinner-border spinner-border-sm" aria-hidden="true" />
    </div>

    <div
      v-else-if="snapshot"
      ref="workbench"
      class="runtime-monitoring-workbench"
      :class="{ 'runtime-monitoring-workbench--resizing': activeResize }"
      :style="columnStyles"
    >
      <RuntimeThreadIndex
        id="runtime-monitoring-threads"
        :threads="snapshot.threads"
        :selected-thread-id="selectedThreadId"
        @select="selectThread"
      />

      <div
        class="runtime-column-resizer"
        role="separator"
        tabindex="0"
        aria-orientation="vertical"
        aria-controls="runtime-monitoring-threads runtime-monitoring-primary"
        :aria-label="t('runtimeMonitoring.resizeThreads')"
        :aria-valuemin="MIN_THREADS_WIDTH"
        :aria-valuemax="maximumThreadsWidth"
        :aria-valuenow="threadsWidth"
        @keydown="resizeColumnWithKeyboard('threads', $event)"
        @pointerdown="startColumnResize('threads', $event)"
      />

      <main class="runtime-thread-workspace">
        <RuntimeRunTrack
          v-if="selectedThread"
          :runs="selectedThread.runs"
          :selected-run-id="selectedRunId"
          @select="selectedRunId = $event"
        />

        <div class="runtime-detail-grid">
          <section id="runtime-monitoring-primary" class="runtime-primary-view">
            <AgentThreadView
              v-if="selectedGraphKind === 'agent' && selectedThreadAvailable && selectedAssistantId"
              :key="`${selectedAssistantId}:${selectedThreadId}`"
              :assistant-id="selectedAssistantId"
              :thread-id="selectedThreadId"
              @state="updateAgentState"
            />
            <WorkflowRuntimeView
              v-else-if="selectedGraphKind === 'workflow'"
              :graph="graph?.workflow_document ?? null"
              :node-catalog="graph?.workflow_node_catalog ?? []"
              :commands="graph?.workflow_commands ?? []"
              :state="state?.state ?? null"
              :loading="detailLoading"
              :error="detailError"
            />
            <div v-else-if="selectedRunObservation" class="runtime-unavailable" role="status">
              <i class="bi bi-dash-circle" aria-hidden="true" />
              <span>{{ selectedRunObservation.error?.message ?? selectedThread?.error?.message }}</span>
            </div>
          </section>

          <div
            class="runtime-column-resizer"
            role="separator"
            tabindex="0"
            aria-orientation="vertical"
            aria-controls="runtime-monitoring-primary runtime-monitoring-inspector"
            :aria-label="t('runtimeMonitoring.resizeInspector')"
            :aria-valuemin="MIN_INSPECTOR_WIDTH"
            :aria-valuemax="maximumInspectorWidth"
            :aria-valuenow="inspectorWidth"
            @keydown="resizeColumnWithKeyboard('inspector', $event)"
            @pointerdown="startColumnResize('inspector', $event)"
          />

          <RuntimeDataInspector
            id="runtime-monitoring-inspector"
            :state="state"
            :store="store"
            :loading="detailLoading"
          />
        </div>
      </main>
    </div>
  </PageShell>
</template>

<style scoped>
.runtime-monitoring-loading {
  display: flex;
  min-height: 0;
  flex: 1 1 0;
  align-items: center;
  justify-content: center;
  color: var(--bs-secondary-color);
}

.runtime-monitoring-workbench {
  display: grid;
  min-height: 0;
  flex: 1 1 0;
  grid-template-columns: var(--runtime-threads-width) .5rem minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid var(--bs-border-color);
  background: var(--bs-body-bg);
}

.runtime-monitoring-workbench--resizing {
  cursor: col-resize;
  user-select: none;
}

.runtime-thread-workspace {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-width: 0;
  overflow: hidden;
}

.runtime-detail-grid {
  display: grid;
  grid-template-columns: minmax(16rem, 1fr) .5rem var(--runtime-inspector-width);
  min-height: 0;
}

.runtime-column-resizer {
  position: relative;
  min-width: .5rem;
  cursor: col-resize;
  touch-action: none;
}

.runtime-column-resizer::before {
  position: absolute;
  inset-block: 0;
  inset-inline-start: calc(50% - .5px);
  width: 1px;
  background: var(--bs-border-color);
  content: '';
}

.runtime-column-resizer:hover::before,
.runtime-column-resizer:focus-visible::before {
  inset-inline-start: calc(50% - 1.5px);
  width: 3px;
  background: var(--bs-primary);
}

.runtime-column-resizer:focus-visible {
  outline: 2px solid var(--bs-primary);
  outline-offset: -2px;
}

.runtime-primary-view {
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.runtime-unavailable {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: .5rem;
  min-height: 30rem;
  padding: 1rem;
  color: var(--bs-secondary-color);
}

@media (max-width: 991.98px) {
  .runtime-monitoring-workbench {
    display: block;
    overflow: auto;
  }

  .runtime-detail-grid {
    display: block;
  }

  .runtime-column-resizer {
    display: none;
  }

  .runtime-primary-view {
    min-height: 32rem;
  }
}
</style>
