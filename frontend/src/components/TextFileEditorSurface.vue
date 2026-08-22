<script setup lang="ts">
import { LteAlert, LteButton } from '@adminlte/vue'
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import {
  ManagementApiError,
  managementApi,
  type ManagedTextFile,
} from '@/api'
import { useConfirmation } from '@/composables/useConfirmation'
import { useManagementError } from '@/composables/useManagementError'
import { useToasts } from '@/composables/useToasts'

interface TextFileApi {
  readManagedTextFile(path: string): Promise<ManagedTextFile>
  saveManagedTextFile(
    path: string,
    content: string,
    revision: string,
  ): Promise<{ path: string; revision: string }>
}

const props = defineProps<{
  path: string
  api?: TextFileApi
}>()
const emit = defineEmits<{
  back: []
  saved: [path: string]
}>()

const api = props.api ?? managementApi
const { t } = useI18n()
const confirmation = useConfirmation()
const managementError = useManagementError()
const { notify } = useToasts()

const file = ref<ManagedTextFile | null>(null)
const draft = ref('')
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const conflict = ref(false)
let requestSequence = 0

async function load(): Promise<void> {
  const sequence = ++requestSequence
  loading.value = true
  error.value = ''
  conflict.value = false
  try {
    const response = await api.readManagedTextFile(props.path)
    if (sequence !== requestSequence) return
    file.value = response
    draft.value = response.content
  } catch (caught) {
    if (sequence !== requestSequence) return
    file.value = null
    error.value = managementError.describe(caught).display
  } finally {
    if (sequence === requestSequence) loading.value = false
  }
}

async function saveWithRevision(revision: string): Promise<void> {
  saving.value = true
  error.value = ''
  conflict.value = false
  try {
    const response = await api.saveManagedTextFile(props.path, draft.value, revision)
    if (file.value) file.value.revision = response.revision
    notify({ tone: 'success', title: t('fileManager.editor.saved') })
    emit('saved', props.path)
  } catch (caught) {
    if (caught instanceof ManagementApiError && caught.code === 'text_file_revision_conflict') {
      conflict.value = true
    } else {
      error.value = managementError.describe(caught).display
    }
  } finally {
    saving.value = false
  }
}

async function save(): Promise<void> {
  if (!file.value?.capabilities.write) return
  await saveWithRevision(file.value.revision)
}

async function overwriteLatest(): Promise<void> {
  if (!file.value?.capabilities.write) return
  const accepted = await confirmation.confirm({
    title: t('fileManager.editor.overwriteTitle'),
    description: t('fileManager.editor.overwriteDescription', { path: props.path }),
    confirmLabel: t('fileManager.editor.overwriteLatest'),
    cancelLabel: t('common.cancel'),
    dangerous: true,
  })
  if (!accepted) return
  saving.value = true
  error.value = ''
  try {
    const latest = await api.readManagedTextFile(props.path)
    file.value = { ...latest, content: file.value.content }
    await saveWithRevision(latest.revision)
  } catch (caught) {
    error.value = managementError.describe(caught).display
    saving.value = false
  }
}

function keepEditing(): void {
  conflict.value = false
}

watch(() => props.path, () => { void load() }, { immediate: true })
</script>

<template>
  <section>
    <div class="d-flex align-items-center gap-2 mb-3">
      <LteButton class="action-button" :aria-label="t('common.back')" theme="secondary" type="button" @click="emit('back')">
        <i class="bi bi-chevron-left" aria-hidden="true" />
        {{ t('common.back') }}
      </LteButton>
      <code class="font-monospace text-break">{{ path }}</code>
      <LteButton
        v-if="file?.capabilities.write"
        class="action-button ms-auto"
        :disabled="loading || saving"
        theme="primary"
        type="button"
        @click="save"
      >
        <span v-if="saving" class="spinner-border spinner-border-sm" aria-hidden="true" />
        <i v-else class="bi bi-floppy" aria-hidden="true" />
        {{ t('common.save') }}
      </LteButton>
    </div>

    <LteAlert v-if="error" class="mb-3" theme="danger" :title="t('fileManager.requestFailed')">
      {{ error }}
    </LteAlert>
    <LteAlert
      v-if="conflict"
      class="mb-3"
      theme="warning"
      :title="t('fileManager.editor.conflictTitle')"
    >
      <p class="mb-2">{{ t('fileManager.editor.conflictDescription') }}</p>
      <div class="d-flex flex-wrap gap-2">
        <LteButton class="action-button" theme="secondary" type="button" @click="load">
          <i class="bi bi-arrow-clockwise" aria-hidden="true" />
          {{ t('fileManager.editor.reloadDisk') }}
        </LteButton>
        <LteButton
          v-if="file?.capabilities.write"
          class="action-button"
          :disabled="saving"
          theme="danger"
          type="button"
          @click="overwriteLatest"
        >
          <i class="bi bi-floppy" aria-hidden="true" />
          {{ t('fileManager.editor.overwriteLatest') }}
        </LteButton>
        <LteButton class="action-button" theme="secondary" type="button" @click="keepEditing">
          <i class="bi bi-pencil" aria-hidden="true" />
          {{ t('fileManager.editor.keepEditing') }}
        </LteButton>
      </div>
    </LteAlert>

    <div v-if="loading" class="d-flex align-items-center gap-2 p-3" role="status">
      <span class="spinner-border" aria-hidden="true" />
      <span>{{ t('common.loading') }}</span>
    </div>
    <textarea
      v-else-if="file"
      v-model="draft"
      class="form-control font-monospace"
      :readonly="!file.capabilities.write"
      rows="24"
      spellcheck="false"
    />
  </section>
</template>
