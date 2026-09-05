<script setup lang="ts">
import { LteAlert, LteCard } from '@adminlte/vue'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import {
  managementApi,
  type ApiServerSettings,
  type ValidationReport,
} from '@/api'
import PageShell from '@/components/PageShell.vue'
import ValidationChecklist from '@/components/ValidationChecklist.vue'
import { useConfigurationValidation } from '@/composables/useConfigurationValidation'
import { useManagementError } from '@/composables/useManagementError'

interface ApiServerSettingsApi {
  getApiServer(): Promise<ApiServerSettings>
  validateRepository(): Promise<ValidationReport>
}

const props = defineProps<{
  api?: ApiServerSettingsApi
}>()

const { t } = useI18n()
const managementError = useManagementError()
const api: ApiServerSettingsApi = props.api ?? managementApi
const settings = ref<ApiServerSettings | null>(null)
const loading = ref(true)
const loadError = ref('')
let loadSequence = 0
const diagnosticEndpoints = computed(() => {
  const endpoints = settings.value?.api_endpoints
  if (!endpoints) return []
  return [
    {
      key: 'agent-shell-health',
      labelKey: 'apiServer.endpoints.agentShellHealth',
      url: endpoints.agent_shell_health_endpoint,
    },
    {
      key: 'agent-shell-readiness',
      labelKey: 'apiServer.endpoints.agentShellReadiness',
      url: endpoints.agent_shell_readiness_endpoint,
    },
    {
      key: 'langgraph-health',
      labelKey: 'apiServer.endpoints.langgraphHealth',
      url: endpoints.langgraph_health_endpoint,
    },
    {
      key: 'langgraph-info',
      labelKey: 'apiServer.endpoints.langgraphInfo',
      url: endpoints.langgraph_info_endpoint,
    },
    {
      key: 'langgraph-metrics',
      labelKey: 'apiServer.endpoints.langgraphMetrics',
      url: endpoints.langgraph_metrics_endpoint,
    },
  ]
})
const { validation: repositoryValidation } = useConfigurationValidation({
  buildRequest: () => ({}),
  validate: () => api.validateRepository(),
  errorMessage: (error) => managementError.describe(
    error,
    'errors.validationUnavailable',
  ).display,
})

async function loadSettings(): Promise<void> {
  const sequence = ++loadSequence
  if (!settings.value) loading.value = true
  try {
    const loaded = await api.getApiServer()
    if (sequence === loadSequence) {
      settings.value = loaded
      loadError.value = ''
    }
  } catch (error) {
    if (sequence === loadSequence) {
      loadError.value = managementError.describe(error).display
    }
  } finally {
    if (sequence === loadSequence) loading.value = false
  }
}

onMounted(() => {
  void loadSettings()
})
</script>

<template>
  <PageShell>
    <template #status>
      <LteAlert
        v-if="loadError"
        data-testid="load-error"
        :title="t('apiServer.loadFailed')"
        theme="danger"
      >
        {{ loadError }}
      </LteAlert>
    </template>

    <div v-if="loading" class="d-flex align-items-center gap-2 p-3" aria-busy="true" role="status">
      <span class="spinner-border" aria-hidden="true" />
      <span>{{ t('common.loading') }}</span>
    </div>
    <template v-else-if="settings">
      <div class="row g-3">
        <div class="col-lg-9">
          <LteCard
            class="mb-3"
            data-testid="service-entry-card"
            :title="t('apiServer.serviceEntries.title')"
          >
            <div class="vstack gap-3">
              <div>
                <div class="form-label">{{ t('apiServer.serviceEntries.managementConsole') }}</div>
                <a
                  class="font-monospace text-break"
                  data-testid="management-console-link"
                  :href="settings.service_entries.management_console_url"
                  rel="noopener noreferrer"
                  target="_blank"
                >
                  {{ settings.service_entries.management_console_url }}
                </a>
              </div>
              <div>
                <label class="form-label" for="agent-server-base-url">
                  {{ t('apiServer.serviceEntries.agentServerBase') }}
                </label>
                <input
                  id="agent-server-base-url"
                  class="form-control font-monospace"
                  readonly
                  :value="settings.service_entries.agent_server_base_url"
                >
              </div>
              <div class="row g-3">
                <div class="col-md-6">
                  <div class="form-label">{{ t('apiServer.serviceEntries.apiDocs') }}</div>
                  <a
                    class="font-monospace text-break"
                    data-testid="api-docs-link"
                    :href="settings.service_entries.api_docs_url"
                    rel="noopener noreferrer"
                    target="_blank"
                  >
                    {{ settings.service_entries.api_docs_url }}
                  </a>
                </div>
                <div class="col-md-6">
                  <div class="form-label">{{ t('apiServer.serviceEntries.openapiSchema') }}</div>
                  <a
                    class="font-monospace text-break"
                    data-testid="openapi-schema-link"
                    :href="settings.service_entries.openapi_schema_url"
                    rel="noopener noreferrer"
                    target="_blank"
                  >
                    {{ settings.service_entries.openapi_schema_url }}
                  </a>
                </div>
              </div>
              <div>
                <div class="form-label">{{ t('apiServer.serviceEntries.langgraphStudio') }}</div>
                <a
                  class="font-monospace text-break"
                  data-testid="langgraph-studio-link"
                  :href="settings.service_entries.langgraph_studio_url"
                  rel="noopener noreferrer"
                  target="_blank"
                >
                  {{ settings.service_entries.langgraph_studio_url }}
                </a>
              </div>
            </div>
          </LteCard>

          <LteCard class="mb-3" data-testid="endpoint-card" :title="t('apiServer.endpoints.title')">
            <div class="mb-3">
              <label class="form-label" for="agent-shell-base-url">
                {{ t('apiServer.endpoints.agentShellBase') }}
              </label>
              <input
                id="agent-shell-base-url"
                class="form-control font-monospace"
                readonly
                :value="settings.api_endpoints.agent_shell_base_url"
              >
            </div>
            <div class="mb-3">
              <label class="form-label" for="openai-base-url">
                {{ t('apiServer.endpoints.openaiBase') }}
              </label>
              <input
                id="openai-base-url"
                class="form-control font-monospace"
                readonly
                :value="settings.api_endpoints.openai_base_url"
              >
            </div>
            <div class="row g-3 mb-3">
              <div class="col-xl-6">
                <label class="form-label" for="models-endpoint">{{ t('apiServer.endpoints.models') }}</label>
                <div class="input-group">
                  <span class="input-group-text font-monospace">{{ t('apiServer.endpoints.getMethod') }}</span>
                  <input
                    id="models-endpoint"
                    class="form-control font-monospace"
                    readonly
                    :value="settings.api_endpoints.models_endpoint"
                  >
                </div>
              </div>
              <div class="col-xl-6">
                <label class="form-label" for="chat-completions-endpoint">
                  {{ t('apiServer.endpoints.chatCompletions') }}
                </label>
                <div class="input-group">
                  <span class="input-group-text font-monospace">{{ t('apiServer.endpoints.postMethod') }}</span>
                  <input
                    id="chat-completions-endpoint"
                    class="form-control font-monospace"
                    readonly
                    :value="settings.api_endpoints.chat_completions_endpoint"
                  >
                </div>
              </div>
            </div>
            <div class="mb-3">
              <h3 class="h6">{{ t('apiServer.endpoints.langgraphRoutes') }}</h3>
              <div class="d-flex flex-wrap gap-2">
                <code
                  v-for="route in settings.api_endpoints.langgraph_route_families"
                  :key="route"
                  class="bg-body-tertiary border rounded px-2 py-1"
                >{{ route }}</code>
              </div>
            </div>
            <div class="mb-3">
              <h3 class="h6">{{ t('apiServer.endpoints.diagnostics') }}</h3>
              <div class="row g-2">
                <div
                  v-for="item in diagnosticEndpoints"
                  :key="item.key"
                  class="col-12"
                >
                  <label class="form-label small mb-1" :for="`diagnostic-${item.key}`">
                    {{ t(item.labelKey) }}
                  </label>
                  <div class="input-group input-group-sm">
                    <span class="input-group-text font-monospace">{{ t('apiServer.endpoints.getMethod') }}</span>
                    <input
                      :id="`diagnostic-${item.key}`"
                      class="form-control font-monospace"
                      readonly
                      :value="item.url"
                    >
                  </div>
                </div>
              </div>
            </div>
            <div class="border-top pt-3 small text-body-secondary">
              <p class="mb-1">{{ t('apiServer.endpoints.managementAuth') }}</p>
              <p class="mb-0">{{ t('apiServer.endpoints.apiKeyAuth') }}</p>
            </div>
          </LteCard>
        </div>

        <div class="col-lg-3 validation-sidebar" data-testid="configuration-alerts">
          <ValidationChecklist
            :title="t('apiServer.alerts.title')"
            :validation="repositoryValidation"
          />
        </div>
      </div>
    </template>
  </PageShell>
</template>
