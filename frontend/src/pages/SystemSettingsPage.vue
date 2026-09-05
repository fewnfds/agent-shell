<script setup lang="ts">
import {
  LteAlert,
  LteButton,
  LteInput,
  LteTextarea,
} from '@adminlte/vue'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import {
  managementApi,
  type ApiServerSettings,
  type ApiServerSettingsUpdate,
  type ConfigurationValidationSettings,
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
}

const props = defineProps<{ api?: SystemSettingsApi }>()
const api = props.api ?? managementApi
const { locale, t } = useI18n()
const managementError = useManagementError()
const { notify } = useToasts()
const validationSettingsController = useConfigurationValidationSettings()

const settings = ref<SystemSettings | null>(null)
const apiServerSettings = ref<ApiServerSettings | null>(null)
const loading = ref(true)
const loadError = ref('')
const langgraphSaving = ref(false)
const limitsSaving = ref(false)
const langsmithSaving = ref(false)
const proxySaving = ref(false)
const apiServerSaving = ref(false)
const validationSaving = ref(false)
const langgraphError = ref('')
const limitsError = ref('')
const langsmithError = ref('')
const proxyError = ref('')
const apiServerError = ref('')
const validationError = ref('')
const host = ref('127.0.0.1')
const port = ref(19100)
const nJobsPerWorker = ref(10)
const recursionLimit = ref(25)
const maxConcurrency = ref<number | ''>('')
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
const validationDebounceMs = ref(1000)
const validationDebounceMin = ref(100)
const corsOrigins = ref('')
const trustedProxies = ref('')

const apiKeyPlaceholder = computed(() => apiServerSettings.value?.api_key.configured
  ? t('common.configuredSecretPlaceholder')
  : t('common.apiKeyPlaceholder'))
const langsmithApiKeyPlaceholder = computed(() => settings.value?.langsmith_api_key.configured
  ? t('common.configuredSecretPlaceholder')
  : t('common.apiKeyPlaceholder'))

function fieldLabel(messageKey: string, wireField: string): string {
  return locale.value === 'debug' ? wireField : t(messageKey)
}

const langgraphSettingsValid = computed(() => {
  const normalizedPort = Number(port.value)
  const normalizedDebugPort = debugPort.value === '' ? null : Number(debugPort.value)
  const savedPort = settings.value?.port ?? normalizedPort
  return normalizedDebugPort === null
    || (Number.isInteger(normalizedDebugPort)
      && normalizedDebugPort >= 1
      && normalizedDebugPort <= 65_535
      && normalizedDebugPort !== savedPort)
})
const limitsSettingsValid = computed(() => {
  const normalizedJobs = Number(nJobsPerWorker.value)
  const normalizedRecursion = Number(recursionLimit.value)
  const normalizedConcurrency = maxConcurrency.value === '' ? null : Number(maxConcurrency.value)
  return Number.isInteger(normalizedJobs)
    && normalizedJobs >= 1
    && Number.isInteger(normalizedRecursion)
    && normalizedRecursion >= 1
    && (normalizedConcurrency === null
      || (Number.isInteger(normalizedConcurrency) && normalizedConcurrency >= 1))
})
const langsmithSettingsValid = computed(() => {
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
  return endpointValid
    && Boolean(langsmithProject.value.trim())
    && (!langsmithTracingEnabled.value || langsmithApiKeyAvailable)
})
const proxySettingsValid = computed(() => {
  const normalizedPort = Number(port.value)
  const savedDebugPort = settings.value?.debug_port
  return Boolean(host.value.trim())
    && Number.isInteger(normalizedPort)
    && normalizedPort >= 1
    && normalizedPort <= 65_535
    && (savedDebugPort === null || savedDebugPort !== normalizedPort)
})
const validationSettingsValid = computed(() => {
  const value = Number(validationDebounceMs.value)
  return Number.isInteger(value) && value >= validationDebounceMin.value
})
const anySaving = computed(() => langgraphSaving.value
  || limitsSaving.value
  || langsmithSaving.value
  || proxySaving.value
  || apiServerSaving.value
  || validationSaving.value)

function lines(value: string): string[] {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)
}

function applySystemSettings(value: SystemSettings): void {
  settings.value = value
  host.value = value.host
  port.value = value.port
  nJobsPerWorker.value = value.n_jobs_per_worker
  recursionLimit.value = value.recursion_limit
  maxConcurrency.value = value.max_concurrency ?? ''
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
}

function applyValidationSettings(value: ConfigurationValidationSettings): void {
  validationDebounceMs.value = value.debounce_ms
  validationDebounceMin.value = value.min_debounce_ms
  validationSettingsController.apply(value)
}

type SystemSettingsSection = 'langgraph' | 'limits' | 'langsmith' | 'proxy'

function applySystemSettingsSection(
  value: SystemSettings,
  section: SystemSettingsSection,
): void {
  settings.value = value
  if (section === 'langgraph') {
    debugPort.value = value.debug_port ?? ''
    return
  }
  if (section === 'limits') {
    nJobsPerWorker.value = value.n_jobs_per_worker
    recursionLimit.value = value.recursion_limit
    maxConcurrency.value = value.max_concurrency ?? ''
    return
  }
  if (section === 'langsmith') {
    langsmithTracingEnabled.value = value.langsmith_tracing_enabled
    langsmithEndpoint.value = value.langsmith_endpoint
    langsmithProject.value = value.langsmith_project
    langsmithWorkspaceId.value = value.langsmith_workspace_id ?? ''
    langsmithApiKey.value = ''
    langsmithApiKeyDirty.value = false
    showLangsmithApiKey.value = false
    return
  }
  host.value = value.host
  port.value = value.port
  allowRemote.value = value.allow_remote
  corsOrigins.value = value.cors_origins.join('\n')
  trustedProxies.value = value.trusted_proxy_cidrs.join('\n')
  managementPassword.value = ''
  showManagementPassword.value = false
}

function systemSettingsPayload(section: SystemSettingsSection): SystemSettingsUpdate {
  const saved = settings.value
  if (!saved) {
    throw new Error('System settings are not loaded.')
  }
  const langsmithApiKeyUpdate: SystemSettingsUpdate['langsmith_api_key'] = section === 'langsmith'
    ? langsmithApiKey.value
      ? { operation: 'replace', value: langsmithApiKey.value }
      : langsmithApiKeyDirty.value
        ? { operation: 'clear' }
        : { operation: 'keep' }
    : { operation: 'keep' }
  const managementTokenUpdate: SystemSettingsUpdate['management_token'] = section === 'proxy'
    ? managementPassword.value
      ? { operation: 'replace', value: managementPassword.value }
      : { operation: 'preserve' }
    : { operation: 'preserve' }
  return {
    host: section === 'proxy' ? host.value.trim() : saved.host,
    port: section === 'proxy' ? Number(port.value) : saved.port,
    n_jobs_per_worker: section === 'limits' ? Number(nJobsPerWorker.value) : saved.n_jobs_per_worker,
    recursion_limit: section === 'limits' ? Number(recursionLimit.value) : saved.recursion_limit,
    max_concurrency: section === 'limits'
      ? (maxConcurrency.value === '' ? null : Number(maxConcurrency.value))
      : saved.max_concurrency,
    debug_port: section === 'langgraph'
      ? (debugPort.value === '' ? null : Number(debugPort.value))
      : saved.debug_port,
    allow_remote: section === 'proxy' ? allowRemote.value : saved.allow_remote,
    langsmith_tracing_enabled: section === 'langsmith'
      ? langsmithTracingEnabled.value
      : saved.langsmith_tracing_enabled,
    langsmith_endpoint: section === 'langsmith' ? langsmithEndpoint.value.trim().replace(/\/$/, '') : saved.langsmith_endpoint,
    langsmith_project: section === 'langsmith' ? langsmithProject.value.trim() : saved.langsmith_project,
    langsmith_workspace_id: section === 'langsmith'
      ? langsmithWorkspaceId.value.trim() || null
      : saved.langsmith_workspace_id,
    langsmith_api_key: langsmithApiKeyUpdate,
    management_token: managementTokenUpdate,
    cors_origins: section === 'proxy' ? lines(corsOrigins.value) : saved.cors_origins,
    trusted_proxy_cidrs: section === 'proxy' ? lines(trustedProxies.value) : saved.trusted_proxy_cidrs,
  }
}

async function saveSystemCard(section: SystemSettingsSection): Promise<void> {
  const valid = section === 'langgraph'
    ? langgraphSettingsValid.value
    : section === 'limits'
      ? limitsSettingsValid.value
      : section === 'langsmith'
        ? langsmithSettingsValid.value
        : proxySettingsValid.value
  const saving = section === 'langgraph'
    ? langgraphSaving
    : section === 'limits'
      ? limitsSaving
      : section === 'langsmith'
        ? langsmithSaving
        : proxySaving
  const error = section === 'langgraph'
    ? langgraphError
    : section === 'limits'
      ? limitsError
      : section === 'langsmith'
        ? langsmithError
        : proxyError
  const invalidMessage = section === 'langgraph'
    ? 'systemSettings.langgraphInvalid'
    : section === 'limits'
      ? 'systemSettings.runtimePolicyInvalid'
      : section === 'langsmith'
        ? 'systemSettings.langsmithInvalid'
        : 'systemSettings.proxyInvalid'
  const savedMessage = section === 'langgraph'
    ? 'systemSettings.langgraphSaved'
    : section === 'limits'
      ? 'systemSettings.runtimePolicySaved'
      : section === 'langsmith'
        ? 'systemSettings.langsmithSaved'
        : 'systemSettings.proxySaved'
  if (!valid) {
    error.value = t(invalidMessage)
    return
  }
  saving.value = true
  error.value = ''
  try {
    const saved = await api.updateSystemSettings(systemSettingsPayload(section))
    applySystemSettingsSection(saved, section)
    notify({ tone: 'success', title: t(savedMessage) })
  } catch (caught) {
    error.value = managementError.describe(caught).display
  } finally {
    saving.value = false
  }
}

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const [
      loadedSystemSettings,
      loadedApiServerSettings,
      loadedValidationSettings,
    ] = await Promise.all([
      api.getSystemSettings(),
      api.getApiServer(),
      api.getValidationSettings(),
    ])
    applySystemSettings(loadedSystemSettings)
    applyApiServerSettings(loadedApiServerSettings)
    applyValidationSettings(loadedValidationSettings)
  } catch (error) {
    loadError.value = managementError.describe(error).display
  } finally {
    loading.value = false
  }
}

async function saveApiServerSettings(): Promise<void> {
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
      v-else-if="settings && apiServerSettings"
      data-testid="system-settings-form"
      class="row g-3"
    >
      <div class="col-12">
        <form class="card" data-testid="system-card-langgraph-dev" @submit.prevent="saveSystemCard('langgraph')">
          <header class="card-header d-flex align-items-center gap-2">
            <h2 class="card-title">
              <i class="bi bi-diagram-3 me-2" aria-hidden="true" />
              {{ t('systemSettings.langgraphDev.title') }}
            </h2>
            <LteButton
              class="action-button ms-auto"
              data-testid="save-langgraph-settings"
              :disabled="langgraphSaving || !langgraphSettingsValid"
              type="submit"
            >
              <span v-if="langgraphSaving" class="spinner-border spinner-border-sm" aria-hidden="true" />
              <i v-else class="bi bi-floppy" aria-hidden="true" />
              {{ t('common.save') }}
            </LteButton>
          </header>
          <div class="card-body" :aria-busy="langgraphSaving">
            <LteAlert v-if="langgraphError" theme="danger" :title="t('systemSettings.langgraphSaveFailed')">
              {{ langgraphError }}
            </LteAlert>
            <div class="row g-3">
              <div class="col-lg-3 col-md-6">
                <FormField
                  control-id="langgraph-debug-port"
                  field-path="debug_port"
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
              <div class="col-12">
                <h3 class="h6 mb-2">{{ t('systemSettings.langgraphDev.tools') }}</h3>
                <div class="d-flex flex-wrap gap-2">
                  <a
                    class="btn btn-outline-primary"
                    data-testid="langgraph-api-docs-link"
                    :href="settings.active_api_docs_url"
                    rel="noopener noreferrer"
                    target="_blank"
                  >
                    {{ t('systemSettings.langgraphDev.apiDocs') }}
                  </a>
                  <a
                    class="btn btn-outline-primary"
                    data-testid="langgraph-studio-link"
                    :href="settings.active_studio_url"
                    rel="noopener noreferrer"
                    target="_blank"
                  >
                    {{ t('systemSettings.langgraphDev.studio') }}
                  </a>
                </div>
              </div>
            </div>
          </div>
        </form>
      </div>

      <div class="col-12">
        <form class="card" data-testid="system-card-runtime-policy" @submit.prevent="saveSystemCard('limits')">
          <header class="card-header d-flex align-items-center gap-2">
            <h2 class="card-title">
              <i class="bi bi-sliders me-2" aria-hidden="true" />
              {{ t('systemSettings.runtimePolicy.title') }}
            </h2>
            <LteButton
              class="action-button ms-auto"
              data-testid="save-runtime-policy"
              :disabled="limitsSaving || !limitsSettingsValid"
              type="submit"
            >
              <span v-if="limitsSaving" class="spinner-border spinner-border-sm" aria-hidden="true" />
              <i v-else class="bi bi-floppy" aria-hidden="true" />
              {{ t('common.save') }}
            </LteButton>
          </header>
          <div class="card-body" :aria-busy="limitsSaving">
            <LteAlert v-if="limitsError" theme="danger" :title="t('systemSettings.runtimePolicySaveFailed')">
              {{ limitsError }}
            </LteAlert>
            <div class="row g-3">
              <div class="col-lg-3 col-md-6">
                <FormField control-id="limit-jobs-per-worker" field-path="n_jobs_per_worker" label-key="systemSettings.runtimePolicy.jobs">
                  <template #default="{ describedBy }">
                    <input id="limit-jobs-per-worker" v-model.number="nJobsPerWorker" :aria-describedby="describedBy" class="form-control" min="1" required step="1" type="number">
                  </template>
                </FormField>
              </div>
              <div class="col-lg-3 col-md-6">
                <FormField control-id="limit-recursion" field-path="recursion_limit" label-key="systemSettings.runtimePolicy.recursionLimit">
                  <template #default="{ describedBy }">
                    <input id="limit-recursion" v-model.number="recursionLimit" :aria-describedby="describedBy" class="form-control" min="1" required step="1" type="number">
                  </template>
                </FormField>
              </div>
              <div class="col-lg-3 col-md-6">
                <FormField control-id="limit-concurrency" field-path="max_concurrency" label-key="systemSettings.runtimePolicy.maxConcurrency">
                  <template #default="{ describedBy }">
                    <input id="limit-concurrency" v-model.number="maxConcurrency" :aria-describedby="describedBy" class="form-control" min="1" :placeholder="t('systemSettings.runtimePolicy.officialDefault')" step="1" type="number">
                  </template>
                </FormField>
              </div>
            </div>
          </div>
        </form>
      </div>

      <div class="col-12">
        <form class="card" data-testid="system-card-langsmith" @submit.prevent="saveSystemCard('langsmith')">
          <header class="card-header d-flex align-items-center gap-2">
            <h2 class="card-title">
              <i class="bi bi-cloud-arrow-up me-2" aria-hidden="true" />
              {{ t('systemSettings.langsmith.title') }}
            </h2>
            <LteButton
              class="action-button ms-auto"
              data-testid="save-langsmith-settings"
              :disabled="langsmithSaving || !langsmithSettingsValid"
              type="submit"
            >
              <span v-if="langsmithSaving" class="spinner-border spinner-border-sm" aria-hidden="true" />
              <i v-else class="bi bi-floppy" aria-hidden="true" />
              {{ t('common.save') }}
            </LteButton>
          </header>
          <div class="card-body" :aria-busy="langsmithSaving">
            <LteAlert v-if="langsmithError" theme="danger" :title="t('systemSettings.langsmithSaveFailed')">
              {{ langsmithError }}
            </LteAlert>
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
                <input id="langsmith-project" v-model="langsmithProject" class="form-control" required spellcheck="false" type="text">
              </div>
              <div class="col-lg-3 col-md-6">
                <label class="form-label" for="langsmith-workspace-id">
                  {{ fieldLabel('systemSettings.langsmith.workspaceId', 'langsmith_workspace_id') }}
                </label>
                <input id="langsmith-workspace-id" v-model="langsmithWorkspaceId" class="form-control" spellcheck="false" type="text">
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
              <div class="col-12">
                <div class="form-check form-switch">
                  <input id="langsmith-tracing" v-model="langsmithTracingEnabled" class="form-check-input" role="switch" type="checkbox">
                  <label class="form-check-label" for="langsmith-tracing">
                    {{ fieldLabel('systemSettings.langsmith.tracing', 'langsmith_tracing_enabled') }}
                  </label>
                </div>
              </div>
            </div>
          </div>
        </form>
      </div>

      <div class="col-12">
        <form class="card" data-testid="system-card-proxy" @submit.prevent="saveSystemCard('proxy')">
          <header class="card-header d-flex align-items-center gap-2">
            <h2 class="card-title">
              <i class="bi bi-hdd-network me-2" aria-hidden="true" />
              {{ t('systemSettings.proxyAndDiagnostics') }}
            </h2>
            <LteButton
              class="action-button ms-auto"
              data-testid="save-proxy-settings"
              :disabled="proxySaving || !proxySettingsValid"
              type="submit"
            >
              <span v-if="proxySaving" class="spinner-border spinner-border-sm" aria-hidden="true" />
              <i v-else class="bi bi-floppy" aria-hidden="true" />
              {{ t('common.save') }}
            </LteButton>
          </header>
          <div class="card-body" :aria-busy="proxySaving">
            <LteAlert v-if="proxyError" theme="danger" :title="t('systemSettings.proxySaveFailed')">
              {{ proxyError }}
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
              <div class="col-12">
                <div class="form-check form-switch">
                  <input id="allow-remote" v-model="allowRemote" class="form-check-input" role="switch" type="checkbox">
                  <label class="form-check-label" for="allow-remote">
                    {{ fieldLabel('systemSettings.allowRemote', 'allow_remote') }}
                  </label>
                </div>
              </div>
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
              :disabled="apiServerSaving"
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
    </div>
  </PageShell>
</template>
