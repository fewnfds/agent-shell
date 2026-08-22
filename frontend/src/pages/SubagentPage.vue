<script setup lang="ts">
import { LteAlert, LteButton } from '@adminlte/vue'
import { computed, inject, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import ConfigurationCrudActions from '@/components/ConfigurationCrudActions.vue'
import ConfigurationEditorLayout from '@/components/ConfigurationEditorLayout.vue'
import CopyNameModal from '@/components/CopyNameModal.vue'
import PageShell from '@/components/PageShell.vue'
import MiddlewareReferencesEditor from '@/components/MiddlewareReferencesEditor.vue'
import ToolReferencesEditor from '@/components/ToolReferencesEditor.vue'
import RecordPicker from '@/components/RecordPicker.vue'
import ValidationChecklist from '@/components/ValidationChecklist.vue'
import { useConfigurationValidation } from '@/composables/useConfigurationValidation'
import { useConfirmation } from '@/composables/useConfirmation'
import { useManagementError } from '@/composables/useManagementError'
import { useToasts } from '@/composables/useToasts'
import { useUnsavedChanges } from '@/composables/useUnsavedChanges'
import {
  agentAuthoringServiceKey,
  blankSubagent,
  managementAgentAuthoringService,
  normalizeSubagent,
  overrideSelection,
  setOverrideSelection,
  subagentPayload,
  type AgentAuthoringService,
  type CapabilityManifest,
  type CapabilityType,
  type StoredBlock,
  type SubagentProfile,
} from '@/domain/agents'

const INHERIT_VALUE = '__inherit__'
const DISABLED_VALUE = '__disabled__'
const INVALID_VALUE = '__invalid__'

const props = defineProps<{
  service?: AgentAuthoringService
}>()

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const managementError = useManagementError()
const { notify } = useToasts()
const { confirm } = useConfirmation()
const providedService = inject(agentAuthoringServiceKey, managementAgentAuthoringService)
const service = computed(() => props.service ?? providedService)

const loading = ref(true)
const saving = ref(false)
const copying = ref(false)
const deleting = ref(false)
const copyOpen = ref(false)
const copyName = ref('')
const copyError = ref('')
const feedbackKey = ref('')
const feedbackDetail = ref('')
const manifests = ref<CapabilityManifest[]>([])
const blocks = ref<Record<string, StoredBlock[]>>({})
const profiles = ref<SubagentProfile[]>([])
const selectedProfileId = ref('')
const form = ref(blankSubagent())
const recordOptions = computed(() => profiles.value.map((profile) => ({
  id: profile.id,
  name: profile.component_name,
})))
let profileLoadSequence = 0

function editorLocation(id = ''): { path: string, query?: { id: string } } {
  return id ? { path: '/agents/subagents', query: { id } } : { path: '/agents/subagents' }
}

const obsoleteOverrides = computed(() => {
  const supported = new Set<string>(manifests.value
    .filter((manifest) => manifest.type !== 'custom-middleware')
    .map((manifest) => manifest.type))
  return form.value.settings.capability_overrides
    .map((override, index) => ({ index, override }))
    .filter(({ override }) => !supported.has(override.type))
})
const nonGeneralCapabilityTypes = new Set<CapabilityType>([
  'filesystem',
  'filesystem-permissions',
  'subagent',
  'custom-tool',
  'custom-middleware',
])
const generalManifests = computed(() => manifests.value.filter(
  (manifest) => !nonGeneralCapabilityTypes.has(manifest.type),
))
const filesystemPermissionsManifest = computed(() => manifests.value.find(
  (manifest) => manifest.type === 'filesystem-permissions',
))
const filesystemManifest = computed(() => manifests.value.find(
  (manifest) => manifest.type === 'filesystem',
))

const { markClean, runAfterDiscard } = useUnsavedChanges(
  () => form.value,
  () => ({
    title: t('unsavedChanges.title'),
    description: t('unsavedChanges.description'),
    confirmLabel: t('unsavedChanges.confirm'),
    cancelLabel: t('common.cancel'),
  }),
)

const { validation, validateNow } = useConfigurationValidation({
  source: form,
  buildRequest: () => ({
    target: {
      kind: 'subagent',
      id: form.value.id,
    },
    payload: subagentPayload(form.value),
  }),
  validate: async (request) => {
    if (!service.value) throw new Error(t('agents.serviceUnavailable'))
    return service.value.validateDraft(request)
  },
  errorMessage: (error) => managementError.describe(
    error,
    'errors.validationUnavailable',
  ).display,
})

function capabilityBlocks(type: CapabilityType): StoredBlock[] {
  return blocks.value[type] ?? []
}

function selectionValue(type: CapabilityType): string {
  const manifest = manifests.value.find((item) => item.type === type)
  if (!manifest?.subagent_overrideable) {
    return manifest?.subagent_policy === 'inherit' ? INHERIT_VALUE : INVALID_VALUE
  }
  const selection = overrideSelection(form.value, type)
  if (selection.mode === 'inherit') return INHERIT_VALUE
  if (selection.mode === 'disabled') return DISABLED_VALUE
  return selection.block_id
}

function updateSelection(capability: CapabilityManifest, value: string): void {
  if (!capability.subagent_overrideable) return
  if (value === INHERIT_VALUE) {
    setOverrideSelection(form.value, capability.type, 'inherit')
    return
  }
  if (value === DISABLED_VALUE) {
    setOverrideSelection(form.value, capability.type, 'disabled')
    return
  }
  setOverrideSelection(form.value, capability.type, 'replace', value)
}

function removeObsoleteOverride(index: number): void {
  form.value.settings.capability_overrides.splice(index, 1)
}

async function startNew(): Promise<void> {
  await runAfterDiscard(async () => {
    profileLoadSequence += 1
    selectedProfileId.value = ''
    form.value = blankSubagent()
    feedbackKey.value = ''
    feedbackDetail.value = ''
    notify({ tone: 'info', title: t('agents.feedback.newDraft') })
    markClean()
    await router.replace(editorLocation())
  })
}

async function loadProfile(id: string): Promise<void> {
  const sequence = ++profileLoadSequence
  if (!id) {
    selectedProfileId.value = ''
    form.value = blankSubagent()
    feedbackKey.value = ''
    feedbackDetail.value = ''
    notify({ tone: 'info', title: t('agents.feedback.newDraft') })
    markClean()
    return
  }
  if (!service.value) return
  loading.value = true
  feedbackKey.value = ''
  feedbackDetail.value = ''
  try {
    const loaded = normalizeSubagent(
      await service.value.getSubagent(id),
    )
    if (sequence !== profileLoadSequence) return
    form.value = loaded
    selectedProfileId.value = loaded.id
    markClean()
  } catch (error) {
    if (sequence !== profileLoadSequence) return
    selectedProfileId.value = form.value.id
    feedbackKey.value = 'agents.feedback.loadFailed'
    feedbackDetail.value = managementError.describe(error).display
  } finally {
    if (sequence === profileLoadSequence) loading.value = false
  }
}

async function loadSelected(value?: string): Promise<void> {
  const id = value ?? selectedProfileId.value
  await runAfterDiscard(async () => {
    await loadProfile(id)
    if (selectedProfileId.value === id) {
      await router.replace(editorLocation(id))
    }
  })
}

function upsertProfile(saved: SubagentProfile): void {
  const index = profiles.value.findIndex((profile) => profile.id === saved.id)
  if (index === -1) profiles.value.push(saved)
  else profiles.value[index] = saved
}

async function save(): Promise<void> {
  if (!service.value) {
    feedbackKey.value = 'agents.serviceUnavailable'
    feedbackDetail.value = ''
    return
  }
  saving.value = true
  feedbackKey.value = ''
  feedbackDetail.value = ''
  try {
    const state = await validateNow()
    if (state.status !== 'valid') return
    const payload = subagentPayload(form.value)
    const saved = form.value.id
      ? await service.value.updateSubagent(form.value.id, payload)
      : await service.value.createSubagent(payload)
    const normalized = normalizeSubagent(saved)
    form.value = normalized
    selectedProfileId.value = normalized.id
    upsertProfile(normalized)
    markClean()
    await router.replace(editorLocation(normalized.id))
    notify({ tone: 'success', title: t('agents.feedback.saved') })
  } catch (error) {
    feedbackKey.value = 'agents.feedback.saveFailed'
    feedbackDetail.value = managementError.describe(error).display
  } finally {
    saving.value = false
  }
}

function openCopy(): void {
  if (!form.value.id) return
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
  if (!service.value || !form.value.id || copying.value) return
  const componentName = copyName.value.trim()
  if (!componentName) {
    copyError.value = t('agents.copy.nameRequired')
    return
  }
  await runAfterDiscard(async () => {
    copying.value = true
    copyError.value = ''
    try {
      const copied = normalizeSubagent(
        await service.value!.copySubagent(form.value.id, componentName),
      )
      upsertProfile(copied)
      form.value = copied
      selectedProfileId.value = copied.id
      markClean()
      copyOpen.value = false
      copyName.value = ''
      await router.replace(editorLocation(copied.id))
      notify({ tone: 'success', title: t('agents.feedback.copied') })
    } catch (error) {
      copyError.value = managementError.describe(error).display
    } finally {
      copying.value = false
    }
  })
}

async function removeCurrent(): Promise<void> {
  if (!service.value || !form.value.id || deleting.value) return
  await runAfterDiscard(async () => {
    const id = form.value.id
    const accepted = await confirm({
      title: t('agents.delete.title'),
      description: t('agents.delete.description', { name: form.value.component_name }),
      confirmLabel: t('common.delete'),
      cancelLabel: t('common.cancel'),
      dangerous: true,
    })
    if (!accepted) return
    deleting.value = true
    feedbackKey.value = ''
    feedbackDetail.value = ''
    try {
      await service.value!.deleteSubagent(id)
      profiles.value = profiles.value.filter((profile) => profile.id !== id)
      profileLoadSequence += 1
      selectedProfileId.value = ''
      form.value = blankSubagent()
      markClean()
      await router.replace(editorLocation())
      notify({ tone: 'success', title: t('agents.feedback.deleted') })
    } catch (error) {
      feedbackKey.value = 'agents.feedback.deleteFailed'
      feedbackDetail.value = managementError.describe(error).display
    } finally {
      deleting.value = false
    }
  })
}

async function loadWorkspace(): Promise<void> {
  if (!service.value) {
    feedbackKey.value = 'agents.serviceUnavailable'
    loading.value = false
    return
  }
  loading.value = true
  try {
    const [catalog, profileItems] = await Promise.all([
      service.value.getCatalog(),
      service.value.listSubagents(),
    ])
    manifests.value = [...catalog.block_types].sort((left, right) => left.order - right.order)
    profiles.value = profileItems.map(normalizeSubagent)
    const entries = await Promise.all(manifests.value
      .filter((manifest) => (
        manifest.subagent_overrideable
        || manifest.type === 'custom-middleware'
        || manifest.type === 'custom-tool'
      ))
      .map(async (manifest) => [
        manifest.type,
        await service.value?.listBlocks(manifest.type) ?? [],
      ] as const))
    blocks.value = Object.fromEntries(entries)
    const requestedId = typeof route.query.id === 'string' ? route.query.id : ''
    if (requestedId) await loadProfile(requestedId)
    else markClean()
  } catch (error) {
    feedbackKey.value = 'agents.feedback.loadFailed'
    feedbackDetail.value = managementError.describe(error).display
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadWorkspace()
})

watch(
  () => route.query.id,
  (value) => {
    const id = typeof value === 'string' ? value : ''
    if (id === selectedProfileId.value) return
    void loadProfile(id)
  },
)
</script>

<template>
  <PageShell>
    <template #actions>
      <ConfigurationCrudActions
        :can-save="true"
        :copying="copying"
        :deleting="deleting"
        :has-selection="Boolean(form.id)"
        :loading="loading"
        :saving="saving"
        @copy="openCopy"
        @delete="removeCurrent"
        @new="startNew"
        @save="save"
      />
    </template>

    <template #status>
      <LteAlert v-if="feedbackKey" data-testid="page-feedback" theme="danger">
        {{ t(feedbackKey) }}<span v-if="feedbackDetail">{{ t('common.detailSeparator') }}{{ feedbackDetail }}</span>
      </LteAlert>
    </template>

    <ConfigurationEditorLayout :loading="loading">
      <template #editor>
        <div class="mb-3">
          <RecordPicker
            :model-value="selectedProfileId"
            :name="form.component_name"
            :records="recordOptions"
            :disabled="loading"
            @select="loadSelected"
            @update:name="form.component_name = $event"
          />
        </div>

        <section class="mb-3" :aria-label="t('agents.subagent.identityTitle')">
          <div class="row g-3">
            <div class="col-md-6">
              <section class="card h-100">
                <header class="card-header d-flex flex-wrap align-items-center justify-content-between gap-2">
                  <label class="card-title mb-0" for="subagent-role-name">{{ t('agents.subagent.roleName') }}</label>
                  <span class="badge text-bg-primary ms-auto">{{ t('agents.capability.required') }}</span>
                </header>
                <div class="card-body">
                  <input
                    id="subagent-role-name"
                    v-model="form.name"
                    autocomplete="off"
                    class="form-control"
                  >
                </div>
              </section>
            </div>
            <div class="col-md-6">
              <section class="card h-100">
                <header class="card-header d-flex flex-wrap align-items-center justify-content-between gap-2">
                  <label class="card-title mb-0" for="subagent-description">{{ t('fields.description') }}</label>
                  <span class="badge text-bg-primary ms-auto">{{ t('agents.capability.required') }}</span>
                </header>
                <div class="card-body">
                  <textarea id="subagent-description" v-model="form.description" class="form-control" rows="1" />
                </div>
              </section>
            </div>
          </div>
        </section>

        <section
          v-if="obsoleteOverrides.length"
          class="card card-danger card-outline mb-3"
          data-testid="obsolete-capability-overrides"
        >
          <header class="card-header">
            <h2 class="card-title h5 mb-0 fw-semibold">
              {{ t('agents.obsoleteReferences.title') }}
            </h2>
          </header>
          <ul class="list-group list-group-flush">
            <li
              v-for="item in obsoleteOverrides"
              :key="`${item.override.type}:${item.override.block_id}:${item.index}`"
              class="list-group-item d-flex align-items-center justify-content-between gap-2"
            >
              <div class="text-break">
                <strong>{{ item.override.type }}</strong>
                <small class="d-block font-monospace text-body-secondary">
                  {{ item.override.block_id }}
                </small>
              </div>
              <LteButton
                class="icon-action-button ms-auto"
                :aria-label="t('agents.obsoleteReferences.remove')"
                :title="t('agents.obsoleteReferences.remove')"
                data-action="remove-obsolete-capability-override"
                size="sm"
                theme="danger"
                type="button"
                @click="removeObsoleteOverride(item.index)"
              >
                <i class="bi bi-trash" aria-hidden="true" />
              </LteButton>
            </li>
          </ul>
        </section>

        <section class="mb-3" :aria-label="t('agents.workspace.title')">
          <div class="row g-3">
            <div class="col-md-6">
              <section class="card h-100" data-testid="subagent-filesystem-card">
                <header class="card-header d-flex flex-wrap align-items-center justify-content-between gap-2">
                  <label class="card-title mb-0" for="subagent-capability-filesystem">{{ t('capabilities.filesystem.label') }}</label>
                  <span class="badge text-bg-primary ms-auto">{{ t('agents.capability.required') }}</span>
                </header>
                <div class="card-body">
                  <select
                    id="subagent-capability-filesystem"
                    class="form-select"
                    data-testid="subagent-capability-filesystem"
                    :value="selectionValue('filesystem')"
                    @change="filesystemManifest && updateSelection(filesystemManifest, ($event.target as HTMLSelectElement).value)"
                  >
                    <option :value="INHERIT_VALUE">{{ t('agents.override.mode.inherit') }}</option>
                    <option :value="DISABLED_VALUE">{{ t('agents.capability.minimal') }}</option>
                    <option v-for="block in capabilityBlocks('filesystem')" :key="block.id" :value="block.id">{{ block.name }}</option>
                  </select>
                </div>
              </section>
            </div>
            <div class="col-md-6">
              <section class="card h-100" data-testid="subagent-filesystem-permissions-card">
                <header class="card-header d-flex flex-wrap align-items-center justify-content-between gap-2">
                  <label class="card-title mb-0" for="subagent-capability-filesystem-permissions">{{ t('capabilities.filesystem-permissions.label') }}</label>
                  <span class="badge text-bg-info ms-auto">{{ t('agents.capability.optional') }}</span>
                </header>
                <div class="card-body">
                  <select
                    id="subagent-capability-filesystem-permissions"
                    class="form-select"
                    data-testid="subagent-capability-filesystem-permissions"
                    :value="selectionValue('filesystem-permissions')"
                    @change="filesystemPermissionsManifest && updateSelection(filesystemPermissionsManifest, ($event.target as HTMLSelectElement).value)"
                  >
                    <option :value="INHERIT_VALUE">{{ t('agents.override.mode.inherit') }}</option>
                    <option :value="DISABLED_VALUE">{{ t('agents.override.mode.disabled') }}</option>
                    <option v-for="block in capabilityBlocks('filesystem-permissions')" :key="block.id" :value="block.id">{{ block.name }}</option>
                  </select>
                </div>
              </section>
            </div>
          </div>
        </section>

        <section class="mb-3" :aria-label="t('agents.override.capabilitiesTitle')">
          <div class="row g-3">
            <div
              v-for="capability in generalManifests"
              :key="capability.type"
              class="col-md-6 col-xxl-4"
              :data-capability="capability.type"
            >
              <section class="card h-100">
                <header class="card-header d-flex flex-wrap align-items-center justify-content-between gap-2">
                  <label
                    class="card-title mb-0"
                    :for="`subagent-capability-${capability.type}`"
                  >
                    {{ t(`capabilities.${capability.type}.label`) }}
                  </label>
                  <span v-if="capability.subagent_overrideable && capability.required" class="badge text-bg-primary ms-auto">
                    {{ t('agents.capability.required') }}
                  </span>
                  <span v-else-if="capability.subagent_overrideable" class="badge text-bg-info ms-auto">
                    {{ t('agents.capability.optional') }}
                  </span>
                </header>
                <div class="card-body">
                  <select
                    :id="`subagent-capability-${capability.type}`"
                    class="form-select"
                    :data-testid="`subagent-capability-${capability.type}`"
                    :disabled="!capability.subagent_overrideable"
                    :value="selectionValue(capability.type)"
                    @change="updateSelection(capability, ($event.target as HTMLSelectElement).value)"
                  >
                    <template v-if="!capability.subagent_overrideable">
                      <option v-if="capability.subagent_policy === 'inherit'" :value="INHERIT_VALUE">
                        {{ t('agents.override.mode.inherit') }}
                      </option>
                      <option v-else :value="INVALID_VALUE">
                        {{ t('agents.override.mode.invalid') }}
                      </option>
                    </template>
                    <template v-else>
                      <option :value="INHERIT_VALUE">{{ t('agents.override.mode.inherit') }}</option>
                      <option v-if="!capability.required" :value="DISABLED_VALUE">
                        {{ t('agents.override.mode.disabled') }}
                      </option>
                      <option v-for="block in capabilityBlocks(capability.type)" :key="block.id" :value="block.id">
                        {{ block.name }}
                      </option>
                    </template>
                  </select>
                </div>
              </section>
            </div>
          </div>
        </section>

        <ToolReferencesEditor
          v-model:references="form.settings.tool_refs"
          id-prefix="subagent-tool"
          :tools="capabilityBlocks('custom-tool')"
        />

        <MiddlewareReferencesEditor
          v-model:references="form.settings.middleware_refs"
          id-prefix="subagent-middleware"
          :middlewares="capabilityBlocks('custom-middleware')"
        />
      </template>
      <template #aside>
        <ValidationChecklist
          :title="t('validation.draftTitle')"
          :validation="validation"
        />
      </template>
    </ConfigurationEditorLayout>
  </PageShell>

  <CopyNameModal
    :busy="copying"
    :busy-label="t('common.copying')"
    error-test-id="subagent-copy-error"
    field-path="component_name"
    form-id="subagent-copy-form"
    :hint="t('agents.copy.nameHint')"
    :name="copyName"
    :open="copyOpen"
    :submit-label="t('common.copy')"
    :title="t('agents.copy.title')"
    :error="copyError"
    @close="closeCopy"
    @submit="copyCurrent"
    @update:name="copyName = $event"
  />
</template>
