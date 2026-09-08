<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import type { LangGraphThreadObservation } from '@/api'

import {
  monitoringLocalTime,
  monitoringPrimaryRun,
  monitoringRunName,
  monitoringShortId,
  monitoringStatusIcon,
  monitoringThreadActive,
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
        :class="{
          'runtime-thread-row--selected': thread.thread_id === selectedThreadId,
          'runtime-thread-row--active': monitoringThreadActive(thread),
        }"
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
          <strong>{{ threadName(thread) }}</strong>
          <span>{{ monitoringShortId(thread.thread_id) }}</span>
          <span>{{ monitoringLocalTime(threadUpdatedAt(thread)) }}</span>
        </span>
        <span class="runtime-thread-status">
          <i
            class="bi"
            :class="[
              monitoringStatusIcon(monitoringThreadStatus(thread)),
              { 'runtime-status-spin': monitoringThreadActive(thread) },
            ]"
            aria-hidden="true"
          />
          {{ t(`workflowLifecycles.runStatuses.${monitoringThreadStatus(thread)}`) }}
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
  min-height: 3rem;
  padding-inline: .85rem;
  border-block-end: 1px solid var(--bs-border-color);
}

.runtime-panel-heading h2 {
  margin: 0;
  font-size: .875rem;
  font-weight: 600;
}

.runtime-panel-heading span,
.runtime-thread-main span,
.runtime-thread-status {
  color: var(--bs-secondary-color);
  font-size: .75rem;
}

.runtime-thread-list {
  height: calc(100% - 3rem);
  overflow: auto;
}

.runtime-thread-row {
  position: relative;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: .65rem;
  width: 100%;
  padding: .8rem;
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

.runtime-thread-row--active {
  box-shadow: inset 0 -2px 0 var(--bs-primary-border-subtle);
}

.runtime-thread-icon {
  padding-block-start: .1rem;
  color: var(--bs-secondary-color);
}

.runtime-thread-main {
  display: grid;
  min-width: 0;
}

.runtime-thread-main strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.runtime-thread-status {
  grid-column: 2;
  display: flex;
  align-items: center;
  gap: .35rem;
}

.runtime-status-spin {
  animation: runtime-status-spin 1.2s linear infinite;
}

@keyframes runtime-status-spin {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .runtime-status-spin { animation: none; }
}

@media (max-width: 991.98px) {
  .runtime-thread-index {
    max-height: 18rem;
    border-inline-end: 0;
    border-block-end: 1px solid var(--bs-border-color);
  }
}
</style>
