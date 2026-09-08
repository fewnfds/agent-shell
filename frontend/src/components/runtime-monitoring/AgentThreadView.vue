<script setup lang="ts">
import type { BaseMessage } from '@langchain/core/messages'
import { useStream, type AssembledToolCall } from '@langchain/vue'
import MarkdownRender from 'markstream-vue'
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { managementAuthorizedFetch } from '@/api'

import StructuredValueTree from './StructuredValueTree.vue'
import ToolActivityRow from './ToolActivityRow.vue'

interface DisplayToolCall {
  id?: string
  name?: string
  args?: unknown
}

const SERVER_RUN_ERROR_PREFIX = 'agent-shell.runtime-error.v1:'

type MessageBlock =
  | { kind: 'text' | 'reasoning', id: string, text: string }
  | { kind: 'tool', id: string, call: DisplayToolCall }

const props = defineProps<{
  assistantId: string
  threadId: string
}>()

const emit = defineEmits<{
  state: [value: Record<string, unknown>]
}>()

const { t } = useI18n()
const viewport = ref<HTMLElement | null>(null)
const following = ref(true)
const stream = useStream<Record<string, unknown>>({
  assistantId: props.assistantId,
  threadId: props.threadId,
  apiUrl: window.location.origin,
  callerOptions: { fetch: managementAuthorizedFetch },
  fetch: managementAuthorizedFetch,
  fetchStateHistory: false,
})
const streamedMessages = stream.messages
const streamedToolCalls = stream.toolCalls
const streamedInterrupts = stream.interrupts
const streamingError = stream.error
const streaming = stream.isLoading
const hydrating = stream.isThreadLoading

const declaredToolCallIds = computed(() => new Set(
  stream.messages.value.flatMap((message) => toolCalls(message).map((call) => call.id ?? '')),
))

function messageType(message: BaseMessage): string {
  return message.type
}

function messageKey(message: BaseMessage, index: number): string {
  return message.id ?? `${message.type}-${index}`
}

function messageBlocks(message: BaseMessage): MessageBlock[] {
  return message.contentBlocks.flatMap((block, index) => {
    if (block.type === 'text' && typeof block.text === 'string') {
      return [{ kind: 'text' as const, text: block.text, id: String(block.id ?? `text-${index}`) }]
    }
    if (block.type === 'reasoning' && typeof block.reasoning === 'string') {
      return [{ kind: 'reasoning' as const, text: block.reasoning, id: String(block.id ?? `reasoning-${index}`) }]
    }
    if (block.type === 'tool_call' && typeof block.name === 'string') {
      const id = typeof block.id === 'string' ? block.id : ''
      return [{
        kind: 'tool' as const,
        id: id || `tool-${index}`,
        call: { id, name: block.name, args: block.args },
      }]
    }
    return []
  })
}

function toolCalls(message: BaseMessage): DisplayToolCall[] {
  const value = (message as BaseMessage & { tool_calls?: unknown }).tool_calls
  return Array.isArray(value) ? value as DisplayToolCall[] : []
}

function toolResult(callId: string): (BaseMessage & { tool_call_id?: string, status?: string }) | undefined {
  return stream.messages.value.find((message) => (
    message.type === 'tool'
    && (message as BaseMessage & { tool_call_id?: string }).tool_call_id === callId
  )) as (BaseMessage & { tool_call_id?: string, status?: string }) | undefined
}

function liveTool(callId: string): AssembledToolCall | undefined {
  return stream.toolCalls.value.find((tool) => tool.callId === callId)
}

function toolStatus(call: DisplayToolCall): 'running' | 'finished' | 'error' {
  const active = liveTool(call.id ?? '')
  if (active) return active.status
  const result = toolResult(call.id ?? '')
  return result?.status === 'error' ? 'error' : result ? 'finished' : 'running'
}

function toolOutput(call: DisplayToolCall): unknown {
  const active = liveTool(call.id ?? '')
  if (active?.status === 'finished') return active.output
  return toolResult(call.id ?? '')?.content
}

function toolError(call: DisplayToolCall): string | undefined {
  const active = liveTool(call.id ?? '')
  if (active?.error) return active.error
  const result = toolResult(call.id ?? '')
  return result?.status === 'error' ? result.text : undefined
}

function orphanToolId(message: BaseMessage): string {
  return String((message as BaseMessage & { tool_call_id?: string }).tool_call_id ?? '')
}

function streamError(): string {
  const value = stream.error.value
  const message = value instanceof Error ? value.message : String(value ?? '')
  if (!message.startsWith(SERVER_RUN_ERROR_PREFIX)) return message
  try {
    const payload: unknown = JSON.parse(message.slice(SERVER_RUN_ERROR_PREFIX.length))
    if (
      typeof payload === 'object'
      && payload !== null
      && 'message' in payload
      && typeof payload.message === 'string'
      && payload.message
    ) {
      return payload.message
    }
  } catch {
    return message
  }
  return message
}

function onScroll(): void {
  const element = viewport.value
  if (!element) return
  following.value = element.scrollHeight - element.scrollTop - element.clientHeight < 48
}

async function scrollToBottom(): Promise<void> {
  following.value = true
  await nextTick()
  viewport.value?.scrollTo({ top: viewport.value.scrollHeight })
}

watch(stream.values, (value) => emit('state', value))
watch([stream.messages, stream.toolCalls, stream.interrupts], async () => {
  if (following.value) await scrollToBottom()
}, { deep: true })
</script>

<template>
  <section class="agent-thread" :aria-label="t('runtimeMonitoring.agent.title')">
    <div ref="viewport" class="agent-thread-feed" @scroll.passive="onScroll">
      <div v-if="hydrating" class="agent-thread-loading" aria-busy="true">
        <span class="spinner-border spinner-border-sm" aria-hidden="true" />
      </div>

      <template v-for="(message, index) in streamedMessages" :key="messageKey(message, index)">
        <article v-if="messageType(message) === 'human'" class="agent-message agent-message--human">
          <MarkdownRender mode="chat" :content="message.text" :final="true" />
        </article>

        <article v-else-if="messageType(message) === 'ai'" class="agent-message agent-message--ai">
          <template v-for="block in messageBlocks(message)" :key="block.id">
            <details
              v-if="block.kind === 'reasoning'"
              class="agent-reasoning"
              :open="streaming && index === streamedMessages.length - 1"
            >
              <summary>{{ t('runtimeMonitoring.agent.reasoning') }}</summary>
              <MarkdownRender
                mode="chat"
                :content="block.text"
                :final="!streaming || index < streamedMessages.length - 1"
              />
            </details>
            <MarkdownRender
              v-else-if="block.kind === 'text'"
              mode="chat"
              :content="block.text"
              :final="!streaming || index < streamedMessages.length - 1"
            />
            <ToolActivityRow
              v-else
              :name="block.call.name ?? t('runtimeMonitoring.agent.tool')"
              :call-id="block.call.id ?? ''"
              :status="toolStatus(block.call)"
              :input="block.call.args"
              :output="toolOutput(block.call)"
              :error="toolError(block.call)"
            />
          </template>
        </article>

        <ToolActivityRow
          v-else-if="messageType(message) === 'tool' && !declaredToolCallIds.has(orphanToolId(message))"
          :name="message.name ?? t('runtimeMonitoring.agent.tool')"
          :call-id="orphanToolId(message)"
          :status="(message as BaseMessage & { status?: string }).status === 'error' ? 'error' : 'finished'"
          :input="null"
          :output="message.content"
          :error="(message as BaseMessage & { status?: string }).status === 'error' ? message.text : undefined"
        />

        <article v-else-if="messageType(message) !== 'tool'" class="agent-message agent-message--system">
          <MarkdownRender mode="chat" :content="message.text" :final="true" />
        </article>
      </template>

      <ToolActivityRow
        v-for="tool in streamedToolCalls.filter((value) => !declaredToolCallIds.has(value.callId))"
        :key="tool.callId"
        :name="tool.name"
        :call-id="tool.callId"
        :status="tool.status"
        :input="tool.input"
        :output="tool.output"
        :error="tool.error"
      />

      <div v-for="interrupt in streamedInterrupts" :key="interrupt.id" class="agent-event-row">
        <i class="bi bi-pause-circle" aria-hidden="true" />
        <StructuredValueTree :name="t('runtimeMonitoring.agent.interrupt')" :value="interrupt.value" />
      </div>

      <div v-if="streamingError" class="agent-event-row agent-event-row--error" role="alert">
        <i class="bi bi-exclamation-triangle" aria-hidden="true" />
        <span>{{ streamError() }}</span>
      </div>
    </div>

    <button
      v-if="!following"
      class="btn btn-outline-secondary agent-thread-bottom"
      type="button"
      :aria-label="t('runtimeMonitoring.agent.toBottom')"
      @click="scrollToBottom"
    >
      <i class="bi bi-arrow-down" aria-hidden="true" />
    </button>
  </section>
</template>

<style scoped>
.agent-thread {
  position: relative;
  height: 100%;
  min-height: 30rem;
}

.agent-thread-feed {
  height: 100%;
  overflow: auto;
  padding: 1rem;
}

.agent-thread-loading {
  color: var(--bs-secondary-color);
}

.agent-message {
  width: min(100%, 58rem);
  margin-block: 0 1.25rem;
  overflow-wrap: anywhere;
}

.agent-message--human {
  width: fit-content;
  max-width: min(85%, 42rem);
  margin-inline-start: auto;
  padding: .65rem .85rem;
  border: 1px solid var(--bs-border-color);
  border-radius: var(--bs-border-radius-lg);
  background: var(--bs-tertiary-bg);
}

.agent-message--ai,
.agent-message--system {
  margin-inline-end: auto;
}

.agent-message--system {
  padding-inline-start: .75rem;
  border-inline-start: 2px solid var(--bs-border-color);
  color: var(--bs-secondary-color);
}

.agent-reasoning {
  margin-block: .5rem .75rem;
  padding-inline-start: .8rem;
  border-inline-start: 2px solid var(--bs-border-color);
  color: var(--bs-secondary-color);
}

.agent-reasoning summary {
  margin-block-end: .35rem;
  font-size: .75rem;
  font-weight: 600;
  cursor: pointer;
}

.agent-event-row {
  display: flex;
  align-items: flex-start;
  gap: .5rem;
  width: min(100%, 58rem);
  margin-block: .75rem;
  padding-block: .55rem;
  border-block: 1px solid var(--bs-border-color);
}

.agent-event-row--error {
  color: var(--bs-danger-text-emphasis);
}

.agent-thread-bottom {
  position: absolute;
  inset-inline-end: 1rem;
  inset-block-end: 1rem;
  width: 2.4rem;
  height: 2.4rem;
  padding: 0;
  border-radius: 50%;
}

:deep(.markstream-vue) {
  --ms-flow-paragraph-y: .75em;

  color: inherit;
  background: transparent;
}
</style>
