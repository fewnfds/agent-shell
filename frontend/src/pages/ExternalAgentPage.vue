<script setup lang="ts">
import { LteAlert } from '@adminlte/vue'
import { computed, inject, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import ConfigurationCrudActions from '@/components/ConfigurationCrudActions.vue'
import ConfigurationEditorLayout from '@/components/ConfigurationEditorLayout.vue'
import CopyNameModal from '@/components/CopyNameModal.vue'
import PageShell from '@/components/PageShell.vue'
import RecordPicker from '@/components/RecordPicker.vue'
import ValidationChecklist from '@/components/ValidationChecklist.vue'
import { useConfigurationResource } from '@/composables/useConfigurationResource'
import {
  blankExternalAgent,
  externalAgentAuthoringServiceKey,
  externalAgentConversations,
  externalAgentEfforts,
  externalAgentOutputFormats,
  externalAgentPayload,
  externalAgentProviders,
  externalAgentToolPermissions,
  externalAgentTools,
  managementExternalAgentService,
  normalizeExternalAgent,
  type ExternalAgentAuthoringService,
} from '@/domain/externalAgent'
import type {
  ExternalAgentConversation,
  ExternalAgentEffort,
  ExternalAgentOutputFormat,
  ExternalAgentToolPermission,
} from '@/api'

const props = defineProps<{
  service?: ExternalAgentAuthoringService
}>()

const { t } = useI18n()
const providedService = inject(
  externalAgentAuthoringServiceKey,
  managementExternalAgentService,
)
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
  records: presets,
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
  blank: blankExternalAgent,
  normalize: normalizeExternalAgent,
  payload: externalAgentPayload,
  get: (id) => service.value!.getExternalAgent(id),
  create: (payload) => service.value!.createExternalAgent(payload),
  update: (id, payload) => service.value!.updateExternalAgent(id, payload),
  copy: (id, name) => service.value!.copyExternalAgent(id, name),
  remove: (id) => service.value!.deleteExternalAgent(id),
  location: (id = '') => id
    ? { path: '/agents/external', query: { id } }
    : { path: '/agents/external' },
  validationRequest: (resource) => ({
    target: { kind: 'external_agent' as const, id: resource.id },
    payload: externalAgentPayload(resource),
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

const recordOptions = computed(() => presets.value.map((preset) => ({
  id: preset.id,
  name: preset.name,
})))

const modelText = computed({
  get: () => form.value.model ?? '',
  set: (value: string) => { form.value.model = value },
})

const effortSelection = computed({
  get: () => form.value.effort ?? '',
  set: (value: string) => {
    form.value.effort = value ? value as ExternalAgentEffort : null
  },
})

const conversationSelection = computed({
  get: () => form.value.conversation,
  set: (value: string) => {
    form.value.conversation = value as ExternalAgentConversation
  },
})

const outputFormatSelection = computed({
  get: () => form.value.output_format,
  set: (value: string) => {
    form.value.output_format = value as ExternalAgentOutputFormat
  },
})

const toolPermissionSelection = computed({
  get: () => form.value.tool_permission,
  set: (value: string) => {
    form.value.tool_permission = value as ExternalAgentToolPermission
  },
})

const permissionAllowText = computed({
  get: () => form.value.permission_allow.join('\n'),
  set: (value: string) => {
    form.value.permission_allow = lines(value)
  },
})

const envText = computed({
  get: () => Object.entries(form.value.env)
    .map(([key, value]) => `${key}=${value}`)
    .join('\n'),
  set: (value: string) => {
    form.value.env = parseEnv(value)
  },
})

function lines(value: string): string[] {
  return value
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)
}

function parseEnv(value: string): Record<string, string> {
  const entries: Record<string, string> = {}
  const reserved = new Set(['HOME', 'USERPROFILE', 'XDG_CONFIG_HOME'])
  for (const item of value.split('\n')) {
    const separator = item.indexOf('=')
    if (separator <= 0) continue
    const key = item.slice(0, separator).trim()
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key) || reserved.has(key)) continue
    entries[key] = item.slice(separator + 1).trim()
  }
  return entries
}

onMounted(() => {
  void initializeWorkspace(async () => {
    const collection = await service.value!.listExternalAgents()
    return collection.items
  })
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
            :name="form.name"
            :records="recordOptions"
            :disabled="loading"
            @select="loadSelected"
            @update:name="form.name = $event"
          />
        </div>

        <section class="mb-3" :aria-label="t('agents.external.identityTitle')">
          <div class="row g-3">
            <div class="col-md-4">
              <section class="card h-100">
                <header class="card-header d-flex flex-wrap align-items-center justify-content-between gap-2">
                  <label class="card-title mb-0" for="external-agent-provider">
                    {{ t('fields.provider') }}
                    <span class="text-danger" aria-hidden="true">{{ t('common.requiredMarker') }}</span>
                    <span class="visually-hidden">{{ t('agents.capability.required') }}</span>
                  </label>
                </header>
                <div class="card-body">
                  <select
                    id="external-agent-provider"
                    v-model="form.provider"
                    class="form-select"
                    data-testid="external-agent-provider"
                  >
                    <option
                      v-for="option in externalAgentProviders"
                      :key="option"
                      :value="option"
                    >
                      {{ t(`agents.external.provider.${option}`) }}
                    </option>
                  </select>
                </div>
              </section>
            </div>
            <div class="col-md-8">
              <section class="card h-100">
                <header class="card-header d-flex flex-wrap align-items-center justify-content-between gap-2">
                  <label class="card-title mb-0" for="external-agent-description">
                    {{ t('fields.description') }}
                    <span class="text-danger" aria-hidden="true">{{ t('common.requiredMarker') }}</span>
                    <span class="visually-hidden">{{ t('agents.capability.required') }}</span>
                  </label>
                </header>
                <div class="card-body">
                  <textarea
                    id="external-agent-description"
                    v-model="form.description"
                    aria-required="true"
                    class="form-control"
                    data-testid="external-agent-description"
                    rows="2"
                  />
                </div>
              </section>
            </div>
          </div>
        </section>

        <section class="mb-3" :aria-label="t('agents.external.agentDefinitionTitle')">
          <div class="row g-3">
            <div class="col-md-4">
              <section class="card h-100">
                <header class="card-header d-flex flex-wrap align-items-center justify-content-between gap-2">
                  <label class="card-title mb-0" for="external-agent-agent-name">
                    {{ t('fields.agent_name') }}
                    <span class="text-danger" aria-hidden="true">{{ t('common.requiredMarker') }}</span>
                    <span class="visually-hidden">{{ t('agents.capability.required') }}</span>
                  </label>
                </header>
                <div class="card-body">
                  <input
                    id="external-agent-agent-name"
                    v-model="form.agent_name"
                    aria-required="true"
                    autocomplete="off"
                    class="form-control"
                    data-testid="external-agent-agent-name"
                  >
                </div>
              </section>
            </div>
            <div class="col-md-8">
              <section class="card h-100">
                <header class="card-header d-flex flex-wrap align-items-center justify-content-between gap-2">
                  <label class="card-title mb-0" for="external-agent-system-prompt">
                    {{ t('fields.system_prompt') }}
                    <span class="text-danger" aria-hidden="true">{{ t('common.requiredMarker') }}</span>
                    <span class="visually-hidden">{{ t('agents.capability.required') }}</span>
                  </label>
                </header>
                <div class="card-body">
                  <textarea
                    id="external-agent-system-prompt"
                    v-model="form.system_prompt"
                    aria-required="true"
                    class="form-control font-monospace"
                    data-testid="external-agent-system-prompt"
                    rows="6"
                  />
                </div>
              </section>
            </div>
          </div>
        </section>

        <section class="mb-3" :aria-label="t('agents.external.invocationTitle')">
          <div class="row g-3">
            <div class="col-md-6 col-xxl-3">
              <section class="card h-100">
                <header class="card-header d-flex flex-wrap align-items-center justify-content-between gap-2">
                  <label class="card-title mb-0" for="external-agent-model">
                    {{ t('fields.model') }}
                  </label>
                </header>
                <div class="card-body">
                  <input
                    id="external-agent-model"
                    v-model="modelText"
                    autocomplete="off"
                    class="form-control"
                    data-testid="external-agent-model"
                    :placeholder="t('agents.external.modelDefault')"
                  >
                </div>
              </section>
            </div>
            <div class="col-md-6 col-xxl-3">
              <section class="card h-100">
                <header class="card-header d-flex flex-wrap align-items-center justify-content-between gap-2">
                  <label class="card-title mb-0" for="external-agent-effort">
                    {{ t('fields.effort') }}
                  </label>
                </header>
                <div class="card-body">
                  <select
                    id="external-agent-effort"
                    v-model="effortSelection"
                    class="form-select"
                    data-testid="external-agent-effort"
                  >
                    <option value="">{{ t('agents.external.effortDefault') }}</option>
                    <option v-for="option in externalAgentEfforts" :key="option" :value="option">
                      {{ t(`agents.external.effort.${option}`) }}
                    </option>
                  </select>
                </div>
              </section>
            </div>
            <div class="col-md-6 col-xxl-3">
              <section class="card h-100">
                <header class="card-header d-flex flex-wrap align-items-center justify-content-between gap-2">
                  <label class="card-title mb-0" for="external-agent-print-timeout">
                    {{ t('fields.print_timeout') }}
                    <span class="text-danger" aria-hidden="true">{{ t('common.requiredMarker') }}</span>
                    <span class="visually-hidden">{{ t('agents.capability.required') }}</span>
                  </label>
                </header>
                <div class="card-body">
                  <input
                    id="external-agent-print-timeout"
                    v-model="form.print_timeout"
                    aria-required="true"
                    autocomplete="off"
                    class="form-control"
                    data-testid="external-agent-print-timeout"
                  >
                </div>
              </section>
            </div>
            <div class="col-md-6 col-xxl-3">
              <section class="card h-100">
                <header class="card-header d-flex flex-wrap align-items-center justify-content-between gap-2">
                  <label class="card-title mb-0" for="external-agent-conversation">
                    {{ t('fields.conversation') }}
                    <span class="text-danger" aria-hidden="true">{{ t('common.requiredMarker') }}</span>
                    <span class="visually-hidden">{{ t('agents.capability.required') }}</span>
                  </label>
                </header>
                <div class="card-body">
                  <select
                    id="external-agent-conversation"
                    v-model="conversationSelection"
                    class="form-select"
                    data-testid="external-agent-conversation"
                  >
                    <option
                      v-for="option in externalAgentConversations"
                      :key="option"
                      :value="option"
                    >
                      {{ t(`agents.external.conversationValue.${option}`) }}
                    </option>
                  </select>
                </div>
              </section>
            </div>
            <div class="col-md-6 col-xxl-3">
              <section class="card h-100">
                <header class="card-header d-flex flex-wrap align-items-center justify-content-between gap-2">
                  <label class="card-title mb-0" for="external-agent-output-format">
                    {{ t('fields.output_format') }}
                  </label>
                </header>
                <div class="card-body">
                  <select
                    id="external-agent-output-format"
                    v-model="outputFormatSelection"
                    class="form-select"
                    data-testid="external-agent-output-format"
                  >
                    <option v-for="option in externalAgentOutputFormats" :key="option" :value="option">
                      {{ option }}
                    </option>
                  </select>
                </div>
              </section>
            </div>
            <div class="col-md-6 col-xxl-3">
              <section class="card h-100">
                <header class="card-header d-flex flex-wrap align-items-center justify-content-between gap-2">
                  <label class="card-title mb-0" for="external-agent-tool-permission">
                    {{ t('fields.tool_permission') }}
                  </label>
                </header>
                <div class="card-body">
                  <select
                    id="external-agent-tool-permission"
                    v-model="toolPermissionSelection"
                    class="form-select"
                    data-testid="external-agent-tool-permission"
                  >
                    <option
                      v-for="option in externalAgentToolPermissions"
                      :key="option"
                      :value="option"
                    >
                      {{ t(`agents.external.toolPermission.${option}`) }}
                    </option>
                  </select>
                </div>
              </section>
            </div>
          </div>
        </section>

        <section class="mb-3" :aria-label="t('agents.external.capabilitiesTitle')">
          <div class="row g-3">
            <div class="col-md-4">
              <section class="card h-100">
                <header class="card-header">
                  <span class="card-title mb-0">{{ t('fields.tools') }}</span>
                </header>
                <div class="card-body">
                  <div class="form-check mb-3">
                    <input
                      id="external-agent-exclude-defaults"
                      v-model="form.exclude_default_components"
                      class="form-check-input"
                      data-testid="external-agent-exclude-defaults"
                      type="checkbox"
                    >
                    <label class="form-check-label" for="external-agent-exclude-defaults">
                      {{ t('agents.external.excludeDefaults') }}
                    </label>
                  </div>
                  <div
                    v-for="tool in externalAgentTools"
                    :key="tool"
                    class="form-check"
                  >
                    <input
                      :id="`external-agent-tool-${tool}`"
                      v-model="form.tools"
                      class="form-check-input"
                      :data-testid="`external-agent-tool-${tool}`"
                      type="checkbox"
                      :value="tool"
                    >
                    <label class="form-check-label" :for="`external-agent-tool-${tool}`">
                      {{ tool }}
                    </label>
                  </div>
                </div>
              </section>
            </div>
            <div class="col-md-8">
              <div class="row g-3">
                <div class="col-12">
                  <section class="card">
                    <header class="card-header">
                      <label class="card-title mb-0" for="external-agent-tool-guidance">
                        {{ t('fields.tool_guidance') }}
                      </label>
                    </header>
                    <div class="card-body">
                      <textarea
                        id="external-agent-tool-guidance"
                        v-model="form.tool_guidance"
                        class="form-control font-monospace"
                        data-testid="external-agent-tool-guidance"
                        rows="3"
                      />
                    </div>
                  </section>
                </div>
                <div class="col-md-6">
                  <section class="card h-100">
                    <header class="card-header">
                      <label class="card-title mb-0" for="external-agent-permission-allow">
                        {{ t('fields.permission_allow') }}
                      </label>
                    </header>
                    <div class="card-body">
                      <textarea
                        id="external-agent-permission-allow"
                        v-model="permissionAllowText"
                        class="form-control font-monospace"
                        data-testid="external-agent-permission-allow"
                        rows="4"
                      />
                    </div>
                  </section>
                </div>
                <div class="col-md-6">
                  <section class="card h-100">
                    <header class="card-header">
                      <label class="card-title mb-0" for="external-agent-env">
                        {{ t('fields.env') }}
                      </label>
                    </header>
                    <div class="card-body">
                      <textarea
                        id="external-agent-env"
                        v-model="envText"
                        class="form-control font-monospace"
                        data-testid="external-agent-env"
                        rows="4"
                      />
                    </div>
                  </section>
                </div>
              </div>
            </div>
          </div>
        </section>
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
    error-test-id="external-agent-copy-error"
    field-path="name"
    form-id="external-agent-copy-form"
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
