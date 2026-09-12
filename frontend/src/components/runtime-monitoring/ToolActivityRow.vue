<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import StructuredValueTree from './StructuredValueTree.vue'

const props = defineProps<{
  name: string
  callId: string
  status: 'running' | 'finished' | 'error'
  input: unknown
  // `| undefined` keeps callers that forward a value which may be absent
  // (`error: string | undefined`) assignable under `exactOptionalPropertyTypes`.
  output?: unknown
  error?: string | undefined
}>()

const { t } = useI18n()
const icon = computed(() => ({
  running: 'bi-arrow-repeat',
  finished: 'bi-check2',
  error: 'bi-exclamation-triangle',
})[props.status])
</script>

<template>
  <details class="tool-activity" :open="status === 'running'">
    <summary class="tool-activity-summary">
      <i
        class="bi tool-activity-icon"
        :class="[icon, { 'tool-activity-icon--running': status === 'running' }]"
        aria-hidden="true"
      />
      <span class="tool-activity-name">{{ name }}</span>
      <span class="tool-activity-status">{{ t(`runtimeMonitoring.agent.toolStatuses.${status}`) }}</span>
      <span class="tool-activity-id">{{ callId.slice(0, 8) }}</span>
    </summary>
    <div class="tool-activity-body">
      <StructuredValueTree :name="t('runtimeMonitoring.agent.input')" :value="input" />
      <StructuredValueTree
        v-if="status === 'finished'"
        :name="t('runtimeMonitoring.agent.output')"
        :value="output"
      />
      <StructuredValueTree
        v-if="status === 'error'"
        :name="t('runtimeMonitoring.agent.error')"
        :value="error"
      />
    </div>
  </details>
</template>

<style scoped>
.tool-activity {
  margin-block: .55rem;
  border-block: 1px solid var(--bs-border-color);
}

.tool-activity-summary {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto auto;
  align-items: center;
  gap: .5rem;
  padding: .55rem .25rem;
  cursor: pointer;
  list-style: none;
}

.tool-activity-summary::-webkit-details-marker {
  display: none;
}

.tool-activity-icon,
.tool-activity-status,
.tool-activity-id {
  color: var(--bs-secondary-color);
}

.tool-activity-name {
  min-width: 0;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.tool-activity-status,
.tool-activity-id {
  font-size: .75rem;
}

.tool-activity-id {
  font-family: var(--bs-font-monospace);
}

.tool-activity-body {
  padding: 0 .25rem .55rem 1.65rem;
}

.tool-activity-icon--running {
  animation: tool-activity-spin 1.2s linear infinite;
}

@keyframes tool-activity-spin {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .tool-activity-icon--running { animation: none; }
}
</style>
