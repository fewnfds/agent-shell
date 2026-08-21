<script setup lang="ts">
import { LteTextarea } from '@adminlte/vue'
import { useI18n } from 'vue-i18n'

import type { SystemPromptDraft } from '@/domain/blocks'

import { useEditorModel } from './shared/useEditorModel'

const props = defineProps<{ modelValue: SystemPromptDraft }>()
const emit = defineEmits<{ 'update:modelValue': [value: SystemPromptDraft] }>()
const { t } = useI18n()
const draft = useEditorModel(() => props.modelValue, (value) => emit('update:modelValue', value))
</script>

<template>
  <div data-editor="system-prompt">
    <section class="card mb-3">
      <header class="card-header">
        <h3 class="card-title">{{ t('capabilities.system-prompt.label') }}</h3>
      </header>
      <div class="card-body">
        <LteTextarea
          v-model="draft.system_prompt"
          :aria-label="t('capabilities.system-prompt.label')"
          :rows="16"
          :placeholder="t('editors.systemPrompt.promptPlaceholder')"
        />
      </div>
    </section>
  </div>
</template>
