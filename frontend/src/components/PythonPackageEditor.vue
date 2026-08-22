<script setup lang="ts">
import { LteAlert, LteButton } from '@adminlte/vue'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import type { LocalizedMessagePayload, PythonPackageTemplate } from '@/api'
import FileWorkspaceDialog from '@/components/FileWorkspaceDialog.vue'
import {
  applyPythonPackageTemplate,
  type PythonPackageDraftState,
} from '@/domain/blocks/pythonPackage'
import { useEditorModel } from '@/editors/shared/useEditorModel'

const props = withDefaults(defineProps<{
  modelValue: PythonPackageDraftState
  saved: boolean
  catalog?: PythonPackageTemplate[]
  errors?: Record<string, LocalizedMessagePayload>
  loading?: boolean
  idPrefix: string
}>(), {
  catalog: () => [],
  errors: () => ({}),
  loading: false,
})
const emit = defineEmits<{
  'update:modelValue': [value: PythonPackageDraftState]
  refresh: []
}>()

const { t } = useI18n()
const draft = useEditorModel(
  () => props.modelValue,
  (value) => emit('update:modelValue', value),
)
const workspaceOpen = ref(false)
const workspacePath = ref('')

const selectedTemplate = computed(() => props.catalog.find(
  (item) => item.key === draft.python_package_template.key,
))
const inspection = computed(() => draft.python_package_inspection)

function selectTemplate(key: string): void {
  applyPythonPackageTemplate(draft, props.catalog.find((item) => item.key === key))
}

function templateLabel(template: PythonPackageTemplate): string {
  return template.name === template.key
    ? template.name
    : `${template.name} (${template.key})`
}

function resourceError(error: LocalizedMessagePayload): string {
  return t(error.message_key, error.message_args)
}

function openFile(path: string): void {
  workspacePath.value = path
  workspaceOpen.value = true
}

function refresh(): void {
  emit('refresh')
}
</script>

<template>
  <section class="card mb-3">
    <header class="card-header d-flex align-items-center gap-2">
      <h3 class="card-title h5 mb-0">{{ t('editors.pythonPackage.title') }}</h3>
      <LteButton
        class="ms-auto"
        :aria-label="t('common.refresh')"
        :disabled="loading"
        size="sm"
        theme="info"
        type="button"
        @click="refresh"
      >
        <i class="bi bi-arrow-clockwise" aria-hidden="true" />
      </LteButton>
    </header>
    <div class="card-body">
      <template v-if="!saved">
        <label class="form-label" :for="`${idPrefix}-template`">
          {{ t('editors.pythonPackage.template') }}
        </label>
        <select
          :id="`${idPrefix}-template`"
          class="form-select"
          :value="draft.python_package_template.key"
          @change="selectTemplate(($event.target as HTMLSelectElement).value)"
        >
          <option value="">{{ t('editors.pythonPackage.selectTemplate') }}</option>
          <option v-for="item in catalog" :key="item.key" :value="item.key">
            {{ templateLabel(item) }}
          </option>
        </select>
        <div v-if="selectedTemplate" class="form-text">
          {{ selectedTemplate.files.map((file) => file.path).join(', ') }}
        </div>
      </template>

      <template v-else>
        <LteAlert
          v-if="inspection?.python_package_error"
          class="mb-3"
          theme="warning"
          :title="resourceError(inspection.python_package_error)"
        />
        <div v-if="!inspection" class="d-flex align-items-center gap-2 p-3" role="status">
          <span class="spinner-border" aria-hidden="true" />
          <span>{{ t('common.loading') }}</span>
        </div>
        <div v-else class="table-responsive">
          <table class="table table-hover align-middle">
            <thead class="management-table-head">
              <tr>
                <th>{{ t('editors.pythonPackage.files') }}</th>
                <th>{{ t('fileManager.columns.size') }}</th>
                <th class="text-end">{{ t('fileManager.columns.actions') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="inspection.files.length === 0">
                <td class="text-center text-body-secondary p-3" colspan="3">
                  {{ t('fileManager.empty') }}
                </td>
              </tr>
              <tr v-for="file in inspection.files" :key="file.path">
                <td class="font-monospace text-break">{{ file.path }}</td>
                <td>{{ file.size }}</td>
                <td class="text-end">
                  <LteButton
                    class="icon-action-button"
                    :aria-label="t('common.edit')"
                    :title="t('common.edit')"
                    size="sm"
                    theme="info"
                    type="button"
                    @click="openFile(file.file_manager_path)"
                  >
                    <i class="bi bi-pencil" aria-hidden="true" />
                  </LteButton>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <LteAlert
          v-if="inspection?.dependency_status && inspection.dependency_status !== 'ready'"
          class="mt-3 mb-0"
          theme="info"
          :title="t(`editors.pythonPackage.status.${inspection.dependency_status}`)"
        />
      </template>
    </div>
    <div v-if="!saved && Object.keys(errors).length" class="card-body">
      <div class="alert alert-danger mb-0" role="alert">
        <p v-for="(error, folder) in errors" :key="folder" class="mb-1">
          <strong>{{ folder }}</strong> {{ resourceError(error) }}
        </p>
      </div>
    </div>

    <FileWorkspaceDialog
      :open="workspaceOpen"
      :path="workspacePath"
      @changed="refresh"
      @close="workspaceOpen = false"
    />
  </section>
</template>
