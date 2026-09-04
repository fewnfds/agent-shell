<script setup lang="ts">
import { LteAlert } from '@adminlte/vue'
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import {
  managementApi,
  type LangGraphGraphResponse,
  type LangGraphHistoryResponse,
  type LangGraphLifecycleSnapshot,
  type LangGraphRun,
  type LangGraphStateResponse,
} from '@/api'
import PageShell from '@/components/PageShell.vue'
import { useManagementError } from '@/composables/useManagementError'

const { t } = useI18n()
const managementError = useManagementError()
const route = useRoute()
const lifecycleId = computed(() => String(route.params.lifecycleId || ''))
const snapshot = ref<LangGraphLifecycleSnapshot | null>(null)
const selectedRunId = ref('')
const graph = ref<LangGraphGraphResponse | null>(null)
const state = ref<LangGraphStateResponse | null>(null)
const history = ref<LangGraphHistoryResponse | null>(null)
const loading = ref(false)
const detailLoading = ref(false)
const error = ref('')

const selectedRun = computed<LangGraphRun | null>(() => (
  snapshot.value?.runs.find((run) => run.run_id === selectedRunId.value) ?? null
))

function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2)
}

function runName(run: LangGraphRun): string {
  const workflowName = run.metadata.workflow_name
  return typeof workflowName === 'string' && workflowName
    ? workflowName
    : run.run_id
}

async function loadSnapshot(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    snapshot.value = await managementApi.getLangGraphLifecycleSnapshot(lifecycleId.value)
    if (!snapshot.value.runs.some((run) => run.run_id === selectedRunId.value)) {
      selectedRunId.value = snapshot.value.runs[0]?.run_id ?? ''
    }
  }
  catch (cause) {
    error.value = managementError.describe(cause).display
  }
  finally {
    loading.value = false
  }
}

async function loadRunDetails(runId: string): Promise<void> {
  graph.value = null
  state.value = null
  history.value = null
  if (!runId) return
  detailLoading.value = true
  error.value = ''
  try {
    [graph.value, state.value, history.value] = await Promise.all([
      managementApi.getLangGraphRunGraph(lifecycleId.value, runId),
      managementApi.getLangGraphRunState(lifecycleId.value, runId),
      managementApi.getLangGraphRunHistory(lifecycleId.value, runId, 10),
    ])
  }
  catch (cause) {
    error.value = managementError.describe(cause).display
  }
  finally {
    detailLoading.value = false
  }
}

watch(selectedRunId, (runId) => { void loadRunDetails(runId) })
onMounted(() => { void loadSnapshot() })
</script>

<template>
  <PageShell>
    <template #actions>
      <RouterLink class="btn btn-outline-secondary action-button" to="/system/workflow-lifecycles">
        {{ t('runtimeMonitoring.backToCatalog') }}
      </RouterLink>
      <button class="btn btn-primary action-button" type="button" :disabled="loading" @click="loadSnapshot">
        {{ t('common.refresh') }}
      </button>
    </template>

    <LteAlert v-if="error" theme="danger" :title="t('runtimeMonitoring.snapshot.loadFailed')">
      {{ error }}
    </LteAlert>

    <div v-if="loading && !snapshot" class="text-secondary py-4">
      {{ t('runtimeMonitoring.snapshot.loading') }}
    </div>

    <template v-else-if="snapshot">
      <div class="card">
        <div class="card-body d-flex flex-wrap gap-4">
          <div><strong>{{ t('runtimeMonitoring.lifecycleId') }}:</strong> {{ snapshot.lifecycle_id }}</div>
          <div><strong>{{ t('workflowLifecycles.columns.status') }}:</strong> {{ t(`workflowLifecycles.runStatuses.${snapshot.status}`) }}</div>
          <div><strong>{{ t('workflowLifecycles.columns.runs') }}:</strong> {{ snapshot.active_run_count }} / {{ snapshot.run_count }}</div>
        </div>
      </div>

      <div class="row g-3">
        <div class="col-lg-4">
          <div class="card h-100">
            <header class="card-header"><h2 class="card-title">{{ t('runtimeMonitoring.runIndex.title') }}</h2></header>
            <div class="list-group list-group-flush" role="listbox" :aria-label="t('runtimeMonitoring.runIndex.ariaLabel')">
              <button
                v-for="run in snapshot.runs"
                :key="run.run_id"
                class="list-group-item list-group-item-action"
                :class="{ active: run.run_id === selectedRunId }"
                type="button"
                role="option"
                :aria-selected="run.run_id === selectedRunId"
                @click="selectedRunId = run.run_id"
              >
                <span class="d-block fw-semibold">{{ runName(run) }}</span>
                <span class="d-block small text-break">{{ run.run_id }}</span>
                <span class="badge text-bg-secondary mt-1">{{ run.status }}</span>
              </button>
            </div>
          </div>
        </div>

        <div class="col-lg-8">
          <div v-if="selectedRun" class="card mb-3">
            <header class="card-header"><h2 class="card-title">{{ t('runtimeMonitoring.officialRun') }}</h2></header>
            <pre class="card-body mb-0 overflow-auto"><code>{{ pretty(selectedRun) }}</code></pre>
          </div>
          <div v-if="detailLoading" class="text-secondary py-4">{{ t('common.loading') }}</div>
          <template v-else>
            <div v-if="graph" class="card mb-3">
              <header class="card-header"><h2 class="card-title">{{ t('runtimeMonitoring.graph.title') }}</h2></header>
              <pre class="card-body mb-0 overflow-auto"><code>{{ pretty(graph.graph) }}</code></pre>
            </div>
            <div v-if="state" class="card mb-3">
              <header class="card-header"><h2 class="card-title">{{ t('runtimeMonitoring.state.title') }}</h2></header>
              <pre class="card-body mb-0 overflow-auto"><code>{{ pretty(state.state) }}</code></pre>
            </div>
            <div v-if="history" class="card">
              <header class="card-header"><h2 class="card-title">{{ t('runtimeMonitoring.history') }}</h2></header>
              <pre class="card-body mb-0 overflow-auto"><code>{{ pretty(history.history) }}</code></pre>
            </div>
          </template>
        </div>
      </div>
    </template>
  </PageShell>
</template>
