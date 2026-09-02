<script setup lang="ts">
import { LteButton } from '@adminlte/vue'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type {
  JsonValue,
  RuntimeMonitoringAgentInvocationResponse,
  RuntimeMonitoringProtocolEventSequence,
} from '@/api'
import RuntimeProtocolEventList from '@/components/runtime-monitoring/RuntimeProtocolEventList.vue'

const props = defineProps<{
  invocationId: string
  artifact: RuntimeMonitoringAgentInvocationResponse | null
  artifactLoading: boolean
  artifactError: string
  protocol: RuntimeMonitoringProtocolEventSequence | null
  protocolLoading: boolean
  protocolError: string
}>()

const emit = defineEmits<{
  retryArtifact: []
  retryProtocol: []
}>()

const { t } = useI18n()

function record(value: JsonValue | undefined): Record<string, JsonValue> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : null
}

const messages = computed(() => {
  const value = props.artifact?.artifact?.messages
  return Array.isArray(value) ? value : []
})

function messageRole(message: JsonValue): string {
  const item = record(message)
  return typeof item?.role === 'string'
    ? item.role
    : typeof item?.type === 'string' ? item.type : t('runtimeMonitoring.agent.message')
}

function messageTextContent(message: JsonValue): string {
  const content = record(message)?.content
  if (typeof content === 'string') return content
  return ''
}

function messageBlocks(message: JsonValue): JsonValue[] {
  const content = record(message)?.content
  return Array.isArray(content) ? content : []
}

function blockText(block: JsonValue): string {
  const item = record(block)
  return typeof item?.text === 'string' ? item.text : ''
}

function blockType(block: JsonValue): string {
  const item = record(block)
  return typeof item?.type === 'string'
    ? item.type
    : t('runtimeMonitoring.agent.structuredBlock')
}

function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2)
}
</script>

<template>
  <div class="runtime-agent-invocation">
    <p v-if="!invocationId" class="m-0 p-3 text-body-secondary" role="status">
      {{ t('runtimeMonitoring.agent.selectInvocation') }}
    </p>
    <template v-else>
      <RuntimeProtocolEventList
        :error="protocolError"
        :loading="protocolLoading"
        :sequence="protocol"
        @retry="emit('retryProtocol')"
      />

      <section class="runtime-detail-section">
        <div class="runtime-detail-section-heading">
          <h3 class="h6 mb-0">{{ t('runtimeMonitoring.agent.completedArtifact') }}</h3>
        </div>
        <div
          v-if="artifactLoading && !artifact"
          class="d-flex align-items-center gap-2 p-3"
          role="status"
        >
          <span class="spinner-border spinner-border-sm" aria-hidden="true" />
          {{ t('runtimeMonitoring.agent.loadingArtifact') }}
        </div>
        <div v-if="artifactError" class="alert alert-danger m-3" role="alert">
          <p class="runtime-monitoring-error mb-3">{{ artifactError }}</p>
          <LteButton class="action-button" type="button" @click="emit('retryArtifact')">
            <i class="bi bi-arrow-clockwise" aria-hidden="true" />
            {{ t('common.retry') }}
          </LteButton>
        </div>
        <template v-if="artifact">
          <div
            v-if="artifact.availability !== 'available'"
            class="alert alert-info rounded-0 border-start-0 border-end-0 mb-0"
            role="status"
          >
            {{ t('runtimeMonitoring.agent.artifactAvailability', {
              availability: t(`runtimeMonitoring.availability.${artifact.availability}`),
            }) }}
          </div>
          <p v-if="messages.length === 0" class="m-0 p-3 text-body-secondary" role="status">
            {{ t('runtimeMonitoring.agent.noCompletedMessages') }}
          </p>
          <ol v-else class="list-group list-group-flush">
            <li v-for="(message, index) in messages" :key="index" class="list-group-item">
              <strong class="text-capitalize">{{ messageRole(message) }}</strong>
              <p v-if="messageTextContent(message)" class="mt-2 mb-0 text-break">
                {{ messageTextContent(message) }}
              </p>
              <div v-else-if="messageBlocks(message).length" class="d-grid gap-2 mt-2">
                <div v-for="(block, blockIndex) in messageBlocks(message)" :key="blockIndex">
                  <p v-if="blockText(block)" class="mb-0 text-break">
                    {{ blockText(block) }}
                  </p>
                  <div v-else>
                    <span class="badge text-bg-light border">{{ blockType(block) }}</span>
                    <pre class="runtime-json mt-2 mb-0"><code>{{ pretty(block) }}</code></pre>
                  </div>
                </div>
              </div>
              <pre v-else class="runtime-json mt-2 mb-0"><code>{{ pretty(message) }}</code></pre>
            </li>
          </ol>
          <details v-if="artifact.artifact" class="p-3 border-top">
            <summary>{{ t('runtimeMonitoring.agent.rawArtifact') }}</summary>
            <pre class="runtime-json mt-2 mb-0"><code>{{ pretty(artifact.artifact) }}</code></pre>
          </details>
        </template>
      </section>
    </template>
  </div>
</template>
