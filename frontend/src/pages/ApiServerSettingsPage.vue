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
const serviceEntryFields = computed(() => {
  const entries = settings.value?.service_entries
  if (!entries) return []
  return [
    {
      key: 'management-console',
      labelKey: 'apiServer.serviceEntries.managementConsole',
      url: entries.management_console_url,
      href: entries.management_console_url,
    },
    {
      key: 'agent-server-base',
      labelKey: 'apiServer.serviceEntries.agentServerBase',
      url: entries.agent_server_base_url,
      href: null,
    },
    {
      key: 'api-docs',
      labelKey: 'apiServer.serviceEntries.apiDocs',
      url: entries.api_docs_url,
      href: entries.api_docs_url,
    },
    {
      key: 'openapi-schema',
      labelKey: 'apiServer.serviceEntries.openapiSchema',
      url: entries.openapi_schema_url,
      href: entries.openapi_schema_url,
    },
    {
      key: 'langgraph-studio',
      labelKey: 'apiServer.serviceEntries.langgraphStudio',
      url: entries.langgraph_studio_url,
      href: entries.langgraph_studio_url,
    },
  ]
})
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
const langgraphRouteLabelKeys: Record<string, string> = {
  '/assistants/*': 'apiServer.endpoints.assistantsApi',
  '/threads/*': 'apiServer.endpoints.threadsApi',
  '/runs/*': 'apiServer.endpoints.runsApi',
  '/store/*': 'apiServer.endpoints.storeApi',
  '/mcp/': 'apiServer.endpoints.mcp',
  '/a2a/{assistant_id}': 'apiServer.endpoints.a2a',
}
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
            <div class="row g-3">
              <div
                v-for="item in serviceEntryFields"
                :key="item.key"
                class="col-lg-6"
              >
                <label class="form-label" :for="`service-entry-${item.key}`">
                  {{ t(item.labelKey) }}
                </label>
                <div v-if="item.href" class="input-group">
                  <input
                    :id="`service-entry-${item.key}`"
                    class="form-control font-monospace"
                    readonly
                    :value="item.url"
                  >
                  <a
                    class="btn btn-outline-secondary"
                    :data-testid="`service-entry-${item.key}-link`"
                    :href="item.href"
                    :aria-label="t('apiServer.serviceEntries.enter', { entry: t(item.labelKey) })"
                    rel="noopener noreferrer"
                    target="_blank"
                  >
                    {{ t('common.enter') }}
                  </a>
                </div>
                <input
                  v-else
                  :id="`service-entry-${item.key}`"
                  class="form-control font-monospace"
                  readonly
                  :value="item.url"
                >
              </div>
            </div>
          </LteCard>

          <LteCard
            class="mb-3"
            data-testid="langgraph-dev-api-card"
            :title="t('apiServer.endpoints.langgraphDevTitle')"
          >
            <div class="row g-3">
              <div class="col-lg-6">
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
              <div
                v-for="(route, index) in settings.api_endpoints.langgraph_route_families"
                :key="route"
                class="col-lg-6"
              >
                <label class="form-label" :for="`langgraph-route-${index}`">
                  {{ t(langgraphRouteLabelKeys[route] ?? 'apiServer.endpoints.langgraphRoute') }}
                </label>
                <input
                  :id="`langgraph-route-${index}`"
                  class="form-control font-monospace"
                  readonly
                  :value="route"
                >
              </div>
              <div
                v-for="item in diagnosticEndpoints"
                :key="item.key"
                class="col-lg-6"
              >
                <label class="form-label" :for="`diagnostic-${item.key}`">
                  {{ t(item.labelKey) }}
                </label>
                <input
                  :id="`diagnostic-${item.key}`"
                  class="form-control font-monospace"
                  readonly
                  :value="item.url"
                >
              </div>
            </div>
          </LteCard>

          <LteCard
            class="mb-3"
            data-testid="openai-api-card"
            :title="t('apiServer.endpoints.openaiTitle')"
          >
            <div class="row g-3">
              <div class="col-lg-6">
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
              <div class="col-lg-6">
                <label class="form-label" for="models-endpoint">
                  {{ t('apiServer.endpoints.models') }}
                </label>
                <input
                  id="models-endpoint"
                  class="form-control font-monospace"
                  readonly
                  :value="settings.api_endpoints.models_endpoint"
                >
              </div>
              <div class="col-lg-6">
                <label class="form-label" for="chat-completions-endpoint">
                  {{ t('apiServer.endpoints.chatCompletions') }}
                </label>
                <input
                  id="chat-completions-endpoint"
                  class="form-control font-monospace"
                  readonly
                  :value="settings.api_endpoints.chat_completions_endpoint"
                >
              </div>
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
