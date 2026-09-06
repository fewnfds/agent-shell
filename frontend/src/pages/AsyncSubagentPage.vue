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

        <section class="card mb-3">
          <header class="card-header">
            <h2 class="card-title mb-0">{{ t('agents.asyncSubagentEntity.identityTitle') }}</h2>
          </header>
          <div class="card-body">
            <div class="row g-3">
              <div class="col-lg-4">
                <label class="form-label" for="async-subagent-template">{{ t('agents.asyncSubagentEntity.template') }}</label>
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
              <div class="col-lg-4">
                <label class="form-label" for="async-subagent-role-name">{{ t('agents.asyncSubagentEntity.roleName') }}</label>
                <input id="async-subagent-role-name" v-model="form.name" class="form-control" autocomplete="off">
              </div>
              <div class="col-lg-4">
                <label class="form-label" for="async-subagent-description">{{ t('fields.description') }}</label>
                <textarea id="async-subagent-description" v-model="form.description" class="form-control" rows="2" />
              </div>
            </div>
          </div>
        </section>

        <section class="card mb-3">
          <header class="card-header">
            <h2 class="card-title mb-0">{{ t('agents.asyncSubagentEntity.runtimeTitle') }}</h2>
          </header>
          <ul class="list-group list-group-flush">
            <li class="list-group-item d-flex justify-content-between gap-3">
              <span>{{ t('agents.asyncSubagentEntity.templateAssembly') }}</span>
              <strong>{{ t('agents.asyncSubagentEntity.inheritTemplate') }}</strong>
            </li>
            <li class="list-group-item d-flex justify-content-between gap-3">
              <span>{{ t('agents.mainAgent.fields.onDisconnect') }}</span>
              <strong>{{ template ? t(`agents.mainAgent.onDisconnect.${template.on_disconnect}`) : '—' }}</strong>
            </li>
            <li class="list-group-item d-flex justify-content-between gap-3">
              <span>{{ t('agents.mainAgent.fields.checkpointMode') }}</span>
              <strong>{{ t('agents.asyncSubagentEntity.checkpointFixed') }}</strong>
            </li>
            <li class="list-group-item d-flex justify-content-between gap-3">
              <span>{{ t('agents.mainAgent.fields.durability') }}</span>
              <strong>{{ t('agents.asyncSubagentEntity.durabilityFixed') }}</strong>
            </li>
          </ul>
        </section>

        <LteAlert :title="t('agents.asyncSubagentEntity.noticeTitle')" theme="info">
          <p>{{ t('agents.asyncSubagentEntity.noticeAsync') }}</p>
          <p>{{ t('agents.asyncSubagentEntity.noticeSync') }}</p>
          <p class="mb-0">{{ t('agents.asyncSubagentEntity.noticeAssembly') }}</p>
        </LteAlert>
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
