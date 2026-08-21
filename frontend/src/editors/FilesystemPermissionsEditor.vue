<script setup lang="ts">
import { LteButton, LteTextarea } from '@adminlte/vue'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import FormField from '@/components/FormField.vue'
import type {
  FilesystemImportSource,
  FilesystemPermissionsDefaults,
  FilesystemPermissionsDraft,
  FilesystemPermissionValue,
} from '@/domain/blocks'

import { useEditorModel } from './shared/useEditorModel'

const props = defineProps<{
  modelValue: FilesystemPermissionsDraft
  defaults: FilesystemPermissionsDefaults
  filesystems: FilesystemImportSource[]
}>()
const emit = defineEmits<{ 'update:modelValue': [value: FilesystemPermissionsDraft] }>()
const { t } = useI18n()
const draft = useEditorModel(() => props.modelValue, (value) => emit('update:modelValue', value))

const importFilesystemId = ref('')
const permissionOptions: FilesystemPermissionValue[] = ['read-write', 'read-only', 'no-access']
const toolRows = computed(() => props.defaults.tools.flatMap((tool) => {
  const override = draft.tool_overrides[tool.name]
  return override ? [{ tool, override }] : []
}))

function addPermission(): void {
  draft.permissions.push({ path: '', permission: 'read-only' })
}

function movePermission(index: number, offset: -1 | 1): void {
  const target = index + offset
  if (target < 0 || target >= draft.permissions.length) return
  const [item] = draft.permissions.splice(index, 1)
  if (item) draft.permissions.splice(target, 0, item)
}

function directoryPattern(path: string): string {
  const normalized = path.replaceAll('\\', '/').replace(/\/+$/, '')
  return normalized ? `${normalized}/**` : '/**'
}

function importFilesystemPaths(): void {
  const filesystem = props.filesystems.find((item) => item.id === importFilesystemId.value)
  if (!filesystem) return
  const paths = [
    ...(filesystem.mapped_directories ?? []).map((item) => directoryPattern(item.virtual_path)),
    ...(filesystem.virtual_directories ?? []).map((item) => directoryPattern(item.virtual_path)),
    ...(filesystem.virtual_files ?? []).map((item) => item.virtual_path.replaceAll('\\', '/')),
  ]
  const existing = new Set(draft.permissions.map((item) => item.path.trim()))
  for (const path of paths) {
    if (!path || existing.has(path)) continue
    draft.permissions.push({ path, permission: 'read-write' })
    existing.add(path)
  }
}
</script>

<template>
  <div data-editor="filesystem-permissions">
    <section class="card mb-3">
      <header class="card-header">
        <h3 class="card-title h5 mb-0 fw-semibold">{{ t('editors.filesystemPermissions.permissionsTitle') }}</h3>
      </header>
      <div class="card-body">
        <div class="row g-3">
          <div class="col-md-6">
            <FormField field-path="filesystem_import" label-key="editors.filesystemPermissions.importFilesystem">
              <div class="input-group">
                <select v-model="importFilesystemId" class="form-select">
                  <option value="">{{ t('common.chooseConfiguration') }}</option>
                  <option v-for="filesystem in filesystems" :key="filesystem.id" :value="filesystem.id">{{ filesystem.name }}</option>
                </select>
                <LteButton :disabled="!importFilesystemId" data-action="import-filesystem-paths" theme="primary" type="button" @click="importFilesystemPaths">
                  {{ t('editors.filesystemPermissions.importAction') }}
                </LteButton>
              </div>
            </FormField>
          </div>
        </div>
        <div v-if="draft.permissions.length" class="simple-mapping-list mt-3">
          <div v-for="(entry, index) in draft.permissions" :key="index" class="simple-mapping-row" data-testid="filesystem-permission-row">
            <div class="simple-mapping-primary">
              <label class="visually-hidden" :for="`filesystem-permission-path-${index}`">{{ t('fields.path') }}</label>
              <input :id="`filesystem-permission-path-${index}`" v-model="entry.path" class="form-control">
            </div>
            <div class="simple-mapping-secondary">
              <label class="visually-hidden" :for="`filesystem-permission-value-${index}`">{{ t('fields.permission') }}</label>
              <select :id="`filesystem-permission-value-${index}`" v-model="entry.permission" class="form-select">
                <option v-for="permission in permissionOptions" :key="permission" :value="permission">{{ t(`editors.filesystemPermissions.permission.${permission}`) }}</option>
              </select>
            </div>
            <div class="simple-mapping-actions">
              <LteButton :aria-label="t('editors.common.moveUp')" :disabled="index === 0" :title="t('editors.common.moveUp')" size="sm" theme="secondary" type="button" @click="movePermission(index, -1)"><i class="bi bi-arrow-up" aria-hidden="true" /></LteButton>
              <LteButton :aria-label="t('editors.common.moveDown')" :disabled="index === draft.permissions.length - 1" :title="t('editors.common.moveDown')" size="sm" theme="secondary" type="button" @click="movePermission(index, 1)"><i class="bi bi-arrow-down" aria-hidden="true" /></LteButton>
              <LteButton :aria-label="t('editors.common.remove')" :title="t('editors.common.remove')" data-action="remove-filesystem-permission" size="sm" theme="danger" type="button" @click="draft.permissions.splice(index, 1)"><i class="bi bi-trash" aria-hidden="true" /></LteButton>
            </div>
          </div>
        </div>
        <p v-else class="text-body-secondary mt-3 mb-0">{{ t('editors.filesystemPermissions.emptyPermissions') }}</p>
        <div class="simple-mapping-footer">
          <LteButton :aria-label="t('editors.common.add')" :title="t('editors.common.add')" data-action="add-filesystem-permission" size="sm" theme="success" type="button" @click="addPermission">
            <i class="bi bi-plus-lg" aria-hidden="true" />
          </LteButton>
        </div>
      </div>
    </section>

    <section class="card mb-3">
      <header class="card-header d-flex flex-wrap align-items-center justify-content-between gap-2">
        <h3 class="card-title h5 mb-0 fw-semibold">{{ t('editors.filesystemPermissions.systemPromptTitle') }}</h3>
        <div class="form-check form-switch ms-auto">
          <input id="filesystem-permissions-system-prompt" v-model="draft.system_prompt_override_enabled" class="form-check-input" type="checkbox">
          <label class="form-check-label" for="filesystem-permissions-system-prompt">{{ t('editors.filesystemPermissions.override') }}</label>
        </div>
      </header>
      <div class="card-body">
        <div class="form-check mb-3">
          <input id="filesystem-permissions-default-prompt" v-model="draft.system_prompt_use_default" class="form-check-input" :disabled="!draft.system_prompt_override_enabled" type="checkbox">
          <label class="form-check-label" for="filesystem-permissions-default-prompt">{{ t('editors.filesystemPermissions.useDefaultPrompt') }}</label>
        </div>
        <LteTextarea v-model="draft.system_prompt_value" :aria-label="t('editors.filesystemPermissions.systemPromptTitle')" :disabled="!draft.system_prompt_override_enabled || draft.system_prompt_use_default" :rows="10" />
      </div>
    </section>

    <section class="mb-3">
      <h3 class="h5 fw-semibold mb-3">{{ t('editors.filesystemPermissions.toolsTitle') }}</h3>
      <div class="row g-3">
        <div v-for="row in toolRows" :key="row.tool.name" class="col-md-6">
          <article class="card h-100" data-testid="filesystem-permission-tool-card">
            <header class="card-header d-flex flex-wrap align-items-center justify-content-between gap-2">
              <h4 class="card-title mb-0 font-monospace">{{ row.tool.name }}</h4>
              <div class="form-check form-switch ms-auto">
                <input :id="`tool-override-${row.tool.name}`" v-model="row.override.override" class="form-check-input" type="checkbox">
                <label class="form-check-label" :for="`tool-override-${row.tool.name}`">{{ t('editors.filesystemPermissions.override') }}</label>
              </div>
            </header>
            <div class="card-body">
              <div class="form-check form-switch mb-3">
                <input :id="`permission-tool-visible-${row.tool.name}`" v-model="row.override.visible" class="form-check-input" :disabled="!row.override.override || !row.tool.configurable" type="checkbox">
                <label class="form-check-label" :for="`permission-tool-visible-${row.tool.name}`">{{ row.override.visible ? t('editors.common.enabled') : t('editors.common.disabled') }}</label>
              </div>
              <LteTextarea v-model="row.override.description_override" :aria-label="t('editors.filesystem.toolDescriptionLabel', { tool: row.tool.name })" :disabled="!row.override.override" :rows="6" />
            </div>
          </article>
        </div>
      </div>
    </section>
  </div>
</template>
