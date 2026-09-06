<script setup lang="ts">
import { LteButton, LteTextarea } from '@adminlte/vue'
import { useI18n } from 'vue-i18n'

import type { TodoListDefaults, TodoListDraft } from '@/domain/blocks'

import { useEditorModel } from './shared/useEditorModel'

const props = defineProps<{
  modelValue: TodoListDraft
  defaults: TodoListDefaults
}>()
const emit = defineEmits<{ 'update:modelValue': [value: TodoListDraft] }>()
const { t } = useI18n()
const draft = useEditorModel(() => props.modelValue, (value) => emit('update:modelValue', value))
</script>

<template>
  <div data-editor="todo-list">
    <section class="card mb-3" data-testid="system-prompt-card">
      <header class="card-header">
        <h3 class="card-title">{{ t('editors.todoList.systemPromptTitle') }}</h3>
      </header>
      <div class="card-body">
        <div class="d-flex flex-wrap align-items-center gap-2 mb-3">
          <LteButton class="action-button ms-auto" data-action="restore-default" @click="draft.system_prompt_override = defaults.system_prompt">
            <i class="bi bi-arrow-clockwise" aria-hidden="true" />
            {{ t('editors.common.restoreDefault') }}
          </LteButton>
        </div>
        <LteTextarea
          v-model="draft.system_prompt_override"
          :aria-label="t('editors.todoList.systemPromptTitle')"
          :rows="14"
        />
      </div>
    </section>
    <section class="card mb-3" data-testid="tool-description-card">
      <header class="card-header">
        <h3 class="card-title">{{ t('editors.todoList.toolDescriptionTitle') }}</h3>
      </header>
      <div class="list-group list-group-flush">
        <div class="list-group-item" data-testid="tool-description-item">
          <div class="d-flex flex-wrap align-items-center gap-2 mb-2">
            <label class="form-label font-monospace mb-0" for="todo-list-write-todos-description">write_todos</label>
            <LteButton class="action-button ms-auto" data-action="restore-default" @click="draft.tool_description_override = defaults.tool_description">
              <i class="bi bi-arrow-clockwise" aria-hidden="true" />
              {{ t('editors.common.restoreDefault') }}
            </LteButton>
          </div>
          <LteTextarea
            id="todo-list-write-todos-description"
            v-model="draft.tool_description_override"
            :aria-label="t('editors.todoList.toolDescriptionTitle')"
            :rows="14"
          />
        </div>
      </div>
    </section>
  </div>
</template>
