<script setup lang="ts">
import { LteButton, LteTextarea } from '@adminlte/vue'
import { useI18n } from 'vue-i18n'

import FormField from '@/components/FormField.vue'
import type {
  FilesystemDefaults,
  FilesystemDraft,
  FilesystemPermissionValue,
  SkillPackageSummary,
} from '@/domain/blocks'

import { useEditorModel } from './shared/useEditorModel'

const props = withDefaults(defineProps<{
  modelValue: FilesystemDraft
  defaults: FilesystemDefaults
  skillPackages?: SkillPackageSummary[]
}>(), { skillPackages: () => [] })
const emit = defineEmits<{ 'update:modelValue': [value: FilesystemDraft] }>()
const { t } = useI18n()
const draft = useEditorModel(() => props.modelValue, (value) => emit('update:modelValue', value))
const permissions: FilesystemPermissionValue[] = ['read-write', 'read-only', 'no-access']

function selectBackend(type: 'composite' | 'local-shell'): void {
  draft.backend_type = type
  if (type === 'local-shell') {
    draft.workspace ??= { local_path: '', path_origin: 'absolute' }
    draft.skill_package_id = ''
  } else {
    draft.workspace = null
  }
}

function addMapped(): void {
  draft.mapped_directories.push({
    virtual_path: '',
    local_path: '',
    path_origin: 'absolute',
    lifecycle_mode: 'fixed',
    permission: 'read-write',
  })
}

function addVirtualDirectory(): void {
  draft.virtual_directories.push({
    virtual_path: '',
    source_path: '',
    permission: 'read-write',
  })
}

function addVirtualFile(): void {
  draft.virtual_files.push({
    virtual_path: '',
    source_path: '',
    permission: 'read-write',
  })
}

function hasSkillPackage(id: string): boolean {
  return props.skillPackages.some((item) => item.id === id)
}
</script>

<template>
  <div data-editor="filesystem">
    <fieldset class="mb-3">
      <legend class="h5 fw-semibold mb-3">{{ t('editors.filesystem.backendTitle') }}</legend>
      <div class="row g-3">
        <div v-for="type in (['composite', 'local-shell'] as const)" :key="type" class="col-md-6">
          <article class="card h-100" :class="draft.backend_type === type ? 'border-primary' : ''">
            <header class="card-header">
              <div class="form-check mb-0">
                <input
                  :id="`filesystem-backend-${type}`"
                  :checked="draft.backend_type === type"
                  class="form-check-input"
                  name="filesystem-backend-type"
                  type="radio"
                  :value="type"
                  @change="selectBackend(type)"
                >
                <label class="form-check-label fw-semibold" :for="`filesystem-backend-${type}`">
                  {{ t(`editors.filesystem.backend.${type}.label`) }}
                </label>
              </div>
            </header>
            <div class="card-body small text-body-secondary">
              {{ t(`editors.filesystem.backend.${type}.description`) }}
            </div>
          </article>
        </div>
      </div>
    </fieldset>

    <template v-if="draft.backend_type === 'composite'">
      <section class="card mb-3">
        <header class="card-header d-flex align-items-center">
          <div>
            <h3 class="h5 fw-semibold mb-1">{{ t('editors.filesystem.mappedDirectoriesTitle') }}</h3>
            <p class="small text-body-secondary mb-0">{{ t('editors.filesystem.mappedDirectoriesHint') }}</p>
          </div>
          <LteButton
            class="icon-action-button ms-auto"
            type="button"
            :aria-label="t('editors.common.add')"
            :title="t('editors.common.add')"
            @click="addMapped"
          >
            <i class="bi bi-plus-lg" aria-hidden="true" />
          </LteButton>
        </header>
        <div v-if="draft.mapped_directories.length" class="list-group list-group-flush">
          <article
            v-for="(item, index) in draft.mapped_directories"
            :key="index"
            class="list-group-item"
            data-testid="mapped-directory-row"
          >
            <div class="mb-2">
              <div class="row g-3 align-items-end">
                <FormField
                  class="col"
                  :control-id="`mapped-directory-local-path-${index}`"
                  :field-path="`mapped_directories[${index}].local_path`"
                >
                  <input
                    :id="`mapped-directory-local-path-${index}`"
                    v-model="item.local_path"
                    class="form-control"
                    :placeholder="t('editors.filesystem.mappingExamples.localDirectory')"
                  >
                </FormField>
                <div class="col-auto mb-3 pb-2" aria-hidden="true"><i class="bi bi-arrow-right" /></div>
                <FormField
                  class="col"
                  :control-id="`mapped-directory-virtual-path-${index}`"
                  :field-path="`mapped_directories[${index}].virtual_path`"
                >
                  <input
                    :id="`mapped-directory-virtual-path-${index}`"
                    v-model="item.virtual_path"
                    class="form-control"
                    :placeholder="t('editors.filesystem.mappingExamples.virtualDirectory')"
                  >
                </FormField>
              </div>
            </div>
            <div class="row g-3">
              <FormField
                class="col-md-4"
                :control-id="`mapped-directory-path-origin-${index}`"
                :field-path="`mapped_directories[${index}].path_origin`"
              >
                <select :id="`mapped-directory-path-origin-${index}`" v-model="item.path_origin" class="form-select">
                  <option value="absolute">{{ t('editors.filesystem.pathOrigin.absolute') }}</option>
                  <option value="data-root-relative">{{ t('editors.filesystem.pathOrigin.dataRootRelative') }}</option>
                </select>
              </FormField>
              <FormField
                class="col-md-4"
                :control-id="`mapped-directory-lifecycle-mode-${index}`"
                :field-path="`mapped_directories[${index}].lifecycle_mode`"
              >
                <select :id="`mapped-directory-lifecycle-mode-${index}`" v-model="item.lifecycle_mode" class="form-select">
                  <option value="fixed">{{ t('editors.filesystem.lifecycle.fixed') }}</option>
                  <option value="dynamic">{{ t('editors.filesystem.lifecycle.dynamic') }}</option>
                </select>
              </FormField>
              <FormField
                class="col-md-4"
                :control-id="`mapped-directory-permission-${index}`"
                :field-path="`mapped_directories[${index}].permission`"
              >
                <select :id="`mapped-directory-permission-${index}`" v-model="item.permission" class="form-select">
                  <option v-for="permission in permissions" :key="permission" :value="permission">
                    {{ t(`editors.filesystem.permission.${permission}`) }}
                  </option>
                </select>
              </FormField>
            </div>
            <div class="d-flex">
              <LteButton
                class="icon-action-button ms-auto"
                type="button"
                :aria-label="t('editors.common.remove')"
                :title="t('editors.common.remove')"
                @click="draft.mapped_directories.splice(index, 1)"
              >
                <i class="bi bi-trash" aria-hidden="true" />
              </LteButton>
            </div>
          </article>
        </div>
        <div v-else class="card-body">
          <p class="text-body-secondary mb-0">{{ t('editors.filesystem.emptyMappings') }}</p>
        </div>
      </section>

      <section v-for="kind in (['virtual_directories', 'virtual_files'] as const)" :key="kind" class="card mb-3">
        <header class="card-header d-flex align-items-center">
          <div>
            <h3 class="h5 fw-semibold mb-1">
              {{ t(`editors.filesystem.${kind === 'virtual_directories' ? 'virtualDirectoriesTitle' : 'virtualFilesTitle'}`) }}
            </h3>
            <p class="small text-body-secondary mb-0">
              {{ t(`editors.filesystem.${kind === 'virtual_directories' ? 'virtualDirectoriesHint' : 'virtualFilesHint'}`) }}
            </p>
          </div>
          <LteButton
            class="icon-action-button ms-auto"
            type="button"
            :aria-label="t('editors.common.add')"
            :title="t('editors.common.add')"
            @click="kind === 'virtual_directories' ? addVirtualDirectory() : addVirtualFile()"
          >
            <i class="bi bi-plus-lg" aria-hidden="true" />
          </LteButton>
        </header>
        <div v-if="draft[kind].length" class="list-group list-group-flush">
          <article v-for="(item, index) in draft[kind]" :key="index" class="list-group-item">
            <div class="row g-3 align-items-end">
              <FormField
                class="col"
                :control-id="`${kind}-source-path-${index}`"
                :field-path="`${kind}[${index}].source_path`"
              >
                <input
                  :id="`${kind}-source-path-${index}`"
                  v-model="item.source_path"
                  class="form-control"
                  :placeholder="t(`editors.filesystem.mappingExamples.${kind === 'virtual_directories' ? 'sourceDirectory' : 'sourceFile'}`)"
                >
              </FormField>
              <div class="col-auto mb-3 pb-2" aria-hidden="true"><i class="bi bi-arrow-right" /></div>
              <FormField
                class="col"
                :control-id="`${kind}-virtual-path-${index}`"
                :field-path="`${kind}[${index}].virtual_path`"
              >
                <input
                  :id="`${kind}-virtual-path-${index}`"
                  v-model="item.virtual_path"
                  class="form-control"
                  :placeholder="t(`editors.filesystem.mappingExamples.${kind === 'virtual_directories' ? 'virtualDirectory' : 'virtualFile'}`)"
                >
              </FormField>
              <FormField
                class="col-md-3"
                :control-id="`${kind}-permission-${index}`"
                :field-path="`${kind}[${index}].permission`"
              >
                <select :id="`${kind}-permission-${index}`" v-model="item.permission" class="form-select">
                  <option v-for="permission in permissions" :key="permission" :value="permission">
                    {{ t(`editors.filesystem.permission.${permission}`) }}
                  </option>
                </select>
              </FormField>
              <div class="col-auto mb-3">
                <LteButton
                  class="icon-action-button"
                  type="button"
                  :aria-label="t('editors.common.remove')"
                  :title="t('editors.common.remove')"
                  @click="draft[kind].splice(index, 1)"
                >
                  <i class="bi bi-trash" aria-hidden="true" />
                </LteButton>
              </div>
            </div>
          </article>
        </div>
        <div v-else class="card-body">
          <p class="text-body-secondary mb-0">
            {{ t(`editors.filesystem.${kind === 'virtual_directories' ? 'emptyVirtualDirectories' : 'emptyVirtualFiles'}`) }}
          </p>
        </div>
      </section>

      <section class="card mb-3">
        <header class="card-header"><h3 class="card-title">{{ t('editors.filesystem.skillPackageTitle') }}</h3></header>
        <div class="card-body">
          <FormField
            control-id="filesystem-skill-package"
            field-path="skill_package_id"
          >
            <select id="filesystem-skill-package" v-model="draft.skill_package_id" class="form-select">
              <option value="">{{ t('editors.filesystem.noSkillPackage') }}</option>
              <option
                v-if="draft.skill_package_id && !hasSkillPackage(draft.skill_package_id)"
                disabled
                :value="draft.skill_package_id"
              >
                {{ t('common.missingConfiguration', { id: draft.skill_package_id }) }}
              </option>
              <option v-for="item in skillPackages" :key="item.id" :value="item.id">{{ item.name }}</option>
            </select>
          </FormField>
        </div>
      </section>
    </template>

    <section v-else class="card mb-3">
      <header class="card-header"><h3 class="card-title">{{ t('editors.filesystem.workspaceTitle') }}</h3></header>
      <div v-if="draft.workspace" class="card-body">
        <div class="row g-3">
          <FormField
            class="col-md-8"
            control-id="filesystem-workspace-local-path"
            field-path="workspace.local_path"
          >
            <input
              id="filesystem-workspace-local-path"
              v-model="draft.workspace.local_path"
              class="form-control"
              :placeholder="t('editors.filesystem.mappingExamples.localDirectory')"
            >
          </FormField>
          <FormField
            class="col-md-4"
            control-id="filesystem-workspace-path-origin"
            field-path="workspace.path_origin"
          >
            <select id="filesystem-workspace-path-origin" v-model="draft.workspace.path_origin" class="form-select">
              <option value="absolute">{{ t('editors.filesystem.pathOrigin.absolute') }}</option>
              <option value="data-root-relative">{{ t('editors.filesystem.pathOrigin.dataRootRelative') }}</option>
            </select>
          </FormField>
        </div>
        <p class="form-text mb-0">{{ t('editors.filesystem.workspaceHint') }}</p>
      </div>
    </section>

    <section class="card mb-3" data-testid="system-prompt-card">
      <header class="card-header">
        <h3 class="card-title">{{ t('editors.filesystem.systemPromptTitle') }}</h3>
      </header>
      <div class="card-body">
        <div class="d-flex flex-wrap align-items-center gap-2 mb-3">
          <LteButton
            class="action-button ms-auto"
            data-action="restore-default"
            type="button"
            @click="draft.system_prompt_override = defaults.system_prompt"
          >
            <i class="bi bi-arrow-clockwise" aria-hidden="true" />
            {{ t('editors.common.restoreDefault') }}
          </LteButton>
        </div>
        <LteTextarea
          v-model="draft.system_prompt_override"
          :aria-label="t('editors.filesystem.systemPromptTitle')"
          :rows="12"
        />
      </div>
    </section>
  </div>
</template>
