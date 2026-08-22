<script setup lang="ts">
import { LteButton, LteInput, LteTextarea } from '@adminlte/vue'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ModelProviderCatalogItem } from '@/api'
import FormField from '@/components/FormField.vue'
import type { ModelDraft, ModelProviderSettingInput } from '@/domain/blocks'

import { useEditorModel } from './shared/useEditorModel'

const props = withDefaults(defineProps<{
  modelValue: ModelDraft
  models?: string[]
  loadingModels?: boolean
  providers?: ModelProviderCatalogItem[]
  loadingProviders?: boolean
}>(), {
  models: () => [],
  loadingModels: false,
  providers: () => [],
  loadingProviders: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: ModelDraft]
  'fetch-models': [request: { provider: string, baseUrl: string, credential: string, blockId: string }]
}>()

const { t } = useI18n()
const draft = useEditorModel(() => props.modelValue, (value) => emit('update:modelValue', value))
const responseFormatPlaceholder = '{"title":"Result","description":"Structured result","type":"object","properties":{}}'
const modelSettingsPlaceholder = '{"parallel_tool_calls":false}'
const credentialPlaceholder = computed(() => draft.credential_status === 'masked'
  ? t('common.configuredSecretPlaceholder')
  : t('common.apiKeyPlaceholder'))
const selectedProviderId = computed(() => draft.provider.trim())

type ParameterKind = 'boolean' | 'boolean-number' | 'enum' | 'number' | 'string-list' | 'text'
interface ProviderParameterField {
  key: string
  kind: ParameterKind
  options?: string[]
}

const openAIFields: ProviderParameterField[] = [
  { key: 'temperature', kind: 'number' },
  { key: 'max_completion_tokens', kind: 'number' },
  { key: 'top_p', kind: 'number' },
  { key: 'stop_sequences', kind: 'string-list' },
  { key: 'presence_penalty', kind: 'number' },
  { key: 'frequency_penalty', kind: 'number' },
  { key: 'seed', kind: 'number' },
  { key: 'timeout', kind: 'number' },
  { key: 'max_retries', kind: 'number' },
  { key: 'stream_usage', kind: 'boolean' },
  { key: 'streaming', kind: 'boolean' },
  { key: 'reasoning_effort', kind: 'text' },
  { key: 'service_tier', kind: 'text' },
  { key: 'logprobs', kind: 'boolean' },
  { key: 'top_logprobs', kind: 'number' },
]
const deepSeekFields: ProviderParameterField[] = [
  { key: 'temperature', kind: 'number' },
  { key: 'max_tokens', kind: 'number' },
  { key: 'top_p', kind: 'number' },
  { key: 'stop_sequences', kind: 'string-list' },
  { key: 'presence_penalty', kind: 'number' },
  { key: 'frequency_penalty', kind: 'number' },
  { key: 'seed', kind: 'number' },
  { key: 'timeout', kind: 'number' },
  { key: 'max_retries', kind: 'number' },
  { key: 'stream_usage', kind: 'boolean' },
  { key: 'streaming', kind: 'boolean' },
  { key: 'reasoning_effort', kind: 'text' },
  { key: 'service_tier', kind: 'text' },
  { key: 'logprobs', kind: 'boolean' },
  { key: 'top_logprobs', kind: 'number' },
]
const xAIFields: ProviderParameterField[] = [
  { key: 'temperature', kind: 'number' },
  { key: 'max_tokens', kind: 'number' },
  { key: 'top_p', kind: 'number' },
  { key: 'stop_sequences', kind: 'string-list' },
  { key: 'presence_penalty', kind: 'number' },
  { key: 'frequency_penalty', kind: 'number' },
  { key: 'seed', kind: 'number' },
  { key: 'timeout', kind: 'number' },
  { key: 'max_retries', kind: 'number' },
  { key: 'stream_usage', kind: 'boolean' },
  { key: 'streaming', kind: 'boolean' },
  { key: 'reasoning_effort', kind: 'text' },
  { key: 'service_tier', kind: 'text' },
  { key: 'logprobs', kind: 'boolean' },
  { key: 'top_logprobs', kind: 'number' },
]
const providerParameterFields: Record<string, ProviderParameterField[]> = {
  openai: openAIFields,
  deepseek: deepSeekFields,
  xai: xAIFields,
  anthropic: [
    { key: 'temperature', kind: 'number' },
    { key: 'max_tokens_to_sample', kind: 'number' },
    { key: 'top_p', kind: 'number' },
    { key: 'stop', kind: 'string-list' },
    { key: 'timeout', kind: 'number' },
    { key: 'max_retries', kind: 'number' },
    { key: 'stream_usage', kind: 'boolean' },
    { key: 'streaming', kind: 'boolean' },
    { key: 'effort', kind: 'enum', options: ['low', 'medium', 'high', 'xhigh', 'max'] },
  ],
  google_genai: [
    { key: 'temperature', kind: 'number' },
    { key: 'max_tokens', kind: 'number' },
    { key: 'top_p', kind: 'number' },
    { key: 'stop_sequences', kind: 'string-list' },
    { key: 'presence_penalty', kind: 'number' },
    { key: 'frequency_penalty', kind: 'number' },
    { key: 'seed', kind: 'number' },
    { key: 'request_timeout', kind: 'number' },
    { key: 'retries', kind: 'number' },
    { key: 'streaming', kind: 'boolean' },
    { key: 'thinking_level', kind: 'enum', options: ['minimal', 'low', 'medium', 'high'] },
    { key: 'thinking_budget', kind: 'number' },
    { key: 'include_thoughts', kind: 'boolean' },
  ],
  google_vertexai: [
    { key: 'temperature', kind: 'number' },
    { key: 'max_tokens', kind: 'number' },
    { key: 'top_p', kind: 'number' },
    { key: 'stop_sequences', kind: 'string-list' },
    { key: 'presence_penalty', kind: 'number' },
    { key: 'frequency_penalty', kind: 'number' },
    { key: 'seed', kind: 'number' },
    { key: 'timeout', kind: 'number' },
    { key: 'max_retries', kind: 'number' },
    { key: 'streaming', kind: 'boolean' },
    { key: 'logprobs', kind: 'boolean-number' },
    { key: 'thinking_budget', kind: 'number' },
    { key: 'include_thoughts', kind: 'boolean' },
  ],
}
const parameterFields = computed(() => providerParameterFields[selectedProviderId.value] ?? [])

function fetchModels(): void {
  emit('fetch-models', {
    provider: draft.provider,
    baseUrl: draft.base_url,
    credential: draft.credential_secret,
    blockId: draft.id,
  })
}

function selectModel(model: string): void {
  draft.model = model
}

function setProvider(event: Event): void {
  const provider = (event.target as HTMLSelectElement).value
  if (provider !== draft.provider) {
    draft.provider = provider
    draft.provider_settings = {}
  }
}

function booleanValue(key: string): string {
  const value = draft.provider_settings[key]
  if (value === true) return 'true'
  if (value === false) return 'false'
  return ''
}

function setProviderSetting(key: string, value: ModelProviderSettingInput): void {
  draft.provider_settings = { ...draft.provider_settings, [key]: value }
}

function openAIConnectionType(): 'compatible' | 'responses' {
  return draft.provider_settings.use_responses_api === true ? 'responses' : 'compatible'
}

function setOpenAIConnectionType(event: Event): void {
  setProviderSetting(
    'use_responses_api',
    (event.target as HTMLSelectElement).value === 'responses',
  )
}

function setBoolean(key: string, event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  setProviderSetting(key, value === '' ? '' : value === 'true')
}

function setText(key: string, event: Event): void {
  setProviderSetting(key, (event.target as HTMLSelectElement).value)
}

function setNumber(key: string, event: Event): void {
  const value = (event.target as HTMLInputElement).value
  setProviderSetting(key, value === '' ? '' : Number(value))
}

function setBooleanNumber(key: string, event: Event): void {
  const value = (event.target as HTMLInputElement).value.trim()
  if (value === '' || value === 'true' || value === 'false') {
    setProviderSetting(key, value === '' ? '' : value === 'true')
  } else {
    const number = Number(value)
    setProviderSetting(key, Number.isFinite(number) ? number : value)
  }
}
</script>

<template>
  <div data-editor="model">
    <section class="card mb-3" data-testid="provider-switch-card">
      <header class="card-header">
        <h3 class="card-title">{{ t('editors.model.providerTitle') }}</h3>
      </header>
      <div class="card-body">
        <select
          :value="draft.provider"
          :aria-label="t('editors.model.providerTitle')"
          class="form-select"
          data-testid="model-provider-input"
          :disabled="loadingProviders || providers.length === 0"
          @change="setProvider"
        >
          <option disabled value="">{{ t('editors.model.providerPlaceholder') }}</option>
          <option
            v-for="provider in providers"
            :key="provider.provider"
            :value="provider.provider"
            :disabled="!provider.installed"
          >
            {{ provider.package }}
          </option>
        </select>
        <div
          v-if="loadingProviders"
          class="small text-body-secondary mt-3"
          data-testid="provider-catalog-loading"
        >
          <span class="spinner-border spinner-border-sm me-2" aria-hidden="true" />
          {{ t('editors.model.providerCatalogLoading') }}
        </div>
      </div>
    </section>

    <section class="card mb-3">
      <header class="card-header">
        <h3 class="card-title">{{ t('editors.model.connectionTitle') }}</h3>
      </header>
      <div class="card-body">
        <div class="row g-3">
          <div class="col-md-6">
            <FormField field-path="base_url" technical>
              <LteInput v-model="draft.base_url" inputmode="url" :placeholder="t('editors.model.baseUrlPlaceholder')" />
            </FormField>
          </div>
          <div class="col-md-6">
            <FormField field-path="credential" technical>
              <LteInput
                v-model="draft.credential_secret"
                autocomplete="new-password"
                :disabled="selectedProviderId === 'google_vertexai'"
                :placeholder="credentialPlaceholder"
                type="password"
              />
              <p v-if="selectedProviderId === 'google_vertexai'" class="small text-body-secondary mb-0 mt-2">
                {{ t('editors.model.vertexCredentialHint') }}
              </p>
            </FormField>
          </div>
          <div v-if="selectedProviderId === 'openai'" class="col-md-6">
            <FormField
              field-path="provider_settings.use_responses_api"
              :hint="t('editors.model.connectionTypeHint')"
              :label-key="'editors.model.connectionTypeLabel'"
            >
              <select
                class="form-select"
                data-testid="openai-connection-type"
                :value="openAIConnectionType()"
                @change="setOpenAIConnectionType"
              >
                <option value="compatible">{{ t('editors.model.connectionTypes.compatible') }}</option>
                <option value="responses">{{ t('editors.model.connectionTypes.responses') }}</option>
              </select>
            </FormField>
          </div>
          <div class="col-md-6">
            <FormField field-path="model" technical>
              <form class="input-group" data-testid="model-fetch-group" @submit.prevent="fetchModels">
                <input
                  v-model="draft.model"
                  class="form-control"
                  :placeholder="t('editors.model.modelPlaceholder')"
                >
                <LteButton
                  class="action-button"
                  data-action="fetch-models"
                  :disabled="loadingModels"
                  type="submit"
                >
                  <span v-if="loadingModels" class="spinner-border spinner-border-sm" aria-hidden="true" />
                  <i v-else class="bi bi-search" aria-hidden="true" />
                  {{ t('common.search') }}
                </LteButton>
              </form>
            </FormField>
          </div>
        </div>
        <div v-if="models.length" class="d-flex flex-wrap gap-2">
          <template v-for="model in models" :key="model">
            <LteButton
              v-if="draft.model === model"
              aria-pressed="true"
              data-testid="model-option"
              theme="primary"
              @click="selectModel(model)"
            >
              {{ model }}
            </LteButton>
            <LteButton
              v-else
              aria-pressed="false"
              data-testid="model-option"
              theme="secondary"
              @click="selectModel(model)"
            >
              {{ model }}
            </LteButton>
          </template>
        </div>
      </div>
    </section>

    <section class="card mb-3">
      <header class="card-header">
        <h3 class="card-title">{{ t('editors.model.parametersTitle') }}</h3>
        <p class="small text-body-secondary mb-0">{{ t('editors.model.providerParametersHint') }}</p>
      </header>
      <div class="card-body">
        <div v-if="parameterFields.length" class="row g-3" data-testid="provider-parameter-fields">
          <div v-for="field in parameterFields" :key="field.key" class="col-md-6">
            <FormField :field-path="`provider_settings.${field.key}`" technical>
              <select
                v-if="field.kind === 'boolean'"
                class="form-select"
                :data-provider-setting="field.key"
                :value="booleanValue(field.key)"
                @change="setBoolean(field.key, $event)"
              >
                <option value="">{{ t('editors.common.useDefault') }}</option>
                <option value="true">{{ t('editors.common.true') }}</option>
                <option value="false">{{ t('editors.common.false') }}</option>
              </select>
              <select
                v-else-if="field.kind === 'enum'"
                class="form-select"
                :data-provider-setting="field.key"
                :value="draft.provider_settings[field.key] ?? ''"
                @change="setText(field.key, $event)"
              >
                <option value="">{{ t('editors.common.useDefault') }}</option>
                <option v-for="option in field.options" :key="option" :value="option">{{ option }}</option>
              </select>
              <input
                v-else-if="field.kind === 'number'"
                class="form-control"
                :data-provider-setting="field.key"
                type="number"
                :value="draft.provider_settings[field.key] ?? ''"
                @input="setNumber(field.key, $event)"
              >
              <input
                v-else-if="field.kind === 'boolean-number'"
                class="form-control"
                :data-provider-setting="field.key"
                :placeholder="'true | false | 0'"
                :value="draft.provider_settings[field.key] ?? ''"
                @input="setBooleanNumber(field.key, $event)"
              >
              <LteInput
                v-else
                :data-provider-setting="field.key"
                :model-value="String(draft.provider_settings[field.key] ?? '')"
                :placeholder="field.kind === 'string-list' ? t('editors.model.stopPlaceholder') : ''"
                @update:model-value="setProviderSetting(field.key, $event)"
              />
            </FormField>
          </div>
        </div>
        <p v-else class="text-body-secondary mb-0">{{ t('editors.model.selectProviderFirst') }}</p>
      </div>
    </section>

    <section class="card mb-3">
      <header class="card-header">
        <h3 class="card-title">{{ t('editors.model.requestSettingsTitle') }}</h3>
        <p class="small text-body-secondary mb-0">{{ t('editors.model.requestSettingsHint') }}</p>
      </header>
      <div class="card-body">
        <FormField
          data-request-setting="tool_choice"
          field-path="tool_choice"
          :hint="t('editors.model.toolChoiceHint')"
          technical
        >
          <input
            v-model="draft.tool_choice"
            class="form-control"
            list="tool-choice-options"
            :placeholder="t('editors.model.toolChoicePlaceholder')"
          >
          <datalist id="tool-choice-options"><option value="auto" /><option value="none" /><option value="required" /><option value="any" /></datalist>
        </FormField>
        <FormField
          data-request-setting="response_format"
          field-path="response_format"
          :hint="t('editors.model.responseFormatHint')"
          technical
        >
          <LteTextarea
            v-model="draft.response_format"
            :placeholder="responseFormatPlaceholder"
            :rows="8"
          />
        </FormField>
        <FormField
          data-request-setting="model_settings"
          field-path="model_settings"
          :hint="t('editors.model.modelSettingsHint')"
          technical
        >
          <LteTextarea
            v-model="draft.model_settings"
            :placeholder="modelSettingsPlaceholder"
            :rows="5"
          />
        </FormField>
      </div>
    </section>
  </div>
</template>
