<script setup lang="ts">
import { LteAlert } from '@adminlte/vue'
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import {
  managementApi,
  type McpTool,
  type ConfigurationSummary,
  type McpToolPayload,
  type McpToolSummary,
  type ValidationReport,
} from '@/api'
import ConfigurationCrudActions from '@/components/ConfigurationCrudActions.vue'
import ConfigurationEditorLayout from '@/components/ConfigurationEditorLayout.vue'
import CopyNameModal from '@/components/CopyNameModal.vue'
import PageShell from '@/components/PageShell.vue'
import RecordPicker from '@/components/RecordPicker.vue'
import ValidationChecklist from '@/components/ValidationChecklist.vue'
import { useConfigurationResource } from '@/composables/useConfigurationResource'
import { useConfigurationValidation } from '@/composables/useConfigurationValidation'

const { t } = useI18n()
const router = useRouter()
const pythonSchemas = ref<ConfigurationSummary[]>([])

function sortMcpTools<T extends Pick<McpToolSummary, 'id' | 'name'>>(
  items: readonly T[],
): T[] {
  return [...items].sort((left, right) => (
    left.name.localeCompare(right.name, undefined, { sensitivity: 'base' })
    || left.id.localeCompare(right.id)
  ))
}

type McpToolResource = McpToolPayload & Pick<McpTool, 'id' | 'enabled'>

function blankMcpTool(): McpToolResource {
  return {
    id: '',
    name: '',
    description: '',
    python_schema_id: null,
    enabled: false,
  }
}

function normalizeMcpTool(value: unknown): McpToolResource {
  const item = value as Partial<McpTool>
  return {
    id: item.id ?? '',
    name: item.name ?? '',
    description: item.description ?? '',
    python_schema_id: item.python_schema_id ?? null,
    enabled: item.enabled ?? false,
  }
}

function toPayload(item: McpToolResource): McpToolPayload {
  return {
    name: item.name.trim(),
    description: item.description.trim(),
    python_schema_id: item.python_schema_id || null,
  }
}

const {
  loading,
  saving,
  copying,
  deleting,
  copyOpen,
  copyName,
  copyError,
  feedbackDetail: error,
  records,
  selectedId,
  form,
  initializeWorkspace,
  startNew,
  loadSelected: selectRecord,
  save,
  openCopy,
  closeCopy,
  copyCurrent,
  removeCurrent,
} = useConfigurationResource<McpToolResource, McpToolPayload, never>({
  available: () => true,
  blank: blankMcpTool,
  normalize: normalizeMcpTool,
  payload: toPayload,
  get: (id) => managementApi.getMcpTool(id),
  create: (payload) => managementApi.createMcpTool(payload),
  update: (id, payload) => managementApi.updateMcpTool(id, payload),
  copy: (id, name) => managementApi.copyMcpTool(id, name),
  remove: (id) => managementApi.deleteMcpTool(id),
  location: (id = '') => ({
    path: '/workflows/mcp-tools',
    ...(id ? { query: { id } } : {}),
  }),
  deleteConfirmation: (item) => ({
    title: t('mcpTools.deleteTitle'),
    description: t('mcpTools.deleteDescription', { name: item.name }),
    confirmLabel: t('common.delete'),
    cancelLabel: t('common.cancel'),
    dangerous: true,
  }),
  initialSelection: (items, requestedId) => (
    items.some((item) => item.id === requestedId) ? requestedId : items[0]?.id ?? ''
  ),
  sort: sortMcpTools,
  trackUnsaved: false,
  messages: {
    serviceUnavailable: 'errors.requestFailed',
    loadFailed: 'mcpTools.loadFailed',
    saved: 'mcpTools.saved',
    saveFailed: 'mcpTools.loadFailed',
    copied: 'mcpTools.copied',
    deleted: 'mcpTools.deleted',
    deleteFailed: 'mcpTools.deleteFailed',
    copyNameRequired: 'mcpTools.copy.nameRequired',
  },
})

const {
  validation: ownerValidation,
  validateNow: validateOwner,
} = useConfigurationValidation({
  source: selectedId,
  debounceMs: 0,
  buildRequest: () => selectedId.value || null,
  validate: async (mcpToolId): Promise<ValidationReport> => {
    const report = await managementApi.validateRepository()
    const issues = report.issues.filter((issue) => (
      issue.scope === 'mcp_tool' && issue.owner_id === mcpToolId
    ))
    return {
      valid: !issues.some((issue) => issue.severity !== 'warning'),
      stage: report.stage,
      issues,
    }
  },
})

async function saveMcpTool(): Promise<void> {
  await save()
  await validateOwner()
}

async function loadWorkspace(): Promise<void> {
  await initializeWorkspace(async () => {
    const options = await managementApi.getConfigurationOptions()
    pythonSchemas.value = options.components['python-schema'] ?? []
    return options.mcp_tools
  })
}

function newMcpTool(): void {
  if (saving.value || copying.value || deleting.value) return
  void startNew()
}

function updateName(value: string): void {
  form.value.name = value
}

function hasConfiguration(options: ConfigurationSummary[], id: string | null): boolean {
  return Boolean(id && options.some((item) => item.id === id))
}

function editGraph(): void {
  if (selectedId.value) {
    void router.push(
      `/workflows/mcp-tools/${encodeURIComponent(selectedId.value)}/editor`,
    )
  }
}

onMounted(() => { void loadWorkspace() })
</script>

<template>
  <PageShell>
    <LteAlert
      v-if="error"
      data-testid="mcp-tool-error"
      :title="t('mcpTools.loadFailed')"
      theme="danger"
    >
      {{ error }}
    </LteAlert>
    <template #actions>
      <ConfigurationCrudActions
        :copying="copying"
        :deleting="deleting"
        :has-selection="Boolean(selectedId)"
        :loading="loading"
        :saving="saving"
        :show-edit="true"
        @copy="openCopy"
        @delete="removeCurrent"
        @edit="editGraph"
        @new="newMcpTool"
        @save="saveMcpTool"
      />
    </template>
    <ConfigurationEditorLayout v-if="!loading" :loading="saving">
      <template #editor>
        <RecordPicker
          :disabled="saving"
          :model-value="selectedId"
          :name="form.name"
          :records="records"
          @select="selectRecord"
          @update:name="updateName"
        />
        <section class="mt-3">
          <div class="row g-3">
            <div class="col-lg-8">
              <section class="card h-100">
                <header class="card-header">
                  <label class="card-title mb-0" for="mcp-tool-description">
                    {{ t('mcpTools.fields.description') }}
                  </label>
                </header>
                <div class="card-body">
                  <textarea
                    id="mcp-tool-description"
                    v-model="form.description"
                    class="form-control"
                    rows="4"
                  />
                </div>
              </section>
            </div>
            <div class="col-lg-4">
              <section class="card h-100">
                <header class="card-header">
                  <label class="card-title mb-0" for="mcp-tool-python-schema">
                    {{ t('mcpTools.fields.pythonSchema') }}
                  </label>
                </header>
                <div class="card-body">
                  <select
                    id="mcp-tool-python-schema"
                    v-model="form.python_schema_id"
                    class="form-select"
                  >
                    <option :value="null">{{ t('common.none') }}</option>
                    <option
                      v-if="form.python_schema_id && !hasConfiguration(pythonSchemas, form.python_schema_id)"
                      disabled
                      :value="form.python_schema_id"
                    >
                      {{ t('common.missingConfiguration', { id: form.python_schema_id }) }}
                    </option>
                    <option v-for="schema in pythonSchemas" :key="schema.id" :value="schema.id">
                      {{ schema.name }}
                    </option>
                  </select>
                </div>
              </section>
            </div>
          </div>
        </section>
      </template>
      <template #aside>
        <ValidationChecklist
          v-if="selectedId"
          :title="t('validation.storedTitle')"
          :validation="ownerValidation"
        />
        <div class="card">
          <header class="card-header"><h2 class="card-title">{{ t('mcpTools.statusTitle') }}</h2></header>
          <div class="card-body">
            <p class="mb-0">
              {{ selectedId
                ? (records.find((item) => item.id === selectedId)?.enabled
                  ? t('mcpTools.status.published')
                  : t('mcpTools.status.draft'))
                : t('mcpTools.newStatus') }}
            </p>
          </div>
        </div>
      </template>
    </ConfigurationEditorLayout>
  </PageShell>

  <CopyNameModal
    :busy="copying"
    :busy-label="t('common.copying')"
    error-test-id="mcp-tool-copy-error"
    form-id="mcp-tool-copy-form"
    :name="copyName"
    :open="copyOpen"
    :submit-label="t('common.copy')"
    :title="t('mcpTools.copy.title')"
    :error="copyError"
    @close="closeCopy"
    @submit="copyCurrent"
    @update:name="copyName = $event"
  />
</template>
