<script setup lang="ts">
import { LteButton } from '@adminlte/vue'
import { useI18n } from 'vue-i18n'

import type {
  RuntimeMonitoringNodeAttempt,
  RuntimeMonitoringNodeAttemptPage,
  RuntimeMonitoringNodeSummary,
  WorkflowNodeType,
} from '@/api'
import PaginationControls from '@/components/PaginationControls.vue'

defineProps<{
  nodeId: string
  nodeType: WorkflowNodeType
  summary: RuntimeMonitoringNodeSummary | null
  page: RuntimeMonitoringNodeAttemptPage | null
  loading: boolean
  error: string
}>()

const emit = defineEmits<{
  close: []
  retry: []
  pageChange: [page: number]
  pageSizeChange: [pageSize: number]
}>()

const { t } = useI18n()

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
  <aside class="card runtime-monitoring-node-panel" aria-labelledby="runtime-node-attempts-title">
    <header class="card-header d-flex align-items-start justify-content-between gap-2">
      <div class="runtime-monitoring-heading">
        <h2 id="runtime-node-attempts-title" class="card-title mb-1 text-break">
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
    </div>

    <div class="runtime-monitoring-node-body">
      <div
        v-if="loading"
        class="d-flex align-items-center gap-2 p-3"
        aria-busy="true"
        role="status"
      >
        <span class="spinner-border spinner-border-sm" aria-hidden="true" />
        <span>{{ t('runtimeMonitoring.nodeAttempts.loading') }}</span>
      </div>

      <div v-else-if="error" class="p-3">
        <div class="alert alert-danger mb-0" role="alert">
          <p class="runtime-monitoring-error mb-3 text-break">{{ error }}</p>
          <LteButton class="action-button" type="button" @click="emit('retry')">
            <i class="bi bi-arrow-clockwise" aria-hidden="true" />
            {{ t('common.retry') }}
          </LteButton>
        </div>
      </div>

      <template v-else-if="page">
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
          <li v-for="item in page.items" :key="item.sequence" class="list-group-item">
            <div class="d-flex align-items-start justify-content-between gap-2 mb-2">
              <strong>
                {{ t('runtimeMonitoring.nodeAttempts.attemptNumber', { attempt: item.attempt }) }}
              </strong>
              <span class="badge text-bg-light border">
                <i class="bi me-1" :class="statusIcon(item)" aria-hidden="true" />
                {{ t(`runtimeMonitoring.nodeStatuses.${item.status}`) }}
              </span>
            </div>
            <dl class="runtime-node-attempt-fields mb-0">
              <dt>{{ t('runtimeMonitoring.nodeAttempts.invocation') }}</dt>
              <dd><code class="text-break">{{ item.invocation_id }}</code></dd>
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
      </template>
    </div>

    <PaginationControls
      v-if="page && page.total > 0 && !loading && !error"
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
  </aside>
</template>
