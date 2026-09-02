<script setup lang="ts">
import { LteButton } from '@adminlte/vue'
import { useI18n } from 'vue-i18n'

import type { RuntimeMonitoringCommandObservationSequence } from '@/api'

defineProps<{
  sequence: RuntimeMonitoringCommandObservationSequence | null
  loading: boolean
  error: string
}>()

const emit = defineEmits<{
  retry: []
}>()

const { t } = useI18n()

function localTime(value: string): string {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2)
}
</script>

<template>
  <section class="runtime-detail-section">
    <div class="runtime-detail-section-heading">
      <h3 class="h6 mb-0">{{ t('runtimeMonitoring.command.title') }}</h3>
    </div>
    <div v-if="loading && !sequence" class="d-flex align-items-center gap-2 p-3" role="status">
      <span class="spinner-border spinner-border-sm" aria-hidden="true" />
      {{ t('runtimeMonitoring.command.loading') }}
    </div>
    <div v-if="error" class="alert alert-danger m-3" role="alert">
      <p class="runtime-monitoring-error mb-3">{{ error }}</p>
      <LteButton class="action-button" type="button" @click="emit('retry')">
        <i class="bi bi-arrow-clockwise" aria-hidden="true" />
        {{ t('common.retry') }}
      </LteButton>
    </div>
    <template v-if="sequence">
      <div
        v-if="sequence.availability !== 'available'"
        class="alert alert-warning rounded-0 border-start-0 border-end-0 mb-0"
        role="status"
      >
        {{ t('runtimeMonitoring.command.availability', {
          availability: t(`runtimeMonitoring.availability.${sequence.availability}`),
        }) }}
      </div>
      <p v-if="sequence.items.length === 0" class="m-0 p-3 text-body-secondary" role="status">
        {{ t('runtimeMonitoring.command.empty') }}
      </p>
      <ol v-else class="list-group list-group-flush">
        <li v-for="item in sequence.items" :key="item.sequence" class="list-group-item">
          <div class="d-flex flex-wrap align-items-start justify-content-between gap-2">
            <strong>{{ t(`runtimeMonitoring.command.phases.${item.phase}`) }}</strong>
            <span class="small text-body-secondary">
              #{{ item.sequence }} · {{ localTime(item.occurred_at) }}
            </span>
          </div>
          <p class="small text-body-secondary text-break mt-1 mb-0">
            {{ item.invocation_id }} · {{ t('runtimeMonitoring.nodeAttempts.attemptNumber', {
              attempt: item.attempt,
            }) }}
          </p>
          <p v-if="item.error_code" class="text-danger mt-2 mb-0">
            {{ t('runtimeMonitoring.nodeAttempts.errorCode') }}: {{ item.error_code }}
          </p>
          <dl v-if="Object.keys(item.payload).length" class="runtime-command-payload mt-2 mb-0">
            <template v-for="(value, key) in item.payload" :key="key">
              <dt>{{ key }}</dt>
              <dd><pre class="runtime-json mb-0"><code>{{ pretty(value) }}</code></pre></dd>
            </template>
          </dl>
        </li>
      </ol>
    </template>
  </section>
</template>
