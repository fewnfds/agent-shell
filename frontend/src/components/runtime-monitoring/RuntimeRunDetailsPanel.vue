<script setup lang="ts">
import { LteButton } from '@adminlte/vue'
import { useI18n } from 'vue-i18n'

import type {
  RuntimeMonitoringModelRequestPage,
  RuntimeMonitoringProtocolEventSequence,
  RuntimeMonitoringStateResponse,
} from '@/api'
import PaginationControls from '@/components/PaginationControls.vue'
import RuntimeProtocolEventList from '@/components/runtime-monitoring/RuntimeProtocolEventList.vue'
import type { RuntimeMonitoringRunDetailKind } from '@/composables/useRuntimeMonitoringRunDetails'

defineProps<{
  runId: string
  runName: string
  activeKind: RuntimeMonitoringRunDetailKind
  protocol: RuntimeMonitoringProtocolEventSequence | null
  protocolLoading: boolean
  protocolError: string
  modelPage: RuntimeMonitoringModelRequestPage | null
  modelsLoading: boolean
  modelsError: string
  state: RuntimeMonitoringStateResponse | null
  stateLoading: boolean
  stateError: string
}>()

const emit = defineEmits<{
  close: []
  selectKind: [kind: RuntimeMonitoringRunDetailKind]
  modelPageChange: [page: number]
  modelPageSizeChange: [pageSize: number]
  retryProtocol: []
  retryModels: []
  retryState: []
}>()

const { t } = useI18n()

function localTime(value: string | null): string {
  if (!value) return t('common.none')
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2)
}

function channelNames(value: RuntimeMonitoringStateResponse): string {
  const names = Object.keys(value.state?.state ?? {})
  return names.length ? names.join(', ') : t('common.none')
}
</script>

<template>
  <aside class="card runtime-monitoring-node-panel" aria-labelledby="runtime-run-details-title">
    <header class="card-header d-flex align-items-start justify-content-between gap-2">
      <div class="runtime-monitoring-heading">
        <h2 id="runtime-run-details-title" class="card-title mb-1 text-break">{{ runName }}</h2>
        <p class="mb-0 small text-body-secondary text-break">{{ runId }}</p>
      </div>
      <LteButton
        class="icon-action-button"
        :aria-label="t('runtimeMonitoring.runDetails.close')"
        :title="t('runtimeMonitoring.runDetails.close')"
        type="button"
        @click="emit('close')"
      >
        <i class="bi bi-x-lg" aria-hidden="true" />
        <span class="visually-hidden">{{ t('runtimeMonitoring.runDetails.close') }}</span>
      </LteButton>
    </header>

    <nav class="nav nav-tabs px-2 pt-2" :aria-label="t('runtimeMonitoring.runDetails.tabs')">
      <button
        v-for="kind in (['protocol', 'models', 'state'] as const)"
        :key="kind"
        class="nav-link"
        :class="{ active: activeKind === kind }"
        :aria-current="activeKind === kind ? 'page' : undefined"
        type="button"
        @click="emit('selectKind', kind)"
      >
        {{ t(`runtimeMonitoring.runDetails.kinds.${kind}`) }}
      </button>
    </nav>

    <div class="runtime-monitoring-node-body">
      <RuntimeProtocolEventList
        v-if="activeKind === 'protocol'"
        :error="protocolError"
        :loading="protocolLoading"
        :sequence="protocol"
        @retry="emit('retryProtocol')"
      />

      <section v-else-if="activeKind === 'models'" class="runtime-detail-section">
        <div class="runtime-detail-section-heading">
          <h3 class="h6 mb-0">{{ t('runtimeMonitoring.models.title') }}</h3>
        </div>
        <div
          v-if="modelsLoading && !modelPage"
          class="d-flex align-items-center gap-2 p-3"
          role="status"
        >
          <span class="spinner-border spinner-border-sm" aria-hidden="true" />
          {{ t('runtimeMonitoring.models.loading') }}
        </div>
        <div v-if="modelsError" class="alert alert-danger m-3" role="alert">
          <p class="runtime-monitoring-error mb-3">{{ modelsError }}</p>
          <LteButton class="action-button" type="button" @click="emit('retryModels')">
            <i class="bi bi-arrow-clockwise" aria-hidden="true" />
            {{ t('common.retry') }}
          </LteButton>
        </div>
        <template v-if="modelPage">
          <div
            v-if="modelPage.availability !== 'available'"
            class="alert alert-warning rounded-0 border-start-0 border-end-0 mb-0"
            role="status"
          >
            {{ t('runtimeMonitoring.models.availability', {
              availability: t(`runtimeMonitoring.availability.${modelPage.availability}`),
            }) }}
          </div>
          <p v-if="modelPage.items.length === 0" class="m-0 p-3 text-body-secondary" role="status">
            {{ t('runtimeMonitoring.models.empty') }}
          </p>
          <ol v-else class="list-group list-group-flush">
            <li v-for="item in modelPage.items" :key="item.sequence" class="list-group-item">
              <div class="d-flex flex-wrap align-items-start justify-content-between gap-2">
                <strong class="text-break">{{ item.model_run_id }}</strong>
                <span class="badge text-bg-light border">
                  {{ t(`runtimeMonitoring.models.statuses.${item.status}`) }}
                </span>
              </div>
              <dl class="runtime-node-attempt-fields mt-2 mb-0">
                <dt>{{ t('runtimeMonitoring.nodeAttempts.sequence') }}</dt>
                <dd>{{ item.sequence }}</dd>
                <dt>{{ t('runtimeMonitoring.nodeAttempts.started') }}</dt>
                <dd>{{ localTime(item.started_at) }}</dd>
                <dt>{{ t('runtimeMonitoring.nodeAttempts.finished') }}</dt>
                <dd>{{ localTime(item.finished_at) }}</dd>
                <template v-if="item.error_code">
                  <dt>{{ t('runtimeMonitoring.nodeAttempts.errorCode') }}</dt>
                  <dd>{{ item.error_code }}</dd>
                </template>
              </dl>
              <p class="small fw-semibold mt-3 mb-1">{{ t('runtimeMonitoring.models.usage') }}</p>
              <pre class="runtime-json mb-2"><code>{{ pretty(item.usage) }}</code></pre>
              <details>
                <summary>{{ t('runtimeMonitoring.models.rawRequest') }}</summary>
                <pre class="runtime-json mt-2 mb-0"><code>{{ pretty(item.request) }}</code></pre>
              </details>
            </li>
          </ol>
          <PaginationControls
            v-if="modelPage.total > 0"
            id="runtime-model-requests"
            :aria-label="t('runtimeMonitoring.models.pagination')"
            :item-count="modelPage.items.length"
            :page="modelPage.page"
            :page-size="modelPage.page_size"
            :page-size-options="[20, 50, 100]"
            :total="modelPage.total"
            :total-pages="modelPage.total_pages"
            @change="emit('modelPageChange', $event)"
            @page-size-change="emit('modelPageSizeChange', $event)"
          />
        </template>
      </section>

      <section v-else class="runtime-detail-section">
        <div class="runtime-detail-section-heading">
          <h3 class="h6 mb-0">{{ t('runtimeMonitoring.state.title') }}</h3>
          <LteButton class="btn btn-sm btn-outline-secondary" type="button" @click="emit('retryState')">
            <i class="bi bi-arrow-clockwise" aria-hidden="true" />
            {{ t('common.refresh') }}
          </LteButton>
        </div>
        <div
          v-if="stateLoading && !state"
          class="d-flex align-items-center gap-2 p-3"
          role="status"
        >
          <span class="spinner-border spinner-border-sm" aria-hidden="true" />
          {{ t('runtimeMonitoring.state.loading') }}
        </div>
        <div v-if="stateError" class="alert alert-danger m-3" role="alert">
          <p class="runtime-monitoring-error mb-3">{{ stateError }}</p>
          <LteButton class="action-button" type="button" @click="emit('retryState')">
            <i class="bi bi-arrow-clockwise" aria-hidden="true" />
            {{ t('common.retry') }}
          </LteButton>
        </div>
        <template v-if="state">
          <div
            v-if="state.availability !== 'available'"
            class="alert alert-info rounded-0 border-start-0 border-end-0 mb-0"
            role="status"
          >
            {{ t('runtimeMonitoring.state.availability', {
              availability: t(`runtimeMonitoring.availability.${state.availability}`),
            }) }}
          </div>
          <p v-if="!state.state" class="m-0 p-3 text-body-secondary" role="status">
            {{ t('runtimeMonitoring.state.empty') }}
          </p>
          <div v-else class="p-3">
            <dl class="runtime-node-attempt-fields mb-3">
              <dt>{{ t('runtimeMonitoring.state.checkpoint') }}</dt>
              <dd class="text-break">{{ state.state.checkpoint_id }}</dd>
              <dt>{{ t('runtimeMonitoring.state.namespace') }}</dt>
              <dd class="text-break">{{ state.state.checkpoint_ns || t('common.none') }}</dd>
              <dt>{{ t('runtimeMonitoring.state.persistedAt') }}</dt>
              <dd>{{ localTime(state.state.created_at) }}</dd>
              <dt>{{ t('runtimeMonitoring.state.source') }}</dt>
              <dd>{{ state.state.source }}</dd>
              <dt>{{ t('runtimeMonitoring.state.step') }}</dt>
              <dd>{{ state.state.step ?? t('common.none') }}</dd>
              <dt>{{ t('runtimeMonitoring.state.pendingWrites') }}</dt>
              <dd>{{ state.state.pending_write_count }}</dd>
              <dt>{{ t('runtimeMonitoring.state.channels') }}</dt>
              <dd class="text-break">{{ channelNames(state) }}</dd>
            </dl>
            <pre class="runtime-json mb-0"><code>{{ pretty(state.state.state) }}</code></pre>
          </div>
        </template>
      </section>
    </div>
  </aside>
</template>
