<script setup lang="ts">
import { LteAlert } from '@adminlte/vue'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
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
import { triggerBrowserDownload } from '@/utils/download'

const LIVE_REFRESH_MILLISECONDS = 3000

const { t } = useI18n()
const managementError = useManagementError()
const route = useRoute()
const lifecycleId = computed(() => String(route.params.lifecycleId || ''))
const snapshot = ref<LangGraphLifecycleSnapshot | null>(null)
const store = ref<LangGraphLifecycleStore | null>(null)
const selectedThreadId = ref('')
const selectedRunId = ref('')
const graph = ref<LangGraphGraphResponse | null>(null)
const state = ref<LangGraphStateResponse | null>(null)
const loading = ref(false)
const detailLoading = ref(false)
const downloading = ref(false)
const error = ref('')
const detailError = ref('')
let refreshTimer: ReturnType<typeof setInterval> | undefined
let detailGeneration = 0
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
  loading.value = snapshot.value === null
  error.value = ''
  try {
    const [snapshotValue, storeValue] = await Promise.all([
      managementApi.getLangGraphLifecycleSnapshot(lifecycleId.value),
      managementApi.getLangGraphLifecycleStore(lifecycleId.value),
    ])
    snapshot.value = snapshotValue
    store.value = storeValue
    keepOrSelect(snapshotValue)
  }
  catch (cause) {
    error.value = managementError.describe(cause).display
  }
  finally {
    loading.value = false
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
  refreshing = true
  try {
    const [snapshotValue, storeValue] = await Promise.all([
      managementApi.getLangGraphLifecycleSnapshot(lifecycleId.value),
      managementApi.getLangGraphLifecycleStore(lifecycleId.value),
    ])
    snapshot.value = snapshotValue
    store.value = storeValue
    keepOrSelect(snapshotValue)
    if (selectedGraphKind.value === 'workflow' && selectedRunId.value) {
      const stateValue = await managementApi.getLangGraphRunState(
        lifecycleId.value,
        selectedRunId.value,
      )
      state.value = stateValue
      detailError.value = stateValue.error?.message ?? ''
    }
  }
  catch (cause) {
    detailError.value = managementError.describe(cause).display
  }
  finally {
    refreshing = false
  }
}

function updateAgentState(values: Record<string, unknown>): void {
  if (!selectedRunId.value || !selectedThreadId.value) return
  state.value = {
    run_id: selectedRunId.value,
    thread_id: selectedThreadId.value,
    state: { ...(state.value?.state ?? {}), values },
    error: null,
  } as LangGraphStateResponse
}

async function downloadLifecycle(): Promise<void> {
  downloading.value = true
  error.value = ''
  try {
    const download = await managementApi.downloadLangGraphLifecycle(lifecycleId.value)
    triggerBrowserDownload(download.blob, download.filename)
  }
  catch (cause) {
    error.value = managementError.describe(cause).display
  }
  finally {
    downloading.value = false
  }
}

watch(
  () => `${selectedThreadId.value}:${selectedRunId.value}:${selectedGraphKind.value ?? ''}`,
  () => { void loadRunDetails() },
)

onMounted(() => {
  void loadLifecycle()
  refreshTimer = setInterval(() => { void refreshActiveFacts() }, LIVE_REFRESH_MILLISECONDS)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<template>
  <PageShell>
    <template #actions>
      <RouterLink class="btn btn-outline-secondary action-button" to="/system/workflow-lifecycles">
        <i class="bi bi-arrow-left" aria-hidden="true" />
        {{ t('runtimeMonitoring.backToCatalog') }}
      </RouterLink>
      <button
        class="btn btn-primary action-button"
        type="button"
        :disabled="downloading || !snapshot"
        @click="downloadLifecycle"
      >
        <span v-if="downloading" class="spinner-border spinner-border-sm" aria-hidden="true" />
        <i v-else class="bi bi-download" aria-hidden="true" />
        {{ t('runtimeMonitoring.download') }}
      </button>
    </template>

    <LteAlert v-if="error" theme="danger" :title="t('runtimeMonitoring.snapshot.loadFailed')">
      {{ error }}
    </LteAlert>

    <div v-if="loading && !snapshot" class="runtime-monitoring-loading" aria-busy="true">
      <span class="spinner-border spinner-border-sm" aria-hidden="true" />
    </div>

    <div v-else-if="snapshot" class="runtime-monitoring-workbench">
      <RuntimeThreadIndex
        :threads="snapshot.threads"
        :selected-thread-id="selectedThreadId"
        @select="selectThread"
      />

      <main class="runtime-thread-workspace">
        <RuntimeRunTrack
          v-if="selectedThread"
          :runs="selectedThread.runs"
          :selected-run-id="selectedRunId"
          @select="selectedRunId = $event"
        />

        <div class="runtime-detail-grid">
          <section class="runtime-primary-view">
            <AgentThreadView
              v-if="selectedGraphKind === 'agent' && selectedThreadAvailable && selectedAssistantId"
              :key="`${selectedAssistantId}:${selectedThreadId}`"
              :assistant-id="selectedAssistantId"
              :thread-id="selectedThreadId"
              @state="updateAgentState"
            />
            <WorkflowRuntimeView
              v-else-if="selectedGraphKind === 'workflow'"
              :graph="graph?.graph ?? null"
              :state="state?.state ?? null"
              :loading="detailLoading"
              :error="detailError"
            />
            <div v-else-if="selectedRunObservation" class="runtime-unavailable" role="status">
              <i class="bi bi-dash-circle" aria-hidden="true" />
              <span>{{ selectedRunObservation.error?.message ?? selectedThread?.error?.message }}</span>
            </div>
          </section>

          <RuntimeDataInspector :state="state" :store="store" :loading="detailLoading" />
        </div>
      </main>
    </div>
  </PageShell>
</template>

<style scoped>
.runtime-monitoring-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 20rem;
  color: var(--bs-secondary-color);
}

.runtime-monitoring-workbench {
  display: grid;
  grid-template-columns: minmax(14rem, 18rem) minmax(0, 1fr);
  min-height: 42rem;
  height: calc(100vh - 10rem);
  border: 1px solid var(--bs-border-color);
  background: var(--bs-body-bg);
}

.runtime-thread-workspace {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-width: 0;
  overflow: hidden;
}

.runtime-detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(16rem, 24rem);
  min-height: 0;
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
    grid-template-columns: 1fr;
    height: auto;
  }

  .runtime-detail-grid {
    grid-template-columns: 1fr;
  }

  .runtime-primary-view {
    min-height: 32rem;
  }
}
</style>
