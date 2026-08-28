<script setup lang="ts">
import { LteAlert, LteButton, LteTextarea } from '@adminlte/vue'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import {
  managementApi,
  type ResponseContentDelivery,
  type ResponseEventDelivery,
  type ResponseSourceVisibility,
  type ResponseStreamPolicy,
  type ResponseToolDelivery,
  type Workflow,
  type WorkflowGraphNode,
} from '@/api'
import ConfigurationEditorLayout from '@/components/ConfigurationEditorLayout.vue'
import FormField from '@/components/FormField.vue'
import PageShell from '@/components/PageShell.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const saved = ref(false)
const workflow = ref<Workflow | null>(null)
const graphNodes = ref<WorkflowGraphNode[]>([])
const form = ref<ResponseStreamPolicy>(defaultPolicy())

type ActivityTimingKey =
  | 'hidden_delta_pulse_seconds'
  | 'quiet_notice_after_seconds'
  | 'quiet_notice_repeat_seconds'

const contentDeliveries: ResponseContentDelivery[] = [
  'live',
  'complete',
  'activity',
  'hidden',
]
const eventDeliveries: ResponseEventDelivery[] = ['complete', 'activity', 'hidden']
const toolDeliveries: ResponseToolDelivery[] = ['paired', 'activity', 'hidden']

const executableNodes = computed(() => graphNodes.value.filter((node) => (
  ['agent', 'command', 'task-dispatcher'].includes(node.type)
)))

const preview = computed(() => {
  const reasoning = form.value.reasoning.live_wrapper
  const text = form.value.assistant_text.live_wrapper
  const ordering = form.value.queue.mode === 'fair_turns'
    ? t('workflows.responseStream.preview.fairTimeline')
    : t('workflows.responseStream.preview.strictTimeline')
  return [
    ordering,
    `${reasoning.start}${t('workflows.responseStream.preview.reasoning')}${reasoning.end}`,
    `${text.start}${t('workflows.responseStream.preview.answer')}${text.end}`,
    t('workflows.responseStream.preview.toolWait'),
    `${reasoning.start}${t('workflows.responseStream.preview.continuation')}${reasoning.end}`,
  ].join('\n')
})

function defaultPolicy(): ResponseStreamPolicy {
  return {
    queue: { mode: 'fair_turns', successor_grace_seconds: 2 },
    assistant_text: {
      delivery: 'live',
      live_wrapper: { start: '', end: '' },
    },
    reasoning: {
      delivery: 'live',
      live_wrapper: {
        start: '<details type="agent"><summary>Reasoning</summary>',
        end: '</details>\n',
      },
    },
    subagent_content: { delivery: 'hidden' },
    tools: { delivery: 'paired' },
    subagent_lifecycle: { delivery: 'activity' },
    workflow_custom: { delivery: 'complete' },
    workflow_lifecycle: { delivery: 'activity' },
    activity: {
      announce_start: true,
      announce_queued: true,
      hidden_delta_pulse_seconds: 15,
      quiet_notice_after_seconds: 30,
      quiet_notice_repeat_seconds: 60,
    },
    source_overrides: [],
  }
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  saved.value = false
  try {
    const id = String(route.params.id ?? '')
    const [loadedWorkflow, policy, graph] = await Promise.all([
      managementApi.getWorkflow(id),
      managementApi.getResponseStreamPolicy(id),
      managementApi.getWorkflowGraph(id),
    ])
    if (loadedWorkflow.workflow_role !== 'parent') {
      throw new Error(t('workflows.responseStream.parentOnly'))
    }
    workflow.value = loadedWorkflow
    form.value = clonePolicy(policy)
    graphNodes.value = graph.definition.nodes
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t('workflows.responseStream.loadFailed')
  } finally {
    loading.value = false
  }
}

async function save(): Promise<void> {
  if (!workflow.value || saving.value) return
  saving.value = true
  error.value = ''
  saved.value = false
  try {
    form.value = await managementApi.updateResponseStreamPolicy(
      workflow.value.id,
      clonePolicy(form.value),
    )
    saved.value = true
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t('workflows.responseStream.saveFailed')
  } finally {
    saving.value = false
  }
}

function back(): void {
  void router.push({ path: '/workflows/parents', query: workflow.value?.id ? { id: workflow.value.id } : {} })
}

function sourceVisibility(nodeId: string): ResponseSourceVisibility | 'inherit' {
  return form.value.source_overrides.find(
    (item) => item.workflow_node_id === nodeId,
  )?.visibility ?? 'inherit'
}

function setSourceVisibility(nodeId: string, rawValue: string): void {
  const retained = form.value.source_overrides.filter(
    (item) => item.workflow_node_id !== nodeId,
  )
  if (rawValue !== 'inherit') {
    retained.push({
      workflow_node_id: nodeId,
      visibility: rawValue as ResponseSourceVisibility,
    })
  }
  form.value.source_overrides = retained
}

function setOptionalNumber(key: ActivityTimingKey, event: Event): void {
  const value = (event.target as HTMLInputElement).value
  form.value.activity[key] = value === '' ? null : Number(value)
}

function deliveryLabel(value: string): string {
  return t(`workflows.responseStream.delivery.${value}`)
}

function nodeLabel(node: WorkflowGraphNode): string {
  return `${node.id} · ${t(`workflows.responseStream.nodeTypes.${node.type}`)}`
}

function clonePolicy(policy: ResponseStreamPolicy): ResponseStreamPolicy {
  return JSON.parse(JSON.stringify(policy)) as ResponseStreamPolicy
}

onMounted(() => { void load() })
</script>

<template>
  <PageShell>
    <LteAlert
      v-if="error"
      data-testid="response-stream-error"
      :title="t('workflows.responseStream.errorTitle')"
      theme="danger"
    >
      {{ error }}
    </LteAlert>
    <LteAlert
      v-if="saved"
      data-testid="response-stream-saved"
      :title="t('workflows.responseStream.saved')"
      theme="success"
    />

    <ConfigurationEditorLayout
      v-if="!loading"
      :loading="loading"
      layout-test-id="response-stream-layout"
    >
      <template #editor>
        <div class="card">
          <header class="card-header">
            <h1 class="card-title">
              {{ t('workflows.responseStream.title') }} · {{ workflow?.name }}
            </h1>
          </header>
          <div class="card-body">
            <p class="text-body-secondary">
              {{ t('workflows.responseStream.description') }}
            </p>
            <div class="row g-3" data-ui-control-row>
              <div class="col-lg-8">
                <FormField
                  control-id="response-queue-mode"
                  field-path="queue.mode"
                  label-key="workflows.responseStream.queue.mode"
                >
                  <select id="response-queue-mode" v-model="form.queue.mode" class="form-select">
                    <option value="fair_turns">{{ t('workflows.responseStream.queue.fair') }}</option>
                    <option value="strict_source">{{ t('workflows.responseStream.queue.strict') }}</option>
                  </select>
                </FormField>
              </div>
              <div class="col-lg-4">
                <FormField
                  control-id="response-successor-grace"
                  field-path="queue.successor_grace_seconds"
                  label-key="workflows.responseStream.queue.grace"
                >
                  <div class="input-group">
                    <input
                      id="response-successor-grace"
                      v-model.number="form.queue.successor_grace_seconds"
                      class="form-control"
                      min="0"
                      step="0.1"
                      type="number"
                    >
                    <span class="input-group-text">{{ t('workflows.seconds') }}</span>
                  </div>
                </FormField>
              </div>
            </div>
            <p class="mb-0 small text-body-secondary">
              {{ form.queue.mode === 'fair_turns'
                ? t('workflows.responseStream.queue.fairHint')
                : t('workflows.responseStream.queue.strictHint') }}
            </p>
          </div>
        </div>

        <div class="card mt-3">
          <header class="card-header"><h2 class="card-title">{{ t('workflows.responseStream.deliveryTitle') }}</h2></header>
          <div class="card-body">
            <div class="row g-3" data-ui-control-row>
              <div v-for="key in (['assistant_text', 'reasoning', 'subagent_content'] as const)" :key="key" class="col-lg-4">
                <FormField :control-id="`response-${key}`" :field-path="`${key}.delivery`" :label-key="`workflows.responseStream.events.${key}`">
                  <select :id="`response-${key}`" v-model="form[key].delivery" class="form-select">
                    <option v-for="delivery in contentDeliveries" :key="delivery" :value="delivery">{{ deliveryLabel(delivery) }}</option>
                  </select>
                </FormField>
              </div>
              <div class="col-lg-4">
                <FormField control-id="response-tools" field-path="tools.delivery" label-key="workflows.responseStream.events.tools">
                  <select id="response-tools" v-model="form.tools.delivery" class="form-select">
                    <option v-for="delivery in toolDeliveries" :key="delivery" :value="delivery">{{ deliveryLabel(delivery) }}</option>
                  </select>
                </FormField>
              </div>
              <div v-for="key in (['subagent_lifecycle', 'workflow_custom', 'workflow_lifecycle'] as const)" :key="key" class="col-lg-4">
                <FormField :control-id="`response-${key}`" :field-path="`${key}.delivery`" :label-key="`workflows.responseStream.events.${key}`">
                  <select :id="`response-${key}`" v-model="form[key].delivery" class="form-select">
                    <option v-for="delivery in eventDeliveries" :key="delivery" :value="delivery">{{ deliveryLabel(delivery) }}</option>
                  </select>
                </FormField>
              </div>
            </div>
          </div>
        </div>

        <div class="card mt-3">
          <header class="card-header"><h2 class="card-title">{{ t('workflows.responseStream.wrapperTitle') }}</h2></header>
          <div class="card-body">
            <p class="text-body-secondary">{{ t('workflows.responseStream.wrapperHint') }}</p>
            <div class="row g-3" data-ui-control-row>
              <div v-for="key in (['assistant_text', 'reasoning'] as const)" :key="key" class="col-lg-6">
                <h3 class="h6">{{ t(`workflows.responseStream.events.${key}`) }}</h3>
                <FormField :field-path="`${key}.live_wrapper.start`" label-key="workflows.responseStream.wrapperStart">
                  <LteTextarea v-model="form[key].live_wrapper.start" :rows="3" />
                </FormField>
                <FormField :field-path="`${key}.live_wrapper.end`" label-key="workflows.responseStream.wrapperEnd">
                  <LteTextarea v-model="form[key].live_wrapper.end" :rows="3" />
                </FormField>
              </div>
            </div>
          </div>
        </div>

        <div class="card mt-3">
          <header class="card-header"><h2 class="card-title">{{ t('workflows.responseStream.activityTitle') }}</h2></header>
          <div class="card-body">
            <div class="row g-3" data-ui-control-row>
              <div class="col-lg-6">
                <div class="form-check form-switch mb-3">
                  <input id="activity-start" v-model="form.activity.announce_start" class="form-check-input" type="checkbox">
                  <label class="form-check-label" for="activity-start">{{ t('workflows.responseStream.activity.announceStart') }}</label>
                </div>
                <div class="form-check form-switch">
                  <input id="activity-queued" v-model="form.activity.announce_queued" class="form-check-input" type="checkbox">
                  <label class="form-check-label" for="activity-queued">{{ t('workflows.responseStream.activity.announceQueued') }}</label>
                </div>
              </div>
              <div class="col-lg-6">
                <FormField
                  v-for="key in (['hidden_delta_pulse_seconds', 'quiet_notice_after_seconds', 'quiet_notice_repeat_seconds'] as const)"
                  :key="key"
                  :control-id="`activity-${key}`"
                  :field-path="`activity.${key}`"
                  :label-key="`workflows.responseStream.activity.${key}`"
                >
                  <div class="input-group">
                    <input
                      :id="`activity-${key}`"
                      class="form-control"
                      min="0.1"
                      :value="form.activity[key] ?? ''"
                      step="0.1"
                      type="number"
                      @input="setOptionalNumber(key, $event)"
                    >
                    <span class="input-group-text">{{ t('workflows.secondsOrDisabled') }}</span>
                  </div>
                </FormField>
              </div>
            </div>
          </div>
        </div>

        <div class="card mt-3">
          <header class="card-header"><h2 class="card-title">{{ t('workflows.responseStream.sourcesTitle') }}</h2></header>
          <div class="card-body">
            <p v-if="!executableNodes.length" class="mb-0 text-body-secondary">{{ t('workflows.responseStream.noSources') }}</p>
            <div v-else class="row g-3" data-ui-control-row>
              <div v-for="node in executableNodes" :key="node.id" class="col-lg-6">
                <label class="form-label" :for="`source-${node.id}`">{{ nodeLabel(node) }}</label>
                <select
                  :id="`source-${node.id}`"
                  class="form-select"
                  :value="sourceVisibility(node.id)"
                  @change="setSourceVisibility(node.id, ($event.target as HTMLSelectElement).value)"
                >
                  <option value="inherit">{{ t('workflows.responseStream.sources.inherit') }}</option>
                  <option value="activity_only">{{ t('workflows.responseStream.sources.activityOnly') }}</option>
                  <option value="hidden">{{ t('workflows.responseStream.sources.hidden') }}</option>
                </select>
              </div>
            </div>
          </div>
        </div>
      </template>

      <template #aside>
        <div class="card">
          <header class="card-header"><h2 class="card-title">{{ t('workflows.responseStream.preview.title') }}</h2></header>
          <div class="card-body">
            <pre class="mb-0 text-wrap" data-testid="response-stream-preview">{{ preview }}</pre>
          </div>
        </div>
        <LteAlert :title="t('workflows.responseStream.warnings.liveTitle')" theme="warning">
          {{ t('workflows.responseStream.warnings.live') }}
        </LteAlert>
        <LteAlert :title="t('workflows.responseStream.warnings.activityTitle')" theme="warning">
          {{ t('workflows.responseStream.warnings.activity') }}
        </LteAlert>
      </template>
    </ConfigurationEditorLayout>

    <template #actions>
      <LteButton class="action-button" type="button" @click="back">
        <i class="bi bi-arrow-left" aria-hidden="true" />
        {{ t('workflows.responseStream.back') }}
      </LteButton>
      <LteButton
        class="action-button"
        data-testid="response-stream-save"
        :disabled="loading || saving || !workflow"
        type="button"
        @click="save"
      >
        <span v-if="saving" class="spinner-border spinner-border-sm" aria-hidden="true" />
        <i v-else class="bi bi-floppy" aria-hidden="true" />
        {{ t('common.save') }}
      </LteButton>
    </template>
  </PageShell>
</template>
