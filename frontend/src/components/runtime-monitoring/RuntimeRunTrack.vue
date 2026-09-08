<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import type { LangGraphRunObservation } from '@/api'

import {
  monitoringCompactTime,
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
      :class="[
        { 'runtime-run-item--selected': run.run_id === selectedRunId },
        `runtime-run-item--${monitoringRunStatus(run)}`,
      ]"
      type="button"
      :aria-current="run.run_id === selectedRunId ? 'true' : undefined"
      @click="emit('select', run.run_id)"
    >
      <span class="runtime-run-status">
        <i class="bi" :class="monitoringStatusIcon(monitoringRunStatus(run))" aria-hidden="true" />
        <strong>{{ t(`workflowLifecycles.runStatuses.${monitoringRunStatus(run)}`) }}</strong>
      </span>
      <span class="runtime-run-meta">
        <time :datetime="runTime(run)" :title="monitoringLocalTime(runTime(run))">
          {{ monitoringCompactTime(runTime(run)) }}
        </time>
        <span aria-hidden="true">·</span>
        <span :title="run.run_id">{{ monitoringShortId(run.run_id) }}</span>
      </span>
    </button>
  </nav>
</template>

<style scoped>
.runtime-run-track {
  display: flex;
  min-height: 2.75rem;
  overflow-x: auto;
  border-block-end: 1px solid var(--bs-border-color);
}

.runtime-run-item {
  position: relative;
  display: grid;
  align-content: center;
  gap: .1rem;
  flex: 0 0 auto;
  min-width: 8.75rem;
  padding: .3rem .65rem;
  border: 0;
  border-inline-end: 1px solid var(--bs-border-color);
  background: transparent;
  color: var(--bs-body-color);
  text-align: start;
}

.runtime-run-item:hover {
  background: var(--bs-tertiary-bg);
}

.runtime-run-item--selected {
  background: var(--bs-tertiary-bg);
}

.runtime-run-item--selected::after {
  position: absolute;
  inset-inline: 0;
  inset-block-end: 0;
  height: 2px;
  background: var(--bs-primary);
  content: '';
}

.runtime-run-status,
.runtime-run-meta {
  display: flex;
  align-items: center;
  gap: .3rem;
  white-space: nowrap;
}

.runtime-run-status strong {
  font-size: .75rem;
  font-weight: 600;
}

.runtime-run-meta {
  color: var(--bs-secondary-color);
  font-size: .7rem;
}

.runtime-run-item--pending .runtime-run-status i,
.runtime-run-item--running .runtime-run-status i {
  color: var(--bs-primary);
}

.runtime-run-item--success .runtime-run-status i {
  color: var(--bs-success);
}

.runtime-run-item--error .runtime-run-status i {
  color: var(--bs-danger);
}

.runtime-run-item--timeout .runtime-run-status i,
.runtime-run-item--interrupted .runtime-run-status i {
  color: var(--bs-warning);
}
</style>
