<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import FormField from '@/components/FormField.vue'
import type { ModelCallLimitDraft } from '@/domain/blocks'
import { useEditorModel } from './shared/useEditorModel'

const props = defineProps<{ modelValue: ModelCallLimitDraft }>()
const emit = defineEmits<{ 'update:modelValue': [value: ModelCallLimitDraft] }>()
const { t } = useI18n()
const draft = useEditorModel(() => props.modelValue, (value) => emit('update:modelValue', value))
</script>

<template>
  <div data-editor="model-call-limit">
    <div class="row g-3">
      <div class="col-lg-4">
        <FormField control-id="model-call-run-limit" field-path="run_limit">
          <input id="model-call-run-limit" v-model.number="draft.run_limit" class="form-control" min="1" step="1" type="number">
        </FormField>
      </div>
      <div class="col-lg-4">
        <FormField control-id="model-call-thread-limit" field-path="thread_limit">
          <input id="model-call-thread-limit" v-model.number="draft.thread_limit" class="form-control" min="1" step="1" type="number">
        </FormField>
      </div>
      <div class="col-lg-4">
        <FormField control-id="model-call-exit-behavior" field-path="exit_behavior">
          <select id="model-call-exit-behavior" v-model="draft.exit_behavior" class="form-select">
            <option value="end">{{ t('editors.callLimits.exitBehaviors.end') }}</option>
            <option value="error">{{ t('editors.callLimits.exitBehaviors.error') }}</option>
          </select>
        </FormField>
      </div>
    </div>
  </div>
</template>
