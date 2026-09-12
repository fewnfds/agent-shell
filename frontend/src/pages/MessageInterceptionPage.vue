<script setup lang="ts">
import { LteAlert, LteButton } from '@adminlte/vue'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import {
  managementApi,
  type InterceptedMessageRequest,
  type ManagementEvent,
  type MessageInterception,
} from '@/api'
import PageShell from '@/components/PageShell.vue'
import {
  useManagementEvents,
  type ManagementEventSource,
} from '@/composables/useManagementEvents'
import { useManagementError } from '@/composables/useManagementError'

interface MessageInterceptionApi extends ManagementEventSource {
  getMessageInterception(): Promise<MessageInterception>
  updateMessageInterception(enabled: boolean): Promise<MessageInterception>
}

const props = defineProps<{ api?: MessageInterceptionApi }>()
const api = props.api ?? managementApi
const { t } = useI18n()
const managementError = useManagementError()

const loading = ref(true)
const saving = ref(false)
const pageError = ref('')
const failureTitle = ref<'loadFailed' | 'updateFailed'>('loadFailed')
const enabled = ref(false)
const latest = ref<InterceptedMessageRequest | null>(null)
let loadSequence = 0
let loadingRequest = 0
let updateSequence = 0

const requestRawJson = computed(() => latest.value?.request_raw_json ?? '')

function applySnapshot(
  snapshot: MessageInterception,
  options: { includeEnabled?: boolean, includeLatest?: boolean } = {},
): void {
  if (options.includeEnabled !== false) enabled.value = snapshot.enabled
  if (options.includeLatest !== false) latest.value = snapshot.latest
}

async function load(showLoading = false): Promise<void> {
  const request = ++loadSequence
  const includeEnabled = !saving.value
  if (showLoading) {
    loading.value = true
    loadingRequest = request
    pageError.value = ''
    failureTitle.value = 'loadFailed'
  }
  try {
    const snapshot = await api.getMessageInterception()
    if (request === loadSequence) applySnapshot(snapshot, { includeEnabled })
  } catch (error) {
    if (request === loadSequence && !saving.value) {
      failureTitle.value = 'loadFailed'
      pageError.value = managementError.describe(error).display
    }
  } finally {
    if (showLoading && loadingRequest === request) loading.value = false
  }
}

async function updateEnabled(): Promise<void> {
  const request = ++updateSequence
  const requested = enabled.value
  saving.value = true
  pageError.value = ''
  failureTitle.value = 'updateFailed'
  try {
    const snapshot = await api.updateMessageInterception(requested)
    if (request !== updateSequence) return
    loadSequence += 1
    applySnapshot(snapshot, { includeLatest: false })
  } catch (error) {
    if (request === updateSequence) {
      loadSequence += 1
      enabled.value = !requested
      pageError.value = managementError.describe(error).display
    }
  } finally {
    if (request === updateSequence) saving.value = false
  }
}

function handleManagementEvent(event: ManagementEvent): void {
  if (
    event.type === 'message_intercepted'
    || event.type === 'message_interception_changed'
  ) {
    void load()
  }
}

useManagementEvents(handleManagementEvent, api, () => { void load() })
onMounted(() => { void load(true) })
</script>

<template>
  <PageShell>
    <template #actions>
      <LteButton class="action-button" :disabled="loading || saving" type="button" @click="load(true)">
        <span v-if="loading" class="spinner-border spinner-border-sm" aria-hidden="true" />
        <i v-else class="bi bi-arrow-clockwise" aria-hidden="true" />
        {{ t('common.refresh') }}
      </LteButton>
    </template>

    <template #status>
      <LteAlert v-if="pageError" theme="danger" :title="t(`messageInterception.${failureTitle}`)">
        {{ pageError }}
      </LteAlert>
      <LteAlert
        v-else-if="enabled"
        theme="warning"
        :title="t('messageInterception.title')"
      >
        {{ t('messageInterception.enabledWarning') }}
      </LteAlert>
    </template>

    <div v-if="loading" class="d-flex align-items-center gap-2" aria-busy="true">
      <span class="spinner-border" aria-hidden="true" />
      <span>{{ t('common.loading') }}</span>
    </div>

    <section v-else class="card">
      <header class="card-header">
        <h2 class="card-title">{{ t('messageInterception.cardTitle') }}</h2>
      </header>
      <div class="card-body">
        <div class="form-check form-switch mb-3">
          <input
            id="message-interception-enabled"
            v-model="enabled"
            class="form-check-input"
            :disabled="saving"
            role="switch"
            type="checkbox"
            @change="updateEnabled"
          >
          <label class="form-check-label" for="message-interception-enabled">
            {{ t('messageInterception.enabled') }}
          </label>
        </div>

        <textarea
          id="message-interception-raw"
          :aria-label="t('messageInterception.rawRequest')"
          class="form-control font-monospace"
          :placeholder="t('messageInterception.empty')"
          readonly
          rows="22"
          spellcheck="false"
          :value="requestRawJson"
        />
        <p v-if="latest" class="form-text text-break">
          {{ t('messageInterception.metadata', {
            time: latest.intercepted_at,
            requestId: latest.request_id,
          }) }}
        </p>
      </div>
    </section>
  </PageShell>
</template>
