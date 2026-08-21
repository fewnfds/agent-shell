<script setup lang="ts">
import { LteAlert, LteCard } from '@adminlte/vue'
import { onMounted, ref } from 'vue'
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
          <LteCard class="mb-3" data-testid="endpoint-card" :title="t('apiServer.endpoints.title')">
            <div class="mb-3">
              <label class="form-label" for="api-base-url">{{ t('apiServer.endpoints.base') }}</label>
              <input id="api-base-url" class="form-control font-monospace" readonly :value="settings.api_base_url">
            </div>
            <div class="mb-3">
              <label class="form-label" for="models-endpoint">{{ t('apiServer.endpoints.models') }}</label>
              <input id="models-endpoint" class="form-control font-monospace" readonly :value="settings.models_endpoint">
            </div>
            <div>
              <label class="form-label" for="chat-completions-endpoint">
                {{ t('apiServer.endpoints.chatCompletions') }}
              </label>
              <input
                id="chat-completions-endpoint"
                class="form-control font-monospace"
                readonly
                :value="settings.chat_completions_endpoint"
              >
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
