<script setup lang="ts">
import { LteButton, LteTextarea } from '@adminlte/vue'
import { useI18n } from 'vue-i18n'

import FormField from '@/components/FormField.vue'
import type {
  SummarizationDefaults,
  SummarizationDraft,
  SummarizationThresholdDraft,
  SummarizationThresholdType,
} from '@/domain/blocks'
import { useEditorModel } from './shared/useEditorModel'

const props = defineProps<{
  modelValue: SummarizationDraft
  defaults: SummarizationDefaults
}>()
const emit = defineEmits<{ 'update:modelValue': [value: SummarizationDraft] }>()
const { t } = useI18n()
const draft = useEditorModel(() => props.modelValue, (value) => emit('update:modelValue', value))
const thresholdTypes: SummarizationThresholdType[] = ['auto', 'fraction', 'tokens', 'messages']

function thresholdDefaultValue(type: SummarizationThresholdType): number | null {
  if (type === 'auto') return null
  if (type === 'fraction') return 0.85
  if (type === 'messages') return 20
  return null
}

function setThresholdType(threshold: SummarizationThresholdDraft, event: Event): void {
  const type = (event.target as HTMLSelectElement).value as SummarizationThresholdType
  if (threshold.type === type) return
  threshold.type = type
  threshold.value = thresholdDefaultValue(type)
}
</script>

<template>
  <div data-editor="summarization">
    <section class="card mb-3" data-summarization-section="strategy">
      <header class="card-header">
        <h3 class="card-title h5 mb-0">{{ t('editors.summarization.strategyTitle') }}</h3>
      </header>
      <div class="card-body">
        <div class="row g-3">
          <div class="col-lg-6">
            <FormField
              control-id="summarization-trigger-type"
              field-path="trigger"
              label-key="editors.summarization.triggerRule"
            >
              <div class="input-group">
                <select
                  id="summarization-trigger-type"
                  :value="draft.trigger.type"
                  class="form-select"
                  @change="setThresholdType(draft.trigger, $event)"
                >
                  <option v-for="type in thresholdTypes" :key="type" :value="type">
                    {{ t(`editors.summarization.thresholdTypes.${type}`) }}
                  </option>
                </select>
                <input
                  v-if="draft.trigger.type !== 'auto'"
                  v-model.number="draft.trigger.value"
                  :aria-label="t('editors.summarization.triggerValue')"
                  class="form-control"
                  :max="draft.trigger.type === 'fraction' ? 1 : undefined"
                  :min="draft.trigger.type === 'fraction' ? 0.01 : 1"
                  :step="draft.trigger.type === 'fraction' ? 0.01 : 1"
                  type="number"
                >
              </div>
            </FormField>
          </div>
          <div class="col-lg-6">
            <FormField
              control-id="summarization-keep-type"
              field-path="keep"
              label-key="editors.summarization.keepRule"
            >
              <div class="input-group">
                <select
                  id="summarization-keep-type"
                  :value="draft.keep.type"
                  class="form-select"
                  @change="setThresholdType(draft.keep, $event)"
                >
                  <option v-for="type in thresholdTypes" :key="type" :value="type">
                    {{ t(`editors.summarization.thresholdTypes.${type}`) }}
                  </option>
                </select>
                <input
                  v-if="draft.keep.type !== 'auto'"
                  v-model.number="draft.keep.value"
                  :aria-label="t('editors.summarization.keepValue')"
                  class="form-control"
                  :max="draft.keep.type === 'fraction' ? 1 : undefined"
                  :min="draft.keep.type === 'fraction' ? 0.01 : 1"
                  :step="draft.keep.type === 'fraction' ? 0.01 : 1"
                  type="number"
                >
              </div>
            </FormField>
          </div>
        </div>
      </div>
    </section>

    <section class="card mb-3" data-summarization-section="tool-arguments">
      <header class="card-header d-flex flex-wrap align-items-center gap-2">
        <h3 class="card-title h5 mb-0">{{ t('editors.summarization.truncateArgsTitle') }}</h3>
        <div class="form-check form-switch ms-auto">
          <input
            id="summarization-truncate-args-enabled"
            v-model="draft.truncate_args_enabled"
            class="form-check-input"
            type="checkbox"
          >
          <label class="form-check-label" for="summarization-truncate-args-enabled">
            {{ t('editors.summarization.truncateArgsEnabled') }}
          </label>
        </div>
      </header>
      <div v-if="draft.truncate_args_enabled" class="card-body">
        <div class="row g-3">
          <div class="col-lg-6">
            <FormField
              control-id="summarization-truncate-trigger-type"
              field-path="truncate_args_trigger"
              label-key="editors.summarization.truncateTriggerRule"
            >
              <div class="input-group">
                <select
                  id="summarization-truncate-trigger-type"
                  :value="draft.truncate_args_trigger.type"
                  class="form-select"
                  @change="setThresholdType(draft.truncate_args_trigger, $event)"
                >
                  <option v-for="type in thresholdTypes" :key="type" :value="type">
                    {{ t(`editors.summarization.thresholdTypes.${type}`) }}
                  </option>
                </select>
                <input
                  v-if="draft.truncate_args_trigger.type !== 'auto'"
                  v-model.number="draft.truncate_args_trigger.value"
                  :aria-label="t('editors.summarization.truncateTriggerValue')"
                  class="form-control"
                  :max="draft.truncate_args_trigger.type === 'fraction' ? 1 : undefined"
                  :min="draft.truncate_args_trigger.type === 'fraction' ? 0.01 : 1"
                  :step="draft.truncate_args_trigger.type === 'fraction' ? 0.01 : 1"
                  type="number"
                >
              </div>
            </FormField>
          </div>
          <div class="col-lg-6">
            <FormField
              control-id="summarization-truncate-keep-type"
              field-path="truncate_args_keep"
              label-key="editors.summarization.truncateKeepRule"
            >
              <div class="input-group">
                <select
                  id="summarization-truncate-keep-type"
                  :value="draft.truncate_args_keep.type"
                  class="form-select"
                  @change="setThresholdType(draft.truncate_args_keep, $event)"
                >
                  <option v-for="type in thresholdTypes" :key="type" :value="type">
                    {{ t(`editors.summarization.thresholdTypes.${type}`) }}
                  </option>
                </select>
                <input
                  v-if="draft.truncate_args_keep.type !== 'auto'"
                  v-model.number="draft.truncate_args_keep.value"
                  :aria-label="t('editors.summarization.truncateKeepValue')"
                  class="form-control"
                  :max="draft.truncate_args_keep.type === 'fraction' ? 1 : undefined"
                  :min="draft.truncate_args_keep.type === 'fraction' ? 0.01 : 1"
                  :step="draft.truncate_args_keep.type === 'fraction' ? 0.01 : 1"
                  type="number"
                >
              </div>
            </FormField>
          </div>
          <div class="col-12">
            <FormField
              control-id="summarization-truncate-max-length"
              field-path="truncate_args_max_length"
            >
              <div class="input-group">
                <input
                  id="summarization-truncate-max-length"
                  v-model.number="draft.truncate_args_max_length"
                  aria-describedby="summarization-truncate-max-length-unit"
                  class="form-control"
                  min="1"
                  step="1"
                  type="number"
                >
                <span id="summarization-truncate-max-length-unit" class="input-group-text">
                  {{ t('editors.summarization.charactersUnit') }}
                </span>
              </div>
            </FormField>
          </div>
          <div class="col-12">
            <FormField
              :hint="t('editors.summarization.truncateArgsTextHint')"
              field-path="truncate_args_text"
            >
              <LteTextarea v-model="draft.truncate_args_text" :rows="3" />
            </FormField>
          </div>
        </div>
      </div>
    </section>

    <section class="card mb-3" data-summarization-section="generation">
      <header class="card-header d-flex flex-wrap align-items-center gap-2">
        <h3 class="card-title h5 mb-0">{{ t('editors.summarization.generationTitle') }}</h3>
        <div class="ms-auto">
          <LteButton
            class="action-button"
            data-action="restore-summary-prompt"
            size="sm"
            type="button"
            @click="draft.summary_prompt_override = defaults.summary_prompt_default"
          >
            <i class="bi bi-arrow-clockwise" aria-hidden="true" />
            {{ t('editors.summarization.restoreDefaultPrompt') }}
          </LteButton>
        </div>
      </header>
      <div class="card-body">
        <FormField
          control-id="summarization-trim-tokens"
          field-path="trim_tokens_to_summarize"
        >
          <div class="input-group">
            <input
              id="summarization-trim-tokens"
              v-model.number="draft.trim_tokens_to_summarize"
              aria-describedby="summarization-trim-tokens-unit"
              class="form-control"
              min="1"
              step="1"
              type="number"
            >
            <span id="summarization-trim-tokens-unit" class="input-group-text">
              {{ t('editors.summarization.tokensUnit') }}
            </span>
          </div>
        </FormField>
        <FormField :hint="t('editors.summarization.summaryPromptHint')" field-path="summary_prompt_override">
          <LteTextarea v-model="draft.summary_prompt_override" :rows="14" />
        </FormField>
      </div>
    </section>
  </div>
</template>
