<script setup lang="ts">
import {
  LteAlert,
  LteButton,
  LteInput,
  LteTextarea,
} from '@adminlte/vue'
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import {
  managementApi,
  type ApiServerSettings,
  type ApiServerSettingsUpdate,
  type ConfigurationValidationSettings,
  type RuntimePolicySettings,
  type RuntimePolicyUpdate,
  type SystemSettings,
  type SystemSettingsUpdate,
} from '@/api'
import FormField from '@/components/FormField.vue'
import PageShell from '@/components/PageShell.vue'
import { useConfigurationValidationSettings } from '@/composables/useConfigurationValidationSettings'
import { useManagementError } from '@/composables/useManagementError'
import { useToasts } from '@/composables/useToasts'

interface SystemSettingsApi {
  getSystemSettings(): Promise<SystemSettings>
  updateSystemSettings(payload: SystemSettingsUpdate): Promise<SystemSettings>
  getApiServer(): Promise<ApiServerSettings>
  saveApiServer(payload: ApiServerSettingsUpdate): Promise<ApiServerSettings>
  getValidationSettings(): Promise<ConfigurationValidationSettings>
  updateValidationSettings(debounceMs: number): Promise<ConfigurationValidationSettings>
  getRuntimePolicy(): Promise<RuntimePolicySettings>
  updateRuntimePolicy(payload: RuntimePolicyUpdate): Promise<RuntimePolicySettings>
}

const props = defineProps<{ api?: SystemSettingsApi }>()
const api = props.api ?? managementApi
const { locale, t } = useI18n()
const managementError = useManagementError()
const { notify } = useToasts()
const validationSettingsController = useConfigurationValidationSettings()

const settings = ref<SystemSettings | null>(null)
const apiServerSettings = ref<ApiServerSettings | null>(null)
const runtimePolicy = ref<RuntimePolicySettings | null>(null)
const loading = ref(true)
const loadError = ref('')
const systemSaving = ref(false)
const apiServerSaving = ref(false)
const validationSaving = ref(false)
const runtimePolicySaving = ref(false)
const systemError = ref('')
const apiServerError = ref('')
const validationError = ref('')
const runtimePolicyError = ref('')
const host = ref('127.0.0.1')
const port = ref(19100)
const nJobsPerWorker = ref(10)
const debugPort = ref<number | ''>('')
const allowRemote = ref(false)
const langsmithTracingEnabled = ref(false)
const langsmithEndpoint = ref('https://api.smith.langchain.com')
const langsmithProject = ref('agent-shell')
const langsmithWorkspaceId = ref('')
const langsmithApiKey = ref('')
const langsmithApiKeyDirty = ref(false)
const showLangsmithApiKey = ref(false)
const managementPassword = ref('')
const showManagementPassword = ref(false)
const apiKey = ref('')
const apiKeyDirty = ref(false)
const showApiKey = ref(false)
const maxInitialMessages = ref(1000)
const validationDebounceMs = ref(1000)
const validationDebounceMin = ref(100)
const corsOrigins = ref('')
const trustedProxies = ref('')
const runtimePolicyDraft = reactive<RuntimePolicyUpdate>({
  runtime_monitoring_retention_lifecycles: 20,
  chat_completion_body_bytes: 64 * 1024 * 1024,
  content_blocks: 4096,
  decoded_block_bytes: 24 * 1024 * 1024,
  decoded_total_bytes: 48 * 1024 * 1024,
  media_output_bytes: 64 * 1024 * 1024,
  text_edit_bytes: 2 * 1024 * 1024,
  provider_timeout_seconds: 600,
  provider_connect_timeout_seconds: 5,
  provider_catalog_timeout_seconds: 15,
})
type RuntimePolicyNumberKey = keyof RuntimePolicyUpdate
const runtimePolicyFields: Array<{
  key: RuntimePolicyNumberKey
  labelKey: string
  unit: string
  step: number
  mib?: boolean
  helpKey?: string
}> = [
  {
    key: 'runtime_monitoring_retention_lifecycles',
    labelKey: 'systemSettings.runtimePolicy.runtimeMonitoringRetention',
    helpKey: 'systemSettings.runtimePolicy.runtimeMonitoringRetentionHelp',
    unit: 'Lifecycle',
    step: 1,
  },
  { key: 'chat_completion_body_bytes', labelKey: 'systemSettings.runtimePolicy.chatBody', unit: 'MiB', step: 1, mib: true },
  { key: 'content_blocks', labelKey: 'systemSettings.runtimePolicy.contentBlocks', unit: '', step: 1 },
  { key: 'decoded_block_bytes', labelKey: 'systemSettings.runtimePolicy.mediaBlock', unit: 'MiB', step: 1, mib: true },
  { key: 'decoded_total_bytes', labelKey: 'systemSettings.runtimePolicy.mediaTotal', unit: 'MiB', step: 1, mib: true },
  { key: 'media_output_bytes', labelKey: 'systemSettings.runtimePolicy.mediaOutput', unit: 'MiB', step: 1, mib: true },
  { key: 'text_edit_bytes', labelKey: 'systemSettings.runtimePolicy.textEdit', unit: 'MiB', step: 1, mib: true },
  { key: 'provider_timeout_seconds', labelKey: 'systemSettings.runtimePolicy.providerTimeout', unit: 's', step: 1 },
  { key: 'provider_connect_timeout_seconds', labelKey: 'systemSettings.runtimePolicy.providerConnectTimeout', unit: 's', step: 1 },
  { key: 'provider_catalog_timeout_seconds', labelKey: 'systemSettings.runtimePolicy.providerCatalogTimeout', unit: 's', step: 1 },
]
const MIB_BYTES = 1024 * 1024

const apiKeyPlaceholder = computed(() => apiServerSettings.value?.api_key.configured
  ? t('common.configuredSecretPlaceholder')
  : t('common.apiKeyPlaceholder'))
const langsmithApiKeyPlaceholder = computed(() => settings.value?.langsmith_api_key.configured
  ? t('common.configuredSecretPlaceholder')
  : t('common.apiKeyPlaceholder'))

function fieldLabel(messageKey: string, wireField: string): string {
  return locale.value === 'debug' ? wireField : t(messageKey)
}

const systemSettingsValid = computed(() => {
  const normalizedPort = Number(port.value)
  const normalizedJobs = Number(nJobsPerWorker.value)
  const normalizedDebugPort = debugPort.value === '' ? null : Number(debugPort.value)
  const endpointValid = (() => {
    try {
      const endpoint = new URL(langsmithEndpoint.value.trim())
      return ['http:', 'https:'].includes(endpoint.protocol)
        && !endpoint.username
        && !endpoint.password
        && !endpoint.search
        && !endpoint.hash
    } catch {
      return false
    }
  })()
  const langsmithApiKeyAvailable = Boolean(langsmithApiKey.value)
    || (!langsmithApiKeyDirty.value && Boolean(settings.value?.langsmith_api_key.configured))
  return Number.isInteger(normalizedPort)
    && normalizedPort >= 1
    && normalizedPort <= 65_535
    && Number.isInteger(normalizedJobs)
    && normalizedJobs >= 1
    && (normalizedDebugPort === null
      || (Number.isInteger(normalizedDebugPort)
        && normalizedDebugPort >= 1
        && normalizedDebugPort <= 65_535
        && normalizedDebugPort !== normalizedPort))
    && endpointValid
    && Boolean(langsmithProject.value.trim())
    && (!langsmithTracingEnabled.value || langsmithApiKeyAvailable)
})
const apiServerSettingsValid = computed(() => {
  const value = Number(maxInitialMessages.value)
  return Number.isInteger(value) && value >= 1
})
const validationSettingsValid = computed(() => {
  const value = Number(validationDebounceMs.value)
  return Number.isInteger(value) && value >= validationDebounceMin.value
})
const runtimePolicyValid = computed(() => runtimePolicy.value !== null
  && runtimePolicyFields.every(({ key }) => {
    const value = Number(runtimePolicyDraft[key])
    return Number.isInteger(value) && value >= runtimePolicy.value!.minimums[key]
  }))
const anySaving = computed(() => systemSaving.value
  || apiServerSaving.value
  || validationSaving.value
  || runtimePolicySaving.value)

function lines(value: string): string[] {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)
}

function applySystemSettings(value: SystemSettings): void {
  settings.value = value
  host.value = value.host
  port.value = value.port
  nJobsPerWorker.value = value.n_jobs_per_worker
  debugPort.value = value.debug_port ?? ''
  allowRemote.value = value.allow_remote
  langsmithTracingEnabled.value = value.langsmith_tracing_enabled
  langsmithEndpoint.value = value.langsmith_endpoint
  langsmithProject.value = value.langsmith_project
  langsmithWorkspaceId.value = value.langsmith_workspace_id ?? ''
  langsmithApiKey.value = ''
  langsmithApiKeyDirty.value = false
  showLangsmithApiKey.value = false
  corsOrigins.value = value.cors_origins.join('\n')
  trustedProxies.value = value.trusted_proxy_cidrs.join('\n')
  managementPassword.value = ''
  showManagementPassword.value = false
}

function applyApiServerSettings(value: ApiServerSettings): void {
  apiServerSettings.value = value
  apiKey.value = ''
  apiKeyDirty.value = false
  showApiKey.value = false
  maxInitialMessages.value = value.max_initial_messages
}

function applyValidationSettings(value: ConfigurationValidationSettings): void {
  validationDebounceMs.value = value.debounce_ms
  validationDebounceMin.value = value.min_debounce_ms
  validationSettingsController.apply(value)
}

function applyRuntimePolicy(value: RuntimePolicySettings): void {
  runtimePolicy.value = value
  for (const { key } of runtimePolicyFields) {
    runtimePolicyDraft[key] = value[key]
  }
}

function runtimePolicyDisplayValue(field: (typeof runtimePolicyFields)[number]): number {
  const value = Number(runtimePolicyDraft[field.key])
  return field.mib ? value / MIB_BYTES : value
}

function updateRuntimePolicyValue(field: (typeof runtimePolicyFields)[number], event: Event): void {
  const value = Number((event.target as HTMLInputElement).value)
  runtimePolicyDraft[field.key] = field.mib ? Math.round(value * MIB_BYTES) : value
}

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const [
      loadedSystemSettings,
      loadedApiServerSettings,
      loadedValidationSettings,
      loadedRuntimePolicy,
    ] = await Promise.all([
      api.getSystemSettings(),
      api.getApiServer(),
      api.getValidationSettings(),
      api.getRuntimePolicy(),
    ])
    applySystemSettings(loadedSystemSettings)
    applyApiServerSettings(loadedApiServerSettings)
    applyValidationSettings(loadedValidationSettings)
    applyRuntimePolicy(loadedRuntimePolicy)
  } catch (error) {
    loadError.value = managementError.describe(error).display
  } finally {
    loading.value = false
  }
}

async function saveSystemSettings(): Promise<void> {
  if (!systemSettingsValid.value) {
    systemError.value = t('systemSettings.systemInvalid')
    return
  }
  systemSaving.value = true
  systemError.value = ''
  try {
    const langsmithApiKeyUpdate: SystemSettingsUpdate['langsmith_api_key'] = langsmithApiKey.value
      ? { operation: 'replace', value: langsmithApiKey.value }
      : langsmithApiKeyDirty.value
        ? { operation: 'clear' }
        : { operation: 'keep' }
    const savedSystemSettings = await api.updateSystemSettings({
      host: host.value.trim(),
      port: Number(port.value),
      n_jobs_per_worker: Number(nJobsPerWorker.value),
      debug_port: debugPort.value === '' ? null : Number(debugPort.value),
      allow_remote: allowRemote.value,
      langsmith_tracing_enabled: langsmithTracingEnabled.value,
      langsmith_endpoint: langsmithEndpoint.value.trim().replace(/\/$/, ''),
      langsmith_project: langsmithProject.value.trim(),
      langsmith_workspace_id: langsmithWorkspaceId.value.trim() || null,
      langsmith_api_key: langsmithApiKeyUpdate,
      management_token: managementPassword.value
        ? { operation: 'replace', value: managementPassword.value }
        : { operation: 'preserve' },
      cors_origins: lines(corsOrigins.value),
      trusted_proxy_cidrs: lines(trustedProxies.value),
    })
    applySystemSettings(savedSystemSettings)
    notify({ tone: 'success', title: t('systemSettings.systemSaved') })
  } catch (error) {
    systemError.value = managementError.describe(error).display
  } finally {
    systemSaving.value = false
  }
}

async function saveApiServerSettings(): Promise<void> {
  if (!apiServerSettingsValid.value) {
    apiServerError.value = t('systemSettings.apiServerInvalid')
    return
  }
  apiServerSaving.value = true
  apiServerError.value = ''
  try {
    const apiKeyUpdate: ApiServerSettingsUpdate['api_key'] = apiKey.value
      ? { operation: 'replace', value: apiKey.value }
      : apiKeyDirty.value
        ? { operation: 'clear' }
        : { operation: 'keep' }
    const saved = await api.saveApiServer({
      api_key: apiKeyUpdate,
      max_initial_messages: Number(maxInitialMessages.value),
    })
    applyApiServerSettings(saved)
    notify({ tone: 'success', title: t('systemSettings.apiServerSaved') })
  } catch (error) {
    apiServerError.value = managementError.describe(error).display
  } finally {
    apiServerSaving.value = false
  }
}

async function saveValidationSettings(): Promise<void> {
  if (!validationSettingsValid.value) {
    validationError.value = t('systemSettings.validationInvalid')
    return
  }
  validationSaving.value = true
  validationError.value = ''
  try {
    const saved = await api.updateValidationSettings(Number(validationDebounceMs.value))
    applyValidationSettings(saved)
    notify({ tone: 'success', title: t('systemSettings.validationSaved') })
  } catch (error) {
    validationError.value = managementError.describe(error).display
  } finally {
    validationSaving.value = false
  }
}

async function saveRuntimePolicy(): Promise<void> {
  if (!runtimePolicyValid.value) {
    runtimePolicyError.value = t('systemSettings.runtimePolicyInvalid')
    return
  }
  runtimePolicySaving.value = true
  runtimePolicyError.value = ''
  try {
    const saved = await api.updateRuntimePolicy({ ...runtimePolicyDraft })
    applyRuntimePolicy(saved)
    notify({ tone: 'success', title: t('systemSettings.runtimePolicySaved') })
  } catch (error) {
    runtimePolicyError.value = managementError.describe(error).display
  } finally {
    runtimePolicySaving.value = false
  }
}

onMounted(() => { void load() })
</script>

<template>
  <PageShell>
    <template #actions>
      <LteButton class="action-button" :disabled="loading || anySaving" type="button" @click="load">
        <span v-if="loading" class="spinner-border spinner-border-sm" aria-hidden="true" />
        <i v-else class="bi bi-arrow-clockwise" aria-hidden="true" />
        {{ t('common.refresh') }}
      </LteButton>
    </template>

    <template #status>
      <LteAlert v-if="loadError" theme="danger" :title="t('systemSettings.loadFailed')">
        {{ loadError }}
      </LteAlert>
      <LteAlert
        v-else-if="settings?.restart_required"
        theme="warning"
        :title="t('systemSettings.restartRequired')"
      >
        <span class="font-monospace text-break">{{ settings.active_management_url }}</span>
      </LteAlert>
    </template>

    <div v-if="loading" class="d-flex align-items-center gap-2" aria-busy="true">
      <span class="spinner-border" aria-hidden="true" />
      <span>{{ t('common.loading') }}</span>
    </div>

    <div
      v-else-if="settings && apiServerSettings && runtimePolicy"
      data-testid="system-settings-form"
      class="row g-3"
    >
      <div class="col-12">
        <form class="card" data-testid="system-card-system" @submit.prevent="saveSystemSettings">
          <header class="card-header d-flex align-items-center gap-2">
            <h2 class="card-title">
              <i class="bi bi-hdd-network me-2" aria-hidden="true" />
              {{ t('systemSettings.systemAndDeployment') }}
            </h2>
            <LteButton
              class="action-button ms-auto"
              data-testid="save-system-settings"
              :disabled="systemSaving || !systemSettingsValid"
              type="submit"
            >
              <span v-if="systemSaving" class="spinner-border spinner-border-sm" aria-hidden="true" />
              <i v-else class="bi bi-floppy" aria-hidden="true" />
              {{ t('common.save') }}
            </LteButton>
          </header>
          <div class="card-body" :aria-busy="systemSaving">
            <LteAlert v-if="systemError" theme="danger" :title="t('systemSettings.systemSaveFailed')">
              {{ systemError }}
            </LteAlert>
            <div class="row g-3">
              <div class="col-lg-3 col-md-6">
                <LteInput id="system-host" v-model="host" :label="fieldLabel('systemSettings.host', 'host')" spellcheck="false" />
              </div>
              <div class="col-lg-3 col-md-6">
                <label class="form-label" for="system-port">
                  {{ fieldLabel('systemSettings.port', 'port') }}
                </label>
                <input
                  id="system-port"
                  v-model.number="port"
                  class="form-control"
                  max="65535"
                  min="1"
                  required
                  step="1"
                  type="number"
                >
              </div>
              <div class="col-lg-3 col-md-6">
                <label class="form-label" for="management-password">
                  {{ fieldLabel('systemSettings.managementPassword', 'management_token') }}
                </label>
                <div class="input-group">
                  <input
                    id="management-password"
                    v-model="managementPassword"
                    autocomplete="new-password"
                    class="form-control"
                    :placeholder="settings.management_token.configured ? t('common.configuredSecretPlaceholder') : ''"
                    spellcheck="false"
                    :type="showManagementPassword ? 'text' : 'password'"
                  >
                  <LteButton
                    class="icon-action-button"
                    :aria-label="showManagementPassword ? t('common.hide') : t('common.show')"
                    :aria-pressed="showManagementPassword"
                    type="button"
                    @click="showManagementPassword = !showManagementPassword"
                  >
                    <i v-if="showManagementPassword" class="bi bi-eye-slash" aria-hidden="true" />
                    <i v-else class="bi bi-eye" aria-hidden="true" />
                  </LteButton>
                </div>
              </div>
              <div class="col-lg-3 col-md-6 d-flex align-items-center">
                <div class="form-check form-switch">
                  <input id="allow-remote" v-model="allowRemote" class="form-check-input" role="switch" type="checkbox">
                  <label class="form-check-label" for="allow-remote">
                    {{ fieldLabel('systemSettings.allowRemote', 'allow_remote') }}
                  </label>
                </div>
              </div>
            </div>

            <h3 class="h6 mt-4 mb-3">{{ t('systemSettings.langgraphDev.title') }}</h3>
            <div class="row g-3">
              <div class="col-lg-4 col-md-6">
                <FormField
                  control-id="langgraph-jobs-per-worker"
                  field-path="n_jobs_per_worker"
                  :hint="t('systemSettings.langgraphDev.jobsHelp')"
                  label-key="systemSettings.langgraphDev.jobs"
                >
                  <template #default="{ describedBy }">
                    <input
                      id="langgraph-jobs-per-worker"
                      v-model.number="nJobsPerWorker"
                      :aria-describedby="describedBy"
                      class="form-control"
                      min="1"
                      required
                      step="1"
                      type="number"
                    >
                  </template>
                </FormField>
              </div>
              <div class="col-lg-4 col-md-6">
                <FormField
                  control-id="langgraph-debug-port"
                  field-path="debug_port"
                  :hint="t('systemSettings.langgraphDev.debugPortHelp')"
                  label-key="systemSettings.langgraphDev.debugPort"
                >
                  <template #default="{ describedBy }">
                    <input
                      id="langgraph-debug-port"
                      v-model.number="debugPort"
                      :aria-describedby="describedBy"
                      class="form-control"
                      max="65535"
                      min="1"
                      :placeholder="t('systemSettings.langgraphDev.debugPortDisabled')"
                      step="1"
                      type="number"
                    >
                  </template>
                </FormField>
              </div>
            </div>

            <h3 class="h6 mt-4 mb-3">{{ t('systemSettings.langsmith.title') }}</h3>
            <div class="row g-3">
              <div class="col-lg-3 col-md-6">
                <LteInput
                  id="langsmith-endpoint"
                  v-model="langsmithEndpoint"
                  autocomplete="url"
                  required
                  :label="fieldLabel('systemSettings.langsmith.endpoint', 'langsmith_endpoint')"
                  spellcheck="false"
                  type="url"
                />
              </div>
              <div class="col-lg-3 col-md-6">
                <label class="form-label" for="langsmith-project">
                  {{ fieldLabel('systemSettings.langsmith.project', 'langsmith_project') }}
                </label>
                <input id="langsmith-project" v-model="langsmithProject" class="form-control" maxlength="200" required spellcheck="false" type="text">
              </div>
              <div class="col-lg-3 col-md-6">
                <label class="form-label" for="langsmith-workspace-id">
                  {{ fieldLabel('systemSettings.langsmith.workspaceId', 'langsmith_workspace_id') }}
                </label>
                <input id="langsmith-workspace-id" v-model="langsmithWorkspaceId" class="form-control" maxlength="200" spellcheck="false" type="text">
              </div>
              <div class="col-lg-3 col-md-6">
                <label class="form-label" for="langsmith-api-key">
                  {{ fieldLabel('systemSettings.langsmith.apiKey', 'langsmith_api_key') }}
                </label>
                <div class="input-group">
                  <input
                    id="langsmith-api-key"
                    v-model="langsmithApiKey"
                    autocomplete="off"
                    class="form-control"
                    :placeholder="langsmithApiKeyPlaceholder"
                    spellcheck="false"
                    :type="showLangsmithApiKey ? 'text' : 'password'"
                    @input="langsmithApiKeyDirty = true"
                  >
                  <LteButton
                    class="icon-action-button"
                    :aria-label="showLangsmithApiKey ? t('common.hide') : t('common.show')"
                    :aria-pressed="showLangsmithApiKey"
                    type="button"
                    @click="showLangsmithApiKey = !showLangsmithApiKey"
                  >
                    <i v-if="showLangsmithApiKey" class="bi bi-eye-slash" aria-hidden="true" />
                    <i v-else class="bi bi-eye" aria-hidden="true" />
                  </LteButton>
                </div>
              </div>
              <div class="col-lg-3 col-md-6">
                <div class="form-check form-switch">
                  <input id="langsmith-tracing" v-model="langsmithTracingEnabled" class="form-check-input" role="switch" type="checkbox">
                  <label class="form-check-label" for="langsmith-tracing">
                    {{ fieldLabel('systemSettings.langsmith.tracing', 'langsmith_tracing_enabled') }}
                  </label>
                </div>
              </div>
            </div>

            <h3 class="h6 mt-4 mb-3">{{ t('systemSettings.proxyAndDiagnostics') }}</h3>
            <div class="row g-3">
              <div class="col-md-6">
                <LteTextarea v-model="corsOrigins" :label="fieldLabel('systemSettings.corsOrigins', 'cors_origins')" :rows="4" />
              </div>
              <div class="col-md-6">
                <LteTextarea v-model="trustedProxies" :label="fieldLabel('systemSettings.trustedProxies', 'trusted_proxy_cidrs')" :rows="4" />
              </div>
            </div>
          </div>
        </form>
      </div>

      <div class="col-12">
        <form class="card" data-testid="system-card-api-server" @submit.prevent="saveApiServerSettings">
          <header class="card-header d-flex align-items-center gap-2">
            <h2 class="card-title">
              <i class="bi bi-key me-2" aria-hidden="true" />
              {{ t('systemSettings.apiServer') }}
            </h2>
            <LteButton
              class="action-button ms-auto"
              data-testid="save-api-server-settings"
              :disabled="apiServerSaving || !apiServerSettingsValid"
              type="submit"
            >
              <span v-if="apiServerSaving" class="spinner-border spinner-border-sm" aria-hidden="true" />
              <i v-else class="bi bi-floppy" aria-hidden="true" />
              {{ t('common.save') }}
            </LteButton>
          </header>
          <div class="card-body" :aria-busy="apiServerSaving">
            <LteAlert v-if="apiServerError" theme="danger" :title="t('systemSettings.apiServerSaveFailed')">
              {{ apiServerError }}
            </LteAlert>
            <div class="row g-3">
              <div class="col-lg-6">
                <label class="form-label" for="api-server-key">{{ fieldLabel('apiServer.key.title', 'api_key') }}</label>
                <div class="input-group">
                  <input
                    id="api-server-key"
                    v-model="apiKey"
                    autocomplete="off"
                    class="form-control"
                    :placeholder="apiKeyPlaceholder"
                    spellcheck="false"
                    :type="showApiKey ? 'text' : 'password'"
                    @input="apiKeyDirty = true"
                  >
                  <LteButton
                    class="icon-action-button"
                    :aria-label="showApiKey ? t('common.hide') : t('common.show')"
                    :aria-pressed="showApiKey"
                    type="button"
                    @click="showApiKey = !showApiKey"
                  >
                    <i v-if="showApiKey" class="bi bi-eye-slash" aria-hidden="true" />
                    <i v-else class="bi bi-eye" aria-hidden="true" />
                  </LteButton>
                </div>
              </div>
              <div class="col-lg-6">
                <label class="form-label" for="max-initial-messages">
                  {{ fieldLabel('apiServer.request.maxInitialMessages', 'max_initial_messages') }}
                </label>
                <input id="max-initial-messages" v-model.number="maxInitialMessages" class="form-control" min="1" required step="1" type="number">
              </div>
            </div>
          </div>
        </form>
      </div>

      <div class="col-12">
        <form class="card" data-testid="system-card-validation" @submit.prevent="saveValidationSettings">
          <header class="card-header d-flex align-items-center gap-2">
            <h2 class="card-title">
              <i class="bi bi-check2-square me-2" aria-hidden="true" />
              {{ t('systemSettings.validation') }}
            </h2>
            <LteButton
              class="action-button ms-auto"
              data-testid="save-validation-settings"
              :disabled="validationSaving || !validationSettingsValid"
              type="submit"
            >
              <span v-if="validationSaving" class="spinner-border spinner-border-sm" aria-hidden="true" />
              <i v-else class="bi bi-floppy" aria-hidden="true" />
              {{ t('common.save') }}
            </LteButton>
          </header>
          <div class="card-body" :aria-busy="validationSaving">
            <LteAlert v-if="validationError" theme="danger" :title="t('systemSettings.validationSaveFailed')">
              {{ validationError }}
            </LteAlert>
            <div class="row g-3">
              <div class="col-lg-6">
                <FormField control-id="configuration-validation-debounce" field-path="debounce_ms" label-key="systemSettings.validationDebounceMs">
                  <div class="input-group">
                    <input
                      id="configuration-validation-debounce"
                      v-model.number="validationDebounceMs"
                      aria-describedby="configuration-validation-debounce-unit"
                      class="form-control"
                      :min="validationDebounceMin"
                      required
                      step="100"
                      type="number"
                    >
                    <span id="configuration-validation-debounce-unit" class="input-group-text">ms</span>
                  </div>
                </FormField>
              </div>
            </div>
          </div>
        </form>
      </div>

      <div class="col-12">
        <form class="card" data-testid="system-card-runtime-policy" @submit.prevent="saveRuntimePolicy">
          <header class="card-header d-flex align-items-center gap-2">
            <h2 class="card-title">
              <i class="bi bi-sliders me-2" aria-hidden="true" />
              {{ t('systemSettings.runtimePolicy.title') }}
            </h2>
            <LteButton
              class="action-button ms-auto"
              data-testid="save-runtime-policy"
              :disabled="runtimePolicySaving || !runtimePolicyValid"
              type="submit"
            >
              <span v-if="runtimePolicySaving" class="spinner-border spinner-border-sm" aria-hidden="true" />
              <i v-else class="bi bi-floppy" aria-hidden="true" />
              {{ t('common.save') }}
            </LteButton>
          </header>
          <div class="card-body" :aria-busy="runtimePolicySaving">
            <LteAlert v-if="runtimePolicyError" theme="danger" :title="t('systemSettings.runtimePolicySaveFailed')">
              {{ runtimePolicyError }}
            </LteAlert>
            <div class="row g-3">
              <div v-for="field in runtimePolicyFields" :key="field.key" class="col-lg-3 col-md-6">
                <label class="form-label" :for="`runtime-policy-${field.key}`">
                  {{ fieldLabel(field.labelKey, field.key) }}
                </label>
                <div class="input-group">
                  <input
                    :id="`runtime-policy-${field.key}`"
                    :value="runtimePolicyDisplayValue(field)"
                    class="form-control"
                    :min="field.mib ? runtimePolicy.minimums[field.key] / MIB_BYTES : runtimePolicy.minimums[field.key]"
                    required
                    :step="field.step"
                    type="number"
                    @input="updateRuntimePolicyValue(field, $event)"
                  >
                  <span v-if="field.unit" class="input-group-text">{{ field.unit }}</span>
                </div>
                <div v-if="field.helpKey" class="form-text">
                  {{ t(field.helpKey) }}
                </div>
              </div>
            </div>
          </div>
        </form>
      </div>
    </div>
  </PageShell>
</template>
