<script setup lang="ts">
import { LteButton } from '@adminlte/vue'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type {
  RuntimeMonitoringAgentInvocationResponse,
  RuntimeMonitoringCommandObservationSequence,
  RuntimeMonitoringNodeAttempt,
  RuntimeMonitoringNodeAttemptPage,
  RuntimeMonitoringNodeSummary,
  RuntimeMonitoringProtocolEventSequence,
  WorkflowNodeType,
} from '@/api'
import PaginationControls from '@/components/PaginationControls.vue'
import RuntimeAgentInvocationView from '@/components/runtime-monitoring/RuntimeAgentInvocationView.vue'
import RuntimeCommandObservationView from '@/components/runtime-monitoring/RuntimeCommandObservationView.vue'

const props = defineProps<{
  nodeId: string
  nodeType: WorkflowNodeType
  summary: RuntimeMonitoringNodeSummary | null
  page: RuntimeMonitoringNodeAttemptPage | null
  loading: boolean
  error: string
  selectedInvocationId: string
  agentArtifact: RuntimeMonitoringAgentInvocationResponse | null
  agentArtifactLoading: boolean
  agentArtifactError: string
  agentProtocol: RuntimeMonitoringProtocolEventSequence | null
  agentProtocolLoading: boolean
  agentProtocolError: string
  commandObservations: RuntimeMonitoringCommandObservationSequence | null
  commandLoading: boolean
  commandError: string
}>()

const emit = defineEmits<{
  close: []
  retry: []
  pageChange: [page: number]
  pageSizeChange: [pageSize: number]
  selectInvocation: [invocationId: string]
  viewLatest: []
  retryAgentArtifact: []
  retryAgentProtocol: []
  retryCommand: []
}>()

const { t } = useI18n()
const latestVisibleSequence = computed(() => Math.max(
  0,
  ...(props.page?.items.map((item) => item.sequence) ?? []),
))
const hasNewerAttempts = computed(() => (
  Boolean(props.summary)
  && props.summary!.latest_sequence > latestVisibleSequence.value
))

function localTime(value: string | null): string {
  if (!value) return t('runtimeMonitoring.nodeAttempts.notFinished')
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

function statusIcon(attempt: RuntimeMonitoringNodeAttempt): string {
  if (attempt.status === 'running') return 'bi-arrow-repeat'
  if (attempt.status === 'completed') return 'bi-check-circle'
  if (attempt.status === 'failed') return 'bi-x-circle'
  if (attempt.status === 'cancelled') return 'bi-slash-circle'
  if (attempt.status === 'interrupted') return 'bi-exclamation-circle'
  return 'bi-dash-circle'
}
</script>

<template>
  <aside class="card runtime-monitoring-node-panel" aria-labelledby="runtime-node-details-title">
    <header class="card-header d-flex align-items-start justify-content-between gap-2">
      <div class="runtime-monitoring-heading">
        <h2 id="runtime-node-details-title" class="card-title mb-1 text-break">
          {{ nodeId }}
        </h2>
        <p class="mb-0 small text-body-secondary">
          {{ t(`runtimeMonitoring.graph.nodeTypes.${nodeType}`) }} ·
          {{ t('runtimeMonitoring.nodeAttempts.title') }}
        </p>
      </div>
      <LteButton
        class="icon-action-button"
        :aria-label="t('runtimeMonitoring.nodeAttempts.close')"
        :title="t('runtimeMonitoring.nodeAttempts.close')"
        type="button"
        @click="emit('close')"
      >
        <i class="bi bi-x-lg" aria-hidden="true" />
        <span class="visually-hidden">{{ t('runtimeMonitoring.nodeAttempts.close') }}</span>
      </LteButton>
    </header>

    <div v-if="summary" class="runtime-node-attempt-summary">
      <span class="badge text-bg-light border">
        {{ t('runtimeMonitoring.nodeAttempts.recordedCount', { count: summary.attempt_count }) }}
      </span>
      <span
        v-for="(count, status) in summary.status_counts"
        :key="status"
        class="badge text-bg-light border"
      >
        {{ t(`runtimeMonitoring.nodeStatuses.${status}`) }}: {{ count }}
      </span>
      <LteButton
        v-if="hasNewerAttempts"
        class="btn btn-sm btn-outline-primary"
        type="button"
        @click="emit('viewLatest')"
      >
        <i class="bi bi-arrow-up-right-circle" aria-hidden="true" />
        {{ t('runtimeMonitoring.nodeAttempts.viewLatest') }}
      </LteButton>
    </div>

    <div class="runtime-monitoring-node-body">
      <section class="runtime-detail-section">
        <div class="runtime-detail-section-heading">
          <h3 class="h6 mb-0">{{ t('runtimeMonitoring.nodeAttempts.title') }}</h3>
        </div>
        <div
          v-if="loading && !page"
          class="d-flex align-items-center gap-2 p-3"
          aria-busy="true"
          role="status"
        >
          <span class="spinner-border spinner-border-sm" aria-hidden="true" />
          <span>{{ t('runtimeMonitoring.nodeAttempts.loading') }}</span>
        </div>
        <div v-if="error" class="p-3">
          <div class="alert alert-danger mb-0" role="alert">
            <p class="runtime-monitoring-error mb-3 text-break">{{ error }}</p>
            <LteButton class="action-button" type="button" @click="emit('retry')">
              <i class="bi bi-arrow-clockwise" aria-hidden="true" />
              {{ t('common.retry') }}
            </LteButton>
          </div>
        </div>
        <template v-if="page">
          <div
            v-if="page.availability !== 'available'"
            class="alert alert-warning rounded-0 border-start-0 border-end-0 mb-0"
            role="status"
          >
            {{ t('runtimeMonitoring.nodeAttempts.partial', {
              availability: t(`runtimeMonitoring.availability.${page.availability}`),
            }) }}
          </div>
          <p v-if="page.items.length === 0" class="m-0 p-3 text-body-secondary" role="status">
            {{ t('runtimeMonitoring.nodeAttempts.empty') }}
          </p>
          <ol v-else class="list-group list-group-flush runtime-node-attempt-list">
            <li v-for="item in page.items" :key="item.sequence" class="list-group-item p-0">
              <button
                v-if="nodeType === 'agent'"
                class="runtime-node-attempt-button"
                :data-selected="item.invocation_id === selectedInvocationId"
                type="button"
                @click="emit('selectInvocation', item.invocation_id)"
              >
                <span>
                  <strong>
                    {{ t('runtimeMonitoring.nodeAttempts.attemptNumber', {
                      attempt: item.attempt,
                    }) }}
                  </strong>
                  <small class="d-block text-body-secondary text-break">
                    {{ item.invocation_id }}
                  </small>
                </span>
                <span class="badge text-bg-light border">
                  <i class="bi me-1" :class="statusIcon(item)" aria-hidden="true" />
                  {{ t(`runtimeMonitoring.nodeStatuses.${item.status}`) }}
                </span>
              </button>
              <div v-else class="runtime-node-attempt-button">
                <span>
                  <strong>
                    {{ t('runtimeMonitoring.nodeAttempts.attemptNumber', {
                      attempt: item.attempt,
                    }) }}
                  </strong>
                  <small class="d-block text-body-secondary text-break">
                    {{ item.invocation_id }}
                  </small>
                </span>
                <span class="badge text-bg-light border">
                  <i class="bi me-1" :class="statusIcon(item)" aria-hidden="true" />
                  {{ t(`runtimeMonitoring.nodeStatuses.${item.status}`) }}
                </span>
              </div>
              <dl class="runtime-node-attempt-fields px-3 pb-3 mb-0">
                <dt>{{ t('runtimeMonitoring.nodeAttempts.sequence') }}</dt>
                <dd>{{ item.sequence }}</dd>
                <dt>{{ t('runtimeMonitoring.nodeAttempts.started') }}</dt>
                <dd>{{ localTime(item.started_at) }}</dd>
                <dt>{{ t('runtimeMonitoring.nodeAttempts.finished') }}</dt>
                <dd>{{ localTime(item.finished_at) }}</dd>
                <template v-if="item.error_code">
                  <dt>{{ t('runtimeMonitoring.nodeAttempts.errorCode') }}</dt>
                  <dd><code class="text-break">{{ item.error_code }}</code></dd>
                </template>
              </dl>
            </li>
          </ol>
          <PaginationControls
            v-if="page.total > 0"
            :id="`runtime-node-attempts-${nodeId}`"
            :aria-label="t('runtimeMonitoring.nodeAttempts.pagination')"
            :item-count="page.items.length"
            :page="page.page"
            :page-size="page.page_size"
            :page-size-options="[20, 50, 100]"
            :total="page.total"
            :total-pages="page.total_pages"
            @change="emit('pageChange', $event)"
            @page-size-change="emit('pageSizeChange', $event)"
          />
        </template>
      </section>

      <RuntimeAgentInvocationView
        v-if="nodeType === 'agent'"
        :artifact="agentArtifact"
        :artifact-error="agentArtifactError"
        :artifact-loading="agentArtifactLoading"
        :invocation-id="selectedInvocationId"
        :protocol="agentProtocol"
        :protocol-error="agentProtocolError"
        :protocol-loading="agentProtocolLoading"
        @retry-artifact="emit('retryAgentArtifact')"
        @retry-protocol="emit('retryAgentProtocol')"
      />
      <RuntimeCommandObservationView
        v-else-if="nodeType === 'command'"
        :error="commandError"
        :loading="commandLoading"
        :sequence="commandObservations"
        @retry="emit('retryCommand')"
      />
    </div>
  </aside>
</template>
