<script setup lang="ts">
import { LteButton, LteTextarea } from '@adminlte/vue'
import { useI18n } from 'vue-i18n'

import type { SubagentDefaults, SubagentDraft } from '@/domain/blocks'

import { useEditorModel } from './shared/useEditorModel'

const props = defineProps<{
  modelValue: SubagentDraft
  defaults: SubagentDefaults
}>()
const emit = defineEmits<{ 'update:modelValue': [value: SubagentDraft] }>()
const { t } = useI18n()
const draft = useEditorModel(() => props.modelValue, (value) => emit('update:modelValue', value))
</script>

<template>
  <div data-editor="subagent">
    <section class="card mb-3">
      <header class="card-header">
        <h3 class="card-title">{{ t('editors.subagent.instructionTitle') }}</h3>
      </header>
      <div class="card-body">
        <div class="d-flex justify-content-end mb-3">
          <LteButton class="action-button" data-action="restore-default" @click="draft.instruction_override = defaults.system_prompt">
            <i class="bi bi-arrow-clockwise" aria-hidden="true" />
            {{ t('editors.common.restoreDefault') }}
          </LteButton>
        </div>
        <LteTextarea
          v-model="draft.instruction_override"
          :aria-label="t('editors.subagent.instructionTitle')"
          :rows="14"
        />
      </div>
    </section>
    <section class="card mb-3">
      <header class="card-header">
        <h3 class="card-title">{{ t('editors.subagent.taskDescriptionTitle') }}</h3>
      </header>
      <div class="card-body">
        <div class="d-flex justify-content-end mb-3">
          <LteButton class="action-button" data-action="restore-default" @click="draft.task_description_override = defaults.tool_description">
            <i class="bi bi-arrow-clockwise" aria-hidden="true" />
            {{ t('editors.common.restoreDefault') }}
          </LteButton>
        </div>
        <LteTextarea
          v-model="draft.task_description_override"
          :aria-label="t('editors.subagent.taskDescriptionTitle')"
          :rows="14"
        />
      </div>
    </section>
  </div>
</template>
