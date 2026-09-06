<script setup lang="ts">
import { LteButton, LteTextarea } from '@adminlte/vue'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import FormField from '@/components/FormField.vue'
import type { FilesystemToolsDefaults, FilesystemToolsDraft } from '@/domain/blocks'

import { useEditorModel } from './shared/useEditorModel'

const props = defineProps<{
  modelValue: FilesystemToolsDraft
  defaults: FilesystemToolsDefaults
}>()
const emit = defineEmits<{ 'update:modelValue': [value: FilesystemToolsDraft] }>()
const { t } = useI18n()
const draft = useEditorModel(() => props.modelValue, (value) => emit('update:modelValue', value))
const rows = computed(() => props.defaults.tools.flatMap((tool) => {
  const config = draft.tool_configs[tool.name]
  return config ? [{ tool, config }] : []
}))
</script>

<template>
  <div data-editor="filesystem-tools">
    <section class="card mb-3">
      <header class="card-header"><h3 class="card-title">{{ t('editors.filesystemTools.limitsTitle') }}</h3></header>
      <div class="card-body">
        <div class="row g-3">
          <FormField class="col-md-6" control-id="filesystem-tool-token-limit" field-path="tool_token_limit_before_evict">
            <div class="input-group">
              <input id="filesystem-tool-token-limit" v-model.number="draft.tool_token_limit_before_evict" aria-describedby="filesystem-tool-token-limit-unit" class="form-control" min="1" step="1" type="number">
              <span id="filesystem-tool-token-limit-unit" class="input-group-text">{{ t('editors.filesystemTools.tokensUnit') }}</span>
            </div>
          </FormField>
          <FormField class="col-md-6" control-id="filesystem-human-token-limit" field-path="human_message_token_limit_before_evict">
            <div class="input-group">
              <input id="filesystem-human-token-limit" v-model.number="draft.human_message_token_limit_before_evict" aria-describedby="filesystem-human-token-limit-unit" class="form-control" min="1" step="1" type="number">
              <span id="filesystem-human-token-limit-unit" class="input-group-text">{{ t('editors.filesystemTools.tokensUnit') }}</span>
            </div>
          </FormField>
          <FormField class="col-md-6" control-id="filesystem-grep-limit" field-path="grep_max_count">
            <div class="input-group">
              <input id="filesystem-grep-limit" v-model.number="draft.grep_max_count" aria-describedby="filesystem-grep-limit-unit" class="form-control" min="1" step="1" type="number">
              <span id="filesystem-grep-limit-unit" class="input-group-text">{{ t('editors.filesystemTools.resultsUnit') }}</span>
            </div>
          </FormField>
          <FormField class="col-md-6" control-id="filesystem-execute-timeout" field-path="max_execute_timeout">
            <div class="input-group">
              <input id="filesystem-execute-timeout" v-model.number="draft.max_execute_timeout" aria-describedby="filesystem-execute-timeout-unit" class="form-control" min="1" step="1" type="number">
              <span id="filesystem-execute-timeout-unit" class="input-group-text">{{ t('editors.filesystemTools.secondsUnit') }}</span>
            </div>
          </FormField>
        </div>
      </div>
    </section>

    <section class="card mb-3" data-testid="tool-description-card">
      <header class="card-header"><h3 class="card-title">{{ t('editors.filesystemTools.toolsTitle') }}</h3></header>
      <div class="list-group list-group-flush">
        <article v-for="row in rows" :key="row.tool.name" class="list-group-item" data-testid="tool-description-item">
          <div class="d-flex flex-wrap align-items-center gap-2 mb-2">
            <div v-if="row.tool.configurable" class="form-check form-switch">
              <input :id="`filesystem-tool-${row.tool.name}`" v-model="row.config.visible" class="form-check-input" type="checkbox">
              <label class="form-check-label font-monospace" :for="`filesystem-tool-${row.tool.name}`">{{ row.tool.name }}</label>
            </div>
            <label v-else class="form-label font-monospace mb-0" :for="`filesystem-tool-description-${row.tool.name}`">{{ row.tool.name }}</label>
            <LteButton class="action-button ms-auto" data-action="restore-default" type="button" @click="row.config.description_override = row.tool.default_description">
              <i class="bi bi-arrow-clockwise" aria-hidden="true" />
              {{ t('editors.common.restoreDefault') }}
            </LteButton>
          </div>
          <LteTextarea :id="`filesystem-tool-description-${row.tool.name}`" v-model="row.config.description_override" :aria-label="t('editors.filesystemTools.toolDescriptionLabel', { tool: row.tool.name })" :rows="4" />
        </article>
      </div>
    </section>
  </div>
</template>
