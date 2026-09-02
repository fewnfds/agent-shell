<script setup lang="ts">
import { LteAlert, LteButton } from '@adminlte/vue'
import { computed, onUnmounted, ref, watch } from 'vue'
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
import PageShell from '@/components/PageShell.vue'
import RuntimeRunIndex from '@/components/runtime-monitoring/RuntimeRunIndex.vue'
import RuntimeWorkflowCanvas from '@/components/runtime-monitoring/RuntimeWorkflowCanvas.vue'
import { useManagementError } from '@/composables/useManagementError'
import {
  runtimeMonitoringRunForest,
  selectRuntimeMonitoringRunId,
} from '@/domain/runtimeMonitoring'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const managementError = useManagementError()

const snapshot = ref<RuntimeMonitoringSnapshot | null>(null)
const nodeCatalog = ref<WorkflowNodeCatalogItem[]>([])
const selectedRunId = ref('')
const graphResponse = ref<RuntimeMonitoringGraphResponse | null>(null)
const nodeSummaryPage = ref<RuntimeMonitoringNodeSummaryPage | null>(null)
const lifecycleLoading = ref(false)
const runLoading = ref(false)
const lifecycleError = ref('')
const catalogError = ref('')
const runError = ref('')
let lifecycleGeneration = 0
let runGeneration = 0
let lifecycleController: AbortController | null = null
let runController: AbortController | null = null
let resourceRunId = ''

const lifecycleId = computed(() => String(route.params.lifecycleId ?? ''))
const requestedRunId = computed(() => (
  typeof route.query.run_id === 'string' ? route.query.run_id : ''
))
const runRoots = computed(() => snapshot.value ? runtimeMonitoringRunForest(snapshot.value) : [])
const selectedRun = computed(() => snapshot.value?.runs.find((run) => (
  run.run_id === selectedRunId.value
)) ?? null)
const graphDocument = computed(() => graphResponse.value?.graph?.document ?? null)

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

async function loadRunResources(runId: string, force = false): Promise<void> {
  if (!snapshot.value?.runs.some((run) => run.run_id === runId)) return
  if (!force && selectedRunId.value === runId && resourceRunId === runId) return

  runController?.abort()
  const controller = new AbortController()
  runController = controller
  const generation = ++runGeneration
  const targetLifecycleId = lifecycleId.value
  selectedRunId.value = runId
  resourceRunId = runId
  graphResponse.value = null
  nodeSummaryPage.value = null
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
    if (!graph.graph) return

    const pageSize = Math.max(1, graph.graph.document.definition.nodes.length)
    const nodes = await managementApi.listRuntimeMonitoringNodes(
      targetLifecycleId,
      runId,
      { page: 1, page_size: pageSize },
      controller.signal,
    )
    if (isCurrentRunRequest(generation, runId)) nodeSummaryPage.value = nodes
  } catch (error) {
    if (!controller.signal.aborted && isCurrentRunRequest(generation, runId)) {
      runError.value = managementError.describe(
        error,
        'runtimeMonitoring.graph.loadFailed',
      ).display
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

async function loadLifecycle(): Promise<void> {
  lifecycleController?.abort()
  runController?.abort()
  const controller = new AbortController()
  lifecycleController = controller
  const generation = ++lifecycleGeneration
  runGeneration += 1
  resourceRunId = ''
  snapshot.value = null
  nodeCatalog.value = []
  selectedRunId.value = ''
  graphResponse.value = null
  nodeSummaryPage.value = null
  lifecycleError.value = ''
  catalogError.value = ''
  runError.value = ''
  lifecycleLoading.value = true
  runLoading.value = false
  const targetLifecycleId = lifecycleId.value

  const [snapshotResult, catalogResult] = await Promise.allSettled([
    managementApi.getRuntimeMonitoringSnapshot(targetLifecycleId, controller.signal),
    managementApi.listWorkflowNodeCatalog(),
  ])
  if (controller.signal.aborted || generation !== lifecycleGeneration) return

  if (snapshotResult.status === 'rejected') {
    lifecycleError.value = managementError.describe(
      snapshotResult.reason,
      'runtimeMonitoring.snapshot.loadFailed',
    ).display
  } else {
    snapshot.value = snapshotResult.value
  }
  if (catalogResult.status === 'rejected') {
    catalogError.value = managementError.describe(
      catalogResult.reason,
      'runtimeMonitoring.graph.catalogLoadFailed',
    ).display
  } else {
    nodeCatalog.value = catalogResult.value
  }
  lifecycleLoading.value = false
  applyRouteSelection()
}

function selectRun(runId: string): void {
  if (!snapshot.value?.runs.some((run) => run.run_id === runId)) return
  void loadRunResources(runId)
  if (requestedRunId.value !== runId) {
    void router.push({ query: { ...route.query, run_id: runId } })
  }
}

function retryRun(): void {
  if (selectedRunId.value) void loadRunResources(selectedRunId.value, true)
}

watch(lifecycleId, () => { void loadLifecycle() }, { immediate: true })
watch(requestedRunId, applyRouteSelection)

onUnmounted(() => {
  lifecycleGeneration += 1
  runGeneration += 1
  lifecycleController?.abort()
  runController?.abort()
})
</script>

<template>
  <PageShell>
    <div class="d-flex flex-wrap align-items-start justify-content-between gap-3 mb-3">
      <div class="runtime-monitoring-heading">
        <h1 class="h4 mb-1">{{ snapshot?.lifecycle.workflow_name || t('runtimeMonitoring.title') }}</h1>
        <p class="mb-0 text-body-secondary text-break">
          {{ t('runtimeMonitoring.lifecycleId') }}: {{ lifecycleId }}
        </p>
      </div>
      <RouterLink class="btn btn-outline-secondary action-button" to="/system/workflow-lifecycles">
        <i class="bi bi-arrow-left" aria-hidden="true" />
        {{ t('runtimeMonitoring.backToCatalog') }}
      </RouterLink>
    </div>

    <div
      v-if="lifecycleLoading"
      class="d-flex align-items-center gap-2 p-3"
      aria-busy="true"
      role="status"
    >
      <span class="spinner-border" aria-hidden="true" />
      <span>{{ t('runtimeMonitoring.snapshot.loading') }}</span>
    </div>

    <LteAlert
      v-else-if="lifecycleError"
      :title="t('runtimeMonitoring.snapshot.loadFailed')"
      theme="danger"
    >
      <p class="runtime-monitoring-error mb-3 text-break">{{ lifecycleError }}</p>
      <LteButton class="action-button" type="button" @click="loadLifecycle">
        <i class="bi bi-arrow-clockwise" aria-hidden="true" />
        {{ t('common.retry') }}
      </LteButton>
    </LteAlert>

    <div v-else-if="snapshot" class="runtime-monitoring-layout">
      <aside class="card runtime-monitoring-run-panel">
        <header class="card-header">
          <div class="d-flex align-items-center justify-content-between gap-2">
            <h2 class="card-title mb-0">{{ t('runtimeMonitoring.runIndex.title') }}</h2>
            <span class="badge text-bg-secondary">
              {{ t('runtimeMonitoring.runIndex.count', { count: snapshot.summary.run_count }) }}
            </span>
          </div>
          <p class="mb-0 mt-2 small text-body-secondary">
            {{ t('runtimeMonitoring.runIndex.activeCount', {
              count: snapshot.summary.active_run_count,
            }) }}
          </p>
        </header>
        <div
          v-if="snapshot.forest.relationship_availability === 'partial'"
          class="alert alert-warning rounded-0 border-start-0 border-end-0 mb-0"
          role="status"
        >
          {{ t('runtimeMonitoring.runIndex.partial') }}
        </div>
        <div class="runtime-monitoring-run-scroll">
          <RuntimeRunIndex
            :orphan-run-ids="snapshot.forest.orphan_run_ids"
            :roots="runRoots"
            :selected-run-id="selectedRunId"
            @select="selectRun"
          />
        </div>
      </aside>

      <section class="card runtime-monitoring-graph-panel" aria-live="polite">
        <header class="card-header d-flex flex-wrap align-items-start justify-content-between gap-2">
          <div class="runtime-monitoring-heading">
            <h2 class="card-title mb-1">
              {{ selectedRun?.workflow_name || t('runtimeMonitoring.graph.title') }}
            </h2>
            <p v-if="selectedRun" class="mb-0 small text-body-secondary text-break">
              {{ selectedRun.run_id }} · {{ localTime(selectedRun.created_at) }}
            </p>
          </div>
          <div v-if="selectedRun" class="d-flex flex-wrap gap-2">
            <span class="badge text-bg-secondary">
              {{ t(`workflowLifecycles.runStatuses.${selectedRun.status}`) }}
            </span>
            <span v-if="graphResponse" class="badge text-bg-light border">
              {{ t('runtimeMonitoring.graph.availability', {
                value: availabilityLabel(graphResponse.availability),
              }) }}
            </span>
          </div>
        </header>

        <div class="runtime-monitoring-graph-body">
          <div
            v-if="runLoading"
            class="d-flex align-items-center justify-content-center gap-2 h-100 p-3"
            aria-busy="true"
            role="status"
          >
            <span class="spinner-border" aria-hidden="true" />
            <span>{{ t('runtimeMonitoring.graph.loading') }}</span>
          </div>

          <div v-else-if="runError" class="p-3">
            <div class="alert alert-danger mb-0" role="alert">
              <p class="runtime-monitoring-error mb-3 text-break">{{ runError }}</p>
              <LteButton class="action-button" type="button" @click="retryRun">
                <i class="bi bi-arrow-clockwise" aria-hidden="true" />
                {{ t('common.retry') }}
              </LteButton>
            </div>
          </div>

          <div v-else-if="catalogError" class="p-3">
            <div class="alert alert-danger mb-0" role="alert">
              <p class="runtime-monitoring-error mb-3 text-break">{{ catalogError }}</p>
              <LteButton class="action-button" type="button" @click="loadLifecycle">
                <i class="bi bi-arrow-clockwise" aria-hidden="true" />
                {{ t('common.retry') }}
              </LteButton>
            </div>
          </div>

          <template v-else-if="graphDocument">
            <div
              v-if="graphResponse?.availability !== 'available'"
              class="alert alert-info rounded-0 border-start-0 border-end-0 mb-0"
              role="status"
            >
              {{ t('runtimeMonitoring.graph.partial', {
                availability: availabilityLabel(graphResponse?.availability ?? 'unavailable'),
              }) }}
            </div>
            <div
              v-if="nodeSummaryPage && nodeSummaryPage.availability !== 'available'"
              class="alert alert-warning rounded-0 border-start-0 border-end-0 mb-0"
              role="status"
            >
              {{ t('runtimeMonitoring.graph.nodeSummaryPartial', {
                availability: availabilityLabel(nodeSummaryPage.availability),
              }) }}
            </div>
            <RuntimeWorkflowCanvas
              :key="selectedRunId"
              :document="graphDocument"
              :node-catalog="nodeCatalog"
              :node-summaries="nodeSummaryPage?.items ?? []"
            />
          </template>

          <p v-else class="m-0 p-4 text-center text-body-secondary" role="status">
            {{ graphEmptyMessage() }}
          </p>
        </div>
      </section>
    </div>
  </PageShell>
</template>
