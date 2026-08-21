<script setup lang="ts">
import { LteAlert, LteButton, LteInput } from '@adminlte/vue'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { managementApi, type ModelConnection, type ModelProviderCatalog } from '@/api'
import FormField from '@/components/FormField.vue'
import PageShell from '@/components/PageShell.vue'
import ModelEditor from '@/editors/ModelEditor.vue'
import { modelAdapter, type ModelDraft } from '@/domain/blocks/model'
import { useConfirmation } from '@/composables/useConfirmation'
import { useManagementError } from '@/composables/useManagementError'

const { t } = useI18n()
const { confirm } = useConfirmation()
const managementError = useManagementError()
const records = ref<ModelConnection[]>([])
const providers = ref<ModelProviderCatalog | null>(null)
const draft = ref<ModelDraft>(modelAdapter.blank())
const selectedRecord = ref<ModelConnection | null>(null)
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const errorTitleKey = ref('models.connections.loadFailed')
const models = ref<string[]>([])
const loadingModels = ref(false)

const canSave = computed(() => Boolean(draft.value.name.trim()))
const credentialReplacementRequired = computed(() => Boolean(
  selectedRecord.value
  && draft.value.credential_status === 'masked'
  && !draft.value.credential_secret
  && (
    draft.value.provider !== selectedRecord.value.provider
    || draft.value.base_url.trim() !== selectedRecord.value.base_url
  ),
))

function clearError(): void { error.value = '' }
function select(record: ModelConnection): void {
  draft.value = modelAdapter.fromApi(record)
  selectedRecord.value = record
  clearError()
}
function startNew(): void {
  draft.value = modelAdapter.blank()
  selectedRecord.value = null
  clearError()
}
function suggestedCopyName(name: string): string {
  const suffix = ' (copy)'
  return `${name.trim().slice(0, 120 - suffix.length).trimEnd()}${suffix}`
}
async function load(): Promise<void> {
  loading.value = true
  clearError()
  try {
    ;[records.value, providers.value] = await Promise.all([
      managementApi.listModelConnections(),
      managementApi.listModelProviders(),
    ])
    if (!draft.value.id && records.value[0]) select(records.value[0])
  } catch (cause) {
    errorTitleKey.value = 'models.connections.loadFailed'
    error.value = managementError.describe(cause).display
  }
  finally { loading.value = false }
}
async function save(): Promise<void> {
  if (!canSave.value || saving.value) return
  saving.value = true
  clearError()
  try {
    const saved = await managementApi.saveModelConnection({
      ...modelAdapter.toPayload(draft.value),
      ...(draft.value.id ? { id: draft.value.id } : {}),
    })
    records.value = await managementApi.listModelConnections()
    select(saved)
  } catch (cause) {
    errorTitleKey.value = 'models.connections.saveFailed'
    error.value = managementError.describe(cause).display
  }
  finally { saving.value = false }
}
async function copy(): Promise<void> {
  if (!draft.value.id || saving.value) return
  saving.value = true
  clearError()
  try {
    const copied = await managementApi.copyModelConnection(
      draft.value.id,
      suggestedCopyName(draft.value.name),
    )
    records.value = await managementApi.listModelConnections()
    select(copied)
  } catch (cause) {
    errorTitleKey.value = 'models.connections.copyFailed'
    error.value = managementError.describe(cause).display
  } finally {
    saving.value = false
  }
}
async function remove(): Promise<void> {
  if (!draft.value.id || saving.value) return
  const accepted = await confirm({ title: t('models.connections.deleteTitle'), description: t('models.connections.deleteDescription', { name: draft.value.name }), confirmLabel: t('common.delete'), cancelLabel: t('common.cancel') })
  if (!accepted) return
  saving.value = true
  clearError()
  try { await managementApi.deleteModelConnection(draft.value.id); startNew(); await load() }
  catch (cause) {
    errorTitleKey.value = 'models.connections.deleteFailed'
    error.value = managementError.describe(cause).display
  } finally { saving.value = false }
}
async function fetchModels(request: { provider: string; baseUrl: string; credential: string; blockId: string }): Promise<void> {
  loadingModels.value = true
  clearError()
  try { models.value = await managementApi.fetchModels(request.provider, request.baseUrl, request.credential || null, request.blockId) }
  catch (cause) {
    errorTitleKey.value = 'models.connections.modelsFailed'
    error.value = managementError.describe(cause).display
    models.value = []
  }
  finally { loadingModels.value = false }
}
onMounted(() => { void load() })
</script>

<template>
  <PageShell>
    <template #actions>
      <LteButton :disabled="saving || loading" theme="success" type="button" @click="startNew"><i class="bi bi-plus-lg" aria-hidden="true" /> {{ t('common.new') }}</LteButton>
      <LteButton :disabled="!draft.id || saving || loading" theme="secondary" type="button" @click="copy"><i class="bi bi-copy" aria-hidden="true" /> {{ t('common.copy') }}</LteButton>
      <LteButton :disabled="!draft.id || saving || loading" theme="danger" type="button" @click="remove"><i class="bi bi-trash" aria-hidden="true" /> {{ t('common.delete') }}</LteButton>
      <LteButton :disabled="saving || loading || !canSave" theme="primary" type="button" @click="save"><i class="bi bi-check-lg" aria-hidden="true" /> {{ t('common.save') }}</LteButton>
    </template>
    <template #status><LteAlert v-if="error" theme="danger" :title="t(errorTitleKey)">{{ error }}</LteAlert></template>
    <div class="row g-3 align-items-start">
      <section class="col-lg-4"><div class="card"><header class="card-header"><h2 class="card-title">{{ t('navigation.sections.modelConnections') }}</h2></header><div class="list-group list-group-flush"><button v-for="record in records" :key="record.id" class="list-group-item text-start" type="button" @click="select(record)">{{ record.name }}<small class="d-block text-body-secondary">{{ record.provider }} · {{ record.model }}</small></button><p v-if="!records.length && !loading" class="card-body text-body-secondary mb-0">{{ t('models.connections.empty') }}</p></div></div></section>
      <section class="col-lg-8">
        <FormField control-id="model-connection-name" field-path="name">
          <LteInput id="model-connection-name" v-model="draft.name" autocomplete="off" data-field="model-connection-name" required />
        </FormField>
        <LteAlert v-if="credentialReplacementRequired" theme="warning">
          {{ t('models.connections.credentialReplacementRequired') }}
        </LteAlert>
        <ModelEditor v-model="draft" :models="models" :loading-models="loadingModels" :providers="providers?.providers ?? []" :loading-providers="loading" @fetch-models="fetchModels" />
      </section>
    </div>
  </PageShell>
</template>
