<script setup lang="ts">
import { LteAlert, LteButton } from '@adminlte/vue'
import { computed, inject, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import ConfigurationCrudActions from '@/components/ConfigurationCrudActions.vue'
import ConfigurationEditorLayout from '@/components/ConfigurationEditorLayout.vue'
import CopyNameModal from '@/components/CopyNameModal.vue'
import PageShell from '@/components/PageShell.vue'
import MiddlewareReferencesEditor from '@/components/MiddlewareReferencesEditor.vue'
import McpReferencesEditor from '@/components/McpReferencesEditor.vue'
import ToolReferencesEditor from '@/components/ToolReferencesEditor.vue'
import RecordPicker from '@/components/RecordPicker.vue'
import ValidationChecklist from '@/components/ValidationChecklist.vue'
import { useConfigurationResource } from '@/composables/useConfigurationResource'
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
} from '@/domain/agents'

const INHERIT_VALUE = '__inherit__'
const DISABLED_VALUE = '__disabled__'
const INVALID_VALUE = '__invalid__'

const props = defineProps<{
  service?: AgentAuthoringService
}>()

const { t } = useI18n()
const providedService = inject(agentAuthoringServiceKey, managementAgentAuthoringService)
const service = computed(() => props.service ?? providedService)

const {
  loading,
  saving,
  copying,
  deleting,
  copyOpen,
  copyName,
  copyError,
  feedbackKey,
  feedbackDetail,
  records: profiles,
  selectedId: selectedProfileId,
  form,
  validation,
  initializeWorkspace,
  startNew,
  loadSelected,
  save,
  openCopy,
  closeCopy,
  copyCurrent,
  removeCurrent,
} = useConfigurationResource({
  available: () => Boolean(service.value),
  blank: blankSubagent,
  normalize: normalizeSubagent,
  payload: subagentPayload,
  get: (id) => service.value!.getSubagent(id),
  create: (payload) => service.value!.createSubagent(payload),
  update: (id, payload) => service.value!.updateSubagent(id, payload),
  copy: (id, componentName) => service.value!.copySubagent(id, componentName),
  remove: (id) => service.value!.deleteSubagent(id),
  location: (id = '') => id
    ? { path: '/agents/subagents', query: { id } }
    : { path: '/agents/subagents' },
  validationRequest: (resource) => ({
    target: { kind: 'subagent' as const, id: resource.id },
    payload: subagentPayload(resource),
  }),
  validate: (request) => service.value!.validateDraft(request),
  deleteConfirmation: (resource) => ({
    title: t('agents.delete.title'),
    description: t('agents.delete.description', { name: resource.component_name }),
    confirmLabel: t('common.delete'),
    cancelLabel: t('common.cancel'),
    dangerous: true,
  }),
  messages: {
    serviceUnavailable: 'agents.serviceUnavailable',
    newDraft: 'agents.feedback.newDraft',
    loadFailed: 'agents.feedback.loadFailed',
    saved: 'agents.feedback.saved',
    saveFailed: 'agents.feedback.saveFailed',
    copied: 'agents.feedback.copied',
    deleted: 'agents.feedback.deleted',
    deleteFailed: 'agents.feedback.deleteFailed',
    copyNameRequired: 'agents.copy.nameRequired',
  },
})

const manifests = ref<CapabilityManifest[]>([])
const blocks = ref<Record<string, StoredBlock[]>>({})
const mcpRequirements = ref<StoredBlock[]>([])
const recordOptions = computed(() => profiles.value.map((profile) => ({
  id: profile.id,
  name: profile.component_name,
})))

const obsoleteOverrides = computed(() => {
  const supported = new Set<string>(manifests.value
    .filter((manifest) => manifest.agent_selectable !== false && manifest.type !== 'custom-middleware')
    .map((manifest) => manifest.type))
  return form.value.settings.capability_overrides
    .map((override, index) => ({ index, override }))
    .filter(({ override }) => !supported.has(override.type))
})
const nonGeneralCapabilityTypes = new Set<CapabilityType>([
  'filesystem',
  'filesystem-tools',
  'subagent',
  'custom-tool',
  'custom-middleware',
])
const generalManifests = computed(() => manifests.value.filter(
  (manifest) => !nonGeneralCapabilityTypes.has(manifest.type),
))
const filesystemToolsManifest = computed(() => manifests.value.find(
  (manifest) => manifest.type === 'filesystem-tools',
))
const filesystemManifest = computed(() => manifests.value.find(
  (manifest) => manifest.type === 'filesystem',
))

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

function missingOverrideReference(type: CapabilityType): string {
  const value = selectionValue(type)
  if ([INHERIT_VALUE, DISABLED_VALUE, INVALID_VALUE].includes(value)) return ''
  return value && !capabilityBlocks(type).some((block) => block.id === value)
    ? value
    : ''
}

function removeObsoleteOverride(index: number): void {
  form.value.settings.capability_overrides.splice(index, 1)
}

async function loadWorkspace(): Promise<void> {
  await initializeWorkspace(async () => {
    const [catalog, options] = await Promise.all([
      service.value!.getCatalog(),
      service.value!.getConfigurationOptions(),
    ])
    manifests.value = catalog.block_types.filter((item) => item.agent_selectable !== false).sort((left, right) => left.order - right.order)
    const entries = manifests.value
      .filter((manifest) => (
        manifest.subagent_overrideable
        || manifest.type === 'custom-middleware'
        || manifest.type === 'custom-tool'
      ))
      .map((manifest) => [
        manifest.type,
        options.components[manifest.type] ?? [],
      ] as const)
    blocks.value = Object.fromEntries(entries)
    mcpRequirements.value = options.components['mcp-requirement'] ?? []
    return options.subagents
  })
}

onMounted(() => {
  void loadWorkspace()
})
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

    <ConfigurationEditorLayout :loading="loading || saving">
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
                    <option
                      v-if="missingOverrideReference('filesystem')"
                      disabled
                      :value="missingOverrideReference('filesystem')"
                    >
                      {{ t('common.missingConfiguration', { id: missingOverrideReference('filesystem') }) }}
                    </option>
                    <option v-for="block in capabilityBlocks('filesystem')" :key="block.id" :value="block.id">{{ block.name }}</option>
                  </select>
                </div>
              </section>
            </div>
            <div class="col-md-6">
              <section class="card h-100" data-testid="subagent-filesystem-tools-card">
                <header class="card-header d-flex flex-wrap align-items-center justify-content-between gap-2">
                  <label class="card-title mb-0" for="subagent-capability-filesystem-tools">{{ t('capabilities.filesystem-tools.label') }}</label>
                  <span class="badge text-bg-primary ms-auto">{{ t('agents.capability.required') }}</span>
                </header>
                <div class="card-body">
                  <select
                    id="subagent-capability-filesystem-tools"
                    class="form-select"
                    data-testid="subagent-capability-filesystem-tools"
                    :value="selectionValue('filesystem-tools')"
                    @change="filesystemToolsManifest && updateSelection(filesystemToolsManifest, ($event.target as HTMLSelectElement).value)"
                  >
                    <option :value="INHERIT_VALUE">{{ t('agents.override.mode.inherit') }}</option>
                    <option
                      v-if="missingOverrideReference('filesystem-tools')"
                      disabled
                      :value="missingOverrideReference('filesystem-tools')"
                    >
                      {{ t('common.missingConfiguration', { id: missingOverrideReference('filesystem-tools') }) }}
                    </option>
                    <option v-for="block in capabilityBlocks('filesystem-tools')" :key="block.id" :value="block.id">{{ block.name }}</option>
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
                      <option
                        v-if="missingOverrideReference(capability.type)"
                        disabled
                        :value="missingOverrideReference(capability.type)"
                      >
                        {{ t('common.missingConfiguration', { id: missingOverrideReference(capability.type) }) }}
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

        <McpReferencesEditor
          v-model:references="form.settings.mcp_refs"
          id-prefix="subagent-mcp"
          :requirements="mcpRequirements"
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
