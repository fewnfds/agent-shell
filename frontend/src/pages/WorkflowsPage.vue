<script setup lang="ts">
import { LteAlert, LteButton, LteTextarea } from '@adminlte/vue'
import { onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { managementApi, type ConfigurationSummary, type ValidationReport, type Workflow, type WorkflowPayload, type WorkflowRole, type WorkflowSummary } from '@/api'
import ConfigurationCrudActions from '@/components/ConfigurationCrudActions.vue'
import ConfigurationEditorLayout from '@/components/ConfigurationEditorLayout.vue'
import CopyNameModal from '@/components/CopyNameModal.vue'
import FormField from '@/components/FormField.vue'
import PageShell from '@/components/PageShell.vue'
import RecordPicker from '@/components/RecordPicker.vue'
import ValidationChecklist from '@/components/ValidationChecklist.vue'
import { useConfigurationValidation } from '@/composables/useConfigurationValidation'
import { useConfigurationResource } from '@/composables/useConfigurationResource'

const props = defineProps<{ workflowRole: WorkflowRole }>()
const { t } = useI18n()
const router = useRouter()
const checkpointers = ref<ConfigurationSummary[]>([])
const workflowEventOutputs = ref<ConfigurationSummary[]>([])

function pagePath(): string {
  return `/workflows/${props.workflowRole === 'parent' ? 'parents' : 'children'}`
}
function sortWorkflows<T extends Pick<WorkflowSummary, 'id' | 'name'>>(items: readonly T[]): T[] {
  return [...items].sort((left, right) => (
    left.name.localeCompare(right.name, undefined, { sensitivity: 'base' })
    || left.id.localeCompare(right.id)
  ))
}

type WorkflowResource = WorkflowPayload & Pick<Workflow, 'id' | 'enabled'>

function blankWorkflow(): WorkflowResource {
  return { id: '', name: '', workflow_role: props.workflowRole, description: '', checkpointer_id: null, workflow_event_output_id: null, cancel_on_upstream_termination: true, recursion_limit: 1_000_000, execution_timeout_seconds: 1_200, max_concurrency: 100, enabled: false }
}

function normalizeWorkflow(value: unknown): WorkflowResource {
  const workflow = value as Partial<Workflow>
  const defaults = blankWorkflow()
  return {
    id: workflow.id ?? '',
    name: workflow.name ?? '',
    workflow_role: workflow.workflow_role ?? props.workflowRole,
    description: workflow.description ?? '',
    checkpointer_id: workflow.checkpointer_id ?? null,
    workflow_event_output_id: workflow.workflow_event_output_id ?? null,
    cancel_on_upstream_termination: workflow.cancel_on_upstream_termination ?? true,
    recursion_limit: workflow.recursion_limit ?? defaults.recursion_limit,
    execution_timeout_seconds: workflow.execution_timeout_seconds ?? defaults.execution_timeout_seconds,
    max_concurrency: workflow.max_concurrency ?? defaults.max_concurrency,
    enabled: workflow.enabled ?? false,
  }
}

function toPayload(workflow: WorkflowResource): WorkflowPayload {
  return {
    name: workflow.name.trim(),
    workflow_role: props.workflowRole,
    description: workflow.description.trim(),
    checkpointer_id: workflow.checkpointer_id || null,
    workflow_event_output_id: workflow.workflow_event_output_id || null,
    cancel_on_upstream_termination: workflow.cancel_on_upstream_termination,
    recursion_limit: Number(workflow.recursion_limit),
    execution_timeout_seconds: Number(workflow.execution_timeout_seconds),
    max_concurrency: Number(workflow.max_concurrency),
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
    path: pagePath(),
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
    checkpointers.value = options.components.checkpointer ?? []
    workflowEventOutputs.value = options.components['workflow-event-output'] ?? []
    return options.workflows.filter((item) => item.workflow_role === props.workflowRole)
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

function editResponseStream(): void {
  if (selectedId.value && props.workflowRole === 'parent') {
    void router.push(
      `/workflows/${encodeURIComponent(selectedId.value)}/response-stream`,
    )
  }
}

watch(() => props.workflowRole, () => { void loadWorkspace() })
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
      >
        <LteButton
          v-if="props.workflowRole === 'parent'"
          class="action-button"
          :disabled="!selectedId || loading || saving || copying || deleting"
          type="button"
          @click="editResponseStream"
        >
          <i class="bi bi-broadcast" aria-hidden="true" />
          {{ t('workflows.responseStream.action') }}
        </LteButton>
      </ConfigurationCrudActions>
    </template>
    <ConfigurationEditorLayout v-if="!loading" :loading="loading">
      <template #editor>
        <RecordPicker :disabled="saving" :model-value="selectedId" :name="form.name" :records="records" @select="selectRecord" @update:name="updateName" />
        <div class="card mt-3">
          <header class="card-header"><h2 class="card-title">{{ t('workflows.metadataTitle') }}</h2></header>
          <div class="card-body">
            <FormField control-id="workflow-checkpointer" field-path="checkpointer_id" label-key="workflows.fields.checkpointer">
              <select id="workflow-checkpointer" v-model="form.checkpointer_id" class="form-select">
                <option :value="null">{{ t('common.none') }}</option>
                <option
                  v-if="form.checkpointer_id && !hasConfiguration(checkpointers, form.checkpointer_id)"
                  disabled
                  :value="form.checkpointer_id"
                >
                  {{ t('common.missingConfiguration', { id: form.checkpointer_id }) }}
                </option>
                <option v-for="checkpointer in checkpointers" :key="checkpointer.id" :value="checkpointer.id">{{ checkpointer.name }}</option>
              </select>
            </FormField>
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
            <FormField field-path="description" label-key="workflows.fields.description">
              <LteTextarea v-model="form.description" :rows="4" maxlength="2000" />
            </FormField>
            <FormField
              control-id="workflow-cancel-on-upstream-termination"
              field-path="cancel_on_upstream_termination"
              :label-key="`workflows.termination.${props.workflowRole}.label`"
            >
              <template #default>
                <div class="form-check form-switch">
                  <input
                    id="workflow-cancel-on-upstream-termination"
                    v-model="form.cancel_on_upstream_termination"
                    class="form-check-input"
                    type="checkbox"
                  >
                  <label class="form-check-label visually-hidden" for="workflow-cancel-on-upstream-termination">
                    {{ t(`workflows.termination.${props.workflowRole}.label`) }}
                  </label>
                </div>
              </template>
            </FormField>
            <div class="row g-3" data-ui-control-row>
              <div class="col-lg-4">
                <FormField field-path="recursion_limit" label-key="workflows.fields.recursionLimit">
                  <input v-model.number="form.recursion_limit" class="form-control" min="1" step="1" type="number" required>
                </FormField>
              </div>
              <div class="col-lg-4">
                <FormField field-path="execution_timeout_seconds" label-key="workflows.fields.executionTimeoutSeconds">
                  <div class="input-group">
                    <input v-model.number="form.execution_timeout_seconds" class="form-control" min="1" step="1" type="number" required>
                    <span class="input-group-text">{{ t('workflows.seconds') }}</span>
                  </div>
                </FormField>
              </div>
              <div class="col-lg-4">
                <FormField field-path="max_concurrency" label-key="workflows.fields.maxConcurrency">
                  <input v-model.number="form.max_concurrency" class="form-control" min="1" step="1" type="number" required>
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
    :hint="t('workflows.copy.nameHint')"
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
