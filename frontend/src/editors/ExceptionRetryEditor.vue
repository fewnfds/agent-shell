<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import FormField from '@/components/FormField.vue'
import type {
  ExceptionRetryCondition,
  ExceptionRetryDefaults,
  ExceptionRetryDraft,
} from '@/domain/blocks'

import { useEditorModel } from './shared/useEditorModel'

const props = defineProps<{
  modelValue: ExceptionRetryDraft
  defaults: ExceptionRetryDefaults
}>()
const emit = defineEmits<{ 'update:modelValue': [value: ExceptionRetryDraft] }>()
const { t } = useI18n()
const draft = useEditorModel(() => props.modelValue, (value) => emit('update:modelValue', value))

function conditionEnabled(condition: ExceptionRetryCondition): boolean {
  return draft.retry_on.includes(condition)
}

function setCondition(condition: ExceptionRetryCondition, enabled: boolean): void {
  draft.retry_on = enabled
    ? [...new Set([...draft.retry_on, condition])]
    : draft.retry_on.filter((item) => item !== condition)
}

function onConditionChange(condition: ExceptionRetryCondition, event: Event): void {
  setCondition(condition, (event.target as HTMLInputElement).checked)
}
</script>

<template>
  <div class="row g-3" data-editor="exception-retry">
    <div
      v-for="strategy in defaults.strategies"
      :key="strategy"
      class="col-12 col-lg-6"
    >
      <section
        class="card h-100"
        :data-testid="strategy === 'provider_native' ? 'retry-owner' : 'middleware-policy'"
      >
        <header class="card-header">
          <div class="form-check mb-0">
            <input
              :id="`retry-strategy-${strategy}`"
              v-model="draft.strategy"
              class="form-check-input"
              name="exception-retry-strategy"
              type="radio"
              :value="strategy"
            >
            <label class="form-check-label fw-semibold" :for="`retry-strategy-${strategy}`">
              {{ t(`editors.exceptionRetry.strategies.${strategy}.label`) }}
            </label>
          </div>
        </header>

        <div class="card-body">
          <fieldset :disabled="draft.strategy !== strategy">
            <legend class="visually-hidden">{{ t(`editors.exceptionRetry.strategies.${strategy}.label`) }}</legend>

            <div class="form-check form-switch mb-3">
              <input
                :id="`force-non-streaming-${strategy}`"
                v-model="draft.force_non_streaming"
                class="form-check-input"
                type="checkbox"
              >
              <label class="form-check-label" :for="`force-non-streaming-${strategy}`">
                {{ t('editors.exceptionRetry.forceNonStreamingLabel') }}
              </label>
            </div>

            <FormField field-path="max_retries">
              <input :id="`max-retries-${strategy}`" v-model.number="draft.max_retries" class="form-control" min="0" step="1" type="number">
            </FormField>

            <fieldset v-if="strategy === 'model_retry_middleware'">
              <legend class="fw-semibold mb-3">{{ t('editors.exceptionRetry.conditionsTitle') }}</legend>
              <div v-for="condition in defaults.conditions" :key="condition" class="form-check mb-3">
                <input
                  :id="`retry-${condition}`"
                  class="form-check-input"
                  type="checkbox"
                  :checked="conditionEnabled(condition)"
                  @change="onConditionChange(condition, $event)"
                >
                <label class="form-check-label" :for="`retry-${condition}`">
                  {{ t(`editors.exceptionRetry.conditions.${condition}.label`) }}
                </label>
                <div class="form-text">{{ t(`editors.exceptionRetry.conditions.${condition}.hint`) }}</div>
              </div>
            </fieldset>
          </fieldset>
        </div>
      </section>
    </div>
  </div>
</template>
