<script setup lang="ts">
import {
  LteButton,
  LteTextarea,
} from '@adminlte/vue'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import FormField from '@/components/FormField.vue'
import type { FilesystemDefaults, FilesystemDraft } from '@/domain/blocks'

import { useEditorModel } from './shared/useEditorModel'

const props = defineProps<{
  modelValue: FilesystemDraft
  defaults: FilesystemDefaults
}>()
const emit = defineEmits<{ 'update:modelValue': [value: FilesystemDraft] }>()
const { t } = useI18n()
const draft = useEditorModel(() => props.modelValue, (value) => emit('update:modelValue', value))

const toolRows = computed(() => props.defaults.tools.flatMap((tool) => {
  const config = draft.tool_configs[tool.name]
  return config ? [{ tool, config }] : []
}))

function hasMappingValue(virtualPath: string, sourcePath: string): boolean {
  return Boolean(virtualPath.trim() || sourcePath.trim())
}

function isVirtualDirectoryPathInvalid(virtualPath: string, sourcePath: string): boolean {
  if (!hasMappingValue(virtualPath, sourcePath)) return false
  const value = virtualPath.trim()
  return !value.startsWith('/') || !value.endsWith('/')
}

function isVirtualFilePathInvalid(virtualPath: string, sourcePath: string): boolean {
  if (!hasMappingValue(virtualPath, sourcePath)) return false
  const value = virtualPath.trim()
  return !value.startsWith('/') || value.endsWith('/')
}
</script>

<template>
  <div data-editor="filesystem">
    <section class="card mb-3">
      <header class="card-header">
        <div>
          <h3 class="h5 fw-semibold mb-1">{{ t('editors.filesystem.mappedDirectoriesTitle') }}</h3>
          <p class="small text-body-secondary mb-0">{{ t('editors.filesystem.mappedDirectoriesHint') }}</p>
        </div>
      </header>
      <div class="card-body">
        <div v-if="draft.mapped_directories.length" class="filesystem-mapping-list">
          <div v-for="(item, index) in draft.mapped_directories" :key="index" class="filesystem-mapping-row" data-testid="mapped-directory-row">
            <div class="filesystem-mapping-secondary">
              <label class="visually-hidden" :for="`mapped-directory-local-path-${index}`">{{ t('fields.local_path') }}</label>
              <input :id="`mapped-directory-local-path-${index}`" v-model="item.local_path" class="form-control" :placeholder="t('editors.filesystem.mappingExamples.localDirectory')">
              <div class="d-flex flex-wrap gap-3 mt-2">
                <div class="d-flex gap-1" role="group" :aria-label="t('editors.filesystem.pathOriginLabel')">
                  <input :id="`mapped-directory-path-origin-absolute-${index}`" v-model="item.path_origin" class="btn-check" type="radio" value="absolute">
                  <label class="btn btn-sm btn-outline-primary" :for="`mapped-directory-path-origin-absolute-${index}`">{{ t('editors.filesystem.pathOrigins.absolute') }}</label>
                  <input :id="`mapped-directory-path-origin-relative-${index}`" v-model="item.path_origin" class="btn-check" type="radio" value="data-root-relative">
                  <label class="btn btn-sm btn-outline-primary" :for="`mapped-directory-path-origin-relative-${index}`">{{ t('editors.filesystem.pathOrigins.dataRootRelative') }}</label>
                </div>
                <div class="d-flex gap-1" role="group" :aria-label="t('editors.filesystem.lifecycleModeLabel')">
                  <input :id="`mapped-directory-lifecycle-fixed-${index}`" v-model="item.lifecycle_mode" class="btn-check" type="radio" value="fixed">
                  <label class="btn btn-sm btn-outline-primary" :for="`mapped-directory-lifecycle-fixed-${index}`">{{ t('editors.filesystem.lifecycleModes.fixed') }}</label>
                  <input :id="`mapped-directory-lifecycle-dynamic-${index}`" v-model="item.lifecycle_mode" class="btn-check" type="radio" value="dynamic">
                  <label class="btn btn-sm btn-outline-primary" :for="`mapped-directory-lifecycle-dynamic-${index}`">{{ t('editors.filesystem.lifecycleModes.dynamic') }}</label>
                </div>
              </div>
            </div>
            <div class="filesystem-mapping-arrow" aria-hidden="true"><i class="bi bi-arrow-right" /></div>
            <div class="filesystem-mapping-primary">
              <label class="visually-hidden" :for="`mapped-directory-virtual-path-${index}`">{{ t('fields.virtual_path') }}</label>
              <input :id="`mapped-directory-virtual-path-${index}`" v-model="item.virtual_path" class="form-control filesystem-mapping-input" :aria-invalid="isVirtualDirectoryPathInvalid(item.virtual_path, item.local_path)" :placeholder="t('editors.filesystem.mappingExamples.virtualDirectory')">
              <div v-if="isVirtualDirectoryPathInvalid(item.virtual_path, item.local_path)" class="invalid-feedback">{{ t('editors.filesystem.mappingValidation.virtualDirectoryPath') }}</div>
            </div>
            <div class="filesystem-mapping-actions">
              <LteButton class="icon-action-button" :aria-label="t('editors.common.remove')" :title="t('editors.common.remove')" size="sm" theme="danger" type="button" @click="draft.mapped_directories.splice(index, 1)"><i class="bi bi-trash" aria-hidden="true" /></LteButton>
            </div>
          </div>
        </div>
        <p v-else class="text-body-secondary mb-0">{{ t('editors.filesystem.emptyMappedDirectories') }}</p>
        <div class="simple-mapping-footer">
              <LteButton class="icon-action-button" :aria-label="t('editors.common.add')" :title="t('editors.common.add')" data-action="add-mapped-directory" size="sm" theme="primary" type="button" @click="draft.mapped_directories.push({ virtual_path: '', local_path: '', path_origin: 'absolute', lifecycle_mode: 'fixed' })"><i class="bi bi-plus-lg" aria-hidden="true" /></LteButton>
        </div>
      </div>
    </section>

    <section class="card mb-3">
      <header class="card-header">
        <div>
          <h3 class="h5 fw-semibold mb-1">{{ t('editors.filesystem.virtualDirectoriesTitle') }}</h3>
          <p class="small text-body-secondary mb-0">{{ t('editors.filesystem.virtualDirectoriesHint') }}</p>
        </div>
      </header>
      <div class="card-body">
        <div v-if="draft.virtual_directories.length" class="filesystem-mapping-list">
          <div v-for="(item, index) in draft.virtual_directories" :key="index" class="filesystem-mapping-row" data-testid="virtual-directory-row">
            <div class="filesystem-mapping-secondary">
              <label class="visually-hidden" :for="`virtual-directory-source-path-${index}`">{{ t('fields.source_path') }}</label>
              <input :id="`virtual-directory-source-path-${index}`" v-model="item.source_path" class="form-control" :placeholder="t('editors.filesystem.mappingExamples.sourceDirectory')">
            </div>
            <div class="filesystem-mapping-arrow" aria-hidden="true"><i class="bi bi-arrow-right" /></div>
            <div class="filesystem-mapping-primary">
              <label class="visually-hidden" :for="`virtual-directory-virtual-path-${index}`">{{ t('fields.virtual_path') }}</label>
              <input :id="`virtual-directory-virtual-path-${index}`" v-model="item.virtual_path" class="form-control filesystem-mapping-input" :aria-invalid="isVirtualDirectoryPathInvalid(item.virtual_path, item.source_path)" :placeholder="t('editors.filesystem.mappingExamples.virtualDirectory')">
              <div v-if="isVirtualDirectoryPathInvalid(item.virtual_path, item.source_path)" class="invalid-feedback">{{ t('editors.filesystem.mappingValidation.virtualDirectoryPath') }}</div>
            </div>
            <div class="filesystem-mapping-actions">
              <LteButton class="icon-action-button" :aria-label="t('editors.common.remove')" :title="t('editors.common.remove')" size="sm" theme="danger" type="button" @click="draft.virtual_directories.splice(index, 1)"><i class="bi bi-trash" aria-hidden="true" /></LteButton>
            </div>
          </div>
        </div>
        <p v-else class="text-body-secondary mb-0">{{ t('editors.filesystem.emptyVirtualDirectories') }}</p>
        <div class="simple-mapping-footer">
              <LteButton class="icon-action-button" :aria-label="t('editors.common.add')" :title="t('editors.common.add')" data-action="add-virtual-directory" size="sm" theme="primary" type="button" @click="draft.virtual_directories.push({ virtual_path: '', source_path: '' })"><i class="bi bi-plus-lg" aria-hidden="true" /></LteButton>
        </div>
      </div>
    </section>

    <section class="card mb-3">
      <header class="card-header">
        <div>
          <h3 class="h5 fw-semibold mb-1">{{ t('editors.filesystem.virtualFilesTitle') }}</h3>
          <p class="small text-body-secondary mb-0">{{ t('editors.filesystem.virtualFilesHint') }}</p>
        </div>
      </header>
      <div class="card-body">
        <div v-if="draft.virtual_files.length" class="filesystem-mapping-list">
          <div v-for="(item, index) in draft.virtual_files" :key="index" class="filesystem-mapping-row" data-testid="virtual-file-row">
            <div class="filesystem-mapping-secondary">
              <label class="visually-hidden" :for="`virtual-file-source-path-${index}`">{{ t('fields.source_path') }}</label>
              <input :id="`virtual-file-source-path-${index}`" v-model="item.source_path" class="form-control" :placeholder="t('editors.filesystem.mappingExamples.sourceFile')">
            </div>
            <div class="filesystem-mapping-arrow" aria-hidden="true"><i class="bi bi-arrow-right" /></div>
            <div class="filesystem-mapping-primary">
              <label class="visually-hidden" :for="`virtual-file-virtual-path-${index}`">{{ t('fields.virtual_path') }}</label>
              <input :id="`virtual-file-virtual-path-${index}`" v-model="item.virtual_path" class="form-control filesystem-mapping-input" :aria-invalid="isVirtualFilePathInvalid(item.virtual_path, item.source_path)" :placeholder="t('editors.filesystem.mappingExamples.virtualFile')">
              <div v-if="isVirtualFilePathInvalid(item.virtual_path, item.source_path)" class="invalid-feedback">{{ t('editors.filesystem.mappingValidation.virtualFilePath') }}</div>
            </div>
            <div class="filesystem-mapping-actions">
              <LteButton class="icon-action-button" :aria-label="t('editors.common.remove')" :title="t('editors.common.remove')" size="sm" theme="danger" type="button" @click="draft.virtual_files.splice(index, 1)"><i class="bi bi-trash" aria-hidden="true" /></LteButton>
            </div>
          </div>
        </div>
        <p v-else class="text-body-secondary mb-0">{{ t('editors.filesystem.emptyVirtualFiles') }}</p>
        <div class="simple-mapping-footer">
              <LteButton class="icon-action-button" :aria-label="t('editors.common.add')" :title="t('editors.common.add')" data-action="add-virtual-file" size="sm" theme="primary" type="button" @click="draft.virtual_files.push({ virtual_path: '', source_path: '' })"><i class="bi bi-plus-lg" aria-hidden="true" /></LteButton>
        </div>
      </div>
    </section>

    <section class="card mb-3">
      <header class="card-header">
        <h3 class="card-title">{{ t('editors.filesystem.systemPromptTitle') }}</h3>
      </header>
      <div class="card-body">
        <div class="d-flex justify-content-end mb-3">
              <LteButton class="action-button" theme="warning" @click="draft.system_prompt_override = defaults.system_prompt"><i class="bi bi-arrow-clockwise" aria-hidden="true" />{{ t('editors.common.restoreDefault') }}</LteButton>
        </div>
        <LteTextarea
          v-model="draft.system_prompt_override"
          :aria-label="t('editors.filesystem.systemPromptTitle')"
          :rows="14"
        />
      </div>
    </section>

    <section class="card mb-3" data-testid="filesystem-tool-constraints">
      <header class="card-header">
        <h3 class="card-title">{{ t('editors.filesystem.constraintsTitle') }}</h3>
      </header>
      <div class="card-body">
        <div class="row g-3">
          <div class="col-lg-3">
            <FormField control-id="filesystem-tool-token-limit" field-path="tool_token_limit_before_evict">
              <div class="input-group">
                <input id="filesystem-tool-token-limit" v-model.number="draft.tool_token_limit_before_evict" aria-describedby="filesystem-tool-token-limit-unit" class="form-control" min="1" step="1" type="number">
                <span id="filesystem-tool-token-limit-unit" class="input-group-text">{{ t('editors.filesystem.tokensUnit') }}</span>
              </div>
            </FormField>
          </div>
          <div class="col-lg-3">
            <FormField control-id="filesystem-human-message-token-limit" field-path="human_message_token_limit_before_evict">
              <div class="input-group">
                <input id="filesystem-human-message-token-limit" v-model.number="draft.human_message_token_limit_before_evict" aria-describedby="filesystem-human-message-token-limit-unit" class="form-control" min="1" step="1" type="number">
                <span id="filesystem-human-message-token-limit-unit" class="input-group-text">{{ t('editors.filesystem.tokensUnit') }}</span>
              </div>
            </FormField>
          </div>
          <div class="col-lg-3">
            <FormField control-id="filesystem-grep-max-count" field-path="grep_max_count">
              <div class="input-group">
                <input id="filesystem-grep-max-count" v-model.number="draft.grep_max_count" aria-describedby="filesystem-grep-max-count-unit" class="form-control" min="1" step="1" type="number">
                <span id="filesystem-grep-max-count-unit" class="input-group-text">{{ t('editors.filesystem.resultsUnit') }}</span>
              </div>
            </FormField>
          </div>
          <div class="col-lg-3">
            <FormField control-id="filesystem-max-execute-timeout" field-path="max_execute_timeout">
              <div class="input-group">
                <input id="filesystem-max-execute-timeout" v-model.number="draft.max_execute_timeout" aria-describedby="filesystem-max-execute-timeout-unit" class="form-control" min="1" step="1" type="number">
                <span id="filesystem-max-execute-timeout-unit" class="input-group-text">{{ t('editors.filesystem.secondsUnit') }}</span>
              </div>
            </FormField>
          </div>
        </div>
      </div>
    </section>

    <div class="row g-3">
      <div v-for="row in toolRows" :key="row.tool.name" class="col-md-6">
        <article class="card h-100" data-testid="filesystem-tool-card">
          <header class="card-header d-flex flex-wrap align-items-center justify-content-between gap-2">
            <h4 class="card-title mb-0 font-monospace">{{ row.tool.name }}</h4>
            <div class="form-check form-switch ms-auto">
              <input
                :id="`tool-visible-${row.tool.name}`"
                v-model="row.config.visible"
                class="form-check-input"
                :disabled="!row.tool.configurable"
                type="checkbox"
              >
              <label class="form-check-label" :for="`tool-visible-${row.tool.name}`">
                {{ row.config.visible ? t('editors.common.enabled') : t('editors.common.disabled') }}
              </label>
            </div>
          </header>
          <div class="card-body">
            <div class="d-flex justify-content-end mb-3">
              <LteButton class="action-button" theme="warning" @click="row.config.description_override = row.tool.default_description"><i class="bi bi-arrow-clockwise" aria-hidden="true" />{{ t('editors.common.restoreDefault') }}</LteButton>
            </div>
            <LteTextarea
              v-model="row.config.description_override"
              :aria-label="t('editors.filesystem.toolDescriptionLabel', { tool: row.tool.name })"
              :rows="8"
            />
          </div>
        </article>
      </div>
    </div>
  </div>
</template>
