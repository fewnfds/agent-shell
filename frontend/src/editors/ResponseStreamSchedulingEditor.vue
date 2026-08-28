<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import FormField from '@/components/FormField.vue'
import type { ResponseStreamSchedulingDraft } from '@/domain/blocks'

import { useEditorModel } from './shared/useEditorModel'

const props = defineProps<{ modelValue: ResponseStreamSchedulingDraft }>()
const emit = defineEmits<{
  'update:modelValue': [value: ResponseStreamSchedulingDraft]
}>()
const { t } = useI18n()
const draft = useEditorModel(
  () => props.modelValue,
  (value) => emit('update:modelValue', value),
)
</script>

<template>
  <section data-editor="response-stream-scheduling">
    <p class="text-body-secondary">
      {{ t('workflows.responseStream.description') }}
    </p>
    <div class="row g-3" data-ui-control-row>
      <div class="col-lg-3">
        <FormField control-id="response-queue-strategy" field-path="queue.strategy" label-key="workflows.responseStream.queue.strategy">
          <select id="response-queue-strategy" v-model="draft.queue.strategy" class="form-select">
            <option value="request">{{ t('workflows.responseStream.queue.request') }}</option>
            <option value="node_invocation">{{ t('workflows.responseStream.queue.nodeInvocation') }}</option>
          </select>
        </FormField>
      </div>
      <div class="col-lg-3">
        <FormField control-id="response-idle-timeout" field-path="queue.idle_timeout_seconds" label-key="workflows.responseStream.queue.idleTimeout">
          <div class="input-group">
            <input id="response-idle-timeout" v-model.number="draft.queue.idle_timeout_seconds" aria-describedby="response-idle-timeout-unit" class="form-control" min="0" step="0.1" type="number">
            <span id="response-idle-timeout-unit" class="input-group-text">{{ t('workflows.seconds') }}</span>
          </div>
        </FormField>
      </div>
      <div class="col-lg-3">
        <FormField control-id="response-max-batch" field-path="queue.max_batch_kb" label-key="workflows.responseStream.queue.maxBatch">
          <div class="input-group">
            <input id="response-max-batch" v-model.number="draft.queue.max_batch_kb" aria-describedby="response-max-batch-unit" class="form-control" min="0.001" step="any" type="number">
            <span id="response-max-batch-unit" class="input-group-text">{{ t('workflows.kilobytes') }}</span>
          </div>
        </FormField>
      </div>
      <div class="col-lg-3">
        <FormField control-id="response-send-interval" field-path="queue.send_interval_seconds" label-key="workflows.responseStream.queue.sendInterval">
          <div class="input-group">
            <input id="response-send-interval" v-model.number="draft.queue.send_interval_seconds" aria-describedby="response-send-interval-unit" class="form-control" min="0" step="0.01" type="number">
            <span id="response-send-interval-unit" class="input-group-text">{{ t('workflows.seconds') }}</span>
          </div>
        </FormField>
      </div>
    </div>
    <p class="mb-0 small text-body-secondary">
      {{ draft.queue.strategy === 'request'
        ? t('workflows.responseStream.queue.requestHint')
        : t('workflows.responseStream.queue.nodeInvocationHint') }}
    </p>
    <p class="mb-0 mt-1 small text-body-secondary">
      {{ t('workflows.responseStream.queue.batchHint') }}
    </p>
  </section>
</template>
