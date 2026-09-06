<script setup lang="ts">
import { LteButton, LteTextarea } from '@adminlte/vue'
import { useI18n } from 'vue-i18n'

import {
  asyncSubagentToolNames,
  type AsyncSubagentDefaults,
  type AsyncSubagentDescriptionField,
  type AsyncSubagentDraft,
  type AsyncSubagentToolName,
} from '@/domain/blocks'
import { useEditorModel } from './shared/useEditorModel'

const props = defineProps<{
  modelValue: AsyncSubagentDraft
  defaults: AsyncSubagentDefaults
}>()
const emit = defineEmits<{ 'update:modelValue': [value: AsyncSubagentDraft] }>()
const { t } = useI18n()
const draft = useEditorModel(() => props.modelValue, (value) => emit('update:modelValue', value))

function fieldFor(toolName: AsyncSubagentToolName): AsyncSubagentDescriptionField {
  return `${toolName}_description_override`
}

function updateDescription(toolName: AsyncSubagentToolName, value: string): void {
  draft[fieldFor(toolName)] = value
}
</script>

<template>
  <div data-editor="async-subagent">
    <section class="card mb-3">
      <header class="card-header">
        <h3 class="card-title">{{ t('editors.asyncSubagent.systemPromptTitle') }}</h3>
      </header>
      <div class="card-body">
        <div class="d-flex justify-content-end mb-3">
          <LteButton class="action-button" data-action="restore-default" @click="draft.system_prompt_override = defaults.system_prompt">
            <i class="bi bi-arrow-clockwise" aria-hidden="true" />
            {{ t('editors.common.restoreDefault') }}
          </LteButton>
        </div>
        <LteTextarea
          v-model="draft.system_prompt_override"
          :aria-label="t('editors.asyncSubagent.systemPromptTitle')"
          :rows="8"
        />
      </div>
    </section>

    <section class="card mb-3">
      <header class="card-header">
        <h3 class="card-title">{{ t('editors.asyncSubagent.toolDescriptionsTitle') }}</h3>
      </header>
      <div class="list-group list-group-flush">
        <div v-for="toolName in asyncSubagentToolNames" :key="toolName" class="list-group-item">
          <div class="d-flex flex-wrap align-items-center justify-content-between gap-2 mb-2">
            <label class="form-label font-monospace mb-0" :for="`async-subagent-${toolName}`">{{ toolName }}</label>
            <LteButton
              class="action-button"
              data-action="restore-default"
              size="sm"
              @click="updateDescription(toolName, defaults.tool_descriptions[toolName])"
            >
              <i class="bi bi-arrow-clockwise" aria-hidden="true" />
              {{ t('editors.common.restoreDefault') }}
            </LteButton>
          </div>
          <LteTextarea
            :id="`async-subagent-${toolName}`"
            :model-value="draft[fieldFor(toolName)]"
            :rows="toolName === 'start_async_task' ? 12 : 5"
            @update:model-value="updateDescription(toolName, $event)"
          />
          <p v-if="toolName === 'start_async_task'" class="form-text mb-0">
            {{ t('editors.asyncSubagent.availableAgentsHint') }}
          </p>
        </div>
      </div>
    </section>
  </div>
</template>
