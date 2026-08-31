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
import RecordPicker from '@/components/RecordPicker.vue'
import SubagentReferencesEditor from '@/components/SubagentReferencesEditor.vue'
import ToolReferencesEditor from '@/components/ToolReferencesEditor.vue'
import ValidationChecklist from '@/components/ValidationChecklist.vue'
import { useConfigurationResource } from '@/composables/useConfigurationResource'
import {
  agentAuthoringServiceKey,
  blankMainAgent,
  managementAgentAuthoringService,
  normalizeMainAgent,
  normalizeSubagent,
  mainAgentPayload,
  referenceId,
  setReference,
  type AgentAuthoringService,
  type CapabilityManifest,
  type CapabilityType,
  type StoredBlock,
  type SubagentProfile,
} from '@/domain/agents'

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
  blank: blankMainAgent,
  normalize: normalizeMainAgent,
  payload: mainAgentPayload,
  get: (id) => service.value!.getMainAgent(id),
  create: (payload) => service.value!.createMainAgent(payload),
  update: (id, payload) => service.value!.updateMainAgent(id, payload),
  copy: (id, name) => service.value!.copyMainAgent(id, name),
  remove: (id) => service.value!.deleteMainAgent(id),
  location: (id = '') => id
    ? { path: '/agents/main', query: { id } }
    : { path: '/agents/main' },
  validationRequest: (resource) => ({
    target: { kind: 'main_agent' as const, id: resource.id },
    payload: mainAgentPayload(resource),
  }),
  validate: (request) => service.value!.validateDraft(request),
  deleteConfirmation: (resource) => ({
    title: t('agents.delete.title'),
    description: t('agents.delete.description', { name: resource.name }),
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
const subagentProfiles = ref<SubagentProfile[]>([])
const mcpRequirements = ref<StoredBlock[]>([])

const obsoleteReferences = computed(() => {
  const supported = new Set<string>(
    manifests.value
      .filter((manifest) => manifest.agent_selectable !== false && !['custom-middleware', 'custom-tool'].includes(manifest.type))
      .map((manifest) => manifest.type),
  )
  return form.value.capability_refs
    .map((reference, index) => ({ index, reference }))
    .filter(({ reference }) => !supported.has(reference.type))
})
const workspaceCapabilityTypes = new Set<CapabilityType>([
  'filesystem',
  'filesystem-tools',
  'custom-tool',
  'custom-middleware',
])
const generalManifests = computed(() => manifests.value.filter(
  (manifest) => !workspaceCapabilityTypes.has(manifest.type),
))

function capabilityBlocks(type: CapabilityType): StoredBlock[] {
  return blocks.value[type] ?? []
}

function updateReference(type: CapabilityType, value: string): void {
  setReference(form.value, type, value)
}

function missingCapabilityReference(type: CapabilityType): string {
  const id = referenceId(form.value, type)
  return id && !capabilityBlocks(type).some((block) => block.id === id) ? id : ''
}

function removeObsoleteReference(index: number): void {
  form.value.capability_refs.splice(index, 1)
}

async function loadWorkspace(): Promise<void> {
  await initializeWorkspace(async () => {
    const [catalog, options] = await Promise.all([
      service.value!.getCatalog(),
      service.value!.getConfigurationOptions(),
    ])
    manifests.value = catalog.block_types.filter((item) => item.agent_selectable !== false).sort((left, right) => left.order - right.order)
    subagentProfiles.value = options.subagents.map(normalizeSubagent)
    mcpRequirements.value = options.components['mcp-requirement'] ?? []
    blocks.value = Object.fromEntries(manifests.value.map((manifest) => [
      manifest.type,
      options.components[manifest.type] ?? [],
    ]))
    return options.main_agents
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
            :name="form.name"
            :records="profiles"
            :disabled="loading"
            @select="loadSelected"
            @update:name="form.name = $event"
          />
        </div>

        <section
          v-if="obsoleteReferences.length"
          class="card card-danger card-outline mb-3"
          data-testid="obsolete-capability-references"
        >
          <header class="card-header">
            <h2 class="card-title h5 mb-0 fw-semibold">
              {{ t('agents.obsoleteReferences.title') }}
            </h2>
          </header>
          <ul class="list-group list-group-flush">
            <li
              v-for="item in obsoleteReferences"
              :key="`${item.reference.type}:${item.reference.block_id}:${item.index}`"
              class="list-group-item d-flex align-items-center justify-content-between gap-2"
            >
              <div class="text-break">
                <strong>{{ item.reference.type }}</strong>
                <small class="d-block font-monospace text-body-secondary">
                  {{ item.reference.block_id }}
                </small>
              </div>
              <LteButton
                class="icon-action-button ms-auto"
                :aria-label="t('agents.obsoleteReferences.remove')"
                :title="t('agents.obsoleteReferences.remove')"
                data-action="remove-obsolete-capability-reference"
                size="sm"
                type="button"
                @click="removeObsoleteReference(item.index)"
              >
                <i class="bi bi-trash" aria-hidden="true" />
              </LteButton>
            </li>
          </ul>
        </section>

        <section class="mb-3" :aria-label="t('agents.workspace.title')">
          <div class="row g-3">
            <div class="col-md-6">
              <section class="card h-100" data-testid="main-agent-filesystem-card">
                <header class="card-header d-flex flex-wrap align-items-center justify-content-between gap-2">
                  <label class="card-title mb-0" for="main-agent-capability-filesystem">
                    {{ t('capabilities.filesystem.label') }}
                  </label>
                  <span class="badge text-bg-primary ms-auto">
                    {{ t('agents.capability.required') }}
                  </span>
                </header>
                <div class="card-body">
                  <select
                    id="main-agent-capability-filesystem"
                    class="form-select"
                    data-testid="main-agent-capability-filesystem"
                    :value="referenceId(form, 'filesystem')"
                    @change="updateReference('filesystem', ($event.target as HTMLSelectElement).value)"
                  >
                    <option disabled value="">{{ t('common.chooseConfiguration') }}</option>
                    <option
                      v-if="missingCapabilityReference('filesystem')"
                      disabled
                      :value="missingCapabilityReference('filesystem')"
                    >
                      {{ t('common.missingConfiguration', { id: missingCapabilityReference('filesystem') }) }}
                    </option>
                    <option v-for="block in capabilityBlocks('filesystem')" :key="block.id" :value="block.id">{{ block.name }}</option>
                  </select>
                </div>
              </section>
            </div>
            <div class="col-md-6">
              <section class="card h-100" data-testid="main-agent-filesystem-tools-card">
                <header class="card-header d-flex flex-wrap align-items-center justify-content-between gap-2">
                  <label class="card-title mb-0" for="main-agent-capability-filesystem-tools">
                    {{ t('capabilities.filesystem-tools.label') }}
                  </label>
                  <span class="badge text-bg-primary ms-auto">
                    {{ t('agents.capability.required') }}
                  </span>
                </header>
                <div class="card-body">
                  <select
                    id="main-agent-capability-filesystem-tools"
                    class="form-select"
                    data-testid="main-agent-capability-filesystem-tools"
                    :value="referenceId(form, 'filesystem-tools')"
                    @change="updateReference('filesystem-tools', ($event.target as HTMLSelectElement).value)"
                  >
                    <option disabled value="">{{ t('common.chooseConfiguration') }}</option>
                    <option
                      v-if="missingCapabilityReference('filesystem-tools')"
                      disabled
                      :value="missingCapabilityReference('filesystem-tools')"
                    >
                      {{ t('common.missingConfiguration', { id: missingCapabilityReference('filesystem-tools') }) }}
                    </option>
                    <option v-for="block in capabilityBlocks('filesystem-tools')" :key="block.id" :value="block.id">{{ block.name }}</option>
                  </select>
                </div>
              </section>
            </div>
          </div>
        </section>

        <section class="mb-3" :aria-label="t('agents.mainAgent.capabilitiesTitle')">
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
                    :for="`main-agent-capability-${capability.type}`"
                  >
                    {{ t(`capabilities.${capability.type}.label`) }}
                  </label>
                  <span v-if="capability.required" class="badge text-bg-primary ms-auto">
                    {{ t('agents.capability.required') }}
                  </span>
                  <span v-else class="badge text-bg-info ms-auto">{{ t('agents.capability.optional') }}</span>
                </header>
                <div class="card-body">
                  <select
                    :id="`main-agent-capability-${capability.type}`"
                    class="form-select"
                    :value="referenceId(form, capability.type)"
                    @change="updateReference(capability.type, ($event.target as HTMLSelectElement).value)"
                  >
                    <option v-if="capability.required" disabled value="">{{ t('common.chooseConfiguration') }}</option>
                    <option v-else value="">{{ t('agents.capability.notAttached') }}</option>
                    <option
                      v-if="missingCapabilityReference(capability.type)"
                      disabled
                      :value="missingCapabilityReference(capability.type)"
                    >
                      {{ t('common.missingConfiguration', { id: missingCapabilityReference(capability.type) }) }}
                    </option>
                    <option v-for="block in capabilityBlocks(capability.type)" :key="block.id" :value="block.id">
                      {{ block.name }}
                    </option>
                  </select>
                </div>
              </section>
            </div>
          </div>
        </section>

        <ToolReferencesEditor
          v-model:references="form.tool_refs"
          id-prefix="main-agent-tool"
          :tools="capabilityBlocks('custom-tool')"
        />

        <MiddlewareReferencesEditor
          v-model:references="form.middleware_refs"
          id-prefix="main-agent-middleware"
          :middlewares="capabilityBlocks('custom-middleware')"
        />

        <McpReferencesEditor
          v-model:references="form.mcp_refs"
          id-prefix="main-agent-mcp"
          :requirements="mcpRequirements"
        />

        <SubagentReferencesEditor
          v-model:references="form.subagents"
          :profiles="subagentProfiles"
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
    error-test-id="main-agent-copy-error"
    form-id="main-agent-copy-form"
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
