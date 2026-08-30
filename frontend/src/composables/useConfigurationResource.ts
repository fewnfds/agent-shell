import { ref, watch, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter, type RouteLocationRaw } from 'vue-router'

import type { ConfirmationRequest } from '@/composables/useConfirmation'
import { useConfigurationValidation } from '@/composables/useConfigurationValidation'
import { useConfirmation } from '@/composables/useConfirmation'
import { useManagementError } from '@/composables/useManagementError'
import { useToasts } from '@/composables/useToasts'
import { useUnsavedChanges } from '@/composables/useUnsavedChanges'
import type { ValidationReport } from '@/domain/agents'

interface ConfigurationResource {
  id: string
}

interface ConfigurationResourceMessages {
  serviceUnavailable: string
  newDraft?: string
  loadFailed: string
  saved: string
  saveFailed: string
  copied: string
  deleted: string
  deleteFailed: string
  copyNameRequired: string
}

export interface ConfigurationResourceDefinition<Resource extends ConfigurationResource, Payload, ValidationRequest> {
  available: () => boolean
  blank: () => Resource
  normalize: (value: unknown) => Resource
  payload: (resource: Resource) => Payload
  get: (id: string) => Promise<unknown>
  create: (payload: Payload) => Promise<unknown>
  update: (id: string, payload: Payload) => Promise<unknown>
  copy: (id: string, name: string) => Promise<unknown>
  remove: (id: string) => Promise<unknown>
  location: (id?: string) => RouteLocationRaw
  validationRequest?: (resource: Resource) => ValidationRequest
  validate?: (request: ValidationRequest) => Promise<ValidationReport>
  deleteConfirmation: (resource: Resource) => ConfirmationRequest
  trackUnsaved?: boolean
  initialSelection?: (records: readonly Resource[], requestedId: string) => string
  sort?: (records: readonly Resource[]) => Resource[]
  messages: ConfigurationResourceMessages
}

export function useConfigurationResource<
  Resource extends ConfigurationResource,
  Payload,
  ValidationRequest,
>(definition: ConfigurationResourceDefinition<Resource, Payload, ValidationRequest>) {
  const { t } = useI18n()
  const route = useRoute()
  const router = useRouter()
  const managementError = useManagementError()
  const { notify } = useToasts()
  const { confirm } = useConfirmation()

  const loading = ref(true)
  const saving = ref(false)
  const copying = ref(false)
  const deleting = ref(false)
  const copyOpen = ref(false)
  const copyName = ref('')
  const copyError = ref('')
  const feedbackKey = ref('')
  const feedbackDetail = ref('')
  const records = ref([]) as Ref<Resource[]>
  const selectedId = ref('')
  const form = ref(definition.blank()) as Ref<Resource>
  let loadSequence = 0

  const { markClean, runAfterDiscard } = useUnsavedChanges(
    () => definition.trackUnsaved === false ? null : form.value,
    () => ({
      title: t('unsavedChanges.title'),
      description: t('unsavedChanges.description'),
      confirmLabel: t('unsavedChanges.confirm'),
      cancelLabel: t('common.cancel'),
    }),
  )

  const { validation, validateNow } = useConfigurationValidation({
    source: form,
    buildRequest: () => definition.validationRequest?.(form.value) ?? null,
    validate: (request) => {
      if (!definition.validate) throw new Error('Configuration validation is unavailable.')
      return definition.validate(request)
    },
    errorMessage: (error) => managementError.describe(
      error,
      'errors.validationUnavailable',
    ).display,
  })

  function clearFeedback(): void {
    feedbackKey.value = ''
    feedbackDetail.value = ''
  }

  function setFailure(key: string, error?: unknown): void {
    feedbackKey.value = key
    feedbackDetail.value = error === undefined
      ? ''
      : managementError.describe(error).display
  }

  function setRecords(values: readonly unknown[]): void {
    const normalized = values.map(definition.normalize)
    records.value = definition.sort?.(normalized) ?? normalized
  }

  function upsert(saved: Resource): void {
    const index = records.value.findIndex((item) => item.id === saved.id)
    const next = index === -1 ? [...records.value, saved] : records.value.map((item, itemIndex) => (
      itemIndex === index ? saved : item
    ))
    records.value = definition.sort?.(next) ?? next
  }

  function resetDraft(notifyUser: boolean): void {
    loadSequence += 1
    saving.value = false
    selectedId.value = ''
    form.value = definition.blank()
    clearFeedback()
    if (notifyUser && definition.messages.newDraft) {
      notify({ tone: 'info', title: t(definition.messages.newDraft) })
    }
    markClean()
    loading.value = false
  }

  async function startNew(): Promise<void> {
    await runAfterDiscard(async () => {
      resetDraft(true)
      await router.replace(definition.location())
    })
  }

  async function loadDetail(id: string): Promise<void> {
    const sequence = ++loadSequence
    saving.value = false
    if (!id) {
      resetDraft(true)
      return
    }
    if (!definition.available()) return
    loading.value = true
    clearFeedback()
    try {
      const loaded = definition.normalize(await definition.get(id))
      if (sequence !== loadSequence) return
      form.value = loaded
      selectedId.value = loaded.id
      markClean()
    } catch (error) {
      if (sequence !== loadSequence) return
      selectedId.value = form.value.id
      setFailure(definition.messages.loadFailed, error)
    } finally {
      if (sequence === loadSequence) loading.value = false
    }
  }

  async function loadSelected(value?: string): Promise<void> {
    const id = value ?? selectedId.value
    await runAfterDiscard(async () => {
      await loadDetail(id)
      if (selectedId.value === id) await router.replace(definition.location(id))
    })
  }

  async function initializeWorkspace(
    loadRecords: () => Promise<readonly unknown[]>,
  ): Promise<void> {
    if (!definition.available()) {
      setFailure(definition.messages.serviceUnavailable)
      loading.value = false
      return
    }
    const sequence = ++loadSequence
    saving.value = false
    loading.value = true
    try {
      const loadedRecords = await loadRecords()
      if (sequence !== loadSequence) return
      setRecords(loadedRecords)
      const requestedId = typeof route.query.id === 'string' ? route.query.id : ''
      const initialId = definition.initialSelection?.(records.value, requestedId) ?? requestedId
      if (initialId) await loadDetail(initialId)
      else {
        selectedId.value = ''
        form.value = definition.blank()
        markClean()
      }
      if (initialId !== requestedId && selectedId.value === initialId) {
        await router.replace(definition.location(initialId))
      }
    } catch (error) {
      if (sequence !== loadSequence) return
      setFailure(definition.messages.loadFailed, error)
    } finally {
      if (sequence === loadSequence) loading.value = false
    }
  }

  async function save(): Promise<void> {
    if (!definition.available()) {
      setFailure(definition.messages.serviceUnavailable)
      return
    }
    saving.value = true
    clearFeedback()
    const sequence = loadSequence
    try {
      const targetId = form.value.id
      const payload = definition.payload(form.value)
      if (definition.validationRequest && definition.validate) {
        const state = await validateNow()
        if (state.status !== 'valid') return
      }
      if (sequence !== loadSequence) return
      const result = targetId
        ? await definition.update(targetId, payload)
        : await definition.create(payload)
      if (sequence !== loadSequence) return
      const saved = definition.normalize(result)
      form.value = saved
      selectedId.value = saved.id
      upsert(saved)
      markClean()
      await router.replace(definition.location(saved.id))
      notify({ tone: 'success', title: t(definition.messages.saved) })
    } catch (error) {
      if (sequence === loadSequence) {
        setFailure(definition.messages.saveFailed, error)
      }
    } finally {
      if (sequence === loadSequence) saving.value = false
    }
  }

  function openCopy(): void {
    if (!form.value.id) return
    copyName.value = ''
    copyError.value = ''
    copyOpen.value = true
  }

  function closeCopy(): void {
    if (copying.value) return
    copyOpen.value = false
    copyName.value = ''
    copyError.value = ''
  }

  async function copyCurrent(): Promise<void> {
    if (!definition.available() || !form.value.id || copying.value) return
    const name = copyName.value.trim()
    if (!name) {
      copyError.value = t(definition.messages.copyNameRequired)
      return
    }
    await runAfterDiscard(async () => {
      copying.value = true
      copyError.value = ''
      try {
        const copied = definition.normalize(await definition.copy(form.value.id, name))
        upsert(copied)
        form.value = copied
        selectedId.value = copied.id
        markClean()
        copyOpen.value = false
        copyName.value = ''
        await router.replace(definition.location(copied.id))
        notify({ tone: 'success', title: t(definition.messages.copied) })
      } catch (error) {
        copyError.value = managementError.describe(error).display
      } finally {
        copying.value = false
      }
    })
  }

  async function removeCurrent(): Promise<void> {
    if (!definition.available() || !form.value.id || deleting.value) return
    await runAfterDiscard(async () => {
      const id = form.value.id
      if (!await confirm(definition.deleteConfirmation(form.value))) return
      deleting.value = true
      clearFeedback()
      try {
        await definition.remove(id)
        records.value = records.value.filter((item) => item.id !== id)
        resetDraft(false)
        await router.replace(definition.location())
        notify({ tone: 'success', title: t(definition.messages.deleted) })
      } catch (error) {
        setFailure(definition.messages.deleteFailed, error)
      } finally {
        deleting.value = false
      }
    })
  }

  watch(
    () => route.query.id,
    (value) => {
      const id = typeof value === 'string' ? value : ''
      if (id === selectedId.value) return
      void loadDetail(id)
    },
  )

  return {
    loading,
    saving,
    copying,
    deleting,
    copyOpen,
    copyName,
    copyError,
    feedbackKey,
    feedbackDetail,
    records,
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
  }
}
