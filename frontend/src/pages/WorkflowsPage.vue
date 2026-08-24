<script setup lang="ts">
import { LteAlert, LteTextarea } from '@adminlte/vue'
import { onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import { managementApi, type SavedBlock, type Workflow, type WorkflowPayload, type WorkflowRole } from '@/api'
import ConfigurationCrudActions from '@/components/ConfigurationCrudActions.vue'
import ConfigurationEditorLayout from '@/components/ConfigurationEditorLayout.vue'
import CopyNameModal from '@/components/CopyNameModal.vue'
import FormField from '@/components/FormField.vue'
import PageShell from '@/components/PageShell.vue'
import RecordPicker from '@/components/RecordPicker.vue'
import { useConfirmation } from '@/composables/useConfirmation'
import { useManagementError } from '@/composables/useManagementError'
import { useToasts } from '@/composables/useToasts'

const props = defineProps<{ workflowRole: WorkflowRole }>()
const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const managementError = useManagementError()
const { notify } = useToasts()
const { confirm } = useConfirmation()
const records = ref<Workflow[]>([])
const checkpointers = ref<SavedBlock[]>([])
const workflowEventOutputs = ref<SavedBlock[]>([])
const selectedId = ref('')
const form = ref<WorkflowPayload>(blankWorkflow())
const loading = ref(true)
const saving = ref(false)
const copying = ref(false)
const deleting = ref(false)
const copyOpen = ref(false)
const copyName = ref('')
const copyError = ref('')
const error = ref('')

function pagePath(): string {
  return `/workflows/${props.workflowRole === 'parent' ? 'parents' : 'children'}`
}
function sortWorkflows(items: Workflow[]): Workflow[] {
  return [...items].sort((left, right) => (
    left.name.localeCompare(right.name, undefined, { sensitivity: 'base' })
    || left.id.localeCompare(right.id)
  ))
}
function blankWorkflow(): WorkflowPayload {
  return { name: '', workflow_role: props.workflowRole, description: '', checkpointer_id: null, workflow_event_output_id: null, recursion_limit: 1_000_000, execution_timeout_seconds: 1_200, max_concurrency: 100 }
}
function toPayload(workflow: Workflow): WorkflowPayload {
  return { name: workflow.name, workflow_role: workflow.workflow_role, description: workflow.description, checkpointer_id: workflow.checkpointer_id, workflow_event_output_id: workflow.workflow_event_output_id, recursion_limit: workflow.recursion_limit, execution_timeout_seconds: workflow.execution_timeout_seconds, max_concurrency: workflow.max_concurrency }
}
async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const [listed, configuredCheckpointers, outputs] = await Promise.all([
      managementApi.listWorkflows(props.workflowRole),
      managementApi.listBlocks('checkpointer'),
      managementApi.listBlocks('workflow-event-output'),
    ])
    records.value = sortWorkflows(listed)
    checkpointers.value = configuredCheckpointers
    workflowEventOutputs.value = outputs
    const requested = typeof route.query.id === 'string' ? route.query.id : ''
    const selected = records.value.find((item) => item.id === requested) ?? records.value[0]
    selectedId.value = selected?.id ?? ''
    form.value = selected ? toPayload(selected) : blankWorkflow()
    if (requested !== selectedId.value) {
      await router.replace({
        path: pagePath(),
        ...(selectedId.value ? { query: { id: selectedId.value } } : {}),
      })
    }
  } catch (cause) {
    error.value = managementError.describe(cause).display
  } finally {
    loading.value = false
  }
}
function selectRecord(id: string): void {
  if (saving.value) return
  selectedId.value = id
  const selected = records.value.find((item) => item.id === id)
  form.value = selected ? toPayload(selected) : blankWorkflow()
  void router.replace({ path: pagePath(), ...(id ? { query: { id } } : {}) })
}
function updateName(value: string): void { form.value.name = value }
function newWorkflow(): void {
  if (saving.value || copying.value || deleting.value) return
  selectedId.value = ''
  form.value = blankWorkflow()
  void router.replace({ path: pagePath() })
}
function openCopy(): void {
  if (!selectedId.value) return
  copyName.value = ''
  copyError.value = ''
  copyOpen.value = true
}
function closeCopy(): void {
  if (copying.value) return
  copyOpen.value = false
  copyName.value = ''
  copyError.value = ''
}
async function copyCurrent(): Promise<void> {
  if (!selectedId.value || copying.value) return
  const name = copyName.value.trim()
  if (!name) {
    copyError.value = t('workflows.copy.nameRequired')
    return
  }
  copying.value = true
  copyError.value = ''
  try {
    const copied = await managementApi.copyWorkflow(selectedId.value, name)
    records.value = sortWorkflows([...records.value, copied])
    selectedId.value = copied.id
    form.value = toPayload(copied)
    copyOpen.value = false
    copyName.value = ''
    await router.replace({ path: pagePath(), query: { id: copied.id } })
    notify({ tone: 'success', title: t('workflows.copied') })
  } catch (cause) {
    copyError.value = managementError.describe(cause).display
  } finally {
    copying.value = false
  }
}
async function removeCurrent(): Promise<void> {
  if (!selectedId.value || deleting.value) return
  const id = selectedId.value
  const name = records.value.find((item) => item.id === id)?.name ?? form.value.name
  const accepted = await confirm({
    title: t('workflows.deleteTitle'),
    description: t('workflows.deleteDescription', { name }),
    confirmLabel: t('common.delete'),
    cancelLabel: t('common.cancel'),
    dangerous: true,
  })
  if (!accepted) return
  deleting.value = true
  error.value = ''
  try {
    await managementApi.deleteWorkflow(id)
    records.value = records.value.filter((item) => item.id !== id)
    selectedId.value = ''
    form.value = blankWorkflow()
    await router.replace({ path: pagePath() })
    notify({ tone: 'success', title: t('workflows.deleted') })
  } catch (cause) {
    error.value = managementError.describe(cause).display
  } finally {
    deleting.value = false
  }
}
async function save(): Promise<void> {
  if (saving.value || copying.value || deleting.value) return
  saving.value = true
  error.value = ''
  try {
    const payload: WorkflowPayload = { ...form.value, name: form.value.name.trim(), workflow_role: props.workflowRole, description: form.value.description.trim(), checkpointer_id: form.value.checkpointer_id || null, workflow_event_output_id: form.value.workflow_event_output_id || null, recursion_limit: Number(form.value.recursion_limit), execution_timeout_seconds: Number(form.value.execution_timeout_seconds), max_concurrency: Number(form.value.max_concurrency) }
    const saved = selectedId.value ? await managementApi.updateWorkflow(selectedId.value, payload) : await managementApi.createWorkflow(payload)
    records.value = sortWorkflows(
      selectedId.value
        ? records.value.map((item) => item.id === saved.id ? saved : item)
        : [...records.value, saved],
    )
    selectedId.value = saved.id
    form.value = toPayload(saved)
    await router.replace({ path: pagePath(), query: { id: saved.id } })
    notify({ tone: 'success', title: t('workflows.saved') })
  } catch (cause) {
    error.value = managementError.describe(cause).display
  } finally {
    saving.value = false
  }
}
function editGraph(): void {
  if (selectedId.value) void router.push(`/workflows/${encodeURIComponent(selectedId.value)}/editor`)
}
watch(() => props.workflowRole, () => { void load() })
onMounted(() => { void load() })
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
        @save="save"
      />
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
                <option v-for="checkpointer in checkpointers" :key="checkpointer.id" :value="checkpointer.id">{{ checkpointer.name }}</option>
              </select>
            </FormField>
            <FormField control-id="workflow-event-output" field-path="workflow_event_output_id" label-key="workflows.fields.eventOutput">
              <select id="workflow-event-output" v-model="form.workflow_event_output_id" class="form-select">
                <option :value="null">{{ t('common.none') }}</option>
                <option v-for="output in workflowEventOutputs" :key="output.id" :value="output.id">{{ output.name }}</option>
              </select>
            </FormField>
            <FormField field-path="description" label-key="workflows.fields.description">
              <LteTextarea v-model="form.description" :rows="4" maxlength="2000" />
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
