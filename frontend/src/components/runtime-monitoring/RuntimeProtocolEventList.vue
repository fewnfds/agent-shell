<script setup lang="ts">
import { LteButton } from '@adminlte/vue'
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type {
  JsonValue,
  RuntimeMonitoringProtocolEvent,
  RuntimeMonitoringProtocolEventSequence,
} from '@/api'

const props = defineProps<{
  sequence: RuntimeMonitoringProtocolEventSequence | null
  loading: boolean
  error: string
}>()

const emit = defineEmits<{
  retry: []
}>()

const { t } = useI18n()
const scrollElement = ref<HTMLElement | null>(null)
const followLatest = ref(true)
const itemCount = computed(() => props.sequence?.items.length ?? 0)

function record(value: JsonValue | undefined): Record<string, JsonValue> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : null
}

function payload(event: RuntimeMonitoringProtocolEvent): JsonValue | undefined {
  const params = record(event.envelope.params)
  const data = params?.data
  return Array.isArray(data) ? data[0] : data
}

function eventName(event: RuntimeMonitoringProtocolEvent): string {
  const value = record(payload(event))?.event
  return typeof value === 'string' ? value : event.method
}

function readableText(event: RuntimeMonitoringProtocolEvent): string {
  const value = payload(event)
  if (typeof value === 'string') return value
  const item = record(value)
  if (!item) return ''
  const delta = record(item.delta)
  if (delta?.type === 'text-delta' && typeof delta.text === 'string') return delta.text
  const content = record(item.content)
  if (content?.type === 'text' && typeof content.text === 'string') return content.text
  if (typeof item.text === 'string') return item.text
  return ''
}

function originDetails(event: RuntimeMonitoringProtocolEvent): string {
  const origin = event.origin
  const details = [t(`runtimeMonitoring.protocol.sourceTypes.${origin.source_type}`)]
  if (origin.workflow_node_id) {
    details.push(t('runtimeMonitoring.protocol.originNode', { id: origin.workflow_node_id }))
  }
  if (origin.node_invocation_id) {
    details.push(t('runtimeMonitoring.protocol.originInvocation', {
      id: origin.node_invocation_id,
    }))
  }
  if (origin.agent_profile_id) {
    details.push(t('runtimeMonitoring.protocol.originAgent', { id: origin.agent_profile_id }))
  }
  if (origin.subagent_profile_id) {
    details.push(t('runtimeMonitoring.protocol.originSubagent', {
      id: origin.subagent_profile_id,
    }))
  }
  return details.join(' · ')
}

function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2)
}

function localTime(value: string): string {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

function updateFollowState(): void {
  const element = scrollElement.value
  if (!element) return
  followLatest.value = element.scrollHeight - element.scrollTop - element.clientHeight < 24
}

function setFollowLatest(value: boolean): void {
  followLatest.value = value
  if (value) void nextTick(() => {
    const element = scrollElement.value
    if (element) element.scrollTop = element.scrollHeight
  })
}

watch(itemCount, async () => {
  if (!followLatest.value) return
  await nextTick()
  const element = scrollElement.value
  if (element) element.scrollTop = element.scrollHeight
})
</script>

<template>
  <section class="runtime-detail-section">
    <div class="runtime-detail-section-heading">
      <h3 class="h6 mb-0">{{ t('runtimeMonitoring.protocol.title') }}</h3>
      <LteButton
        v-if="sequence?.items.length"
        class="btn btn-sm btn-outline-secondary"
        type="button"
        @click="setFollowLatest(!followLatest)"
      >
        <i class="bi" :class="followLatest ? 'bi-pin-angle-fill' : 'bi-pin-angle'" aria-hidden="true" />
        {{ followLatest
          ? t('runtimeMonitoring.protocol.following')
          : t('runtimeMonitoring.protocol.followLatest') }}
      </LteButton>
    </div>

    <div v-if="loading && !sequence" class="d-flex align-items-center gap-2 p-3" role="status">
      <span class="spinner-border spinner-border-sm" aria-hidden="true" />
      {{ t('runtimeMonitoring.protocol.loading') }}
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
        {{ t('runtimeMonitoring.protocol.availability', {
          availability: t(`runtimeMonitoring.availability.${sequence.availability}`),
        }) }}
      </div>
      <p v-if="sequence.items.length === 0" class="m-0 p-3 text-body-secondary" role="status">
        {{ t('runtimeMonitoring.protocol.empty') }}
      </p>
      <ol
        v-else
        ref="scrollElement"
        class="runtime-protocol-stream list-unstyled mb-0"
        @scroll.passive="updateFollowState"
      >
        <li v-for="event in sequence.items" :key="event.sequence" class="runtime-protocol-event">
          <div class="d-flex flex-wrap align-items-center justify-content-between gap-2">
            <strong>{{ eventName(event) }}</strong>
            <span class="small text-body-secondary">
              #{{ event.sequence }} · {{ localTime(event.captured_at) }}
            </span>
          </div>
          <p v-if="readableText(event)" class="runtime-protocol-text mb-0">
            {{ readableText(event) }}
          </p>
          <p v-else class="small text-body-secondary mb-0">
            {{ t('runtimeMonitoring.protocol.structuredEvent', { method: event.method }) }}
          </p>
          <p class="small text-body-secondary text-break mt-2 mb-0">
            {{ originDetails(event) }}
          </p>
          <details class="mt-2">
            <summary>{{ t('runtimeMonitoring.protocol.rawEvent') }}</summary>
            <pre class="runtime-json mt-2 mb-0"><code>{{ pretty(event) }}</code></pre>
          </details>
        </li>
      </ol>
    </template>
  </section>
</template>
