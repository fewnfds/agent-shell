<script setup lang="ts">
import { LteAlert, LteTextarea } from '@adminlte/vue'
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { managementApi, type ConfigurationSummary, type ValidationReport, type Workflow, type WorkflowPayload, type WorkflowSummary } from '@/api'
import ConfigurationCrudActions from '@/components/ConfigurationCrudActions.vue'
import ConfigurationEditorLayout from '@/components/ConfigurationEditorLayout.vue'
import CopyNameModal from '@/components/CopyNameModal.vue'
import FormField from '@/components/FormField.vue'
import PageShell from '@/components/PageShell.vue'
import RecordPicker from '@/components/RecordPicker.vue'
import ValidationChecklist from '@/components/ValidationChecklist.vue'
import { useConfigurationValidation } from '@/composables/useConfigurationValidation'
import { useConfigurationResource } from '@/composables/useConfigurationResource'

const { t } = useI18n()
const router = useRouter()
const workflowEventOutputs = ref<ConfigurationSummary[]>([])
const responseStreamSchedulingComponents = ref<ConfigurationSummary[]>([])

function sortWorkflows<T extends Pick<WorkflowSummary, 'id' | 'name'>>(items: readonly T[]): T[] {
  return [...items].sort((left, right) => (
    left.name.localeCompare(right.name, undefined, { sensitivity: 'base' })
    || left.id.localeCompare(right.id)
  ))
}

type WorkflowResource = Omit<WorkflowPayload, 'response_stream_scheduling_id'>
  & Pick<Workflow, 'id' | 'enabled'>
  & { response_stream_scheduling_id: string | null }

function blankWorkflow(): WorkflowResource {
  return {
    id: '',
    name: '',
    description: '',
    is_model_entry: false,
    workflow_event_output_id: null,
    response_stream_scheduling_id: null,
    durability: 'async',
    on_disconnect: 'cancel',
    enabled: false,
  }
}

function normalizeWorkflow(value: unknown): WorkflowResource {
  const workflow = value as Partial<Workflow>
  return {
    id: workflow.id ?? '',
    name: workflow.name ?? '',
    description: workflow.description ?? '',
    is_model_entry: workflow.is_model_entry ?? false,
    workflow_event_output_id: workflow.workflow_event_output_id ?? null,
    response_stream_scheduling_id: workflow.response_stream_scheduling_id ?? null,
    durability: workflow.durability ?? 'async',
    on_disconnect: workflow.on_disconnect ?? 'cancel',
    enabled: workflow.enabled ?? false,
  }
}

function toPayload(workflow: WorkflowResource): WorkflowPayload {
  const payload: WorkflowPayload = {
    name: workflow.name.trim(),
    description: workflow.description.trim(),
    is_model_entry: workflow.is_model_entry,
    workflow_event_output_id: workflow.workflow_event_output_id || null,
    durability: workflow.durability,
    on_disconnect: workflow.on_disconnect,
  }
  payload.response_stream_scheduling_id = workflow.response_stream_scheduling_id || null
  return payload
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
} = useConfigurationResource<WorkflowResource, WorkflowPayload, never>({
  available: () => true,
  blank: blankWorkflow,
  normalize: normalizeWorkflow,
  payload: toPayload,
  get: (id) => managementApi.getWorkflow(id),
  create: (payload) => managementApi.createWorkflow(payload),
  update: (id, payload) => managementApi.updateWorkflow(id, payload),
  copy: (id, name) => managementApi.copyWorkflow(id, name),
  remove: (id) => managementApi.deleteWorkflow(id),
  location: (id = '') => ({
    path: '/workflows',
    ...(id ? { query: { id } } : {}),
  }),
  deleteConfirmation: (workflow) => ({
    title: t('workflows.deleteTitle'),
    description: t('workflows.deleteDescription', { name: workflow.name }),
    confirmLabel: t('common.delete'),
    cancelLabel: t('common.cancel'),
    dangerous: true,
  }),
  initialSelection: (items, requestedId) => (
    items.some((item) => item.id === requestedId) ? requestedId : items[0]?.id ?? ''
  ),
  sort: sortWorkflows,
  trackUnsaved: false,
  messages: {
    serviceUnavailable: 'errors.requestFailed',
    loadFailed: 'workflows.loadFailed',
    saved: 'workflows.saved',
    saveFailed: 'workflows.loadFailed',
    copied: 'workflows.copied',
    deleted: 'workflows.deleted',
    deleteFailed: 'workflows.deleteFailed',
    copyNameRequired: 'workflows.copy.nameRequired',
  },
})

const {
  validation: ownerValidation,
  validateNow: validateOwner,
} = useConfigurationValidation({
  source: selectedId,
  debounceMs: 0,
  buildRequest: () => selectedId.value || null,
  validate: async (workflowId): Promise<ValidationReport> => {
    const report = await managementApi.validateRepository()
    const issues = report.issues.filter((issue) => (
      issue.scope === 'workflow' && issue.owner_id === workflowId
    ))
    return {
      valid: !issues.some((issue) => issue.severity !== 'warning'),
      stage: report.stage,
      issues,
    }
  },
})

function hasConfiguration(options: ConfigurationSummary[], id: string | null): boolean {
  return Boolean(id && options.some((item) => item.id === id))
}

async function saveWorkflow(): Promise<void> {
  await save()
  await validateOwner()
}

async function loadWorkspace(): Promise<void> {
  await initializeWorkspace(async () => {
    const options = await managementApi.getConfigurationOptions()
    workflowEventOutputs.value = options.components['workflow-event-output'] ?? []
    responseStreamSchedulingComponents.value = options.components['response-stream-scheduling'] ?? []
    return options.workflows
  })
}

function newWorkflow(): void {
  if (saving.value || copying.value || deleting.value) return
  void startNew()
}

function updateName(value: string): void {
  form.value.name = value
}

function editGraph(): void {
  if (selectedId.value) {
    void router.push(`/workflows/${encodeURIComponent(selectedId.value)}/editor`)
  }
}

onMounted(() => { void loadWorkspace() })
</script>

<template>
  <PageShell>
    <LteAlert v-if="error" data-testid="workflow-error" :title="t('workflows.loadFailed')" theme="danger">{{ error }}</LteAlert>
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
        @new="newWorkflow"
        @save="saveWorkflow"
      />
    </template>
    <ConfigurationEditorLayout v-if="!loading" :loading="saving">
      <template #editor>
        <RecordPicker :disabled="saving" :model-value="selectedId" :name="form.name" :records="records" @select="selectRecord" @update:name="updateName" />
        <div class="card mt-3">
          <header class="card-header"><h2 class="card-title">{{ t('workflows.metadataTitle') }}</h2></header>
          <div class="card-body">
            <FormField field-path="description" label-key="workflows.fields.description">
              <LteTextarea v-model="form.description" :rows="4" />
            </FormField>
            <div class="row g-3" data-testid="workflow-component-assembly-row" data-ui-control-row>
              <div class="col-lg-6">
                <FormField control-id="workflow-event-output" field-path="workflow_event_output_id" label-key="workflows.fields.eventOutput">
                  <select id="workflow-event-output" v-model="form.workflow_event_output_id" class="form-select">
                    <option :value="null">{{ t('common.none') }}</option>
                    <option
                      v-if="form.workflow_event_output_id && !hasConfiguration(workflowEventOutputs, form.workflow_event_output_id)"
                      disabled
                      :value="form.workflow_event_output_id"
                    >
                      {{ t('common.missingConfiguration', { id: form.workflow_event_output_id }) }}
                    </option>
                    <option v-for="output in workflowEventOutputs" :key="output.id" :value="output.id">{{ output.name }}</option>
                  </select>
                </FormField>
              </div>
              <div class="col-lg-6">
                <FormField control-id="workflow-response-stream-scheduling" field-path="response_stream_scheduling_id" label-key="workflows.fields.responseStreamScheduling">
                  <select id="workflow-response-stream-scheduling" v-model="form.response_stream_scheduling_id" class="form-select">
                    <option :value="null">{{ t('common.none') }}</option>
                    <option
                      v-if="form.response_stream_scheduling_id && !hasConfiguration(responseStreamSchedulingComponents, form.response_stream_scheduling_id)"
                      disabled
                      :value="form.response_stream_scheduling_id"
                    >
                      {{ t('common.missingConfiguration', { id: form.response_stream_scheduling_id }) }}
                    </option>
                    <option v-for="scheduling in responseStreamSchedulingComponents" :key="scheduling.id" :value="scheduling.id">{{ scheduling.name }}</option>
                  </select>
                </FormField>
              </div>
            </div>
            <div class="row g-3" data-ui-control-row>
              <div class="col-12">
                <div class="form-check form-switch">
                  <input id="workflow-model-entry" v-model="form.is_model_entry" class="form-check-input" type="checkbox">
                  <label class="form-check-label" for="workflow-model-entry">{{ t('workflows.fields.modelEntry') }}</label>
                </div>
              </div>
              <div class="col-lg-3">
                <FormField control-id="workflow-durability" field-path="durability" label-key="workflows.fields.durability">
                  <select id="workflow-durability" v-model="form.durability" class="form-select">
                    <option value="sync">{{ t('workflows.durability.sync') }}</option>
                    <option value="async">{{ t('workflows.durability.async') }}</option>
                    <option value="exit">{{ t('workflows.durability.exit') }}</option>
                  </select>
                </FormField>
              </div>
              <div class="col-lg-3">
                <FormField control-id="workflow-on-disconnect" field-path="on_disconnect" label-key="workflows.fields.onDisconnect">
                  <select id="workflow-on-disconnect" v-model="form.on_disconnect" class="form-select">
                    <option value="cancel">{{ t('workflows.onDisconnect.cancel') }}</option>
                    <option value="continue">{{ t('workflows.onDisconnect.continue') }}</option>
                  </select>
                </FormField>
              </div>
            </div>
          </div>
        </div>
      </template>
      <template #aside>
        <ValidationChecklist
          v-if="selectedId"
          :title="t('validation.storedTitle')"
          :validation="ownerValidation"
        />
        <div class="card">
          <header class="card-header"><h2 class="card-title">{{ t('workflows.statusTitle') }}</h2></header>
          <div class="card-body">
            <p class="mb-0">{{ selectedId ? (records.find((item) => item.id === selectedId)?.enabled ? t('workflows.status.published') : t('workflows.status.draft')) : t('workflows.newStatus') }}</p>
          </div>
        </div>
      </template>
    </ConfigurationEditorLayout>
  </PageShell>

  <CopyNameModal
    :busy="copying"
    :busy-label="t('common.copying')"
    error-test-id="workflow-copy-error"
    form-id="workflow-copy-form"
    :name="copyName"
    :open="copyOpen"
    :submit-label="t('common.copy')"
    :title="t('workflows.copy.title')"
    :error="copyError"
    @close="closeCopy"
    @submit="copyCurrent"
    @update:name="copyName = $event"
  />
</template>
