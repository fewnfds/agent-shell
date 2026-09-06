<script setup lang="ts">
import { LteAlert } from '@adminlte/vue'
import { computed, inject, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import ConfigurationCrudActions from '@/components/ConfigurationCrudActions.vue'
import ConfigurationEditorLayout from '@/components/ConfigurationEditorLayout.vue'
import CopyNameModal from '@/components/CopyNameModal.vue'
import PageShell from '@/components/PageShell.vue'
import RecordPicker from '@/components/RecordPicker.vue'
import ValidationChecklist from '@/components/ValidationChecklist.vue'
import { useConfigurationResource } from '@/composables/useConfigurationResource'
import {
  agentAuthoringServiceKey,
  asyncSubagentPayload,
  blankAsyncSubagent,
  managementAgentAuthoringService,
  normalizeAsyncSubagent,
  type AgentAuthoringService,
  type MainAgentProfile,
} from '@/domain/agents'
import type { MainAgentSummary } from '@/api'

const props = defineProps<{ service?: AgentAuthoringService }>()
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
  selectedId,
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
  blank: blankAsyncSubagent,
  normalize: normalizeAsyncSubagent,
  payload: asyncSubagentPayload,
  get: (id) => service.value!.getAsyncSubagent(id),
  create: (payload) => service.value!.createAsyncSubagent(payload),
  update: (id, payload) => service.value!.updateAsyncSubagent(id, payload),
  copy: (id, componentName) => service.value!.copyAsyncSubagent(id, componentName),
  remove: (id) => service.value!.deleteAsyncSubagent(id),
  location: (id = '') => id
    ? { path: '/agents/async-subagents', query: { id } }
    : { path: '/agents/async-subagents' },
  validationRequest: (resource) => ({
    target: { kind: 'async_subagent' as const, id: resource.id },
    payload: asyncSubagentPayload(resource),
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

const mainAgents = ref<MainAgentSummary[]>([])
const template = ref<MainAgentProfile | null>(null)
let templateSequence = 0
const recordOptions = computed(() => profiles.value.map((profile) => ({
  id: profile.id,
  name: profile.component_name,
})))

async function loadTemplate(id: string): Promise<void> {
  const sequence = ++templateSequence
  template.value = null
  if (!id) return
  try {
    const value = await service.value!.getMainAgent(id)
    if (sequence === templateSequence && form.value.main_agent_id === id) {
      template.value = value as MainAgentProfile
    }
  } catch {
    // Draft validation owns missing-reference feedback.
  }
}

async function loadWorkspace(): Promise<void> {
  await initializeWorkspace(async () => {
    const options = await service.value!.getConfigurationOptions()
    mainAgents.value = options.main_agents
    return options.async_subagents
  })
}

watch(() => form.value.main_agent_id, (id) => {
  void loadTemplate(id)
}, { immediate: true })

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
            :model-value="selectedId"
            :name="form.component_name"
            :records="recordOptions"
            :disabled="loading"
            @select="loadSelected"
            @update:name="form.component_name = $event"
          />
        </div>

        <section class="mb-3" :aria-label="t('agents.asyncSubagentEntity.identityTitle')">
          <div class="row g-3">
            <div class="col-md-6 col-xxl-4">
              <section class="card h-100" data-testid="async-subagent-option-card">
                <header class="card-header">
                  <label class="card-title mb-0" for="async-subagent-template">{{ t('agents.asyncSubagentEntity.template') }}</label>
                </header>
                <div class="card-body">
                  <select id="async-subagent-template" v-model="form.main_agent_id" class="form-select">
                    <option disabled value="">{{ t('common.chooseConfiguration') }}</option>
                    <option
                      v-if="form.main_agent_id && !mainAgents.some((item) => item.id === form.main_agent_id)"
                      disabled
                      :value="form.main_agent_id"
                    >
                      {{ t('common.missingConfiguration', { id: form.main_agent_id }) }}
                    </option>
                    <option v-for="agent in mainAgents" :key="agent.id" :value="agent.id">{{ agent.name }}</option>
                  </select>
                </div>
              </section>
            </div>
            <div class="col-md-6 col-xxl-4">
              <section class="card h-100" data-testid="async-subagent-option-card">
                <header class="card-header">
                  <label class="card-title mb-0" for="async-subagent-role-name">{{ t('agents.asyncSubagentEntity.roleName') }}</label>
                </header>
                <div class="card-body">
                  <input id="async-subagent-role-name" v-model="form.name" class="form-control" autocomplete="off">
                </div>
              </section>
            </div>
            <div class="col-md-6 col-xxl-4">
              <section class="card h-100" data-testid="async-subagent-option-card">
                <header class="card-header">
                  <label class="card-title mb-0" for="async-subagent-description">{{ t('fields.description') }}</label>
                </header>
                <div class="card-body">
                  <textarea id="async-subagent-description" v-model="form.description" class="form-control" rows="1" />
                </div>
              </section>
            </div>
          </div>
        </section>

        <section class="mb-3" :aria-label="t('agents.asyncSubagentEntity.runtimeTitle')">
          <div class="row g-3">
            <div class="col-md-6 col-xxl-3">
              <section class="card h-100" data-testid="async-subagent-frozen-card">
                <header class="card-header">
                  <label class="card-title mb-0" for="async-subagent-template-assembly">{{ t('agents.asyncSubagentEntity.templateAssembly') }}</label>
                </header>
                <div class="card-body">
                  <input id="async-subagent-template-assembly" class="form-control" disabled :value="t('agents.asyncSubagentEntity.inheritTemplate')">
                </div>
              </section>
            </div>
            <div class="col-md-6 col-xxl-3">
              <section class="card h-100" data-testid="async-subagent-frozen-card">
                <header class="card-header">
                  <label class="card-title mb-0" for="async-subagent-disconnect">{{ t('agents.mainAgent.fields.onDisconnect') }}</label>
                </header>
                <div class="card-body">
                  <input
                    id="async-subagent-disconnect"
                    class="form-control"
                    disabled
                    :value="template ? t(`agents.mainAgent.onDisconnect.${template.on_disconnect}`) : '—'"
                  >
                </div>
              </section>
            </div>
            <div class="col-md-6 col-xxl-3">
              <section class="card h-100" data-testid="async-subagent-frozen-card">
                <header class="card-header">
                  <label class="card-title mb-0" for="async-subagent-checkpoint-mode">{{ t('agents.mainAgent.fields.checkpointMode') }}</label>
                </header>
                <div class="card-body">
                  <input id="async-subagent-checkpoint-mode" class="form-control" disabled :value="t('agents.asyncSubagentEntity.checkpointFixed')">
                </div>
              </section>
            </div>
            <div class="col-md-6 col-xxl-3">
              <section class="card h-100" data-testid="async-subagent-frozen-card">
                <header class="card-header">
                  <label class="card-title mb-0" for="async-subagent-durability">{{ t('agents.mainAgent.fields.durability') }}</label>
                </header>
                <div class="card-body">
                  <input id="async-subagent-durability" class="form-control" disabled :value="t('agents.asyncSubagentEntity.durabilityFixed')">
                </div>
              </section>
            </div>
          </div>
        </section>
      </template>
      <template #aside>
        <ValidationChecklist :title="t('validation.draftTitle')" :validation="validation" />
      </template>
    </ConfigurationEditorLayout>
  </PageShell>

  <CopyNameModal
    :busy="copying"
    :busy-label="t('common.copying')"
    error-test-id="async-subagent-copy-error"
    field-path="component_name"
    form-id="async-subagent-copy-form"
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
