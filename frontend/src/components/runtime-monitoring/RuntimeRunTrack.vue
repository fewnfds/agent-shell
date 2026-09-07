<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import type { LangGraphRunObservation } from '@/api'

import {
  monitoringLocalTime,
  monitoringRunStatus,
  monitoringShortId,
  monitoringStatusIcon,
} from './presentation'

defineProps<{
  runs: LangGraphRunObservation[]
  selectedRunId: string
}>()

const emit = defineEmits<{ select: [runId: string] }>()
const { t } = useI18n()

function runTime(observation: LangGraphRunObservation): string {
  return observation.run?.created_at ?? observation.run?.updated_at ?? ''
}
</script>

<template>
  <nav class="runtime-run-track" :aria-label="t('runtimeMonitoring.runs')">
    <button
      v-for="run in runs"
      :key="run.run_id"
      class="runtime-run-item"
      :class="{ 'runtime-run-item--selected': run.run_id === selectedRunId }"
      type="button"
      :aria-current="run.run_id === selectedRunId ? 'true' : undefined"
      @click="emit('select', run.run_id)"
    >
      <i class="bi" :class="monitoringStatusIcon(monitoringRunStatus(run))" aria-hidden="true" />
      <span>{{ monitoringLocalTime(runTime(run)) }}</span>
      <span>{{ monitoringShortId(run.run_id) }}</span>
      <span>{{ t(`workflowLifecycles.runStatuses.${monitoringRunStatus(run)}`) }}</span>
    </button>
  </nav>
</template>

<style scoped>
.runtime-run-track {
  display: flex;
  min-height: 3rem;
  overflow-x: auto;
  border-block-end: 1px solid var(--bs-border-color);
}

.runtime-run-item {
  display: grid;
  grid-template-columns: auto auto;
  align-items: center;
  gap: .1rem .4rem;
  flex: 0 0 auto;
  min-width: 9.5rem;
  padding: .45rem .7rem;
  border: 0;
  border-block-end: 2px solid transparent;
  background: transparent;
  color: var(--bs-secondary-color);
  font-size: .7rem;
  text-align: start;
}

.runtime-run-item:hover {
  background: var(--bs-tertiary-bg);
}

.runtime-run-item--selected {
  border-block-end-color: var(--bs-primary);
  color: var(--bs-body-color);
}
</style>
