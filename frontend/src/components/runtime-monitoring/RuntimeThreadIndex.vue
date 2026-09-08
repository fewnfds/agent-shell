<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import type { LangGraphThreadObservation } from '@/api'

import {
  monitoringCompactTime,
  monitoringLocalTime,
  monitoringPrimaryRun,
  monitoringRunName,
  monitoringShortId,
  monitoringThreadGraphKind,
  monitoringThreadStatus,
} from './presentation'

defineProps<{
  threads: LangGraphThreadObservation[]
  selectedThreadId: string
}>()

const emit = defineEmits<{
  select: [thread: LangGraphThreadObservation]
}>()
const { t } = useI18n()

function threadName(thread: LangGraphThreadObservation): string {
  const run = monitoringPrimaryRun(thread)
  return run ? monitoringRunName(run) : thread.thread_id
}

function threadUpdatedAt(thread: LangGraphThreadObservation): string {
  return thread.thread?.updated_at ?? monitoringPrimaryRun(thread)?.run?.updated_at ?? ''
}
</script>

<template>
  <aside class="runtime-thread-index" :aria-label="t('runtimeMonitoring.threads')">
    <header class="runtime-panel-heading">
      <h2>{{ t('runtimeMonitoring.threads') }}</h2>
      <span>{{ threads.length }}</span>
    </header>
    <div class="runtime-thread-list" role="listbox">
      <button
        v-for="thread in threads"
        :key="thread.thread_id"
        class="runtime-thread-row"
        :class="[
          { 'runtime-thread-row--selected': thread.thread_id === selectedThreadId },
          `runtime-thread-row--${monitoringThreadStatus(thread)}`,
        ]"
        type="button"
        role="option"
        :aria-selected="thread.thread_id === selectedThreadId"
        @click="emit('select', thread)"
      >
        <span class="runtime-thread-icon">
          <i
            class="bi"
            :class="monitoringThreadGraphKind(thread) === 'workflow'
              ? 'bi-diagram-3'
              : 'bi-chat-square-text'"
            aria-hidden="true"
          />
        </span>
        <span class="runtime-thread-main">
          <span class="runtime-thread-summary">
            <strong>{{ threadName(thread) }}</strong>
            <time
              :datetime="threadUpdatedAt(thread)"
              :title="monitoringLocalTime(threadUpdatedAt(thread))"
            >{{ monitoringCompactTime(threadUpdatedAt(thread)) }}</time>
          </span>
          <span class="runtime-thread-meta">
            <span class="runtime-thread-identity" :title="thread.thread_id">
              {{ monitoringShortId(thread.thread_id) }}
              <span aria-hidden="true">·</span>
              {{ thread.runs.length }} {{ t('runtimeMonitoring.runs') }}
            </span>
            <span class="runtime-thread-status">
              {{ t(`workflowLifecycles.runStatuses.${monitoringThreadStatus(thread)}`) }}
            </span>
          </span>
        </span>
      </button>
    </div>
  </aside>
</template>

<style scoped>
.runtime-thread-index {
  min-width: 0;
  overflow: hidden;
}

.runtime-panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 2.5rem;
  padding-inline: .75rem;
  border-block-end: 1px solid var(--bs-border-color);
}

.runtime-panel-heading h2 {
  margin: 0;
  font-size: .875rem;
  font-weight: 600;
}

.runtime-panel-heading span,
.runtime-thread-summary time,
.runtime-thread-meta,
.runtime-thread-status {
  color: var(--bs-secondary-color);
  font-size: .75rem;
}

.runtime-thread-list {
  height: calc(100% - 2.5rem);
  overflow: auto;
}

.runtime-thread-row {
  position: relative;
  display: grid;
  grid-template-columns: 1.25rem minmax(0, 1fr);
  align-items: center;
  gap: .5rem;
  width: 100%;
  min-height: 3.5rem;
  padding: .5rem .7rem;
  border: 0;
  border-block-end: 1px solid var(--bs-border-color);
  background: transparent;
  color: var(--bs-body-color);
  text-align: start;
}

.runtime-thread-row:hover,
.runtime-thread-row--selected {
  background: var(--bs-tertiary-bg);
}

.runtime-thread-row--selected::before {
  position: absolute;
  inset-block: 0;
  inset-inline-start: 0;
  width: 3px;
  background: var(--bs-primary);
  content: '';
}

.runtime-thread-icon {
  display: grid;
  place-items: center;
  color: var(--bs-secondary-color);
}

.runtime-thread-row--pending .runtime-thread-icon,
.runtime-thread-row--running .runtime-thread-icon {
  color: var(--bs-primary);
}

.runtime-thread-row--success .runtime-thread-icon {
  color: var(--bs-success);
}

.runtime-thread-row--error .runtime-thread-icon {
  color: var(--bs-danger);
}

.runtime-thread-row--timeout .runtime-thread-icon,
.runtime-thread-row--interrupted .runtime-thread-icon {
  color: var(--bs-warning);
}

.runtime-thread-main {
  display: grid;
  min-width: 0;
  gap: .15rem;
}

.runtime-thread-summary,
.runtime-thread-meta {
  display: flex;
  min-width: 0;
  align-items: baseline;
  justify-content: space-between;
  gap: .5rem;
}

.runtime-thread-summary strong,
.runtime-thread-identity {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.runtime-thread-summary strong {
  font-weight: 600;
}

.runtime-thread-summary time,
.runtime-thread-status {
  flex: 0 0 auto;
}

@media (max-width: 991.98px) {
  .runtime-thread-index {
    max-height: 18rem;
    border-inline-end: 0;
    border-block-end: 1px solid var(--bs-border-color);
  }
}
</style>
