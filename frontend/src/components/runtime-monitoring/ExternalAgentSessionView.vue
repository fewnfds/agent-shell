<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import type { ExternalAgentSessionDetail, JsonValue } from '@/api'

import StructuredValueTree from './StructuredValueTree.vue'

defineProps<{
  detail: ExternalAgentSessionDetail | null
  error: string
  loading: boolean
}>()

const { t } = useI18n()

function text(value: JsonValue | undefined): string {
  return typeof value === 'string' ? value : ''
}

function duration(value: number | null): string {
  if (value === null) return '—'
  if (value < 1000) return `${value} ms`
  return `${(value / 1000).toFixed(2)} s`
}
</script>

<template>
  <section class="external-agent-session-view">
    <div v-if="loading && !detail" class="external-agent-session-loading" aria-busy="true">
      <span class="spinner-border spinner-border-sm" aria-hidden="true" />
    </div>
    <div v-else-if="error" class="external-agent-session-error" role="alert">
      {{ error }}
    </div>
    <template v-else-if="detail">
      <header class="external-agent-session-header">
        <div>
          <h2>{{ detail.session.external_agent_name || detail.session.session_id }}</h2>
          <p>{{ detail.session.agent_name }} · {{ detail.session.provider }}</p>
        </div>
        <span
          class="external-agent-session-status"
          :data-status="detail.session.status"
        >
          {{ t(`runtimeMonitoring.externalAgentStatuses.${detail.session.status}`) }}
        </span>
      </header>

      <dl class="external-agent-session-facts">
        <div>
          <dt>{{ t('runtimeMonitoring.externalAgent.conversation') }}</dt>
          <dd>{{ detail.session.conversation_id ?? '—' }}</dd>
        </div>
        <div>
          <dt>{{ t('runtimeMonitoring.externalAgent.duration') }}</dt>
          <dd>{{ duration(detail.session.duration_ms) }}</dd>
        </div>
        <div>
          <dt>{{ t('runtimeMonitoring.externalAgent.workspace') }}</dt>
          <dd>{{ detail.session.workspace_path ?? '—' }}</dd>
        </div>
      </dl>

      <div
        v-if="detail.session.error_message || detail.session.error"
        class="external-agent-session-error"
        role="alert"
      >
        {{ detail.session.error_message || detail.session.error }}
      </div>

      <section v-if="detail.result" class="external-agent-session-result">
        <h3>{{ t('runtimeMonitoring.externalAgent.result') }}</h3>
        <p
          v-if="text(detail.result.response)"
          class="external-agent-session-response"
        >
          {{ text(detail.result.response) }}
        </p>
        <StructuredValueTree :value="detail.result" />
      </section>

      <section class="external-agent-session-events">
        <h3>{{ t('runtimeMonitoring.externalAgent.events') }}</h3>
        <p v-if="detail.events.length === 0" class="external-agent-session-empty">
          {{ t('runtimeMonitoring.externalAgent.noEvents') }}
        </p>
        <ol v-else class="external-agent-event-list">
          <li
            v-for="(event, index) in detail.events"
            :key="`${String(event.at ?? '')}:${index}`"
            class="external-agent-event"
          >
            <div class="external-agent-event-heading">
              <strong>{{ String(event.kind ?? '') }}</strong>
              <time>{{ String(event.at ?? '') }}</time>
            </div>
            <StructuredValueTree :value="event.payload ?? event" />
          </li>
        </ol>
      </section>
    </template>
  </section>
</template>

<style scoped>
.external-agent-session-view {
  height: 100%;
  min-width: 0;
  overflow: auto;
  padding: .75rem;
}

.external-agent-session-loading,
.external-agent-session-error {
  display: flex;
  align-items: center;
  gap: .5rem;
  padding: .75rem;
}

.external-agent-session-error {
  color: var(--bs-danger-text-emphasis);
}

.external-agent-session-header,
.external-agent-event-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.external-agent-session-header h2,
.external-agent-session-events h3,
.external-agent-session-result h3 {
  margin: 0;
  font-size: .95rem;
  font-weight: 600;
}

.external-agent-session-header p {
  margin: .2rem 0 0;
  color: var(--bs-secondary-color);
  font-size: .75rem;
}

.external-agent-session-status {
  flex: 0 0 auto;
  color: var(--bs-secondary-color);
  font-size: .75rem;
  text-transform: capitalize;
}

.external-agent-session-status[data-status='success'] {
  color: var(--bs-success-text-emphasis);
}

.external-agent-session-status[data-status='running'] {
  color: var(--bs-primary-text-emphasis);
}

.external-agent-session-status[data-status='timeout'],
.external-agent-session-status[data-status='denied'] {
  color: var(--bs-warning-text-emphasis);
}

.external-agent-session-status[data-status='failed'] {
  color: var(--bs-danger-text-emphasis);
}

.external-agent-session-facts {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: .5rem 1rem;
  margin: .9rem 0;
  padding: .6rem 0;
  border-block: 1px solid var(--bs-border-color);
}

.external-agent-session-facts dt {
  color: var(--bs-secondary-color);
  font-size: .7rem;
  font-weight: 500;
}

.external-agent-session-facts dd {
  margin: .15rem 0 0;
  overflow-wrap: anywhere;
  font-size: .75rem;
}

.external-agent-session-result,
.external-agent-session-events {
  display: grid;
  gap: .5rem;
  margin-block-start: 1rem;
}

.external-agent-session-response {
  margin: 0;
  padding: .6rem;
  border: 1px solid var(--bs-border-color);
  background: var(--bs-tertiary-bg);
  white-space: pre-wrap;
}

.external-agent-session-empty {
  color: var(--bs-secondary-color);
  font-size: .8rem;
}

.external-agent-event-list {
  display: grid;
  gap: .4rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.external-agent-event {
  min-width: 0;
  padding: .5rem;
  border: 1px solid var(--bs-border-color);
}

.external-agent-event-heading {
  margin-block-end: .25rem;
  color: var(--bs-secondary-color);
  font-size: .7rem;
}
</style>
