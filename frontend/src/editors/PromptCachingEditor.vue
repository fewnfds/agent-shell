<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import FormField from '@/components/FormField.vue'
import type { PromptCachingDefaults, PromptCachingDraft } from '@/domain/blocks'
import { useEditorModel } from './shared/useEditorModel'

const props = defineProps<{
  modelValue: PromptCachingDraft
  defaults: PromptCachingDefaults
}>()
const emit = defineEmits<{ 'update:modelValue': [value: PromptCachingDraft] }>()
const { t } = useI18n()
const draft = useEditorModel(() => props.modelValue, (value) => emit('update:modelValue', value))
</script>

<template>
  <div data-editor="prompt-caching">
    <div class="row g-3">
      <div class="col-lg-4">
        <FormField field-path="type">
          <select v-model="draft.type" class="form-select" disabled>
            <option value="ephemeral">{{ t('editors.promptCaching.cacheTypes.ephemeral') }}</option>
          </select>
        </FormField>
      </div>
      <div class="col-lg-4">
        <FormField field-path="ttl">
          <select v-model="draft.ttl" class="form-select">
            <option value="5m">5m</option>
            <option value="1h">1h</option>
          </select>
        </FormField>
      </div>
      <div class="col-lg-4">
        <FormField field-path="min_messages_to_cache">
          <input v-model.number="draft.min_messages_to_cache" class="form-control" min="0" step="1" type="number">
        </FormField>
      </div>
    </div>
  </div>
</template>
